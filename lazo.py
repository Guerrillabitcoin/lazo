#!/usr/bin/env python3
"""Lazo: mando del PC desde el móvil, en la misma Wi-Fi."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import re
import secrets
import socket
import struct
import subprocess
import sys
import threading
import time
import webbrowser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote

import control

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
VERSION = "0.23"
PIN = ""
PORT = 8787
TOKEN = secrets.token_urlsafe(32)
WIRE_KEY = secrets.token_bytes(32)
FAILS = {"n": 0, "until": 0.0}
FAILS_LOCK = threading.Lock()
VISITS: list[str] = []
VISITS_LOCK = threading.Lock()
MESA_OPENED = False
PAIRED = False
LAST_PHONE = 0.0
PHONE_LOCK = threading.Lock()
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def wire_seal(data: bytes, key: bytes = WIRE_KEY) -> bytes:
    nonce = secrets.token_bytes(12)
    stream = bytearray()
    counter = 0
    while len(stream) < len(data):
        stream += hmac.new(key, nonce + struct.pack(">I", counter), hashlib.sha256).digest()
        counter += 1
    cipher = bytes(left ^ right for left, right in zip(data, stream))
    tag = hmac.new(key, b"LZ2" + nonce + cipher, hashlib.sha256).digest()[:16]
    return b"LZ2" + nonce + cipher + tag


def wire_open(blob: bytes, key: bytes = WIRE_KEY) -> bytes:
    if len(blob) < 31 or not blob.startswith(b"LZ2"):
        raise control.ControlError("cifrado no válido")
    nonce, tag, cipher = blob[3:15], blob[-16:], blob[15:-16]
    expect = hmac.new(key, b"LZ2" + nonce + cipher, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(tag, expect):
        raise control.ControlError("cifrado no válido")
    stream = bytearray()
    counter = 0
    while len(stream) < len(cipher):
        stream += hmac.new(key, nonce + struct.pack(">I", counter), hashlib.sha256).digest()
        counter += 1
    return bytes(left ^ right for left, right in zip(cipher, stream))


def _wire_xor(key: bytes, nonce: bytes, data: bytes, offset: int) -> bytes:
    out = bytearray(len(data))
    pos = 0
    while pos < len(data):
        block_index = (offset + pos) // 32
        skip = (offset + pos) % 32
        block = hmac.new(key, nonce + struct.pack(">I", block_index), hashlib.sha256).digest()
        take = min(32 - skip, len(data) - pos)
        for index in range(take):
            out[pos + index] = data[pos + index] ^ block[skip + index]
        pos += take
    return bytes(out)


def wire_open_to(source, length: int, dest: Path, key: bytes = WIRE_KEY) -> None:
    head = source.read(15)
    if len(head) < 15 or not head.startswith(b"LZ2"):
        raise control.ControlError("cifrado no válido")
    nonce = head[3:15]
    cipher_len = length - 31
    if cipher_len < 0:
        raise control.ControlError("cifrado no válido")
    mac = hmac.new(key, b"LZ2" + nonce, hashlib.sha256)
    offset = 0
    remaining = cipher_len
    with dest.open("wb") as out:
        while remaining:
            chunk = source.read(min(256 * 1024, remaining))
            if not chunk:
                break
            mac.update(chunk)
            out.write(_wire_xor(key, nonce, chunk, offset))
            offset += len(chunk)
            remaining -= len(chunk)
    tag = source.read(16)
    if remaining or not hmac.compare_digest(mac.digest()[:16], tag):
        dest.unlink(missing_ok=True)
        raise control.ControlError("cifrado no válido")


ACTIONS = {
    "move": lambda body: control.move_mouse(body.get("dx", 0), body.get("dy", 0)),
    "click": lambda body: control.mouse_click(body.get("button", "left"), body.get("count", 1)),
    "down": lambda body: control.mouse_down(body.get("button", "left")),
    "up": lambda body: control.mouse_up(body.get("button", "left")),
    "scroll": lambda body: control.scroll_mouse(body.get("dy", 0)),
    "key": lambda body: control.press_key(body.get("key", "")),
    "text": lambda body: control.type_text(body.get("text", "")),
    "volume": lambda body: control.system_volume(body.get("delta", 0)),
    "cursor": lambda body: control.set_cursor_mode(body.get("mode", "normal")),
    "window": lambda body: control.window_action(str(body.get("id", "")), str(body.get("action", ""))),
    "youtube": lambda body: control.youtube(str(body.get("action", "")), body),
    "spotify": lambda body: control.spotify(str(body.get("action", "")), body),
}


def _private(ip: str) -> bool:
    try:
        a, b, _c, _d = (int(part) for part in ip.split("."))
    except ValueError:
        return False
    if a == 192 and b == 168:
        return True
    if a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    return False


def _rank(ip: str) -> tuple[int, str]:
    a, b = (int(part) for part in ip.split(".")[:2])
    if a == 192 and b == 168:
        return (0, ip)
    if a == 10:
        return (1, ip)
    return (2, ip)


SKIP_ADAPTER = (
    "virtual", "vmware", "vbox", "virtualbox", "hyper-v", "vethernet",
    "wsl", "docker", "bluetooth", "loopback", "tap-windows", "tailscale",
    "zerotier", "hamachi", "vpn", "wan miniport", "pseudo", "tun",
    "npcap", "radmin", "virtual",
)


def _adapter_label(name: str) -> str:
    low = name.lower()
    if any(word in low for word in ("wi-fi", "wifi", "wlan", "wireless", "inalámbrica", "inalambrica")):
        return "Wi-Fi"
    if "ethernet" in low or "lan" in low:
        return "Cable"
    return name[:28] or "Red"


def _adapters_from_ipconfig(text: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    blocks = re.split(r"\r?\n(?=\S)", text)
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        name = lines[0].strip().rstrip(":")
        low = name.lower()
        if any(word in low for word in SKIP_ADAPTER):
            continue
        ips: list[str] = []
        for line in lines[1:]:
            low_line = line.lower()
            if "ipv4" not in low_line:
                continue
            ips.extend(ip for ip in IP_RE.findall(line) if _private(ip))
        for ip in ips:
            found.append((_adapter_label(name), ip))
    return found


def _ips_from_system() -> list[tuple[str, str]]:
    if sys.platform == "win32":
        commands = [["ipconfig"]]
    else:
        commands = [["ip", "-4", "-o", "addr"], ["ifconfig"]]
    for cmd in commands:
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=3, text=True, errors="replace")
        except (OSError, subprocess.SubprocessError):
            continue
        if sys.platform == "win32":
            parsed = _adapters_from_ipconfig(out)
            if parsed:
                return parsed
        else:
            ips = [ip for ip in IP_RE.findall(out) if _private(ip)]
            if ips:
                return [("Red", ip) for ip in ips]
    return []


def lan_ips() -> list[str]:
    ordered: list[str] = []
    for _label, ip in _ips_from_system():
        if ip not in ordered:
            ordered.append(ip)
    primary = ""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        primary = sock.getsockname()[0]
        sock.close()
    except OSError:
        pass
    if primary and _private(primary) and primary not in ordered:
        ordered.append(primary)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if _private(ip) and ip not in ordered:
                ordered.append(ip)
    except OSError:
        pass
    wifi = [ip for ip in ordered if any(label == "Wi-Fi" and other == ip for label, other in _ips_from_system())]
    rest = [ip for ip in ordered if ip not in wifi]
    rest.sort(key=_rank)
    if primary in rest and _rank(primary)[0] <= 1:
        rest.remove(primary)
        rest.insert(0, primary)
    ordered = wifi + rest
    return ordered or ["127.0.0.1"]


def lan_targets() -> list[tuple[str, str]]:
    labels = {ip: label for label, ip in _ips_from_system()}
    return [(labels.get(ip, "Red"), ip) for ip in lan_ips()]


def phone_url(ip: str) -> str:
    key = base64.urlsafe_b64encode(WIRE_KEY).decode().rstrip("=")
    return f"http://{ip}:{PORT}/#p={PIN}&k={key}"


def plain_url(ip: str) -> str:
    return f"http://{ip}:{PORT}/"


def qr_svg(url: str) -> str:
    import segno

    svg = segno.make(url, error="l").svg_inline(scale=8, border=4, dark="#000000", light="#ffffff")
    match = re.search(r'width="(\d+(?:\.\d+)?)"\s+height="(\d+(?:\.\d+)?)"', svg)
    if match and "viewBox" not in svg:
        width, height = match.group(1), match.group(2)
        svg = svg.replace("<svg ", f'<svg viewBox="0 0 {width} {height}" ', 1)
    return svg


def note_phone() -> None:
    global LAST_PHONE, PAIRED
    with PHONE_LOCK:
        LAST_PHONE = time.time()
        PAIRED = True


def phone_online() -> bool:
    with PHONE_LOCK:
        return LAST_PHONE > 0 and (time.time() - LAST_PHONE) < 12


def note_visit(ip: str) -> None:
    if ip in ("127.0.0.1", "::1"):
        return
    with VISITS_LOCK:
        if ip not in VISITS:
            VISITS.append(ip)
        del VISITS[:-6]


def connect_page() -> bytes:
    targets = lan_targets()[:3]
    blocks: list[str] = []
    for index, (label, ip) in enumerate(targets):
        url = plain_url(ip)
        try:
            svg = qr_svg(phone_url(ip))
        except Exception:
            svg = ""
        blocks.append(
            f"""<section class="card">
              <h2>{escape(label)}</h2>
              <p class="url">{escape(url)}</p>
              <p class="hint pin-line">PIN {escape(PIN)}</p>
              <div class="qr">{svg if index == 0 else ""}</div>
            </section>"""
        )
    if not blocks:
        blocks.append("<p>No veo una Wi-Fi en este PC.</p>")
    page = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Conectar Lazo</title>
  <style>
    body {{ margin: 0; background: #141210; color: #f3eee6; font-family: "Segoe UI", system-ui, sans-serif; }}
    main {{ max-width: 480px; margin: 0 auto; padding: 28px 16px 48px; text-align: center; }}
    h1 {{ font-weight: 500; font-size: 1.5rem; }}
    h2 {{ font-size: 1rem; font-weight: 500; color: #e07a3d; }}
    .card {{ margin: 0 auto 28px; }}
    .qr {{
      width: min(240px, calc(100vw - 80px));
      aspect-ratio: 1;
      margin: 16px auto 0;
      background: #fff;
      padding: 16px;
      box-sizing: content-box;
    }}
    .qr:empty {{ display: none; }}
    svg {{ width: 100%; height: 100%; display: block; }}
    .url {{ font-size: 1.35rem; color: #fff; word-break: break-all; margin: 14px 0 4px; }}
    .hint {{ letter-spacing: 0.18em; font-size: 1.2rem; }}
    .note, #estado {{ color: #c4b8aa; text-align: left; }}
    a {{ color: #e07a3d; }}
    #estado {{ font-size: 1.05rem; color: #f3eee6; }}
  </style>
</head>
<body>
  <main>
    <h1 id="titulo">Escanea el QR</h1>
    <p id="ayuda" class="note">El QR ya lleva el PIN y cifra el puente. Misma Wi-Fi, sin VPN y sin internet. Quien escuche la red ve ruido, no lo que copias ni los archivos. Si el QR no abre, escribe la dirección y el PIN a mano.</p>
    <p id="estado">Todavía no llega el móvil.</p>
    <p class="note"><a href="/mesa">Abrir el puente Wi-Fi</a> para pegar texto y soltar archivos.</p>
    {''.join(blocks)}
  </main>
  <script>
    async function tick() {{
      try {{
        const data = await fetch("/api/seen").then((res) => res.json());
        const pinBits = document.querySelectorAll(".pin-line, #ayuda, #titulo");
        if (data.paired) {{
          document.querySelector("#estado").textContent = "Móvil conectado";
          pinBits.forEach((el) => {{ el.hidden = true; }});
        }} else {{
          document.querySelector("#estado").textContent = "Escanea el QR";
          pinBits.forEach((el) => {{ el.hidden = false; }});
        }}
      }} catch (_err) {{}}
    }}
    setInterval(tick, 2000);
  </script>
</body>
</html>"""
    return page.encode()


def cookies(header: str | None) -> dict[str, str]:
    found: dict[str, str] = {}
    if not header:
        return found
    for part in header.split(";"):
        if "=" not in part:
            continue
        key, value = part.strip().split("=", 1)
        found[key] = value
    return found


def _ws_read(sock: socket.socket) -> tuple[int, bytes]:
    head = _ws_exact(sock, 2)
    opcode = head[0] & 0x0F
    masked = head[1] & 0x80
    length = head[1] & 0x7F
    if length == 126:
        length = int.from_bytes(_ws_exact(sock, 2), "big")
    elif length == 127:
        length = int.from_bytes(_ws_exact(sock, 8), "big")
    if length > 64:
        raise ValueError("trama larga")
    mask = _ws_exact(sock, 4) if masked else b""
    data = _ws_exact(sock, length) if length else b""
    if mask:
        data = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
    return opcode, data


def _ws_exact(sock: socket.socket, size: int) -> bytes:
    buf = b""
    while len(buf) < size:
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise EOFError
        buf += chunk
    return buf


def _ws_send(sock: socket.socket, opcode: int, payload: bytes) -> None:
    frame = bytes([0x80 | opcode, len(payload)]) + payload
    sock.sendall(frame)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def _authed(self) -> bool:
        if self.client_address[0] in ("127.0.0.1", "::1"):
            return True
        header = self.headers.get("X-Lazo", "")
        if header and len(header) == len(TOKEN) and hmac.compare_digest(header, TOKEN):
            note_phone()
            return True
        got = cookies(self.headers.get("Cookie")).get("lazo", "")
        if got and len(got) == len(TOKEN) and hmac.compare_digest(got, TOKEN):
            note_phone()
            return True
        return False

    def _send(self, code: int, payload: dict | None = None, body: bytes | None = None, content_type: str = "application/json") -> None:
        data = body if body is not None else json.dumps(payload or {}, ensure_ascii=False).encode()
        if body is None and self.headers.get("X-Seal") == "1":
            data = wire_seal(data)
            content_type = "application/octet-stream"
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 120000:
            raise control.ControlError("petición demasiado grande")
        raw = self.rfile.read(length) if length else b"{}"
        if raw.startswith(b"LZ2"):
            raw = wire_open(raw)
        try:
            data = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError as exc:
            raise control.ControlError("JSON no válido") from exc
        if not isinstance(data, dict):
            raise control.ControlError("JSON no válido")
        return data

    def do_GET(self) -> None:  # noqa: N802
        note_visit(self.client_address[0])
        path = self.path.split("?", 1)[0]
        if path == "/ws":
            self._pointer_socket()
            return
        if path in ("/", "/index.html"):
            self._file(STATIC / "index.html", "text/html; charset=utf-8")
            return
        if path == "/app.css":
            self._file(STATIC / "app.css", "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self._file(STATIC / "app.js", "text/javascript; charset=utf-8")
            return
        if path == "/seal.js":
            self._file(STATIC / "seal.js", "text/javascript; charset=utf-8")
            return
        if path == "/mesa":
            self._file(STATIC / "mesa.html", "text/html; charset=utf-8")
            return
        if path == "/conectar":
            host = self.client_address[0]
            if host not in ("127.0.0.1", "::1"):
                self._send(404, {"error": "no está"})
                return
            self._send(200, body=connect_page(), content_type="text/html; charset=utf-8")
            return
        if path == "/api/seen":
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self._send(404, {"error": "no está"})
                return
            self._send(200, {"visits": list(VISITS), "paired": phone_online()})
            return
        if path == "/api/windows":
            self._guard(lambda _body: {"windows": control.list_windows()})
            return
        if path == "/api/clipboard":
            self._guard(lambda _body: control.clipboard_history())
            return
        if path == "/api/files":
            self._guard(lambda _body: control.list_files())
            return
        if path == "/api/photos":
            self._guard(lambda _body: control.list_photos())
            return
        if path.startswith("/api/files/"):
            self._download(path.rsplit("/", 1)[-1])
            return
        if path == "/api/status":
            self._guard(lambda _body: control.status())
            return
        if path == "/api/caret":
            self._guard(lambda _body: {"typing": control.typing_focus()})
            return
        self._send(404, {"error": "no está"})

    def _pointer_socket(self) -> None:
        if self.headers.get("Upgrade", "").lower() != "websocket":
            self._send(426, {"error": "hace falta websocket"})
            return
        if not self._authed():
            self._send(401, {"error": "Entra con el PIN"})
            return
        key = self.headers.get("Sec-WebSocket-Key", "")
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        sock = self.connection
        sock.settimeout(None)
        note_phone()
        try:
            while True:
                opcode, payload = _ws_read(sock)
                note_phone()
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    _ws_send(sock, 0xA, payload)
                    continue
                if opcode == 0x2 and payload.startswith(b"LZ2"):
                    payload = wire_open(payload)
                if opcode == 0x2 and len(payload) >= 8:
                    dx, dy = struct.unpack_from("<ii", payload)
                    control.move_mouse(dx, dy)
                elif opcode == 0x1:
                    parts = payload.decode("ascii", "ignore").split()
                    if len(parts) == 2:
                        control.move_mouse(int(parts[0]), int(parts[1]))
        except (OSError, ValueError, EOFError, control.ControlError):
            pass
        finally:
            self.close_connection = True
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def do_POST(self) -> None:  # noqa: N802
        note_visit(self.client_address[0])
        path = self.path.split("?", 1)[0]
        if path == "/api/login":
            self._login()
            return
        if path == "/api/clipboard":
            self._push_clip()
            return
        if path == "/api/files":
            self._upload()
            return
        if path == "/api/photos/check":
            self._photo_check()
            return
        if path == "/api/photos":
            self._upload_photo()
            return
        if path == "/api/photos/open":
            self._photo_open()
            return
        action = path.removeprefix("/api/")
        if action not in ACTIONS:
            self._send(404, {"error": "no está"})
            return
        self._guard(ACTIONS[action])

    def _file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self._send(404, {"error": "falta el archivo"})
            return
        self._send(200, body=path.read_bytes(), content_type=content_type)

    def _login(self) -> None:
        try:
            body = self._read_json()
        except control.ControlError as exc:
            self._send(400, {"error": str(exc)})
            return
        now = time.time()
        with FAILS_LOCK:
            if now < FAILS["until"]:
                self._send(429, {"error": "Demasiados intentos. Espera un momento."})
                return
            pin = str(body.get("pin", ""))
            if len(pin) != len(PIN) or not hmac.compare_digest(pin, PIN):
                FAILS["n"] += 1
                if FAILS["n"] >= 8:
                    FAILS["until"] = now + 30
                    FAILS["n"] = 0
                self._send(401, {"error": "PIN incorrecto"})
                return
            FAILS["n"] = 0
        note_phone()
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            maybe_open_mesa()
        payload = json.dumps({"ok": True, "token": TOKEN}).encode()
        content_type = "application/json"
        if self.headers.get("X-Seal") == "1":
            payload = wire_seal(payload)
            content_type = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Set-Cookie", f"lazo={TOKEN}; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _guard(self, fn) -> None:
        if not self._authed():
            self._send(401, {"error": "Entra con el PIN"})
            return
        try:
            if self.command == "POST":
                body = self._read_json()
            else:
                body = {}
            result = fn(body)
        except control.ControlError as exc:
            self._send(400, {"error": str(exc)})
            return
        except Exception:
            self._send(500, {"error": "El PC no pudo hacer eso"})
            return
        if isinstance(result, dict):
            self._send(200, result)
        else:
            self._send(200, {"ok": True, "detail": result or ""})

    def _push_clip(self) -> None:
        if not self._authed():
            self._send(401, {"error": "Entra con el PIN"})
            return
        try:
            body = self._read_json()
            result = control.clipboard_history(str(body.get("text", "")), auto=bool(body.get("auto")))
        except control.ControlError as exc:
            self._send(400, {"error": str(exc)})
            return
        self._send(200, result)

    def _upload(self) -> None:
        if not self._authed():
            self._send(401, {"error": "Entra con el PIN"})
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > 80 * 1024 * 1024:
            self._send(400, {"error": "El archivo pasa de 80 MB o está vacío"})
            return
        data = self.rfile.read(length)
        if data.startswith(b"LZ2"):
            try:
                data = wire_open(data)
            except control.ControlError as exc:
                self._send(400, {"error": str(exc)})
                return
        name = unquote(self.headers.get("X-Filename", "archivo"))
        try:
            self._send(200, control.save_file(name, data))
        except control.ControlError as exc:
            self._send(400, {"error": str(exc)})

    def _photo_check(self) -> None:
        if not self._authed():
            self._send(401, {"error": "Entra con el PIN"})
            return
        try:
            body = self._read_json()
            self._send(200, control.photo_status(str(body.get("name", "")), int(body.get("size", 0))))
        except (control.ControlError, TypeError, ValueError) as exc:
            self._send(400, {"error": str(exc)})

    def _photo_open(self) -> None:
        if not self._authed():
            self._send(401, {"error": "Entra con el PIN"})
            return
        try:
            self._send(200, control.open_photos_folder())
        except control.ControlError as exc:
            self._send(400, {"error": str(exc)})

    def _upload_photo(self) -> None:
        if not self._authed():
            self._send(401, {"error": "Entra con el PIN"})
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        name = unquote(self.headers.get("X-Filename", "foto"))
        sealed = self.headers.get("X-Seal") == "1"
        plain_size = int(self.headers.get("X-Plain-Size", "0") or 0) if sealed else length
        try:
            started = control.start_photo(name, plain_size)
        except control.ControlError as exc:
            self._send(400, {"error": str(exc)})
            return
        if started is None:
            if length:
                self.rfile.read(length)
            self._send(200, {"skipped": True})
            return
        part, final = started
        try:
            if sealed:
                wire_open_to(self.rfile, length, part)
            else:
                remaining = length
                with part.open("wb") as out:
                    while remaining > 0:
                        chunk = self.rfile.read(min(256 * 1024, remaining))
                        if not chunk:
                            break
                        out.write(chunk)
                        remaining -= len(chunk)
            self._send(200, control.finish_photo(part, final, plain_size))
        except control.ControlError as exc:
            self._send(400, {"error": str(exc)})
        except OSError:
            part.unlink(missing_ok=True)
            self._send(400, {"error": "No se pudo guardar"})

    def _download(self, file_id: str) -> None:
        if not self._authed():
            self._send(401, {"error": "Entra con el PIN"})
            return
        try:
            name, data = control.read_file(file_id)
        except control.ControlError as exc:
            self._send(404, {"error": str(exc)})
            return
        except OSError:
            self._send(404, {"error": "ese archivo ya no está"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(name)}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_DELETE(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if not path.startswith("/api/files/"):
            self._send(404, {"error": "no está"})
            return
        if not self._authed():
            self._send(401, {"error": "Entra con el PIN"})
            return
        self._send(200, control.delete_file(path.rsplit("/", 1)[-1]))


def maybe_open_mesa() -> None:
    global MESA_OPENED
    if MESA_OPENED:
        return
    MESA_OPENED = True
    webbrowser.open(f"http://127.0.0.1:{PORT}/mesa")


def main() -> None:
    global PIN, PORT
    parser = argparse.ArgumentParser(description="Mando Lazo para este PC")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--pin", default="")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    PIN = args.pin if args.pin.isdigit() and len(args.pin) == 4 else f"{secrets.randbelow(9000) + 1000}"
    PORT = args.port
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print()
    print(f"  LaZoo {VERSION}")
    print(f"  PIN: {PIN}")
    print("  En el PC se abre la dirección. Escríbela en el móvil, no hace falta el QR.")
    print("  Misma Wi-Fi de casa. No hace falta VPN. Si no se abre, entra aquí en el PC:")
    print(f"    http://127.0.0.1:{args.port}/conectar")
    for label, ip in lan_targets():
        print(f"  {label}: {plain_url(ip)}")
    print("  Al entrar el móvil se abre el puente Wi-Fi. No pasa por internet.")
    print("  No abras este puerto en el router.")
    print()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        control.set_cursor_mode("normal")
    except Exception:
        pass
    control.watch_physical_mouse()
    if not args.no_browser:
        threading.Timer(0.3, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}/conectar")).start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nLazo cerrado.")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
