"""Pruebas de la 0.42: solo red local, aprobación de dispositivos nuevos y Descargatodo fuera."""

import io
import json
import re
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import aprobacion
import lazo
import protocol

ROOT = Path(__file__).resolve().parent

TABLE = {
    "127.0.0.1": True, "127.5.6.7": True, "::1": True,
    "10.0.0.1": True, "10.255.255.254": True,
    "172.15.0.1": False, "172.16.0.1": True, "172.31.255.1": True, "172.32.0.1": False,
    "192.168.1.5": True, "192.169.0.1": False,
    "169.254.10.1": True, "fe80::1": True, "fe80::1%eth0": True,
    "fd12:3456::1": True, "fc00::1": True,
    "::ffff:192.168.1.5": True, "::ffff:10.1.2.3": True, "::ffff:8.8.8.8": False,
    "8.8.8.8": False, "1.1.1.1": False, "100.64.1.1": False,
    "2001:4860:4860::8888": False, "2a00:1450::1": False,
    "": False, "no-es-ip": False,
}


class LocalNet(unittest.TestCase):
    def tearDown(self):
        aprobacion.EXTRA_NETS.clear()

    def test_table(self):
        for ip, want in TABLE.items():
            self.assertEqual(aprobacion.allowed(ip), want, ip)

    def test_extra_range(self):
        self.assertFalse(aprobacion.allowed("100.64.1.1"))
        self.assertEqual(aprobacion.add_allowed("100.64.0.0/10"), "100.64.0.0/10")
        self.assertTrue(aprobacion.allowed("100.64.1.1"))
        self.assertFalse(aprobacion.allowed("8.8.8.8"))
        with self.assertRaises(ValueError):
            aprobacion.add_allowed("no/vale")

    def test_log_limit(self):
        log = aprobacion.RejectLog(every=60)
        out = io.StringIO()
        self.assertTrue(log.note("8.8.8.8", out))
        self.assertFalse(log.note("8.8.8.8", out))
        self.assertTrue(log.note("1.1.1.1", out))
        self.assertEqual(out.getvalue().count("Rechazada conexión desde fuera de la red local"), 2)

    def test_socket_rejects_public_ip(self):
        """Servidor real: la misma petición entra desde una IP local y se corta desde una pública."""
        server = lazo.LazoServer(("127.0.0.1", 0), lazo.Handler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        real = lazo.client_ip
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/time", timeout=3) as res:
                self.assertEqual(res.status, 200)
            for fake in ("8.8.8.8", "::ffff:8.8.8.8", "100.64.1.1", "2001:db8::1"):
                lazo.client_ip = lambda _r, _a, ip=fake: ip
                for path in ("/api/time", "/", "/api/login", "/ws"):
                    with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
                        try:  # Windows puede abortar ya al enviar: también es rechazo
                            if path == "/api/login":
                                sock.sendall(b'POST /api/login HTTP/1.1\r\nHost: x\r\nContent-Length: 15\r\n\r\n{"pin":"12345"}')
                            else:
                                sock.sendall(f"GET {path} HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n\r\n".encode())
                            got = sock.recv(100)
                        except ConnectionError:
                            got = b""
                        self.assertEqual(got, b"", f"{fake} {path} recibió respuesta")
            # X-Forwarded-For no sirve para colarse.
            lazo.client_ip = lambda _r, _a: "8.8.8.8"
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/time", headers={"X-Forwarded-For": "192.168.1.2"})
            with self.assertRaises((urllib.error.URLError, ConnectionError, OSError)):
                urllib.request.urlopen(req, timeout=3)
            lazo.client_ip = lambda _r, _a: "192.168.1.9"
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/time", timeout=3) as res:
                self.assertEqual(res.status, 200)
        finally:
            lazo.client_ip = real
            server.shutdown()
            server.server_close()

    def test_cli_flag(self):
        out = subprocess.run([sys.executable, str(ROOT / "lazo.py"), "--help"], capture_output=True, text=True, timeout=20)
        self.assertIn("--permitir-ip", out.stdout)
        self.assertNotIn("auto-aprobar", out.stdout)


class States(unittest.TestCase):
    def setUp(self):
        self.a = aprobacion.Approvals()
        self.asked = []
        self.a.on_new.append(lambda who, row: self.asked.append(who))

    def test_flow(self):
        ua = "Mozilla/5.0 (Linux; Android 14) AppleWebKit Chrome/120 Mobile Safari/537"
        self.assertEqual(self.a.check("aa" * 8, ua, "192.168.1.5"), "pendiente")
        self.assertEqual(self.a.check("aa" * 8, ua, "192.168.1.5"), "pendiente")
        self.assertEqual(self.asked, ["aa" * 8])  # se pregunta una sola vez
        self.assertEqual(self.a.listing()[0]["label"], "Android · Chrome")
        self.assertTrue(self.a.decide("aa" * 8, True))
        self.assertEqual(self.a.check("aa" * 8), "ok")
        self.assertFalse(self.a.decide("aa" * 8, False))  # ya decidido
        self.assertTrue(self.a.kick("aa" * 8))  # expulsado: vuelve a pedir aprobación
        self.assertEqual(self.a.check("aa" * 8), "pendiente")
        self.assertEqual(len(self.asked), 2)

    def test_reject_blocks(self):
        self.a.check("bb" * 8)
        self.a.decide("bb" * 8, False)
        self.assertEqual(self.a.check("bb" * 8), "rechazado")
        self.a.devices["bb" * 8]["until"] = time.time() - 1  # pasan los 5 minutos
        self.assertEqual(self.a.check("bb" * 8), "pendiente")

    def test_timeout_is_reject(self):
        self.a.check("cc" * 8)
        self.a.devices["cc" * 8]["since"] -= aprobacion.WAIT_SECONDS + 1
        self.assertEqual(self.a.state("cc" * 8), "rechazado")
        self.assertEqual(self.a.check("cc" * 8), "rechazado")

    def test_kick_all(self):
        for who in ("dd" * 8, "ee" * 8):
            self.a.check(who)
            self.a.decide(who, True)
        self.a.check("ff" * 8)
        self.a.decide("ff" * 8, False)
        self.assertEqual(self.a.kick_all(), 2)
        self.assertEqual(self.a.state("dd" * 8), "nuevo")
        self.assertEqual(self.a.state("ff" * 8), "rechazado")  # el bloqueo sigue

    def test_auto(self):
        self.a.auto = True
        self.assertEqual(self.a.check("11" * 8), "ok")
        self.assertEqual(self.asked, [])

    def test_console(self):
        keys = iter(["", "s"])
        prompt = aprobacion.ConsolePrompt(self.a, reader=lambda _s: next(keys, ""))
        self.a.on_new.append(prompt)
        self.a.check("22" * 8, "iPhone", "10.0.0.2")
        for _ in range(50):
            if self.a.state("22" * 8) == "aprobado":
                break
            time.sleep(0.05)
        self.assertEqual(self.a.state("22" * 8), "aprobado")
        keys2 = iter(["n"])
        prompt.reader = lambda _s: next(keys2, "")
        self.a.check("33" * 8)
        for _ in range(50):
            if self.a.state("33" * 8) == "rechazado":
                break
            time.sleep(0.05)
        self.assertEqual(self.a.state("33" * 8), "rechazado")


def _req(port, method, path, body=b"", headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body if method == "POST" else None, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=3) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class HttpApproval(unittest.TestCase):
    def test_pending_then_accept_then_kick(self):
        server = lazo.LazoServer(("127.0.0.1", 0), lazo.Handler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        real_loop, real_auto, real_open = lazo.Handler._loopback, lazo.APPROVALS.auto, lazo.maybe_open_mesa
        lazo.APPROVALS.auto = False
        lazo.maybe_open_mesa = lambda: None
        pairing = lazo.PAIRING
        phone = "9a" * 8

        def signed(method, path, body=b""):
            data = pairing.seal(body) if body else b""
            heads = {protocol.H_ID: phone, "User-Agent": "iPhone Safari/1", **pairing.sign(method, path, len(data))}
            if data:
                heads["Content-Type"] = "application/octet-stream"
            return _req(port, method, path, data, heads)

        local = {"X-Lazo-Local": "1", "Content-Type": "application/json"}
        try:
            lazo.Handler._loopback = lambda self: False
            status, raw = signed("GET", "/api/status")
            self.assertEqual(status, 403)
            self.assertTrue(json.loads(raw)["pending"])
            self.assertEqual(json.loads(signed("GET", "/api/aprobacion")[1])["state"], "pendiente")
            self.assertEqual(signed("POST", "/api/move", json.dumps({"dx": 1, "dy": 1}).encode())[0], 403)
            # El móvil no puede aprobarse a sí mismo.
            self.assertEqual(signed("POST", "/api/dispositivos/decidir", json.dumps({"id": phone, "ok": True}).encode())[0], 403)
            lazo.Handler._loopback = real_loop
            listing = json.loads(_req(port, "GET", "/api/dispositivos", headers=local)[1])
            self.assertIn(phone, [d["id"] for d in listing["devices"]])
            seen = json.loads(_req(port, "GET", "/api/seen")[1])
            self.assertEqual(seen["pending"][0]["id"], phone)
            self.assertEqual(_req(port, "POST", "/api/dispositivos/decidir", json.dumps({"id": phone, "ok": True}).encode(), local)[0], 200)
            lazo.Handler._loopback = lambda self: False
            self.assertEqual(signed("GET", "/api/status")[0], 200)
            self.assertEqual(json.loads(signed("GET", "/api/aprobacion")[1])["state"], "aprobado")
            lazo.Handler._loopback = real_loop
            self.assertEqual(_req(port, "POST", "/api/dispositivos/expulsar", json.dumps({"all": True}).encode(), local)[0], 200)
            lazo.Handler._loopback = lambda self: False
            self.assertEqual(signed("GET", "/api/status")[0], 403)  # expulsado: pendiente otra vez
            lazo.Handler._loopback = real_loop
            _req(port, "POST", "/api/dispositivos/decidir", json.dumps({"id": phone, "ok": False}).encode(), local)
            lazo.Handler._loopback = lambda self: False
            status, raw = signed("GET", "/api/status")
            self.assertEqual(status, 403)
            self.assertIn("rechazó", json.loads(raw)["error"])
        finally:
            lazo.Handler._loopback = real_loop
            lazo.APPROVALS.auto = real_auto
            lazo.maybe_open_mesa = real_open
            lazo.APPROVALS.kick(phone)
            lazo.APPROVALS.devices.pop(phone, None)
            server.shutdown()
            server.server_close()


class NoDownloads(unittest.TestCase):
    def test_no_dead_refs(self):
        try:
            files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        except OSError:
            files = []
        if not files:  # copia descomprimida, sin git
            files = [str(p.relative_to(ROOT)).replace("\\", "/") for p in ROOT.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix in (".py", ".js", ".html", ".css", ".md", ".bat", ".sh", ".txt", ".ps1")]
        bad = re.compile(r"Descargatodo|yt-dlp|ytdlp|\bdeno\b|herramientas/|Instalar herramientas|/api/dl|descargas\.py|\bdlOpen|view-dl|ffmpeg", re.I)
        for name in files:
            if name in ("test_v042.py",) or name.endswith((".png", ".ico")) or name.startswith("static/jsqr"):
                continue
            text = (ROOT / name).read_text(encoding="utf-8", errors="ignore")
            for n, line in enumerate(text.splitlines(), 1):
                self.assertIsNone(bad.search(line), f"{name}:{n}: {line[:120]}")
        self.assertFalse((ROOT / "descargas.py").exists())

    def test_order_migration(self):
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('saved.filter((id) => id !== "dl")', js)
        self.assertNotIn('{ id: "dl"', js)


if __name__ == "__main__":
    unittest.main()
