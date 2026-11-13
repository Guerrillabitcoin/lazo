"""LaZoo 0.52: portapapeles compartido (python3 test_v052.py)."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import control  # noqa: E402
import lazo  # noqa: E402

HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
APK = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")


class Fake:
    def __init__(self):
        self.text = ""

    def read(self):
        return self.text


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        control.set_history_path(Path(self.tmp.name) / "h.json")
        control._clip_injected = None
        self.clip = Fake()
        self.watch = control.ClipWatch(read=self.clip.read)
        self.old = control.CLIP_WATCH
        control.CLIP_WATCH = self.watch

    def tearDown(self):
        control.CLIP_WATCH = self.old
        control._clip_injected = None
        self.tmp.cleanup()

    def texts(self):
        return [i["text"] for i in control.clipboard_history()["items"]]


class Vigilante(Base):
    def test_detecta_cambio(self):
        self.clip.text = "hola"
        self.assertTrue(self.watch.poll())
        self.clip.text = "adiós"
        self.assertTrue(self.watch.poll())
        self.assertEqual(self.texts(), ["adiós", "hola"])

    def test_sin_vacio_ni_duplicados(self):
        self.clip.text = "   "
        self.assertFalse(self.watch.poll())
        self.clip.text = "uno"
        self.assertTrue(self.watch.poll())
        for _ in range(5):
            self.assertFalse(self.watch.poll())
        self.assertEqual(self.texts(), ["uno"])

    def test_ignora_enorme(self):
        self.clip.text = "x" * (control.ClipWatch.MAX_CHARS + 1)
        self.assertFalse(self.watch.poll())
        self.assertEqual(self.texts(), [])

    def test_ignora_inyectado_y_sin_bucle(self):
        writes = []

        def fake_write(text):
            writes.append(text)
            self.clip.text = text
            return True

        with mock.patch.object(control, "_write_clipboard_text", fake_write):
            control.clipboard_history("del móvil")
            self.assertTrue(control.clipboard_to_system("del móvil"))
        for _ in range(4):
            self.assertFalse(self.watch.poll())
        self.assertEqual(writes, ["del móvil"])
        self.assertEqual(self.texts(), ["del móvil"])

    def test_margen_inyectado(self):
        control._mark_injected("secreto")
        self.watch._last = None  # aunque no se haya visto, el margen lo cubre
        self.clip.text = "secreto"
        self.assertFalse(self.watch.poll())

    def test_interruptor(self):
        with mock.patch.dict("os.environ", {"LAZO_SIN_PORTAPAPELES": "1"}):
            self.assertFalse(control.ClipWatch().enabled)
        self.assertFalse(control.watch_clipboard())  # nunca en tests


class Post(Base):
    def call(self, body):
        sent = {}
        fake = mock.Mock()
        fake._authed.return_value = True
        fake._read_json.return_value = body
        fake._send.side_effect = lambda code, data: sent.update(code=code, data=data)
        lazo.Handler._push_clip(fake)
        return sent

    def test_to_system_escribe_y_marca(self):
        with mock.patch.object(control, "_write_clipboard_text", return_value=True) as w:
            sent = self.call({"text": "clave", "to_system": True})
        w.assert_called_once_with("clave")
        self.assertEqual(sent["code"], 200)
        self.assertTrue(sent["data"]["to_system"])
        self.assertEqual(control._clip_injected[0], control._clip_digest("clave"))
        self.clip.text = "clave"
        self.assertFalse(self.watch.poll())
        self.assertEqual(self.texts(), ["clave"])

    def test_sin_to_system_no_escribe(self):
        with mock.patch.object(control, "_write_clipboard_text") as w:
            sent = self.call({"text": "solo nota"})
        w.assert_not_called()
        self.assertNotIn("to_system", sent["data"])
        self.assertIsNone(control._clip_injected)


class Ui(unittest.TestCase):
    def test_version(self):
        self.assertEqual(lazo.VERSION, "0.71")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.71")
        self.assertIn('android:versionName="3"', APK)
        self.assertIn('android:versionCode="66"', APK)

    def test_boton(self):
        self.assertIn('id="clip-to-pc"', HTML)
        self.assertIn("Al PC", HTML)
        self.assertIn("to_system: true", JS)
        self.assertIn("Enviado al portapapeles del PC", JS)


if __name__ == "__main__":
    unittest.main()
