"""Protocolo de LaZoo: emparejamiento, WebSocket del ratón y sello LZ2.

Es el único sitio donde vive. El anfitrión (bandeja de Windows, Linux o macOS)
y cualquier mando (navegador, APK) hablan esto y nada más. No importa
`control.py` ni nada del sistema: solo biblioteca estándar.

Emparejamiento (0.54: la clave larga solo sale tras aprobar)
    La clave maestra `k` (32 bytes) NUNCA va en el QR ni sale por el PIN antes de que
    el PC acepte el dispositivo. El QR lleva `http://IP:PUERTO/#p=FICHA`: una ficha de
    emparejamiento de 32 bytes que solo sirve para identificarse y pedir aprobación (se
    renueva tras cada entrega y al reiniciar). Sin cámara se usa el PIN de 6 dígitos.
    Saludo (handshake) en tres pasos, todo en JSON por la red local:
      1. `POST /api/pair/hello {id, mode: "qr"|"pin", pub}`: el móvil manda su clave
         pública X25519 efímera; el PC contesta `{sid, pub}` con la suya, también efímera.
      2. Los dos calculan `dh = X25519(priv, pub_otro)` y
         `hk = HMAC(S, "lazo/pair/1|" + mode + "|" + id + "|" + pub_movil + pub_pc + dh)`,
         con `S` = la ficha del QR o `"pin:" + PIN`. `POST /api/pair/claim {sid, proof}`
         con `proof = HMAC(hk, "lazo/pair/movil")`. Si cuadra, el dispositivo pasa a
         «pendiente» y salta el aviso de Windows/bandeja. El PC devuelve su propia prueba
         `HMAC(hk, "lazo/pair/pc")` para que el móvil sepa que habla con el PC del QR/PIN.
         Un fallo cuenta para el bloqueo creciente del PIN.
      3. `POST /api/pair/wait {sid, proof}` hasta que el PC decide. Solo con «aprobado»
         llega `box` = sello LZ2 de la clave maestra con `derive(hk, "lazo/pair/box/1")`.
    Quien escuche la Wi-Fi ve las dos claves públicas y las pruebas, pero no `dh`: no
    puede sacar la clave larga ni probar PINes sin conexión. Límite conocido: alguien que
    se ponga EN MEDIO durante el emparejamiento por PIN podría probar los 10^6 PINes con
    la prueba del móvil; con el QR (256 bits) no. Por eso el QR sigue siendo lo
    recomendado.

Clave por móvil (0.62)
    La clave maestra `k` no sale nunca del PC. Cada móvil recibe en `box` SU clave
    `kd = HMAC(k, "lazo/dev/1|" + id)` y de ella saca `auth = HMAC(kd, "lazo/auth/1")` y
    `seal = HMAC(kd, "lazo/seal/1")` (el móvil no cambia: trata `kd` como su clave). El PC
    comprueba cada firma y abre cada sello con la clave del `X-Lazo-Id` que dice el móvil,
    así que un móvil no puede hacerse pasar por otro cambiando su id, y expulsar a uno no
    deja a nadie con la clave de los demás. Hasta 0.61 todos compartían `k`.

Firma de peticiones
    Cada petición del móvil lleva `X-Lazo-Id` (id del mando), `X-Lazo-T`
    (milisegundos), `X-Lazo-N` (nonce de 16 bytes en hex) y `X-Lazo-S`:
    HMAC-SHA256(auth, "MÉTODO\nRUTA\nT\nN\nLONGITUD") en hex. La ruta va sin
    consulta y la longitud es la de `Content-Length`. El PC acepta una firma una
    sola vez y solo si la hora está a menos de 60 s. No hay cookie ni token: copiar
    lo que viaja por la Wi-Fi no sirve para controlar el PC. Los cuerpos de las
    peticiones van sellados (LZ2), que además los autentica. En `/ws` los
    mismos cuatro valores van en la consulta: `?i=&t=&n=&s=`.
    Seis fallos seguidos (PIN o ficha) bloquean el emparejamiento y cada bloqueo
    dura el doble que el anterior (30 s, 1 min, 2 min... hasta 1 h).

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
AWAY_SECONDS = 12 * 3600  # 0.69: un móvil que se fue a otro PC cuenta como «en otro PC» hasta 12 h
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


# --- X25519 (RFC 7748), solo biblioteca estándar ------------------------------

_P = 2 ** 255 - 19
_A24 = 121665
PAIR_SECONDS = 120
DELIVERED_SECONDS = 30  # 0.56: la entrega se puede repetir durante este rato
MAX_SESSIONS = 32


def x25519(scalar: bytes, point: bytes) -> bytes:
    if len(scalar) != 32 or len(point) != 32:
        raise ProtocolError("clave no válida")
    k = bytearray(scalar)
    k[0] &= 248
    k[31] &= 127
    k[31] |= 64
    n = int.from_bytes(k, "little")
    x1 = int.from_bytes(point, "little") & ((1 << 255) - 1)
    x2, z2, x3, z3, swap = 1, 0, x1, 1, 0
    p = _P
    for t in range(254, -1, -1):
        bit = (n >> t) & 1
        if swap ^ bit:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = bit
        a = (x2 + z2) % p
        aa = a * a % p
        b = (x2 - z2) % p
        bb = b * b % p
        e = (aa - bb) % p
        c = (x3 + z3) % p
        d = (x3 - z3) % p
        da = d * a % p
        cb = c * b % p
        x3 = (da + cb) ** 2 % p
        z3 = x1 * (da - cb) ** 2 % p
        x2 = aa * bb % p
        z2 = e * (aa + _A24 * e) % p
    if swap:
        x2, z2 = x3, z3
    return (x2 * pow(z2, p - 2, p) % p).to_bytes(32, "little")


X25519_BASE = (9).to_bytes(32, "little")


def x25519_keypair() -> tuple[bytes, bytes]:
    priv = secrets.token_bytes(32)
    return priv, x25519(priv, X25519_BASE)


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64u(text: str) -> bytes:
    text = str(text or "")
    if len(text) > 200 or not all(c.isalnum() or c in "-_" for c in text):
        raise ProtocolError("base64 no válido")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except ValueError as exc:
        raise ProtocolError("base64 no válido") from exc


def pair_secret(mode: str, token: bytes, pin: str) -> bytes:
    return token if mode == "qr" else ("pin:" + pin).encode()


def handshake_key(secret: bytes, mode: str, who: str, pub_phone: bytes, pub_pc: bytes, shared: bytes) -> bytes:
    msg = f"lazo/pair/1|{mode}|{who}|".encode() + pub_phone + pub_pc + shared
    return hmac.new(secret, msg, hashlib.sha256).digest()


def proof(hk: bytes, side: str) -> str:
    return hmac.new(hk, f"lazo/pair/{side}".encode(), hashlib.sha256).hexdigest()


def fingerprint(who: str, pub_phone: bytes) -> str:
    """Huella corta del dispositivo (id + su clave efímera del emparejamiento)."""
    raw = hashlib.sha256(who.encode() + pub_phone).hexdigest()[:16].upper()
    return "-".join(raw[i:i + 4] for i in range(0, 16, 4))


class Pairing:
    """PIN, clave, firma de peticiones y presencia de los mandos de un anfitrión."""

    def __init__(self, pin: str = "") -> None:
        self.pin = pin if pin.isdigit() and len(pin) == PIN_LEN else new_pin()
        self._lock = threading.Lock()
        self.set_key(secrets.token_bytes(32))
        self.token = secrets.token_bytes(32)  # ficha del QR: solo para pedir aprobación
        self.sessions: dict[str, dict] = {}
        self._fails = 0
        self._locks = 0
        self._locked_until = 0.0
        self._seen: dict[str, float] = {}
        self._away: dict[str, float] = {}  # 0.69: móviles en otro PC
        self._nonces: dict[str, float] = {}

    def set_key(self, key: bytes) -> None:
        """Pone la clave maestra (nueva, o la recordada en este PC)."""
        if len(key) != 32:
            raise ProtocolError("clave no válida")
        self.key = key
        self.auth_key = derive(key, "lazo/auth/1")
        self.seal_key = derive(key, "lazo/seal/1")
        self._devices: dict[str, tuple[bytes, bytes]] = {}  # 0.62: id -> (auth, seal) de ese móvil

    # 0.62: clave de cada móvil (ver «Clave por móvil» arriba)

    def device_key(self, who: str) -> bytes:
        return derive(self.key, "lazo/dev/1|" + str(who))

    def device_key_text(self, who: str) -> str:
        return b64u(self.device_key(who))

    def _keys(self, who: str | None) -> tuple[bytes, bytes]:
        """(auth, seal) del móvil `who`; sin `who`, las de la clave maestra (solo el propio PC y pruebas)."""
        if not who:
            return self.auth_key, self.seal_key
        keys = self._devices.get(who)
        if keys is None:
            kd = self.device_key(who)
            keys = (derive(kd, "lazo/auth/1"), derive(kd, "lazo/seal/1"))
            if len(self._devices) > 256:
                self._devices.clear()
            self._devices[who] = keys
        return keys

    def rekey(self) -> None:
        """Clave y ficha nuevas: todo móvil con la clave vieja deja de valer."""
        with self._lock:
            self.set_key(secrets.token_bytes(32))
            self.token = secrets.token_bytes(32)
            self.sessions.clear()
            self._nonces.clear()
            self._seen.clear()

    def new_token(self) -> None:
        with self._lock:
            self.token = secrets.token_bytes(32)

    # Bloqueo creciente (PIN y ficha del QR)

    def locked(self) -> bool:
        with self._lock:
            return time.time() < self._locked_until

    def _fail(self) -> None:
        with self._lock:
            now = time.time()
            self._fails += 1
            if self._fails >= MAX_FAILS:
                wait = min(LOCK_SECONDS * 2 ** self._locks, MAX_LOCK_SECONDS)
                self._locked_until = now + wait
                self._locks += 1
                self._fails = 0

    def _good(self) -> None:
        with self._lock:
            self._fails = 0
            self._locks = 0

    def login(self, pin: str) -> str:
        """Comprueba solo el PIN (no entrega nada). Devuelve "ok", "mal" o "espera"."""
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
        return b64u(self.key)

    def token_text(self) -> str:
        return b64u(self.token)

    def phone_url(self, scheme: str, ip: str, port: int) -> str:
        """0.54: el QR lleva la ficha de emparejamiento, no la clave."""
        return f"{scheme}://{ip}:{port}/#p={self.token_text()}"

    # Saludo de emparejamiento (ver arriba). Nada de esto toca la clave hasta aprobar.

    def _expire_sessions(self, now: float) -> None:
        for sid in [sid for sid, row in self.sessions.items() if now - row["at"] > PAIR_SECONDS]:
            del self.sessions[sid]

    def hello(self, who: str, mode: str, pub_text: str) -> dict:
        if mode not in ("qr", "pin"):
            raise ProtocolError("modo no válido")
        pub = unb64u(pub_text)
        if len(pub) != 32:
            raise ProtocolError("clave no válida")
        priv, mine = x25519_keypair()
        shared = x25519(priv, pub)
        if shared == bytes(32):
            raise ProtocolError("clave no válida")
        sid = secrets.token_hex(16)
        with self._lock:
            now = time.time()
            self._expire_sessions(now)
            if len(self.sessions) >= MAX_SESSIONS:
                oldest = min(self.sessions, key=lambda k: self.sessions[k]["at"])
                del self.sessions[oldest]
            self.sessions[sid] = {"who": who, "mode": mode, "pub": pub, "mine": mine, "shared": shared,
                                  "at": now, "hk": None, "fp": fingerprint(who, pub)}
        return {"sid": sid, "pub": b64u(mine)}

    def claim(self, sid: str, proof_text: str) -> tuple[str, dict | None]:
        """("ok", sesión), ("mal", None), ("espera", None) o ("caducada", None)."""
        if self.locked():
            return "espera", None
        with self._lock:
            self._expire_sessions(time.time())
            row = self.sessions.get(sid)
        if row is None:
            return "caducada", None
        secret = pair_secret(row["mode"], self.token, self.pin)
        hk = handshake_key(secret, row["mode"], row["who"], row["pub"], row["mine"], row["shared"])
        if not hmac.compare_digest(str(proof_text).lower(), proof(hk, "movil")):
            self._fail()
            with self._lock:
                self.sessions.pop(sid, None)  # cada intento pide un saludo nuevo
            return "mal", None
        self._good()
        with self._lock:
            row["hk"] = hk
            row["at"] = time.time()
        return "ok", row

    def session(self, sid: str, proof_text: str) -> dict | None:
        """Sesión ya verificada y su prueba (para /api/pair/wait)."""
        with self._lock:
            self._expire_sessions(time.time())
            row = self.sessions.get(sid)
        if not row or not row["hk"] or not hmac.compare_digest(str(proof_text).lower(), proof(row["hk"], "movil")):
            return None
        return row

    def deliver(self, sid: str) -> str:
        """Entrega la clave sellada con la del saludo.

        0.56: la sesión no se borra al entregar; queda DELIVERED_SECONDS para que una consulta
        repetida o cruzada del mismo móvil (Wi-Fi lenta) reciba la misma respuesta en vez de un
        401 que lo devolvía al PIN. Solo sirve con la prueba del saludo, que solo tiene ese móvil."""
        with self._lock:
            row = self.sessions.get(sid)
            if not row or not row["hk"]:
                raise ProtocolError("sesión no válida")
            first = not row.get("done")
            if first:
                row["done"] = time.time()
                row["at"] = time.time() - PAIR_SECONDS + DELIVERED_SECONDS
        if first and row["mode"] == "qr":
            self.new_token()  # un QR fotografiado no vale para otro dispositivo
        # 0.62: la clave de ESTE móvil, nunca la maestra.
        return b64u(seal(self.device_key_text(row["who"]).encode(), derive(row["hk"], "lazo/pair/box/1")))

    # Firma de peticiones

    def sign(self, method: str, path: str, length: int = 0, now: float | None = None, who: str | None = None) -> dict[str, str]:
        """Cabeceras de firma, como las pone el móvil `who` (sin `who`, con la clave maestra).
        Sirve para pruebas y para el cliente en Python."""
        stamp = int((time.time() if now is None else now) * 1000)
        nonce = secrets.token_hex(16)
        return {
            H_T: str(stamp),
            H_N: nonce,
            H_S: sign_request(self._keys(who)[0], method, path, stamp, nonce, length),
        }

    def verify(self, method: str, path: str, length: int, stamp: str, nonce: str, sig: str, who: str | None = None) -> str:
        """Devuelve "ok", "firma", "hora" o "repetida". Una firma buena solo vale una vez.

        0.62: con `who`, la firma tiene que ser de la clave de ese móvil. El servidor siempre
        lo pasa para las peticiones de fuera; sin `who` solo vale la clave maestra."""
        try:
            when = int(stamp)
        except ValueError:
            return "firma"
        if not (8 <= len(nonce) <= 64 and all(c in "0123456789abcdef" for c in nonce)):
            return "firma"
        expect = sign_request(self._keys(who)[0], method, path, when, nonce, length)
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
            self._away.pop(who, None)

    # 0.69: el móvil avisa antes de cambiar a otro PC de su lista. Este PC no lo da por
    # desconectado (rojo) sino «en otro PC» (naranja) hasta que vuelva, lo expulsen o pasen
    # AWAY_SECONDS. El aviso de «me voy» de la página (/api/bye) no lo borra.

    def phone_away(self, who: str) -> None:
        with self._lock:
            self._seen.pop(who, None)
            self._away[who] = time.time()

    def away_gone(self, who: str) -> None:
        with self._lock:
            self._away.pop(who, None)

    def away_count(self) -> int:
        with self._lock:
            now = time.time()
            for who in [who for who, t in self._away.items() if now - t >= AWAY_SECONDS]:
                del self._away[who]
            return len([who for who in self._away if who not in self._seen])

    def phone_gone(self, who: str = "") -> None:
        with self._lock:
            self._seen.pop(who, None)

    def forget_phones(self) -> None:
        with self._lock:
            self._seen.clear()
            self._away.clear()

    def phone_count(self) -> int:
        with self._lock:
            now = time.time()
            for who in [who for who, last in self._seen.items() if now - last >= ALIVE_SECONDS]:
                del self._seen[who]
            return len(self._seen)

    def phone_online(self) -> bool:
        return self.phone_count() > 0

    # Sello con la clave de este emparejamiento

    def seal(self, data: bytes, who: str | None = None) -> bytes:
        return seal(data, self._keys(who)[1])

    def open(self, blob: bytes, who: str | None = None) -> bytes:
        return open_sealed(blob, self._keys(who)[1])

    def open_to(self, source, length: int, dest: Path, who: str | None = None) -> None:
        open_sealed_to(source, length, dest, self._keys(who)[1])


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


class Arrivals:
    """0.48: diagnóstico de llegada. Guarda solo el instante de cada trama de movimiento
    (una suma a una cola, nada más por trama). Los números se calculan al pedirlos."""

    def __init__(self, keep: int = 1200) -> None:
        import collections

        self._t = collections.deque(maxlen=keep)
        self._lock = threading.Lock()
        self.total = 0

    def note(self, t: float | None = None) -> None:
        self._t.append(time.perf_counter() if t is None else t)
        self.total += 1

    def reset(self) -> None:
        with self._lock:
            self._t.clear()

    def snapshot(self, window: float = 3.0, now: float | None = None) -> dict:
        now = time.perf_counter() if now is None else now
        with self._lock:
            times = [t for t in list(self._t) if now - t <= window]
        gaps = [(b - a) * 1000 for a, b in zip(times, times[1:])]
        out = {"frames": len(times), "fps": round(len(times) / window, 1), "total": self.total,
               "median_ms": None, "p95_ms": None, "max_ms": None,
               "gaps50": 0, "gaps100": 0, "gaps250": 0, "burst": 0, "burst_max": 0}
        if gaps:
            ordered = sorted(gaps)
            out["median_ms"] = round(ordered[len(ordered) // 2], 1)
            out["p95_ms"] = round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 1)
            out["max_ms"] = round(ordered[-1], 1)
            # Un hueco solo cuenta si hay movimiento a los dos lados (no al levantar el dedo).
            moving = [g for g in gaps if g < 1000]
            out["gaps50"] = sum(1 for g in moving if g > 50)
            out["gaps100"] = sum(1 for g in moving if g > 100)
            out["gaps250"] = sum(1 for g in moving if g > 250)
            run = best = 1
            bursty = 0
            for g in gaps:
                if g < 2:
                    run += 1
                    bursty += 1
                else:
                    run = 1
                best = max(best, run)
            out["burst"] = round(bursty / len(gaps), 2)  # parte de tramas pegadas a la anterior
            out["burst_max"] = best if best > 1 else 0
        return out


ARRIVALS = Arrivals()


def pointer_loop(
    sock: socket.socket,
    pairing: Pairing,
    move: Callable[[int, int], object],
    who: str = "",
    require_seal: bool = True,
    arrivals: "Arrivals | None" = None,
) -> None:
    """Lee tramas del mando hasta que cierra. Cada una llama a `move(dx, dy)`.

    Con `require_seal` solo vale lo sellado: cualquier otra trama corta la conexión.
    """
    arrivals = ARRIVALS if arrivals is None else arrivals
    try:
        while True:
            opcode, payload = ws_read(sock)
            got = time.perf_counter()
            pairing.note_phone(who)
            if opcode == 0x8:
                break
            if opcode == 0x9:
                ws_send(sock, 0xA, payload)
                continue
            if opcode in (0x1, 0x2) and require_seal and not (opcode == 0x2 and payload.startswith(MAGIC)):
                raise ProtocolError("trama sin sellar")
            if opcode == 0x2 and payload.startswith(MAGIC):
                payload = pairing.open(payload, who if require_seal else None)  # 0.62: clave de ese móvil
            if opcode == 0x2 and len(payload) == 12 and payload[:4] == b"PIN2":
                # 0.48: eco con la hora del PC al recibir y al contestar, para separar red y proceso.
                ws_send(sock, 0x2, payload + struct.pack("<dd", got * 1000, time.perf_counter() * 1000))
                continue
            if opcode == 0x2 and len(payload) == 12 and payload[:4] == b"PING":
                ws_send(sock, 0x2, payload)  # 0.47: eco para medir el retraso (solo una marca de tiempo)
                continue
            if opcode == 0x2 and len(payload) >= 8:
                arrivals.note(got)
                move(*struct.unpack_from("<ii", payload))
            elif opcode == 0x1:
                parts = payload.decode("ascii", "ignore").split()
                if len(parts) == 2:
                    move(int(parts[0]), int(parts[1]))
    except (OSError, ValueError, EOFError):
        pass
