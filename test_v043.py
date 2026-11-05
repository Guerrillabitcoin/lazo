"""0.43: QR + aprobación sin volver a pedir PIN, y base de la bandeja de Windows."""

import json
import struct
import sys
import unittest
from pathlib import Path

import bandeja
import icono
import lazo

ROOT = Path(__file__).resolve().parent


class QrWaitsWithoutPin(unittest.TestCase):
    def test_status_403_pending_keeps_key(self):
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        start = js.index("if (authKey) {\n  pinPanel.hidden = true;")
        block = js[start:start + 900]
        pend = block.index("res.status === 403 && (data.pending || data.rejected)")
        drop = block.index("forgetKey();")  # 0.57: forgetKey() borra la clave
        self.assertLess(pend, drop, "el 403 pendiente debe tratarse antes de borrar la clave")
        self.assertIn("showWait(", block[pend:drop])

    def test_login_goes_to_wait_not_pin(self):
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        login = js[js.index("async function login()"):]
        login = login[:login.index("\n}\n")]
        # 0.54: el PIN pide permiso con el saludo y espera la aprobación (showPaired -> showWait).
        self.assertIn('pairStart("pin", pin)', login)
        self.assertIn("showPaired(", login)

    def test_tray_hash_only_on_loopback(self):
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('if (onThisPc && fromTray && !authKey)', js)
        self.assertIn('["127.0.0.1", "localhost", "[::1]"].includes(location.hostname)', js)


class TrayModel(unittest.TestCase):
    rows = [
        {"id": "a" * 16, "state": "aprobado", "label": "Android · Chrome", "ip": "192.168.1.5", "left": 0},
        {"id": "b" * 16, "state": "pendiente", "label": "iPhone · Safari", "ip": "192.168.1.6", "left": 40},
        {"id": "c" * 16, "state": "rechazado", "label": "X", "ip": "192.168.1.7", "left": 0},
    ]

    def test_resolve(self):
        self.assertEqual(bandeja.resolve(bandeja.ID_ACCEPT, self.rows), ("accept", "b" * 16))
        self.assertEqual(bandeja.resolve(bandeja.ID_REJECT, self.rows), ("reject", "b" * 16))
        self.assertEqual(bandeja.resolve(bandeja.ID_KICK, self.rows), ("kick", "a" * 16))
        self.assertEqual(bandeja.resolve(bandeja.ID_KICK + 1, self.rows), ("", None))
        self.assertEqual(bandeja.resolve(bandeja.ID_QUIT, []), ("quit", None))
        self.assertEqual(bandeja.resolve(bandeja.ID_CUBE + 1, []), ("cube", "bridge"))

    def test_cubes_match_dock(self):
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        for cid, name in bandeja.CUBES:
            self.assertIn(f'{{ id: "{cid}", name: "{name}" }}', js)

    def test_degrades_off_windows(self):
        if sys.platform != "win32":
            self.assertEqual(bandeja.main([]), 1)

    def test_mesa_anchors(self):
        html = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
        self.assertIn('id="puente"', html)
        self.assertIn('id="dispositivos"', html)

    def test_pyw_exists(self):
        self.assertIn("bandeja.main", (ROOT / "LaZoo.pyw").read_text(encoding="utf-8"))


class Icon(unittest.TestCase):
    def test_ico(self):
        data = (ROOT / "static" / "lazoo.ico").read_bytes()
        self.assertGreater(len(data), 1000)  # 0.55: infinito naranja (diseno/logos.py)
        self.assertEqual(struct.unpack("<HHH", data[:6])[:2], (0, 1))

    def test_dib(self):
        data = icono.dib_icon(32)
        self.assertEqual(len(data), 40 + 32 * 32 * 4 + 4 * 32)


class StartApi(unittest.TestCase):
    def test_start_random_port(self):
        import urllib.request

        auto = lazo.APPROVALS.auto
        server, home = lazo.start(["--no-browser", "--port", "0", "--host", "127.0.0.1"], console=False)
        try:
            self.assertTrue(home.endswith("/mesa"))  # 0.54: abre el Panel de LaZoo
            self.assertNotEqual(lazo.PORT, 0)
            with urllib.request.urlopen(f"http://127.0.0.1:{lazo.PORT}/api/seen", timeout=3) as res:
                self.assertIn("pending", json.loads(res.read()))
        finally:
            server.shutdown()
            server.server_close()
            lazo.APPROVALS.auto = auto


if __name__ == "__main__":
    unittest.main()
