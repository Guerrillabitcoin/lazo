"""Protocolo de LaZoo: emparejamiento, WebSocket del ratón y sello LZ2.

Es el único sitio donde vive. El anfitrión (bandeja de Windows, Linux o macOS)
y cualquier mando (navegador, APK) hablan esto y nada más. No importa
`control.py` ni nada del sistema: solo biblioteca estándar.

Emparejamiento y firma de peticiones
    El PC muestra un QR con `http://IP:PUERTO/#k=CLAVE`. La clave maestra solo
    viaja en el QR (el fragmento nunca sale del móvil). De ella salen dos claves
    con HMAC-SHA256: `auth = HMAC(k, "lazo/auth/1")` y `seal = HMAC(k, "lazo/seal/1")`.
    Cada petición del móvil lleva `X-Lazo-Id` (id del mando), `X-Lazo-T`
    (milisegundos), `X-Lazo-N` (nonce de 16 bytes en hex) y `X-Lazo-S`:
    HMAC-SHA256(auth, "MÉTODO\nRUTA\nT\nN\nLONGITUD") en hex. La ruta va sin
    consulta y la longitud es la de `Content-Length`. El PC acepta una firma una
    sola vez y solo si la hora está a menos de 60 s. No hay cookie ni token: copiar
    lo que viaja por la Wi-Fi no sirve para controlar el PC. Los cuerpos de las
    peticiones van sellados (LZ2), que además los autentica. En `/ws` los
    mismos cuatro valores van en la consulta: `?i=&t=&n=&s=`.
    Sin cámara se puede emparejar con el PIN de 6 dígitos en `POST /api/login`,
    que devuelve la clave. Es más cómodo y menos seguro: en ese momento la clave
    viaja sin cifrar. Seis fallos seguidos bloquean el login y cada bloqueo dura
    el doble que el anterior (30 s, 1 min, 2 min... hasta 1 h).

Sello LZ2
    `b"LZ2" + nonce(12) + cifrado + etiqueta(16)`. El flujo es
    HMAC-SHA256(clave, nonce + contador_u32_be) por bloques de 32 bytes, y la
    etiqueta son los primeros 16 bytes de HMAC-SHA256(clave, b"LZ2" + nonce +
    cifrado), con la clave `seal`. Con `X-Seal: 1` las respuestas salen selladas;
    las peticiones del móvil siempre van selladas y empiezan por `LZ2`.

WebSocket del ratón (`GET /ws`)
    Tramas de hasta 64 bytes. Binaria: dos enteros de 32 bits con signo,
    little-endian, `dx dy`, selladas. Solo el propio PC (127.0.0.1) puede mandarlas
    sin sellar, o en texto `"dx dy"`.
    Cada trama cuenta como señal de vida del móvil.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from itertools import repeat
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
MAX_FAILS = 6
LOCK_SECONDS = 30
MAX_LOCK_SECONDS = 3600
PIN_LEN = 6
CLOCK_SECONDS = 60
MAX_NONCES = 4096
H_ID, H_T, H_N, H_S = "X-Lazo-Id", "X-Lazo-T", "X-Lazo-N", "X-Lazo-S"
ALIVE_SECONDS = 5
CHUNK = 256 * 1024


class ProtocolError(ValueError):
    """Algo del protocolo no es válido: sello roto, trama larga, PIN."""


# --- Sello LZ2 ---------------------------------------------------------------


def _xor(key: bytes, nonce: bytes, data: bytes, offset: int = 0) -> bytes:
    """XOR con el flujo HMAC-SHA256(key, nonce || contador). Hace los bloques de golpe
    con hmac.digest (en C) y el XOR con enteros grandes: unas 2-3 veces más rápido."""
    if not data:
        return b""
    first, skip = divmod(offset, 32)
    count = (skip + len(data) + 31) // 32
    pack = struct.Struct(">12sI").pack if len(nonce) == 12 else None
    if pack is not None:
        msgs = [pack(nonce, first + index) for index in range(count)]
    else:
        msgs = [nonce + struct.pack(">I", first + index) for index in range(count)]
    stream = b"".join(map(hmac.digest, repeat(key, count), msgs, repeat("sha256", count)))[skip : skip + len(data)]
    return (int.from_bytes(data, "little") ^ int.from_bytes(stream, "little")).to_bytes(len(data), "little")


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
    return f"{secrets.randbelow(9 * 10 ** (PIN_LEN - 1)) + 10 ** (PIN_LEN - 1)}"


def derive(master: bytes, label: str) -> bytes:
    return hmac.new(master, label.encode(), hashlib.sha256).digest()


def sign_request(auth_key: bytes, method: str, path: str, stamp: int, nonce: str, length: int) -> str:
    text = f"{method}\n{path}\n{stamp}\n{nonce}\n{length}"
    return hmac.new(auth_key, text.encode(), hashlib.sha256).hexdigest()


class Pairing:
    """PIN, clave, firma de peticiones y presencia de los mandos de un anfitrión."""

    def __init__(self, pin: str = "") -> None:
        self.pin = pin if pin.isdigit() and len(pin) == PIN_LEN else new_pin()
        self.key = secrets.token_bytes(32)
        self.auth_key = derive(self.key, "lazo/auth/1")
        self.seal_key = derive(self.key, "lazo/seal/1")
        self._lock = threading.Lock()
        self._fails = 0
        self._locks = 0
        self._locked_until = 0.0
        self._seen: dict[str, float] = {}
        self._nonces: dict[str, float] = {}

    # PIN (emparejamiento sin cámara)

    def login(self, pin: str) -> str:
        """Devuelve "ok", "mal" o "espera"."""
        with self._lock:
            now = time.time()
            if now < self._locked_until:
                return "espera"
            if len(pin) != len(self.pin) or not hmac.compare_digest(pin, self.pin):
                self._fails += 1
                if self._fails >= MAX_FAILS:
                    wait = min(LOCK_SECONDS * 2 ** self._locks, MAX_LOCK_SECONDS)
                    self._locked_until = now + wait
                    self._locks += 1
                    self._fails = 0
                return "mal"
            self._fails = 0
            self._locks = 0
        return "ok"

    def key_text(self) -> str:
        return base64.urlsafe_b64encode(self.key).decode().rstrip("=")

    def phone_url(self, scheme: str, ip: str, port: int) -> str:
        return f"{scheme}://{ip}:{port}/#k={self.key_text()}"

    # Firma de peticiones

    def sign(self, method: str, path: str, length: int = 0, now: float | None = None) -> dict[str, str]:
        """Cabeceras de firma, como las pone un mando. Sirve para pruebas y para el cliente en Python."""
        stamp = int((time.time() if now is None else now) * 1000)
        nonce = secrets.token_hex(16)
        return {
            H_T: str(stamp),
            H_N: nonce,
            H_S: sign_request(self.auth_key, method, path, stamp, nonce, length),
        }

    def verify(self, method: str, path: str, length: int, stamp: str, nonce: str, sig: str) -> str:
        """Devuelve "ok", "firma", "hora" o "repetida". Una firma buena solo vale una vez."""
        try:
            when = int(stamp)
        except ValueError:
            return "firma"
        if not (8 <= len(nonce) <= 64 and all(c in "0123456789abcdef" for c in nonce)):
            return "firma"
        expect = sign_request(self.auth_key, method, path, when, nonce, length)
        if not hmac.compare_digest(sig.lower(), expect):
            return "firma"
        now = time.time()
        if abs(now * 1000 - when) > CLOCK_SECONDS * 1000:
            return "hora"
        with self._lock:
            for old in [n for n, until in self._nonces.items() if until < now]:
                del self._nonces[old]
            if nonce in self._nonces or len(self._nonces) >= MAX_NONCES:
                return "repetida"
            self._nonces[nonce] = now + 2 * CLOCK_SECONDS
        return "ok"

    # Señal de vida de cada mando. `who` es su `X-Lazo-Id` o, si no manda uno,
    # su IP. Hay alguien conectado mientras algún mando dé señal.

    def note_phone(self, who: str = "") -> None:
        with self._lock:
            self._seen[who] = time.time()

    def phone_gone(self, who: str = "") -> None:
        with self._lock:
            self._seen.pop(who, None)

    def phone_count(self) -> int:
        with self._lock:
            now = time.time()
            for who in [who for who, last in self._seen.items() if now - last >= ALIVE_SECONDS]:
                del self._seen[who]
            return len(self._seen)

    def phone_online(self) -> bool:
        return self.phone_count() > 0

    # Sello con la clave de este emparejamiento

    def seal(self, data: bytes) -> bytes:
        return seal(data, self.seal_key)

    def open(self, blob: bytes) -> bytes:
        return open_sealed(blob, self.seal_key)

    def open_to(self, source, length: int, dest: Path) -> None:
        open_sealed_to(source, length, dest, self.seal_key)


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
    who: str = "",
    require_seal: bool = True,
) -> None:
    """Lee tramas del mando hasta que cierra. Cada una llama a `move(dx, dy)`.

    Con `require_seal` solo vale lo sellado: cualquier otra trama corta la conexión.
    """
    try:
        while True:
            opcode, payload = ws_read(sock)
            pairing.note_phone(who)
            if opcode == 0x8:
                break
            if opcode == 0x9:
                ws_send(sock, 0xA, payload)
                continue
            if opcode in (0x1, 0x2) and require_seal and not (opcode == 0x2 and payload.startswith(MAGIC)):
                raise ProtocolError("trama sin sellar")
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
