"""Pruebas de la 0.41: carpetas en el puente, inputs de archivos y lector de QR servido."""

import tempfile
import unittest
from pathlib import Path

import puente

ROOT = Path(__file__).resolve().parent


class FolderUpload(unittest.TestCase):
    def test_clean_dir(self):
        self.assertEqual(puente.clean_dir("Viaje/fotos"), ["Viaje", "fotos"])
        self.assertEqual(puente.clean_dir("../../etc/x"), ["etc", "x"])
        self.assertEqual(puente.clean_dir("/abs\\\\..\\\\win"), ["abs", "win"])
        self.assertEqual(puente.clean_dir("C:/CON/a?b"), ["C_", "_CON", "a_b"])
        self.assertEqual(len(puente.clean_dir("/".join("abcdefghijk"))), 8)
        self.assertEqual(puente.clean_dir(""), [])

    def test_upload_into_subfolder(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "recibido"
            up = puente.Uploads(lambda: base)
            data = b"%PDF-1.4 hola"
            s = up.start("doc.pdf", len(data), "k1", "w", "Mi carpeta/../sub")
            up.write(s["id"], 0, data)
            done = up.finish(s["id"], hashlib.sha256(data).hexdigest())
            self.assertEqual(done["name"], "Mi carpeta/sub/doc.pdf")
            self.assertEqual((base / "Mi carpeta" / "sub" / "doc.pdf").read_bytes(), data)
            again = up.start("doc.pdf", len(data), "k1", "w", "Mi carpeta/sub")
            self.assertTrue(again.get("skip"))


class Html(unittest.TestCase):
    def test_inputs(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        line = next(l for l in html.splitlines() if 'id="send-input"' in l)
        self.assertNotIn("accept", line)  # sin accept: Android abre el selector de archivos, no la galería
        self.assertNotIn("capture", line)
        self.assertIn("multiple", line)
        self.assertIn('id="send-dir"', html)
        self.assertIn("webkitdirectory", html)
        self.assertIn('id="qr-scan"', html)
        self.assertIn('capture="environment"', html)

    def test_jsqr_vendored(self):
        self.assertTrue((ROOT / "static" / "jsqr.js").stat().st_size > 100_000)
        self.assertIn("Apache License", (ROOT / "static" / "jsqr-LICENSE.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
