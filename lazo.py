#!/usr/bin/env python3
"""Lazo: mando del PC desde el móvil, en la misma Wi-Fi."""

from __future__ import annotations

import argparse
import hmac
import json
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import control

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
PIN = ""
PORT = 8787
TOKEN = secrets.token_urlsafe(32)
FAILS = {"n": 0, "until": 0.0}
FAILS_LOCK = threading.Lock()
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
    "youtube": lambda body: control.youtube(str(body.get("action", ""))),
    "spotify": lambda body: control.spotify(str(body.get("action", ""))),
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


def _ips_from_system() -> set[str]:
    commands = [["ipconfig"]] if sys.platform == "win32" else [["ip", "-4", "-o", "addr"], ["ifconfig"]]
    found: set[str] = set()
    for cmd in commands:
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=3, text=True, errors="replace")
        except (OSError, subprocess.SubprocessError):
            continue
        found.update(IP_RE.findall(out))
        if found:
            break
    return found


def lan_ips() -> list[str]:
    found: set[str] = set()
    primary = ""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        primary = sock.getsockname()[0]
        sock.close()
    except OSError:
        pass
    if primary:
        found.add(primary)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    found.update(_ips_from_system())
    private = [ip for ip in found if _private(ip)]
    private.sort(key=_rank)
    if primary in private and (_rank(primary)[0] == 0 or not any(_rank(ip)[0] == 0 for ip in private)):
        private.remove(primary)
        private.insert(0, primary)
    return private or ["127.0.0.1"]


def phone_url(ip: str) -> str:
    return f"http://{ip}:{PORT}/?pin={PIN}"


def plain_url(ip: str) -> str:
    return f"http://{ip}:{PORT}/"


def qr_svg(url: str) -> str:
    import segno

    return segno.make(url, error="m").svg_inline(scale=8, dark="#141210", light="#f3eee6")


def connect_page() -> bytes:
    ips = lan_ips()
    blocks: list[str] = []
    for index, ip in enumerate(ips[:3]):
        url = phone_url(ip)
        try:
            svg = qr_svg(url)
        except Exception:
            svg = ""
        others = "".join(
            f"<li><a href=\"{escape(phone_url(other))}\">{escape(plain_url(other))}</a></li>"
            for other in ips
            if other != ip
        )
        extra = f"<p>Si esa no entra, prueba:</p><ul>{others}</ul>" if others else ""
        blocks.append(
            f"""<section class="card">
              {svg or f'<p class="url">{escape(plain_url(ip))}</p>'}
              <p class="pin">{escape(PIN)}</p>
              <p class="url">{escape(plain_url(ip))}</p>
              {extra}
            </section>"""
        )
        break
    page = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Conectar Lazo</title>
  <style>
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: #141210; color: #f3eee6; font-family: "Segoe UI", system-ui, sans-serif; }}
    .card {{ width: min(420px, calc(100vw - 32px)); text-align: center; }}
    svg {{ width: min(320px, 80vw); height: auto; background: #f3eee6; border-radius: 16px; }}
    h1 {{ font-weight: 500; font-size: 1.4rem; }}
    .pin {{ font-size: 2.4rem; letter-spacing: 0.3em; margin: 12px 0 4px; }}
    .url, li {{ color: #c4b8aa; word-break: break-all; }}
    a {{ color: #e07a3d; }}
  </style>
</head>
<body>
  <div>
    <h1>Escanea con la cámara del móvil</h1>
    <p>Misma Wi-Fi. Desactiva la VPN en el PC y en el móvil.</p>
    {''.join(blocks)}
  </div>
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


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def _authed(self) -> bool:
        got = cookies(self.headers.get("Cookie")).get("lazo", "")
        return bool(got) and hmac.compare_digest(got, TOKEN)

    def _send(self, code: int, payload: dict | None = None, body: bytes | None = None, content_type: str = "application/json") -> None:
        data = body if body is not None else json.dumps(payload or {}, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 8000:
            raise control.ControlError("petición demasiado grande")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError as exc:
            raise control.ControlError("JSON no válido") from exc
        if not isinstance(data, dict):
            raise control.ControlError("JSON no válido")
        return data

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._file(STATIC / "index.html", "text/html; charset=utf-8")
            return
        if path == "/app.css":
            self._file(STATIC / "app.css", "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self._file(STATIC / "app.js", "text/javascript; charset=utf-8")
            return
        if path == "/conectar":
            host = self.client_address[0]
            if host not in ("127.0.0.1", "::1"):
                self._send(404, {"error": "no está"})
                return
            self._send(200, body=connect_page(), content_type="text/html; charset=utf-8")
            return
            self._guard(lambda _body: {"windows": control.list_windows()})
            return
        if path == "/api/status":
            self._guard(lambda _body: control.status())
            return
        self._send(404, {"error": "no está"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/login":
            self._login()
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
            if not hmac.compare_digest(pin, PIN):
                FAILS["n"] += 1
                if FAILS["n"] >= 8:
                    FAILS["until"] = now + 30
                    FAILS["n"] = 0
                self._send(401, {"error": "PIN incorrecto"})
                return
            FAILS["n"] = 0
        self.send_response(200)
        data = json.dumps({"ok": True}).encode()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Set-Cookie", f"lazo={TOKEN}; HttpOnly; SameSite=Lax; Path=/")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

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


def main() -> None:
    global PIN, PORT
    parser = argparse.ArgumentParser(description="Mando Lazo para este PC")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--pin", default="")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    PIN = args.pin if args.pin.isdigit() and len(args.pin) == 6 else f"{secrets.randbelow(900000) + 100000}"
    PORT = args.port
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    urls = [phone_url(ip) for ip in lan_ips()]
    print()
    print("  Lazo está en este PC")
    print(f"  PIN: {PIN}")
    print("  Se abre una ventana con el QR. Escanéalo con la cámara del móvil.")
    print("  Misma Wi-Fi, sin VPN. Si no se abre, entra aquí en el PC:")
    print(f"    http://127.0.0.1:{args.port}/conectar")
    for url in urls:
        print(f"  Móvil: {url.split('?')[0]}")
    print("  No abras este puerto en el router.")
    print()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if not args.no_browser:
        threading.Timer(0.3, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}/conectar")).start()
    try:
        import segno

        segno.make(urls[0], error="m").terminal(compact=True)
    except Exception:
        pass
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
