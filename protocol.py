"""Protocolo de LaZoo: emparejamiento, WebSocket del ratón y sello LZ2.

Es el único sitio donde vive. El anfitrión (bandeja de Windows, Linux o macOS)
y cualquier mando (navegador, APK) hablan esto y nada más. No importa
`control.py` ni nada del sistema: solo biblioteca estándar.

Emparejamiento
    El PC muestra un QR con `http://IP:PUERTO/#p=PIN&k=CLAVE`. El móvil manda el
    PIN a `POST /api/login` y recibe la cookie `lazo` y el mismo valor como
    `token`. Después usa la cookie o la cabecera `X-Lazo`. Ocho PIN malos
    bloquean el login 30 s. La clave `k` solo viaja en el QR.

Sello LZ2
    `b"LZ2" + nonce(12) + cifrado + etiqueta(16)`. El flujo es
    HMAC-SHA256(clave, nonce + contador_u32_be) por bloques de 32 bytes, y la
    etiqueta son los primeros 16 bytes de HMAC-SHA256(clave, b"LZ2" + nonce +
    cifrado). Con `X-Seal: 1` las respuestas JSON salen selladas; las
    peticiones selladas empiezan por `LZ2`.

WebSocket del ratón (`GET /ws`)
    Tramas de hasta 64 bytes. Binaria: dos enteros de 32 bits con signo,
    little-endian, `dx dy`, tal cual o selladas. Texto: `"dx dy"`.
    Cada trama cuenta como señal de vida del móvil.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import socket
import struct
import threading
import time
from pathlib import Path
from typing import Callable

MAGIC = b"LZ2"
NONCE = 12
TAG = 16
MIN_SEALED = len(MAGIC) + NONCE + TAG
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
WS_MAX_FRAME = 64
MAX_FAILS = 8
LOCK_SECONDS = 30
ALIVE_SECONDS = 5
CHUNK = 256 * 1024


class ProtocolError(ValueError):
    """Algo del protocolo no es válido: sello roto, trama larga, PIN."""


# --- Sello LZ2 ---------------------------------------------------------------


def _xor(key: bytes, nonce: bytes, data: bytes, offset: int = 0) -> bytes:
    out = bytearray(len(data))
    pos = 0
    while pos < len(data):
        block = hmac.new(key, nonce + struct.pack(">I", (offset + pos) // 32), hashlib.sha256).digest()
        skip = (offset + pos) % 32
        take = min(32 - skip, len(data) - pos)
        for index in range(take):
            out[pos + index] = data[pos + index] ^ block[skip + index]
        pos += take
    return bytes(out)


def seal(data: bytes, key: bytes) -> bytes:
    nonce = secrets.token_bytes(NONCE)
    cipher = _xor(key, nonce, data)
    tag = hmac.new(key, MAGIC + nonce + cipher, hashlib.sha256).digest()[:TAG]
    return MAGIC + nonce + cipher + tag


def open_sealed(blob: bytes, key: bytes) -> bytes:
    if len(blob) < MIN_SEALED or not blob.startswith(MAGIC):
        raise ProtocolError("cifrado no válido")
    nonce, tag, cipher = blob[3:15], blob[-TAG:], blob[15:-TAG]
    expect = hmac.new(key, MAGIC + nonce + cipher, hashlib.sha256).digest()[:TAG]
    if not hmac.compare_digest(tag, expect):
        raise ProtocolError("cifrado no válido")
    return _xor(key, nonce, cipher)


def open_sealed_to(source, length: int, dest: Path, key: bytes) -> None:
    """Abre un sello grande leyendo de `source` y escribiendo en `dest`."""
    head = source.read(15)
    if len(head) < 15 or not head.startswith(MAGIC):
        raise ProtocolError("cifrado no válido")
    nonce = head[3:15]
    remaining = length - MIN_SEALED
    if remaining < 0:
        raise ProtocolError("cifrado no válido")
    mac = hmac.new(key, MAGIC + nonce, hashlib.sha256)
    offset = 0
    with dest.open("wb") as out:
        while remaining:
            chunk = source.read(min(CHUNK, remaining))
            if not chunk:
                break
            mac.update(chunk)
            out.write(_xor(key, nonce, chunk, offset))
            offset += len(chunk)
            remaining -= len(chunk)
    tag = source.read(TAG)
    if remaining or not hmac.compare_digest(mac.digest()[:TAG], tag):
        dest.unlink(missing_ok=True)
        raise ProtocolError("cifrado no válido")


# --- Emparejamiento ----------------------------------------------------------


def new_pin() -> str:
    return f"{secrets.randbelow(9000) + 1000}"


def cookies(header: str | None) -> dict[str, str]:
    found: dict[str, str] = {}
    for part in (header or "").split(";"):
        if "=" in part:
            name, value = part.strip().split("=", 1)
            found[name] = value
    return found


class Pairing:
    """PIN, token, clave del sello y señal de vida del móvil de un anfitrión."""

    def __init__(self, pin: str = "") -> None:
        self.pin = pin if pin.isdigit() and len(pin) == 4 else new_pin()
        self.token = secrets.token_urlsafe(32)
        self.key = secrets.token_bytes(32)
        self._lock = threading.Lock()
        self._fails = 0
        self._locked_until = 0.0
        self._last_phone = 0.0

    # PIN y token

    def login(self, pin: str) -> str:
        """Devuelve "ok", "mal" o "espera"."""
        with self._lock:
            now = time.time()
            if now < self._locked_until:
                return "espera"
            if len(pin) != len(self.pin) or not hmac.compare_digest(pin, self.pin):
                self._fails += 1
                if self._fails >= MAX_FAILS:
                    self._locked_until = now + LOCK_SECONDS
                    self._fails = 0
                return "mal"
            self._fails = 0
        self.note_phone()
        return "ok"

    def authed(self, header: str | None, cookie_header: str | None) -> bool:
        for got in (header or "", cookies(cookie_header).get("lazo", "")):
            if got and len(got) == len(self.token) and hmac.compare_digest(got, self.token):
                self.note_phone()
                return True
        return False

    def cookie(self) -> str:
        return f"lazo={self.token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000"

    def phone_url(self, scheme: str, ip: str, port: int) -> str:
        key = base64.urlsafe_b64encode(self.key).decode().rstrip("=")
        return f"{scheme}://{ip}:{port}/#p={self.pin}&k={key}"

    # Señal de vida del móvil

    def note_phone(self) -> None:
        with self._lock:
            self._last_phone = time.time()

    def phone_gone(self) -> None:
        with self._lock:
            self._last_phone = 0.0

    def phone_online(self) -> bool:
        with self._lock:
            return self._last_phone > 0 and time.time() - self._last_phone < ALIVE_SECONDS

    # Sello con la clave de este emparejamiento

    def seal(self, data: bytes) -> bytes:
        return seal(data, self.key)

    def open(self, blob: bytes) -> bytes:
        return open_sealed(blob, self.key)

    def open_to(self, source, length: int, dest: Path) -> None:
        open_sealed_to(source, length, dest, self.key)


# --- WebSocket del ratón -----------------------------------------------------


def ws_accept(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()


def _exact(sock: socket.socket, size: int) -> bytes:
    buf = b""
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise EOFError
        buf += chunk
    return buf


def ws_read(sock: socket.socket) -> tuple[int, bytes]:
    head = _exact(sock, 2)
    opcode, masked, length = head[0] & 0x0F, head[1] & 0x80, head[1] & 0x7F
    if length == 126:
        length = int.from_bytes(_exact(sock, 2), "big")
    elif length == 127:
        length = int.from_bytes(_exact(sock, 8), "big")
    if length > WS_MAX_FRAME:
        raise ProtocolError("trama larga")
    mask = _exact(sock, 4) if masked else b""
    data = _exact(sock, length) if length else b""
    if mask:
        data = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
    return opcode, data


def ws_send(sock: socket.socket, opcode: int, payload: bytes) -> None:
    sock.sendall(bytes([0x80 | opcode, len(payload)]) + payload)


def pointer_loop(
    sock: socket.socket,
    pairing: Pairing,
    move: Callable[[int, int], object],
) -> None:
    """Lee tramas del mando hasta que cierra. Cada una llama a `move(dx, dy)`."""
    try:
        while True:
            opcode, payload = ws_read(sock)
            pairing.note_phone()
            if opcode == 0x8:
                break
            if opcode == 0x9:
                ws_send(sock, 0xA, payload)
                continue
            if opcode == 0x2 and payload.startswith(MAGIC):
                payload = pairing.open(payload)
            if opcode == 0x2 and len(payload) >= 8:
                move(*struct.unpack_from("<ii", payload))
            elif opcode == 0x1:
                parts = payload.decode("ascii", "ignore").split()
                if len(parts) == 2:
                    move(int(parts[0]), int(parts[1]))
    except (OSError, ValueError, EOFError):
        pass
