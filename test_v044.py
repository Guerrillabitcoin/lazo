"""0.44: panel de conexión (QR + PIN) en la ventana del PC y proyecto Android."""

import json
import unittest
import urllib.request
from pathlib import Path

import bandeja
import lazo

ROOT = Path(__file__).resolve().parent


def _get(path):
    with urllib.request.urlopen(f"http://127.0.0.1:{lazo.PORT}{path}", timeout=3) as res:
        return json.loads(res.read())


class ConnectionPanel(unittest.TestCase):
    def test_api_follows_devices(self):
        auto = lazo.APPROVALS.auto
        server, _home = lazo.start(["--no-browser", "--port", "0", "--host", "127.0.0.1"], console=False)
        try:
            lazo.PAIRING.forget_phones()
            data = _get("/api/conexion")
            self.assertEqual(data["connected"], 0)
            self.assertRegex(data["pin"], r"^\d{6}$")
            self.assertIn("pending", data)
            lazo.PAIRING.note_phone("movil1")
            self.assertEqual(_get("/api/conexion")["connected"], 1)
            lazo.PAIRING.phone_gone("movil1")
            self.assertEqual(_get("/api/conexion")["connected"], 0)
        finally:
            lazo.PAIRING.forget_phones()
            server.shutdown()
            server.server_close()
            lazo.APPROVALS.auto = auto

    def test_mesa_has_panel(self):
        html = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
        for bit in ('id="conexion"', 'id="conn-qr"', 'id="conn-pin"', "/api/conexion", "data.connected > 0", 'href="/conectar"'):
            self.assertIn(bit, html)

    def test_tray_opens_window_at_start(self):
        src = (ROOT / "bandeja.py").read_text(encoding="utf-8")
        self.assertIn('tray.open(tray.url("/mesa"))', src)
        self.assertIn("--sin-ventana", src)


class Android(unittest.TestCase):
    def test_project_present(self):
        base = ROOT / "android"
        for rel in ("AndroidManifest.xml", "construir_apk.sh", "README.md",
                    "src/net/lazoo/app/MainActivity.java", "assets/escaner.html", "assets/jsqr.js"):
            self.assertTrue((base / rel).exists(), rel)
        man = (base / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn("android.permission.CAMERA", man)
        self.assertNotIn("com.google.android.gms", man)

    def test_private_hosts_only(self):
        js = (ROOT / "android" / "assets" / "escaner.html").read_text(encoding="utf-8")
        self.assertIn("function privateHost", js)


if __name__ == "__main__":
    unittest.main()
