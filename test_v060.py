"""LaZoo 0.60: contador de avisos «¿Sigues ahí?» quitados, en el Panel.

    python3 test_v060.py

Solo cuenta un pulsado verificado (el aviso desapareció), se guarda entre reinicios, lleva el
de hoy y la hora del último, se pone a cero solo desde el PC y el Panel lo enseña en español.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import lazo  # noqa: E402
import sigues  # noqa: E402

MESA = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")


class Contador(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "ajustes.json"
        self.res = {"ok": True, "visto": True, "pulsado": True, "verificado": True, "ms": 9}

    def tearDown(self):
        self.tmp.cleanup()

    def make(self):
        return sigues.Sigues(find=lambda: "7", probe=lambda h: dict(self.res), file=self.file)

    def test_verificado_cuenta_y_persiste(self):
        s = self.make()
        s.check_once(); s.check_once()
        st = s.status()
        self.assertEqual((st["total"], st["hoy"], st["sesion"]), (2, 2, 2))
        self.assertGreater(st["ultimo"], 0)
        again = self.make()
        self.assertEqual((again.status()["total"], again.status()["hoy"], again.status()["sesion"]), (2, 2, 0))
        data = json.loads(self.file.read_text())
        self.assertEqual(set(data["contador"]), {"total", "hoy", "dia", "ultimo"})

    def test_intento_fallido_no_cuenta(self):
        s = self.make()
        self.res["verificado"] = False
        s.check_once()
        self.res.update(pulsado=False, verificado=False, visto=False)
        s.check_once()
        self.assertEqual(s.status()["total"], 0)

    def test_hoy_se_reinicia_otro_dia(self):
        s = self.make()
        s.contar(time.time() - 3 * 86400)
        self.assertEqual(s.status()["hoy"], 0)
        s.contar()
        self.assertEqual((s.status()["total"], s.status()["hoy"]), (2, 1))

    def test_reset(self):
        s = self.make()
        s.check_once()
        st = s.set_on(None, reset=True)
        self.assertEqual((st["total"], st["hoy"], st["ultimo"]), (0, 0, 0.0))
        self.assertEqual(self.make().status()["total"], 0)
        self.assertTrue(s.on)  # reset no apaga

    def test_no_pierde_el_ajuste(self):
        s = self.make()
        s.set_on(False)
        s.contar()
        self.assertFalse(self.make().on)
        self.assertEqual(self.make().total, 1)

    def test_script_verifica(self):
        ps = sigues.ps_script()
        self.assertIn("function Buscar", ps)
        self.assertIn("$out.verificado = $true", ps)


class Rutas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = (sigues.SIGUES.file, sigues.SIGUES.on, sigues.SIGUES.total, sigues.SIGUES.hoy, sigues.SIGUES.dia)
        sigues.SIGUES.file = Path(self.tmp.name) / "ajustes.json"
        sigues.SIGUES.contar()
        self.server = lazo.LazoServer(("127.0.0.1", 0), lazo.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close()
        sigues.SIGUES.stop()
        (sigues.SIGUES.file, sigues.SIGUES.on, sigues.SIGUES.total, sigues.SIGUES.hoy, sigues.SIGUES.dia) = self.old
        self.tmp.cleanup()

    def test_conexion_y_reset_local(self):
        from test_v054 import _req
        h = {"X-Lazo-Local": "1", "Content-Type": "application/json"}
        info = json.loads(_req(self.port, "GET", "/api/conexion", headers=h)[1])["sigues_info"]
        self.assertGreaterEqual(info["total"], 1)
        st = json.loads(_req(self.port, "POST", "/api/sigues", json.dumps({"reset": True}).encode(), h)[1])
        self.assertEqual(st["total"], 0)

    def test_remoto_sin_clave_no(self):
        from test_v054 import _req
        st, _ = _req(self.port, "POST", "/api/sigues", b'{"reset": true}', {"Content-Type": "application/json"})
        self.assertIn(st, (401, 403))
        self.assertGreaterEqual(sigues.SIGUES.total, 1)


class Panel(unittest.TestCase):
    def test_html(self):
        for t in ('id="sigues-cuenta"', 'id="sigues-cero"', "Avisos quitados: ", "Poner a cero",
                  '{ reset: true }', "siguesTexto(data.sigues_info"):
            self.assertIn(t, MESA)

    @unittest.skipUnless(shutil.which("node"), "sin node")
    def test_texto(self):
        a = MESA.index("function siguesTexto"); b = MESA.index("async function devCall")
        js = MESA[a:b] + """
const now = new Date(2026, 10, 5, 18, 0);
const t = (y, m, d, h, mi) => new Date(y, m, d, h, mi).getTime() / 1000;
console.log(JSON.stringify([
  siguesTexto({total: 0, hoy: 0, ultimo: 0}, now),
  siguesTexto({total: 3, hoy: 2, ultimo: t(2026, 10, 5, 14, 32)}, now),
  siguesTexto({total: 5, hoy: 0, ultimo: t(2026, 10, 4, 9, 5)}, now),
  siguesTexto({total: 9, hoy: 0, ultimo: t(2026, 9, 1, 23, 7)}, now)]));"""
        out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out, ["Avisos quitados: 0", "Avisos quitados: 3 · hoy: 2 · último: hoy 14:32",
                               "Avisos quitados: 5 · hoy: 0 · último: ayer 09:05",
                               "Avisos quitados: 9 · hoy: 0 · último: 01/10/2026 23:07"])


class Version(unittest.TestCase):
    def test_version(self):
        self.assertEqual(lazo.VERSION, "0.74")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.74")
        apk = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:versionCode="66"', apk)
        self.assertIn('android:versionName="3"', apk)
        self.assertIn('<p class="ver">0.74', MESA)
        self.assertIn("## Estado (0.61)", (ROOT / "AGENTS.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
