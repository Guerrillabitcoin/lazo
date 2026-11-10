"""LaZoo 0.59: el aviso «¿Sigues ahí?» de YouTube se contesta solo (sigues.py).

    python3 test_v059.py

Comprueba los textos que reconoce, el bucle con una ventana y un PowerShell de mentira, que
apagado no hace nada, que el ajuste se guarda, las rutas /api/sigues (local sí, remoto sin
clave no), los interruptores del Panel y del móvil y la versión. En Windows, si hay
PowerShell, también comprueba que el script embebido se carga y contesta (sin ventanas).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import lazo  # noqa: E402
import sigues  # noqa: E402

JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
MESA = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
SRC = (ROOT / "sigues.py").read_text(encoding="utf-8")


class Textos(unittest.TestCase):
    def test_aviso(self):
        for t in ["Video paused. Continue watching?", "Vídeo en pausa. ¿Quieres seguir viendo?",
                  "¿Sigues ahí?", "Still watching?", "Vidéo mise en pause. Continuer à regarder ?",
                  "Video pausiert. Weiterschauen?"]:
            self.assertTrue(sigues.es_aviso(t), t)
        for t in ["", "Yes", "Suscribirse", "Continue", "Watch later", "Ver más tarde"]:
            self.assertFalse(sigues.es_aviso(t), t)

    def test_si(self):
        for n in ["Yes", "yes", "Sí", "Si", "Oui", "Ja", " Yes. "]:
            self.assertTrue(sigues.es_si(n), n)
        for n in ["No", "Yes please", "Cancel", "", "Suscribirse"]:
            self.assertFalse(sigues.es_si(n), n)

    def test_script_lleva_los_mismos_textos(self):
        ps = sigues.ps_script()
        for t in ("continue watching", "seguir viendo", "'yes'", "'sí'"):
            self.assertIn(t, ps)
        self.assertIn("InvokePattern", ps)
        self.assertIn("FromHandle", ps)
        # Nada de cursor, teclas, foco ni JavaScript.
        for bad in ("SetCursorPos", "SendKeys", "SetFocus", "keybd_event", "mouse_event", "BringWindowToTop"):
            self.assertNotIn(bad, ps)
        # SetForegroundWindow solo para DEVOLVER el foco a la ventana que ya lo tenía.
        self.assertEqual(ps.count("::SetForegroundWindow("), 1)
        self.assertIn("[LaZoo.Foco]::SetForegroundWindow($antes)", ps)
        sigues.encoded()  # base64 UTF-16LE sin errores

    def test_oculto_y_sin_red(self):
        self.assertIn("CREATE_NO_WINDOW", SRC)
        for bad in ("urllib", "socket", "http://", "https://"):
            self.assertNotIn(bad, SRC)


class Bucle(unittest.TestCase):
    def make(self, hwnd="123", res=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.calls = []

        def probe(h):
            self.calls.append(h)
            return res if res is not None else {"ok": True, "visto": True, "pulsado": True, "verificado": True, "ms": 40}

        return sigues.Sigues(find=lambda: hwnd, probe=probe, file=Path(self.tmp.name) / "ajustes.json")

    def tearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def test_pulsa_y_cuenta(self):
        s = self.make()
        self.assertTrue(s.on)  # activado de serie
        self.assertTrue(s.check_once()["pulsado"])
        self.assertEqual((self.calls, s.pulsados, s.ultima_ms), (["123"], 1, 40))
        self.assertGreater(s.ultimo, 0)

    def test_sin_youtube_no_pregunta(self):
        s = self.make(hwnd=None)
        self.assertEqual(s.check_once(), {"skip": "sin youtube"})
        self.assertEqual(self.calls, [])

    def test_apagado_no_hace_nada_y_se_guarda(self):
        s = self.make()
        self.assertFalse(s.set_on(False)["on"])
        self.assertEqual(s.check_once(), {"skip": "apagado"})
        self.assertEqual(self.calls, [])
        self.assertEqual(json.loads(s.file.read_text())["sigues"], False)
        again = sigues.Sigues(find=lambda: "1", probe=lambda h: {}, file=s.file)
        self.assertFalse(again.on)
        s.set_on(True)
        self.assertTrue(sigues.Sigues(file=s.file).on)
        s.stop()

    def test_consulta_no_cambia(self):
        s = self.make()
        self.assertTrue(s.set_on(None)["on"])

    def test_sin_aviso_no_cuenta(self):
        s = self.make(res={"ok": True, "visto": False, "pulsado": False, "ms": 5})
        s.check_once()
        self.assertEqual(s.pulsados, 0)

    def test_error_se_apunta(self):
        s = self.make(res={"ok": False, "error": "ElementNotAvailableException", "ms": 1})
        s.check_once()
        self.assertEqual(s.error, "ElementNotAvailableException")

    def test_archivo_roto_usa_defecto(self):
        s = self.make()
        s.file.write_text("{roto")
        self.assertTrue(sigues.Sigues(file=s.file).on)

    def test_disabled(self):
        s = self.make()
        s.disabled = True
        self.assertFalse(s.status()["on"])
        self.assertEqual(s.check_once(), {"skip": "apagado"})
        self.assertFalse(s.start())

    def test_no_arranca_en_pruebas(self):
        self.assertFalse(sigues.watch())


class Rutas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (sigues.SIGUES.file, sigues.SIGUES.on, sigues.SIGUES.probe)
        sigues.SIGUES.file = Path(self.tmp.name) / "ajustes.json"
        sigues.SIGUES.probe = lambda h: {"ok": True}
        self.server = lazo.LazoServer(("127.0.0.1", 0), lazo.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        sigues.SIGUES.stop()
        sigues.SIGUES.file, sigues.SIGUES.on, sigues.SIGUES.probe = self.old
        self.tmp.cleanup()

    def req(self, method, body=None, local=True):
        from test_v054 import _req
        headers = {"X-Lazo-Local": "1", "Content-Type": "application/json"} if local else {"Content-Type": "application/json"}
        return _req(self.port, method, "/api/sigues", json.dumps(body).encode() if body is not None else b"", headers)

    def test_panel_local(self):
        st, raw = self.req("POST", {"on": False})
        self.assertEqual((st, json.loads(raw)["on"]), (200, False))
        st, raw = self.req("GET")
        self.assertFalse(json.loads(raw)["on"])
        st, raw = self.req("POST", {"on": True})
        self.assertTrue(json.loads(raw)["on"])

    def test_web_ajena_sin_cabecera_no(self):
        st, _raw = self.req("POST", {"on": False}, local=False)
        self.assertIn(st, (401, 403))
        self.assertTrue(sigues.SIGUES.on or self.old[1] is False)


class Interfaz(unittest.TestCase):
    def test_panel(self):
        self.assertIn('id="sigues"', MESA)
        self.assertIn("Evitar el aviso «¿Sigues ahí?» de YouTube", MESA)
        self.assertIn('devCall("/api/sigues"', MESA)

    def test_movil(self):
        self.assertIn('id="yt-sigues"', HTML)
        self.assertIn('api("/api/sigues", { on: ytSigues.checked })', JS)
        self.assertIn("PREF_PUSH.push(syncSigues)", JS)

    def test_arranque_y_opcion(self):
        LAZO = (ROOT / "lazo.py").read_text(encoding="utf-8")
        self.assertIn("sigues.watch()", LAZO)
        self.assertIn("--sin-sigues", LAZO)


@unittest.skipUnless(sys.platform == "win32", "solo Windows")
class PowerShellReal(unittest.TestCase):
    def test_script_contesta(self):
        s = sigues.Sigues(find=lambda: "0", file=Path(tempfile.mkdtemp()) / "a.json")
        res = s._probe_ps("0")  # hwnd 0: no hay ventana, debe contestar sin colgarse
        s._close()
        self.assertIn("ok", res)


class Version(unittest.TestCase):
    def test_version(self):
        self.assertEqual(lazo.VERSION, "0.64")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.64")
        apk = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:versionCode="64"', apk)
        self.assertIn('android:versionName="1"', apk)
        self.assertIn('const PAGE_VERSION = "0.64"', JS)
        self.assertIn("<title>LaZoo 0.64</title>", HTML)
        self.assertIn("# LaZoo 0.64", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("## Estado (0.61)", (ROOT / "AGENTS.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
