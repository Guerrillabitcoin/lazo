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
VISITS: list[str] = []
VISITS_LOCK = threading.Lock()
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
    return f"http://{ip}:{PORT}/?pin={PIN}"


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
            svg = qr_svg(url)
        except Exception:
            svg = ""
        blocks.append(
            f"""<section class="card">
              <h2>{escape(label)}</h2>
              <p class="url">{escape(url)}</p>
              <p class="hint">PIN {escape(PIN)}</p>
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
    #estado {{ font-size: 1.05rem; color: #f3eee6; }}
  </style>
</head>
<body>
  <main>
    <h1>Escribe esta dirección en el móvil</h1>
    <p class="note">Misma Wi-Fi, sin VPN y sin datos. Si el QR no abre nada, abre Chrome y escribe la dirección de abajo. Tiene que empezar por http://</p>
    <p id="estado">Todavía no llega el móvil.</p>
    {''.join(blocks)}
  </main>
  <script>
    async function tick() {{
      try {{
        const data = await fetch("/api/seen").then((res) => res.json());
        if (data.visits && data.visits.length) {{
          document.querySelector("#estado").textContent = "El móvil ya entró. Escribe el PIN en el móvil.";
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
        note_visit(self.client_address[0])
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
        if path == "/api/seen":
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                self._send(404, {"error": "no está"})
                return
            self._send(200, {"visits": list(VISITS)})
            return
        if path == "/api/windows":
            self._guard(lambda _body: {"windows": control.list_windows()})
            return
        if path == "/api/status":
            self._guard(lambda _body: control.status())
            return
        self._send(404, {"error": "no está"})

    def do_POST(self) -> None:  # noqa: N802
        note_visit(self.client_address[0])
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
    print()
    print("  Lazo está en este PC")
    print(f"  PIN: {PIN}")
    print("  En el PC se abre la dirección. Escríbela en el móvil, no hace falta el QR.")
    print("  Misma Wi-Fi de casa. No hace falta VPN. Si no se abre, entra aquí en el PC:")
    print(f"    http://127.0.0.1:{args.port}/conectar")
    for label, ip in lan_targets():
        print(f"  {label}: {plain_url(ip)}")
    print("  No abras este puerto en el router.")
    print()
    threading.Thread(target=server.serve_forever, daemon=True).start()
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
