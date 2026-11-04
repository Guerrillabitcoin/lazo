"""LaZoo 0.51: predicción de movimiento, inercia y contabilidad sin deriva (python3 test_v051.py)."""
from __future__ import annotations

import importlib.util
import random
import shutil
import statistics
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


def bursty(seconds=2.0, seed=1, lo=0.10, hi=0.30, dx=4, dy=-2):
    """El móvil manda 60/s; la red los entrega a ráfagas con huecos de lo..hi s."""
    rnd = random.Random(seed)
    gen = [(k / 60, dx, dy) for k in range(int(seconds * 60))]
    out, release = [], 0.0
    for t, a, b in gen:
        if t > release:
            release = t + rnd.uniform(lo, hi)
        out.append((release, a, b))
    return out, gen


def simulate(arrivals, until, pred=True, inercia=None, end_at=None, cls=None):
    out = []
    c = (cls or control.Continuo)(dispatch=lambda dx, dy: out.append((dx, dy)), clock=lambda: 0.0)
    if hasattr(c, "set_pred"):
        c.set_pred(pred)
        c.set_inercia(inercia)
    arrivals = sorted(arrivals)
    i, t, per_tick = 0, 0.0, []
    ended = False
    while t <= until:
        while i < len(arrivals) and arrivals[i][0] <= t:
            c.push(arrivals[i][1], arrivals[i][2], now=arrivals[i][0], start=False)
            i += 1
        if end_at is not None and not ended and t >= end_at:
            c.touch_end(now=t, start=False)
            ended = True
        n = len(out)
        c.tick(now=t)
        per_tick.append((t, out[-1] if len(out) > n else (0, 0)))
        t += c.TICK
    return out, per_tick, c


def roughness(per_tick, t0, t1):
    """Desviación típica del cambio de velocidad entre pasos consecutivos (px/tick)."""
    v = [abs(a) + abs(b) for t, (a, b) in per_tick if t0 <= t <= t1]
    return statistics.pstdev([y - x for x, y in zip(v, v[1:])])


def longest_still(per_tick, t0, t1):
    run = best = 0
    for t, (a, b) in per_tick:
        if t0 <= t <= t1:
            run = run + 1 if not (a or b) else 0
            best = max(best, run)
    return best


class Version(unittest.TestCase):
    def test_version(self) -> None:
        self.assertEqual(lazo.VERSION, "0.55")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.55")
        self.assertIn('android:versionName="0.55"', APK)
        self.assertIn('android:versionCode="55"', APK)


class Prediccion(unittest.TestCase):
    def test_sin_deriva(self) -> None:
        for seed in range(6):
            arr, gen = bursty(seed=seed)
            for inercia in (None,):
                out, _p, c = simulate(arr, 3.5)
                self.assertEqual(sum(a for a, _ in out), sum(g[1] for g in gen), seed)
                self.assertEqual(sum(b for _, b in out), sum(g[2] for g in gen), seed)
                self.assertLess(c.drift(), 1e-6)
                self.assertLess(abs(c.pending()[0]) + abs(c.pending()[1]), 1.0)

    def test_sin_deriva_con_fin_de_toque(self) -> None:
        arr, gen = bursty(seed=3)
        out, _p, c = simulate(arr, 3.5, end_at=max(a[0] for a in arr) + 0.01)
        self.assertEqual(sum(a for a, _ in out), sum(g[1] for g in gen))
        self.assertEqual(sum(b for _, b in out), sum(g[2] for g in gen))

    def test_mas_suave(self) -> None:
        better = 0
        for seed in range(6):
            arr, _ = bursty(seed=seed)
            _o, on, _ = simulate(arr, 3.0, pred=True)
            _o, off, _ = simulate(arr, 3.0, pred=False)
            r_on, r_off = roughness(on, 0.4, 1.8), roughness(off, 0.4, 1.8)
            if r_on < r_off:
                better += 1
            self.assertLessEqual(longest_still(on, 0.4, 1.8), longest_still(off, 0.4, 1.8))
            self.assertLessEqual(max(abs(a) + abs(b) for _t, (a, b) in on), max(abs(a) + abs(b) for _t, (a, b) in off) + 2)
        self.assertGreaterEqual(better, 5)

    def test_extrapolacion_acotada(self) -> None:
        # un único tren de datos y luego silencio: la predicción dura <= PRED_MAX y se apaga
        arr = [(k / 60, 5, 0) for k in range(30)]
        out, per, c = simulate(arr, 2.0)
        moving = [t for t, (a, b) in per if a or b]
        last_in = arr[-1][0]
        pred_ticks = [t for t in moving if last_in + 0.06 < t < c.SETTLE + last_in]
        if pred_ticks:
            self.assertLess(max(pred_ticks) - last_in, c.PRED_MAX + c.buffer + 0.07)
        self.assertLess(moving[-1] - last_in, c.SETTLE + c.RETURN_TIME + 0.1)  # devuelve y se para
        self.assertEqual(sum(a for a, _ in out), 150)
        self.assertEqual(c.tick(now=5.0), (0, 0))
        self.assertFalse(c._wants(5.0))

    def test_apagado_igual_que_050(self) -> None:
        src = subprocess.run(["git", "show", "52b10a7:control.py"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        spec = importlib.util.spec_from_loader("control050", loader=None)
        mod = importlib.util.module_from_spec(spec)
        mod.__dict__["__file__"] = str(ROOT / "control050.py")
        exec(compile(src, "control050.py", "exec"), mod.__dict__)
        for seed in range(4):
            arr, _ = bursty(seed=seed)
            a, pa, _ = simulate(arr, 3.0, pred=False)
            b, pb, _ = simulate(arr, 3.0, cls=mod.Continuo)
            self.assertEqual(pa, pb)
            # fin de toque sin inercia no cambia nada
            c, pc, _ = simulate(arr, 3.0, pred=False, end_at=1.0)
            self.assertEqual(pc, pb)

    def test_flush_sin_prediccion(self) -> None:
        out = []
        c = control.Continuo(dispatch=lambda dx, dy: out.append((dx, dy)), clock=lambda: 0.0)
        for k in range(10):
            c.push(6, 0, now=k / 60, start=False)
            c.tick(now=k / 60)
        t = 10 / 60
        while not c._dbx and t < 0.6:
            c.tick(now=t); t += c.TICK
        self.assertGreater(c._dbx, 0)  # había predicho algo
        c.flush()  # un clic
        self.assertEqual(sum(a for a, _ in out), 60)
        self.assertEqual(c._dbx, 0)


class Inercia(unittest.TestCase):
    def test_desliza_y_frena(self) -> None:
        arr = [(k / 60, 8, 0) for k in range(30)]
        out_no, _, _ = simulate(arr, 3.0, end_at=0.5)
        res = {}
        for lvl in ("poca", "media", "mucha"):
            out, per, c = simulate(arr, 3.0, inercia=lvl, end_at=0.5)
            res[lvl] = sum(a for a, _ in out)
            moving = [t for t, (a, b) in per if a or b]
            self.assertLess(moving[-1], 0.5 + c.GLIDE_MAX + 0.01)
        self.assertEqual(sum(a for a, _ in out_no), 240)
        self.assertLess(240, res["poca"])
        self.assertLess(res["poca"], res["media"])
        self.assertLess(res["media"], res["mucha"])

    def test_cancela(self) -> None:
        out = []
        c = control.Continuo(dispatch=lambda dx, dy: out.append((dx, dy)), clock=lambda: 0.0)
        c.set_inercia("mucha")
        for k in range(20):
            c.push(8, 0, now=k / 60, start=False)
        c.touch_end(now=20 / 60, start=False)
        self.assertIsNotNone(c._glide)
        c.flush()
        self.assertIsNone(c._glide)
        c.touch_end(now=20 / 60, start=False)
        c.push(1, 0, now=0.6, start=False)
        self.assertIsNone(c._glide)
        self.assertIsNone(control.Continuo().inercia)  # apagada por defecto


class Api(unittest.TestCase):
    def test_api_y_diag(self) -> None:
        for a in ("prediccion", "inercia", "fin", "continuo"):
            self.assertIn(a, lazo.ACTIONS)
        d = lazo.mouse_diag()["continuo"]
        for k in ("prediccion", "inercia", "predichos_px_s", "error_medio_px", "error_max_px", "deriva_px"):
            self.assertIn(k, d)
        self.assertTrue(control.CONTINUO.pred)


class Interfaz(unittest.TestCase):
    def test_controles(self) -> None:
        raton = HTML[HTML.index('id="pad"'):HTML.index('id="view-windows"')]
        for i in ('id="aim-pred"', 'id="aim-inercia"', 'id="aim-inercia-nivel"', 'id="aim-continuo"'):
            self.assertIn(i, raton)
        for needle in ("Predicción de movimiento", "Inercia al soltar", "Píxeles predichos/s", "Error de predicción",
                       "Deriva acumulada", "/api/prediccion", "/api/inercia", "/api/fin", "lazo-pred", "lazo-inercia"):
            self.assertIn(needle, JS + HTML)

    @unittest.skipUnless(shutil.which("node"), "sin node")
    def test_js_sintaxis(self) -> None:
        subprocess.run(["node", "--check", str(ROOT / "static" / "app.js")], check=True)


if __name__ == "__main__":
    unittest.main()
