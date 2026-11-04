"""LaZoo 0.49: «Modo stats» del ratón dentro de Ratón, con historial para copiar (python3 test_v049.py)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import lazo  # noqa: E402

HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")


class Version(unittest.TestCase):
    def test_version(self) -> None:
        self.assertEqual(lazo.VERSION, "0.55")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.55")


class Interfaz(unittest.TestCase):
    def test_stats_en_raton(self) -> None:
        raton = HTML[HTML.index('id="pad"'):HTML.index('id="view-windows"')]
        for needle in ('id="diag-out"', 'id="diag-on"', 'id="diag-copy"', 'id="diag-freeze"', 'id="diag-win"',
                       'id="diag-vigilante"', 'id="aim-smooth"', 'id="diag-autofreeze"'):
            self.assertIn(needle, raton)
            self.assertEqual(HTML.count(needle), 1, needle)
        lab = HTML[HTML.index('id="view-lab"'):]
        self.assertNotIn('id="diag-out"', lab)

    def test_fondo_no_estorba(self) -> None:
        css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
        block = css[css.index(".diag-bg {"):]
        self.assertIn("pointer-events: none", block[:block.index("}")])

    def test_sigue_sellado(self) -> None:
        for needle in ("/api/diag/raton", "/api/vigilante", "PIN2", "sealBytes", "lagWatch"):
            self.assertIn(needle, JS)


@unittest.skipUnless(shutil.which("node"), "sin node")
class Resumen(unittest.TestCase):
    def run_js(self, code: str) -> str:
        a = JS.index("function diagStats"); b = JS.index("window.__lzDiagSummary")
        src = "const fmt=(v,d=0)=>(v===null||v===undefined?'—':Number(v).toFixed(d));\n" + JS[a:b] + code
        return subprocess.run(["node", "-e", src], capture_output=True, text=True, check=True).stdout

    def test_ultimos_segundos(self) -> None:
        hist = [{"fps": 60 if i < 12 else 0, "pcFps": 58, "rtt": 100 + i * 10, "net": 99, "proc": 0.2, "med": 16,
                 "p95": 30, "g50": 1, "g100": 0, "g250": 0, "burst": 0.1, "burstMax": 3, "lag": 2, "lagPeak": 9,
                 "seal": 0.1, "vig": "apagado", "ws": True} for i in range(15)]
        out = self.run_js("console.log(diagSummary(%s, 5, {version:'0.49', aim:'fina'}))" % json.dumps(hist))
        self.assertIn("LaZoo 0.49", out)
        self.assertIn("últimos 5 s (2 con movimiento)", out)  # aunque se suelte el dedo, quedan los segundos con movimiento
        self.assertIn("Precisión: fina", out)
        self.assertIn("Vigilante: apagado", out)
        self.assertIn("Eco total (RTT): mín 200 · media 205 · máx 210 · p95 210 ms", out)


if __name__ == "__main__":
    unittest.main()
