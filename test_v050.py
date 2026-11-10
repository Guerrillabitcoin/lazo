"""LaZoo 0.50: movimiento continuo en el PC y ritmo de envío en el móvil (python3 test_v050.py)."""
from __future__ import annotations

import random
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import control  # noqa: E402
import lazo  # noqa: E402

HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
APK = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
JAVA = (ROOT / "android" / "src" / "net" / "lazoo" / "app" / "MainActivity.java").read_text(encoding="utf-8")


def simulate(arrivals, until):
    """arrivals: lista de (t, dx, dy). Reproduce a 200 Hz y devuelve (pasos, continuo)."""
    out = []
    c = control.Continuo(dispatch=lambda dx, dy: out.append((dx, dy)), clock=lambda: 0.0)
    if hasattr(c, "set_pred"):
        c.set_pred(False)  # 0.51: aquí se prueba el comportamiento de 0.50
    arrivals = sorted(arrivals)
    i, t, steps = 0, 0.0, []
    while t <= until:
        while i < len(arrivals) and arrivals[i][0] <= t:
            c.push(arrivals[i][1], arrivals[i][2], now=arrivals[i][0], start=False)
            i += 1
        n = len(out)
        c.tick(now=t)
        if len(out) > n:
            steps.append((t, out[-1]))
        t += c.TICK
    return out, steps, c


def bursty(seconds=2.0, seed=1):
    """El móvil genera 60/s de 3 px, pero la red los entrega a ráfagas cada ~150 ms."""
    rnd = random.Random(seed)
    gen = [(k / 60, 3, -2) for k in range(int(seconds * 60))]
    out, release = [], 0.0
    for t, dx, dy in gen:
        if t > release:
            release += rnd.uniform(0.10, 0.18)
        out.append((release, dx, dy))
    return out, gen


class Version(unittest.TestCase):
    def test_version(self) -> None:
        self.assertEqual(lazo.VERSION, "0.64")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.64")
        self.assertIn('android:versionName="1"', APK)
        self.assertIn('android:versionCode="64"', APK)


class Continuo(unittest.TestCase):
    def test_conserva_total(self) -> None:
        arr, gen = bursty()
        out, _steps, c = simulate(arr, 3.0)
        self.assertEqual(sum(a for a, _ in out), sum(g[1] for g in gen))
        self.assertEqual(sum(b for _, b in out), sum(g[2] for g in gen))
        self.assertEqual(c.pending(), (0.0, 0.0))

    def test_reparte_en_pasos(self) -> None:
        arr, _ = bursty()
        out, steps, _c = simulate(arr, 3.0)
        self.assertGreater(len(out), len(set(a[0] for a in arr)) * 3)  # mucho más que una por ráfaga
        times = [t for t, _ in steps if 0.3 < t < 1.8]
        gaps = sorted(b - a for a, b in zip(times, times[1:]))
        self.assertLess(gaps[int(len(gaps) * 0.9)], 0.02)  # pasos regulares, sin huecos largos

    def test_retraso_acotado(self) -> None:
        arr, _ = bursty()
        _out, steps, _c = simulate(arr, 3.0)
        # tras la última llegada, la cola se vacía pronto
        last_in = max(a[0] for a in arr)
        self.assertLess(steps[-1][0] - last_in, 0.20)
        # y un empujón enorme no deja más de ~150 ms de deuda
        out, steps, _ = simulate([(0.0, 2000, 0)], 1.0)
        self.assertEqual(sum(a for a, _ in out), 2000)
        self.assertLess(steps[-1][0], 0.30)

    def test_colchon_se_adapta(self) -> None:
        c = control.Continuo(dispatch=lambda *a: None, clock=lambda: 0.0)
        base = c.buffer
        for k in range(10):
            c.push(5, 0, now=k * 0.12, start=False)
        self.assertGreater(c.buffer, base)
        self.assertLessEqual(c.buffer, c.MAX_BUF)
        for k in range(600):
            c.push(1, 0, now=2 + k * 0.004, start=False)
        self.assertLess(c.buffer, c.MAX_BUF)

    def test_flush_antes_de_clic(self) -> None:
        out = []
        c = control.Continuo(dispatch=lambda dx, dy: out.append((dx, dy)), clock=lambda: 0.0)
        c.push(7, -3, now=0, start=False)
        c.flush()
        self.assertEqual(out, [(7, -3)])
        src = (ROOT / "control.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(src.count("CONTINUO.flush()"), 3)

    def test_api_y_diag(self) -> None:
        self.assertIn("continuo", lazo.ACTIONS)
        d = lazo.mouse_diag()["continuo"]
        for k in ("on", "colchon_ms", "pasos_s", "cola_max_ms"):
            self.assertIn(k, d)
        self.assertTrue(control.CONTINUO.on)


class Interfaz(unittest.TestCase):
    def test_controles(self) -> None:
        raton = HTML[HTML.index('id="pad"'):HTML.index('id="view-windows"')]
        self.assertIn('id="aim-continuo"', raton)
        self.assertIn('id="aim-smooth"', raton)
        for needle in ("Movimiento continuo", "Colchón del PC", "Pasos aplicados/s", "Cola pendiente máx.",
                       "/api/continuo", "/api/move", "sealBytes", "bufferedAmount"):
            self.assertIn(needle, JS)

    def test_apk_wifi(self) -> None:
        self.assertIn("WAKE_LOCK", APK)
        for needle in ("WIFI_MODE_FULL_LOW_LATENCY", "WIFI_MODE_FULL_HIGH_PERF", "onPause", "onDestroy", "release()"):
            self.assertIn(needle, JAVA)


@unittest.skipUnless(shutil.which("node"), "sin node")
class Ritmo(unittest.TestCase):
    def test_send_wait(self) -> None:
        a = JS.index("const SEND_MIN_MS"); b = JS.index("function flushPointer")
        src = "const diag={rtt:[]};const avg=(l)=>(l.length?l.reduce((a,b)=>a+b,0)/l.length:null);\n" + JS[a:b] + \
            "console.log([sendWait(100,0,90,null),sendWait(120,0,90,null),sendWait(100,0,90,200),sendWait(100,1000,90,null)].join(','))"
        out = subprocess.run(["node", "-e", src], capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(out, "7,0,15,30")


if __name__ == "__main__":
    unittest.main()
