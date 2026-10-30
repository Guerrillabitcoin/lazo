#!/usr/bin/env python3
"""Lazo: mando del PC desde el móvil, en la misma Wi-Fi."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

import control
import descargas
import protocol
import puente
import sobre

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
VERSION = "0.40"
PAIRING = protocol.Pairing()
PORT = 8787
VISITS: list[str] = []
VISITS_LOCK = threading.Lock()
MESA_OPENED = False
SCHEME = "http"
UPLOADS = puente.Uploads(control.received_dir)
UP_PATH = re.compile(r"/api/up/([0-9a-f]{20})/(\d{1,7}|done|cancel)")
GET_PATH = re.compile(r"/api/get/(nube|dl)/([0-9A-Za-z_-]{1,40})/(\d{1,7}|info)")
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


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
    "lab": lambda body: control.lab(str(body.get("action", "")), body),
    "system": lambda body: control.system_action(str(body.get("action", "")), body),
    "tabs": lambda body: control.window_tabs(str(body.get("id", ""))),
    "tab": lambda body: control.tab_action(str(body.get("id", "")), str(body.get("action", "")), body.get("index")),
    "screen": lambda body: control.window_to_screen(str(body.get("id", "")), body.get("screen", 0)),
}

DL_ACTIONS = {
    "/api/dl/info": lambda body: descargas.get_info(body.get("url", ""), bool(body.get("playlist"))),
    "/api/dl/start": lambda body: descargas.QUEUE.start(body.get("url", ""), str(body.get("choice", "")), str(body.get("title", "")), bool(body.get("playlist"))),
    "/api/dl/cancel": lambda body: descargas.QUEUE.cancel(str(body.get("id", ""))),
    "/api/dl/install": lambda body: descargas.install(str(body.get("what", "all"))),
    "/api/dl/update": lambda _body: descargas.update(),
    "/api/dl/open": lambda _body: descargas.open_folder(),
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
    return PAIRING.phone_url(SCHEME, ip, PORT)


def plain_url(ip: str) -> str:
    return f"{SCHEME}://{ip}:{PORT}/"


def qr_svg(url: str) -> str:
    import segno

    svg = segno.make(url, error="l").svg_inline(scale=8, border=4, dark="#000000", light="#ffffff")
    match = re.search(r'width="(\d+(?:\.\d+)?)"\s+height="(\d+(?:\.\d+)?)"', svg)
    if match and "viewBox" not in svg:
        width, height = match.group(1), match.group(2)
        svg = svg.replace("<svg ", f'<svg viewBox="0 0 {width} {height}" ', 1)
    return svg


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
              <p class="hint pin-line">PIN {escape(PAIRING.pin)}</p>
              <div class="qr">{svg if index == 0 else ""}</div>
              <h2>{escape(label)}</h2>
              <p class="url">{escape(url)}</p>
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
    main {{ max-width: 520px; margin: 0 auto; padding: 48px 16px; text-align: center; }}
    .top {{
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
    }}
    .brand {{
      display: flex;
      align-items: baseline;
      justify-content: center;
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      font-style: italic;
      font-size: 72px;
      line-height: 1;
    }}
    .ver {{ margin: 0; font-size: 12px; letter-spacing: 0.14em; color: #c4b8aa; }}
    .oo {{ display: inline-flex; align-items: center; }}
    .bridge {{
      width: 0; height: 4px; border-radius: 99px; background: transparent;
      transition: width 0.35s ease, background 0.35s ease, box-shadow 0.35s ease;
    }}
    .o.right {{ transition: margin-left 0.35s ease; }}
    .top[data-link="on"] .bridge {{ width: 28px; background: #3dbe6e; box-shadow: 0 0 12px #3dbe6e; }}
    .top[data-link="on"] .oo {{ color: #3dbe6e; }}
    .top[data-link="off"] .o.right {{ margin-left: -0.55em; }}
    .top[data-link="off"] .oo {{ color: #e23b3b; text-shadow: 0 0 16px rgba(226, 59, 59, 0.9); }}
    #link-label {{ margin: 4px 0 0; font-size: 13px; letter-spacing: 0.08em; text-transform: uppercase; }}
    .top[data-link="on"] #link-label {{ color: #3dbe6e; }}
    .top[data-link="off"] #link-label {{ color: #e23b3b; }}
    h1 {{ font-weight: 500; font-size: 1.4rem; margin: 18px 0 8px; }}
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
    .hint {{ margin: 8px 0 0; letter-spacing: 0.18em; font-size: 2rem; color: #fff; }}
    .note {{ color: #c4b8aa; font-size: 0.95rem; }}
    a {{ color: #e07a3d; }}
    body.on #pair {{ display: none; }}
    #pair {{ display: block; }}
  </style>
</head>
<body>
  <main>
    <header id="status" class="top" data-link="off">
      <div class="brand" aria-hidden="true"><span>LaZ</span><span class="oo"><span class="o">o</span><span class="bridge"></span><span class="o right">o</span></span></div>
      <p class="ver">0.40</p>
      <p id="link-label">Sin conexión</p>
    </header>
    <div id="pair">
      {''.join(blocks)}
      <p id="ayuda" class="note">Misma Wi-Fi. Si el navegador dice que no es segura, es la dirección de casa.</p>
    </div>
    <p class="note"><a href="/mesa">Abrir el puente Wi-Fi</a></p>
  </main>
  <script>
    async function tick() {{
      try {{
        const data = await fetch("/api/seen").then((res) => res.json());
        const bar = document.querySelector("#status");
        const on = data.paired === true;
        document.body.classList.toggle("on", on);
        bar.dataset.link = on ? "on" : "off";
        document.querySelector("#link-label").textContent = on ? "Móvil conectado" : "Sin conexión";
      }} catch (_err) {{}}
    }}
    tick();
    setInterval(tick, 2000);
  </script>
</body>
</html>"""
    return page.encode()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    remote = True
    denied = ""

    def _loopback(self) -> bool:
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return host in ("127.0.0.1", "localhost", "::1")

    def _ws_query(self) -> dict[str, str]:
        return {key: values[0] for key, values in parse_qs(urlsplit(self.path).query).items()}

    def _who(self, ws: bool = False) -> str:
        found = self._ws_query().get("i", "") if ws else self.headers.get(protocol.H_ID, "")
        if re.fullmatch(r"[0-9a-f]{8,40}", found or ""):
            return found
        return self.client_address[0]

    def _authed(self, ws: bool = False) -> bool:
        """El PC se fía de sí mismo, pero no de una web abierta en su navegador: pide la
        cabecera `X-Lazo-Local` (una web ajena no puede ponerla) y un Host de este PC. El
        móvil firma cada petición con la clave del QR; ver protocol.py."""
        self.remote = not self._loopback()
        self.denied = ""
        if not self.remote:
            if not self._host_ok():
                return False
            if ws:
                origin = self.headers.get("Origin")
                return not origin or urlsplit(origin).netloc == self.headers.get("Host")
            return self.headers.get("X-Lazo-Local") == "1"
        path = self.path.split("?", 1)[0]
        if ws:
            query = self._ws_query()
            got, length = (query.get("t", ""), query.get("n", ""), query.get("s", "")), 0
        else:
            got = tuple(self.headers.get(name, "") for name in (protocol.H_T, protocol.H_N, protocol.H_S))
            length = int(self.headers.get("Content-Length", "0") or 0)
        if not got[2] or self._who(ws) == self.client_address[0]:
            return False
        self.denied = PAIRING.verify(self.command, path, length, *got)
        if self.denied != "ok":
            return False
        PAIRING.note_phone(self._who(ws))
        maybe_open_mesa()
        return True

    def _drain(self) -> None:
        """Lee el cuerpo que no vamos a usar; en Windows, cerrar con datos sin leer corta la respuesta."""
        try:
            left = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return
        if left > 4 * 1024 * 1024:
            return
        self.connection.settimeout(2)
        while left > 0:
            chunk = self.rfile.read(min(left, 65536))
            if not chunk:
                break
            left -= len(chunk)

    def _unauth(self) -> None:
        self.close_connection = True
        self._drain()
        if self.denied == "hora":
            self._send(401, {"error": "El reloj del móvil no coincide con el del PC", "clock": True})
        else:
            self._send(401, {"error": "Entra con el QR"})

    def _send(self, code: int, payload: dict | None = None, body: bytes | None = None, content_type: str = "application/json", seal: bool = True) -> None:
        data = body if body is not None else json.dumps(payload or {}, ensure_ascii=False).encode()
        if body is None and seal and self.headers.get("X-Seal") == "1":
            data = PAIRING.seal(data)
            content_type = "application/octet-stream"
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self, need_seal: bool | None = None) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 120000:
            raise control.ControlError("petición demasiado grande")
        raw = self.rfile.read(length) if length else b"{}"
        if (self.remote if need_seal is None else need_seal) and length and not raw.startswith(protocol.MAGIC):
            raise control.ControlError("hace falta cifrado")
        if raw.startswith(protocol.MAGIC):
            try:
                raw = PAIRING.open(raw)
            except protocol.ProtocolError as exc:
                raise control.ControlError(str(exc)) from exc
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
        if path == "/puente-worker.js":
            self._file(STATIC / "puente-worker.js", "text/javascript; charset=utf-8")
            return
        if path == "/mesa":
            self._file(STATIC / "mesa.html", "text/html; charset=utf-8")
            return
        if path == "/conectar":
            host = self.client_address[0]
            if not (_local_pc(host) and self._host_ok()):
                self._send(404, {"error": "no está"})
                return
            self._send(200, body=connect_page(), content_type="text/html; charset=utf-8")
            return
        if path == "/api/time":
            self._send(200, {"t": int(time.time() * 1000)}, seal=False)
            return
        if path == "/api/seen":
            if not (_local_pc(self.client_address[0]) and self._host_ok()):
                self._send(404, {"error": "no está"})
                return
            self._send(200, {"visits": list(VISITS), "paired": PAIRING.phone_online()})
            return
        if path == "/api/windows":
            self._guard(lambda _body: control.windows_with_icons())
            return
        if path == "/api/screens":
            self._guard(lambda _body: {**control.screens_info(), **control.system_caps()})
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
        if path == "/api/dl/tools":
            self._guard(lambda _body: descargas.tools_status())
            return
        if path == "/api/dl/status":
            self._guard(lambda _body: descargas.QUEUE.status())
            return
        if path.startswith("/api/dl/file/"):
            self._dl_file(path.rsplit("/", 1)[-1])
            return
        match = GET_PATH.fullmatch(path)
        if match:
            self._get_chunk(*match.groups())
            return
        if path.startswith("/api/files/"):
            self._download(path.rsplit("/", 1)[-1])
            return
        if path == "/api/status":
            self._guard(lambda _body: {**control.status(), "version": VERSION})
            return
        if path == "/api/about":
            self._guard(lambda _body: sobre.about(ROOT, VERSION, qr_svg))
            return
        if path == "/api/caret":
            self._guard(lambda _body: {"typing": control.typing_focus()})
            return
        self._send(404, {"error": "no está"})

    def _pointer_socket(self) -> None:
        if self.headers.get("Upgrade", "").lower() != "websocket":
            self._send(426, {"error": "hace falta websocket"})
            return
        if not self._authed(ws=True):
            self._unauth()
            return
        accept = protocol.ws_accept(self.headers.get("Sec-WebSocket-Key", ""))
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        sock = self.connection
        sock.settimeout(None)
        who = self._who(ws=True)
        try:
            protocol.pointer_loop(sock, PAIRING, control.move_mouse, who, require_seal=self.remote)
        except control.ControlError:
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
        if path == "/api/up/start":
            self._guard(lambda body: UPLOADS.start(str(body.get("name", "")), body.get("size"), str(body.get("key", ""))[:200], self._who()))
            return
        match = UP_PATH.fullmatch(path)
        if match:
            up_id, step = match.groups()
            if step == "done":
                self._guard(lambda body: UPLOADS.finish(up_id, str(body.get("sha256", ""))))
            elif step == "cancel":
                self._guard(lambda _body: UPLOADS.cancel(up_id))
            else:
                self._up_chunk(up_id, int(step))
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
        if path == "/api/bye":
            PAIRING.phone_gone(parse_qs(urlsplit(self.path).query).get("i", [self._who()])[0])
            self._send(200, {"ok": True})
            return
        if path == "/api/about/check":
            self._guard(lambda _body: sobre.check_update(VERSION))
            return
        if path in DL_ACTIONS:
            self._guard(DL_ACTIONS[path])
            return
        action = path.removeprefix("/api/")
        if action not in ACTIONS:
            self._send(404, {"error": "no está"})
            return
        self._guard(ACTIONS[action])

    def _file(self, path: Path, content_type: str) -> None:
        """Estáticos con ETag: el móvil revalida (304, sin cuerpo) y nunca se queda con
        una versión vieja tras actualizar, porque la etiqueta cambia con el contenido."""
        try:
            data, tag = _static(path)
        except OSError:
            self._send(404, {"error": "falta el archivo"})
            return
        if self.headers.get("If-None-Match") == tag:
            self.send_response(304)
            self.send_header("ETag", tag)
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("ETag", tag)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _login(self) -> None:
        """Emparejar con el PIN cuando no hay cámara. Devuelve la clave sin cifrar:
        es la parte menos segura, y el QR es el camino recomendado."""
        self.remote = not self._loopback()
        try:
            body = self._read_json(need_seal=False)
        except control.ControlError as exc:
            self._send(400, {"error": str(exc)}, seal=False)
            return
        result = PAIRING.login(str(body.get("pin", "")))
        if result == "espera":
            self._send(429, {"error": "Demasiados intentos. Espera un momento."}, seal=False)
            return
        if result == "mal":
            self._send(401, {"error": "PIN incorrecto"}, seal=False)
            return
        if self.remote:
            maybe_open_mesa()
        self._send(200, {"ok": True, "key": PAIRING.key_text()}, seal=False)

    def _guard(self, fn) -> None:
        if not self._authed():
            self._unauth()
            return
        try:
            if self.command == "POST":
                body = self._read_json()
            else:
                body = {}
            result = fn(body)
        except (control.ControlError, puente.BridgeError) as exc:
            self._send(400, {"error": str(exc)})
            return
        except OSError:
            self._send(500, {"error": "El PC no pudo leer o escribir el disco"})
            return
        except (ValueError, TypeError, OverflowError):
            self._send(400, {"error": "Dato no válido"})
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
            self._unauth()
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
            self._unauth()
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        name = unquote(self.headers.get("X-Filename", "archivo"))
        if not self.remote and self.headers.get("X-Seal") != "1" and length > 8 * 1024 * 1024:
            # Desde la ventana del PC: sin sello y a disco a trozos, sin el tope de 80 MB.
            try:
                self._send(200, control.save_file_stream(name, self.rfile, length, puente.MAX_FILE))
            except control.ControlError as exc:
                self.close_connection = True
                self._send(400, {"error": str(exc)})
            return
        if length <= 0 or length > 80 * 1024 * 1024 + 4096:
            self.close_connection = True
            self._send(400, {"error": "El archivo pasa de 80 MB o está vacío"})
            return
        data = self.rfile.read(length)
        if self.remote and not data.startswith(protocol.MAGIC):
            self._send(400, {"error": "hace falta cifrado"})
            return
        if data.startswith(protocol.MAGIC):
            try:
                data = PAIRING.open(data)
            except protocol.ProtocolError as exc:
                self._send(400, {"error": str(exc)})
                return
        try:
            self._send(200, control.save_file(name, data))
        except control.ControlError as exc:
            self._send(400, {"error": str(exc)})

    def _up_chunk(self, up_id: str, index: int) -> None:
        """Un trozo de una subida: sellado si viene del móvil, firmado como cualquier petición."""
        if not self._authed():
            self._unauth()
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length < 0 or length > puente.CHUNK + 64:
            self.close_connection = True
            self._send(413, {"error": "Trozo demasiado grande"})
            return
        data = b""
        left = length
        parts = []
        while left > 0:
            got = self.rfile.read(min(left, 1024 * 1024))
            if not got:
                break
            parts.append(got)
            left -= len(got)
        if left:
            self.close_connection = True
            self._send(400, {"error": "Se cortó el trozo"})
            return
        data = b"".join(parts)
        if data.startswith(protocol.MAGIC) and self.headers.get("X-Seal") == "1":
            try:
                data = PAIRING.open(data)
            except protocol.ProtocolError:
                self._send(400, {"error": "Trozo dañado"})
                return
        elif self.remote:
            self._send(400, {"error": "hace falta cifrado"})
            return
        try:
            self._send(200, UPLOADS.write(up_id, index, data))
        except puente.BridgeError as exc:
            self._send(400, {"error": str(exc)})

    def _get_target(self, kind: str, item: str) -> tuple[Path, str, dict]:
        if kind == "dl":
            target = descargas.QUEUE.file(item)
            return target, target.name, {}
        row, target = control.file_path(item)
        return target, row["name"], row

    def _get_chunk(self, kind: str, item: str, step: str) -> None:
        """PC -> móvil por trozos: `info` da tamaño, trozos y SHA-256; luego cada trozo sellado."""
        if not self._authed():
            self._unauth()
            return
        sealed = self.headers.get("X-Seal") == "1"
        if self.remote and not sealed:
            self._send(400, {"error": "hace falta cifrado"})
            return
        try:
            target, name, row = self._get_target(kind, item)
            small = bool(row) and not row.get("raw")
            if small:
                data = control.read_file(item)[1]
                size = len(data)
            else:
                size = target.stat().st_size
            if step == "info":
                digest = _sha_cached(target, size, data if small else None)
                total = max(1, (size + puente.CHUNK - 1) // puente.CHUNK)
                self._send(200, {"name": name, "size": size, "chunk": puente.CHUNK, "total": total, "sha256": digest})
                return
            index = int(step)
            if small:
                if not 0 <= index < max(1, (size + puente.CHUNK - 1) // puente.CHUNK):
                    raise puente.BridgeError("Trozo fuera de rango")
                piece = data[index * puente.CHUNK : (index + 1) * puente.CHUNK]
            else:
                piece = puente.read_chunk(target, index)
        except (control.ControlError, puente.BridgeError) as exc:
            self._send(404, {"error": str(exc)})
            return
        except OSError:
            self._send(404, {"error": "ese archivo ya no está"})
            return
        body = PAIRING.seal(piece) if sealed else piece
        self._send(200, body=body, content_type="application/octet-stream")

    def _photo_check(self) -> None:
        if not self._authed():
            self._unauth()
            return
        try:
            body = self._read_json()
            self._send(200, control.photo_status(str(body.get("name", "")), int(body.get("size", 0))))
        except (control.ControlError, TypeError, ValueError) as exc:
            self._send(400, {"error": str(exc)})

    def _photo_open(self) -> None:
        if not self._authed():
            self._unauth()
            return
        try:
            self._send(200, control.open_photos_folder())
        except control.ControlError as exc:
            self._send(400, {"error": str(exc)})

    def _upload_photo(self) -> None:
        if not self._authed():
            self._unauth()
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        name = unquote(self.headers.get("X-Filename", "foto"))
        sealed = self.headers.get("X-Seal") == "1"
        if self.remote and not sealed:
            self.close_connection = True
            self._send(400, {"error": "hace falta cifrado"})
            return
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
                PAIRING.open_to(self.rfile, length, part)
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
        except (control.ControlError, protocol.ProtocolError) as exc:
            self._send(400, {"error": str(exc)})
        except OSError:
            part.unlink(missing_ok=True)
            self._send(400, {"error": "No se pudo guardar"})

    def _download(self, file_id: str) -> None:
        if not self._authed():
            self._unauth()
            return
        try:
            row, target = control.file_path(file_id)
            if row.get("raw"):
                if self.headers.get("X-Seal") == "1":
                    self._send(400, {"error": "Archivo grande: actualiza la página del móvil"})
                    return
                size = target.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(size))
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(row['name'])}")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                with target.open("rb") as src:
                    shutil.copyfileobj(src, self.wfile, 1024 * 1024)
                return
            name, data = control.read_file(file_id)
        except control.ControlError as exc:
            self._send(404, {"error": str(exc)})
            return
        except OSError:
            self._send(404, {"error": "ese archivo ya no está"})
            return
        if self.headers.get("X-Seal") == "1":
            data = PAIRING.seal(data)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(name)}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _dl_file(self, job_id: str) -> None:
        """Manda al móvil un archivo del Descargatodo, sellado como el puente."""
        if not self._authed():
            self._unauth()
            return
        try:
            target = descargas.QUEUE.file(job_id)
            size = target.stat().st_size
        except (control.ControlError, OSError) as exc:
            self._send(404, {"error": str(exc) or "ese archivo ya no está"})
            return
        sealed = self.headers.get("X-Seal") == "1"
        if self.remote and not sealed:
            self._send(400, {"error": "hace falta cifrado"})
            return
        if sealed and size > descargas.SEND_CAP:
            self._send(413, {"error": "Pasa de 400 MB: cógelo en la carpeta Descargas/LaZoo del PC"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        if sealed:
            data = PAIRING.seal(target.read_bytes())
            self.send_header("Content-Length", str(len(data)))
        else:
            self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(target.name)}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if sealed:
            self.wfile.write(data)
            return
        with target.open("rb") as src:
            shutil.copyfileobj(src, self.wfile, 256 * 1024)

    def do_DELETE(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if not path.startswith("/api/files/"):
            self._send(404, {"error": "no está"})
            return
        if not self._authed():
            self._unauth()
            return
        self._send(200, control.delete_file(path.rsplit("/", 1)[-1]))


_STATIC_CACHE: dict[str, tuple[float, int, bytes, str]] = {}


def _static(path: Path) -> tuple[bytes, str]:
    stat = path.stat()
    hit = _STATIC_CACHE.get(str(path))
    if hit and hit[0] == stat.st_mtime and hit[1] == stat.st_size:
        return hit[2], hit[3]
    import hashlib

    data = path.read_bytes()
    tag = '"' + hashlib.sha256(data).hexdigest()[:20] + '"'
    _STATIC_CACHE[str(path)] = (stat.st_mtime, stat.st_size, data, tag)
    return data, tag


_SHA_CACHE: dict[tuple[str, int, float], str] = {}
_SHA_LOCK = threading.Lock()


def _sha_cached(path: Path, size: int, data: bytes | None = None) -> str:
    try:
        key = (str(path), size, path.stat().st_mtime)
    except OSError:
        key = (str(path), size, 0.0)
    with _SHA_LOCK:
        if key in _SHA_CACHE:
            return _SHA_CACHE[key]
    import hashlib

    digest = hashlib.sha256(data).hexdigest() if data is not None else puente.file_sha256(path)
    with _SHA_LOCK:
        if len(_SHA_CACHE) > 64:
            _SHA_CACHE.clear()
        _SHA_CACHE[key] = digest
    return digest


def maybe_open_mesa() -> None:
    global MESA_OPENED
    if MESA_OPENED:
        return
    MESA_OPENED = True
    open_local(f"http://127.0.0.1:{PORT}/mesa")


def _local_pc(host: str) -> bool:
    host = host.split("%", 1)[0]
    return host in {"127.0.0.1", "::1", "localhost"} or host.endswith("127.0.0.1")


def open_local(url: str) -> None:
    if sys.platform == "win32":
        subprocess.Popen(f'start "" "{url}"', shell=True)
        return
    webbrowser.open(url)


def listen(host: str, port: int) -> tuple[ThreadingHTTPServer, int]:
    ThreadingHTTPServer.allow_reuse_address = True
    try:
        return ThreadingHTTPServer((host, port), Handler), port
    except OSError:
        print()
        print(f"  El puerto {port} ya está cogido.")
        print("  Cierra la otra ventana negra de Lazo y abre iniciar.bat otra vez.")
        print("  Mientras, uso otro puerto para que la página sí salga.")
        server = ThreadingHTTPServer((host, 0), Handler)
        return server, server.server_address[1]


def main() -> None:
    global PORT
    parser = argparse.ArgumentParser(description="Mando Lazo para este PC")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--pin", default="")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--max-gb", type=float, default=0, help="Tope por archivo del puente (8 por defecto)")
    args = parser.parse_args()
    if args.max_gb > 0:
        puente.set_max_gb(args.max_gb)
    try:
        UPLOADS.cleanup(force=True)
    except OSError:
        pass
    PAIRING.pin = protocol.Pairing(args.pin).pin
    PORT = args.port
    try:
        server, PORT = listen(args.host, args.port)
    except OSError as exc:
        print()
        print("  No pude abrir la página en este PC.")
        print(f"  {exc}")
        print("  Cierra las ventanas negras de Lazo y vuelve a abrir iniciar.bat.")
        return
    home = f"http://127.0.0.1:{PORT}/conectar"
    print()
    print(f"  LaZoo {VERSION}")
    print(f"  PIN: {PAIRING.pin}")
    print("  En este PC abre, con http y no con https:")
    print(f"    {home}")
    print("  Misma Wi-Fi de casa. No hace falta VPN.")
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
    try:
        control.watch_physical_mouse()
    except Exception:
        pass
    if not args.no_browser:
        threading.Timer(0.4, lambda: open_local(home)).start()
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
