#!/usr/bin/env python3
"""Lazo: mando del PC desde el móvil, en la misma Wi-Fi."""

from __future__ import annotations

import argparse
import hmac
import json
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import control

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
PIN = ""
TOKEN = secrets.token_urlsafe(32)
FAILS = {"n": 0, "until": 0.0}
FAILS_LOCK = threading.Lock()

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


def lan_ips() -> list[str]:
    ips: set[str] = set()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ips.add(sock.getsockname()[0])
        sock.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    ips.discard("127.0.0.1")
    return sorted(ips) or ["127.0.0.1"]


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
        if path == "/api/windows":
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
    global PIN
    parser = argparse.ArgumentParser(description="Mando Lazo para este PC")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--pin", default="")
    args = parser.parse_args()
    PIN = args.pin if args.pin.isdigit() and len(args.pin) == 6 else f"{secrets.randbelow(900000) + 100000}"
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print()
    print("  Lazo está en este PC")
    print(f"  PIN: {PIN}")
    print("  En el móvil, misma Wi-Fi, abre:")
    for ip in lan_ips():
        print(f"    http://{ip}:{args.port}")
    print("  No abras este puerto en el router.")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nLazo cerrado.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
