"""LaZoo: en la APK, los botones de QR abren el escáner con cámara, no el selector de fotos.

    python3 test_qr_camara.py
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
JAVA = (ROOT / "android" / "src" / "net" / "lazoo" / "app" / "MainActivity.java").read_text(encoding="utf-8")


def qr_start() -> str:
    m = re.search(r"function qrStart\(\) \{(.*?)\n\}", APP, re.S)
    assert m, "no encuentro qrStart"
    return m.group(1)


class QrCamara(unittest.TestCase):
    def test_apk_usa_el_escaner(self):
        body = qr_start()
        self.assertIn("appBridge.scan()", body)
        # El puente se mira ANTES que el input con capture (que en el WebView abre archivos).
        self.assertLess(body.index("appBridge.scan()"), body.index('"#qr-cam"'))

    def test_puente_existe_en_la_apk(self):
        self.assertIn("public void scan()", JAVA)
        self.assertIn("rescan", JAVA)

    def test_navegador_sigue_igual(self):
        body = qr_start()
        self.assertIn("getUserMedia", body)
        self.assertIn('document.querySelector("#qr-cam").click()', body)

    def test_botones_llaman_a_qrstart(self):
        self.assertIn('document.querySelector("#qr-scan").addEventListener("click", qrStart)', APP)
        self.assertIn('document.querySelector("#qr-top").addEventListener("click", qrStart)', APP)


if __name__ == "__main__":
    unittest.main()
