"""LaZoo 0.53: ajuste fino del ratón (python3 test_v053.py)."""
from __future__ import annotations

import collections
import importlib.util
import json
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
PRESETS = ("equilibrado", "fluidez", "retraso", "como050")


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


def make(preset=None, cls=None, out=None):
    out = [] if out is None else out
    c = (cls or control.Continuo)(dispatch=lambda dx, dy: out.append((dx, dy)), clock=lambda: 0.0)
    if preset:
        c.aplicar(control.PRESETS[preset], preset)
    return c, out


def simulate(arrivals, until, preset=None, cls=None, end_at=None, opts=None):
    c, out = make(preset, cls)
    if opts:
        c.aplicar(opts)
    arrivals = sorted(arrivals)
    i, t, per, ended = 0, 0.0, [], False
    while t <= until:
        while i < len(arrivals) and arrivals[i][0] <= t:
            c.push(arrivals[i][1], arrivals[i][2], now=arrivals[i][0], start=False)
            i += 1
        if end_at is not None and not ended and t >= end_at:
            c.touch_end(now=t, start=False)
            ended = True
        n = len(out)
        c.tick(now=t)
        per.append((t, out[-1] if len(out) > n else (0, 0)))
        t += c.TICK
    return out, per, c


def jerk(per, t0, t1):
    """Cambio de velocidad entre ventanas de 5 ms (desviación típica): menos = más suave."""
    b = collections.Counter()
    for t, (a, bb) in per:
        if t0 <= t <= t1:
            b[int(t / 0.005)] += abs(a) + abs(bb)
    v = [b[k] for k in range(int(t0 / 0.005), int(t1 / 0.005))]
    return statistics.pstdev([y - x for x, y in zip(v, v[1:])]), max(v)


class Version(unittest.TestCase):
    def test_version(self) -> None:
        self.assertEqual(lazo.VERSION, "0.53")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.53")
        self.assertIn('android:versionName="0.53"', APK)
        self.assertIn('android:versionCode="53"', APK)
        self.assertIn("0.53", (ROOT / "static" / "mesa.html").read_text(encoding="utf-8"))
        self.assertIn("LaZoo 0.53", HTML)


class CorreccionSuave(unittest.TestCase):
    def test_reparte_en_pasos_y_suma_exacta(self) -> None:
        for n in (2, 3, 4):
            c, out = make("equilibrado")
            c.aplicar({"correccion_pasos": n, "mezcla_ms": 0, "interpolacion": False})
            for k in range(12):
                c.push(6, 0, now=k / 60, start=False)
                c.tick(now=k / 60)
            t, debt = 12 / 60, 0
            while t < 1.5:
                c.tick(now=t)
                debt = max(debt, c._dbx)
                t += c.TICK
            self.assertGreater(debt, 5)
            back = [a for a, _ in out if a < 0]
            self.assertEqual(len(back), n)  # 2-4 pasos, no un salto
            self.assertEqual(-sum(back), debt)  # devuelve exactamente lo predicho
            self.assertLessEqual(max(back) - min(back), 1)  # pasos iguales
            self.assertEqual(sum(a for a, _ in out), 72)
            self.assertLess(c.drift(), 1e-6)

    def test_sobrepasado_al_llegar_datos(self) -> None:
        c, out = make("equilibrado")
        c.aplicar({"mezcla_ms": 0})
        for k in range(12):
            c.push(6, 0, now=k / 60, start=False)
            c.tick(now=k / 60)
        t = 12 / 60
        while c._dbx < 6 and t < 0.6:
            c.tick(now=t)
            t += c.TICK
        c.push(1, 0, now=t, start=False)  # llega menos de lo predicho
        self.assertEqual(c._corr, 3)
        while abs(c._px) >= 0.5 and t < 1:
            t += c.TICK
            c.tick(now=t)
        self.assertEqual(sum(a for a, _ in out), 12 * 6 + 1)


class Colchon(unittest.TestCase):
    def test_dentro_de_rango(self) -> None:
        for preset in PRESETS:
            c, _ = make(preset)
            a = control.PRESETS[preset]
            lo, hi = a["colchon_min_ms"] / 1000, a["colchon_max_ms"] / 1000
            for k in range(10):
                c.push(5, 0, now=k * 0.2, start=False)
                self.assertTrue(lo - 1e-9 <= c.buffer <= hi + 1e-9, (preset, c.buffer))
            for k in range(800):
                c.push(1, 0, now=3 + k * 0.004, start=False)
                self.assertTrue(lo - 1e-9 <= c.buffer <= hi + 1e-9, (preset, c.buffer))
        c, _ = make("equilibrado")
        for k in range(10):
            c.push(5, 0, now=k * 0.2, start=False)
        self.assertAlmostEqual(c.buffer, 0.040)
        for k in range(1500):
            c.push(1, 0, now=3 + k * 0.004, start=False)
        self.assertAlmostEqual(c.buffer, 0.015)

    def test_fijo(self) -> None:
        c, _ = make("equilibrado")
        c.aplicar({"colchon_modo": "fijo", "colchon_fijo_ms": 20})
        for k in range(10):
            c.push(5, 0, now=k * 0.2, start=False)
        self.assertAlmostEqual(c.buffer, 0.020)


class Interpolacion(unittest.TestCase):
    def test_solo_con_huecos(self) -> None:
        # red buena: 60/s sin huecos -> nunca interpola
        arr = [(k / 60, 4, -2) for k in range(120)]
        _o, _p, c = simulate(arr, 2.5, "equilibrado")
        self.assertEqual(c._n_interp, 0)
        out, per, c = simulate(arr, 2.5, "equilibrado")
        ref, pref, _ = simulate(arr, 2.5, "equilibrado", opts={"interpolacion": False})
        self.assertEqual(per, pref)  # con buena red no cambia nada (ni añade retraso)
        # con huecos sí
        arr2 = [(k * 0.08, 10, 0) for k in range(20)]
        c, out = make("equilibrado")
        c.aplicar({"interpolacion": True})
        lin_seen = 0
        t = 0.0
        i = 0
        while t < 2:
            while i < len(arr2) and arr2[i][0] <= t:
                c.push(arr2[i][1], arr2[i][2], now=arr2[i][0], start=False)
                i += 1
                lin_seen = max(lin_seen, c._lin)
            c.tick(now=t)
            t += c.TICK
        self.assertGreater(lin_seen, 0)
        self.assertLessEqual(lin_seen, round(c.MAX_BUF / c.TICK))  # pasos de 5 ms, nunca más del colchón máx.
        self.assertEqual(sum(a for a, _ in out), 200)


class Deriva(unittest.TestCase):
    def test_deriva_0_todos_los_presets(self) -> None:
        for preset in PRESETS:
            for seed in range(5):
                arr, gen = bursty(seed=seed)
                for end in (None, max(a[0] for a in arr) + 0.01):
                    out, _p, c = simulate(arr, 3.5, preset, end_at=end)
                    self.assertEqual(sum(a for a, _ in out), sum(g[1] for g in gen), (preset, seed))
                    self.assertEqual(sum(b for _, b in out), sum(g[2] for g in gen), (preset, seed))
                    self.assertLess(c.drift(), 1e-6)

    def test_todas_las_opciones_sin_deriva(self) -> None:
        rnd = random.Random(7)
        for _ in range(40):
            opts = {k: rnd.choice(v) if isinstance(v, tuple) and k not in (
                "mezcla_ms", "colchon_min_ms", "colchon_max_ms", "colchon_fijo_ms", "pred_max_ms", "pred_frenado_ms", "cola_max_ms")
                else (rnd.choice([True, False]) if v is bool else rnd.randint(*v))
                for k, v in control.AJUSTE_RANGOS.items() if k != "inercia"}
            opts["colchon_max_ms"] = max(opts["colchon_max_ms"], opts["colchon_min_ms"])
            arr, gen = bursty(seed=rnd.randint(0, 99))
            out, _p, c = simulate(arr, 3.5, "equilibrado", opts=opts)
            self.assertEqual(sum(a for a, _ in out), sum(g[1] for g in gen), opts)
            self.assertLess(c.drift(), 1e-6)


class Validacion(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = control.CONTINUO.ajuste()

    def tearDown(self) -> None:
        control.set_ajuste({"preset": "equilibrado"})

    def test_rangos(self) -> None:
        for bad in ({"correccion_pasos": 1}, {"correccion_pasos": 5}, {"mezcla_ms": 61}, {"mezcla_ms": -1},
                    {"colchon_min_ms": 5}, {"colchon_max_ms": 500}, {"frecuencia_hz": 1000}, {"frecuencia_hz": "200"},
                    {"tasa_envio": 240}, {"interpolacion": 1}, {"colchon_modo": "loco"}, {"inercia": "toda"},
                    {"pred_max_ms": float("nan")}, {"cola_max_ms": True}, {"otra": 1}, {"colchon_min_ms": 40, "colchon_max_ms": 20}):
            with self.assertRaises(control.ControlError, msg=bad):
                control.set_ajuste({"opciones": bad})
        for bad in ("nada", None, 3, [1]):
            with self.assertRaises(control.ControlError):
                control.set_ajuste({"preset": bad} if bad is not None else [])
        with self.assertRaises(control.ControlError):
            control.set_ajuste({"opciones": "x"})
        self.assertEqual(control.CONTINUO.ajuste()["preset"], "equilibrado")

    def test_preset_y_personalizado(self) -> None:
        st = control.set_ajuste({"preset": "fluidez"})
        self.assertEqual(st["preset"], "fluidez")
        self.assertEqual(control.CONTINUO.TICK, 1 / 250)
        st = control.set_ajuste({"opciones": {"frecuencia_hz": 500}})
        self.assertEqual(st["preset"], "personalizado")
        self.assertEqual(control.CONTINUO.TICK, 1 / 500)
        st = control.set_ajuste({"preset": "como050"})
        self.assertFalse(st["opciones"]["prediccion"])
        self.assertIsNone(st["opciones"]["inercia"])
        st = control.set_ajuste({})
        self.assertEqual(st["preset"], "como050")

    def test_por_defecto_equilibrado(self) -> None:
        self.assertEqual(control.CONTINUO.preset, "equilibrado")
        self.assertTrue(control.CONTINUO.pred)
        self.assertIn("ajuste", lazo.ACTIONS)


class Como050(unittest.TestCase):
    def test_identico_a_050(self) -> None:
        src = subprocess.run(["git", "show", "52b10a7:control.py"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        spec = importlib.util.spec_from_loader("control050b", loader=None)
        mod = importlib.util.module_from_spec(spec)
        mod.__dict__["__file__"] = str(ROOT / "control050.py")
        exec(compile(src, "control050.py", "exec"), mod.__dict__)
        for seed in range(5):
            arr, _ = bursty(seed=seed)
            _a, pa, _ = simulate(arr, 3.0, "como050")
            _b, pb, _ = simulate(arr, 3.0, cls=mod.Continuo)
            self.assertEqual(pa, pb, seed)
            _c, pc, _ = simulate(arr, 3.0, "como050", end_at=1.0)
            self.assertEqual(pc, pb)


class Suavidad(unittest.TestCase):
    def test_mas_suave_con_rafagas(self) -> None:
        better = 0
        for seed in range(8):
            arr, _ = bursty(seed=seed)
            _o, eq, _ = simulate(arr, 3.0, "equilibrado")
            _o, old, _ = simulate(arr, 3.0, "como050")
            _o, v052, _ = simulate(arr, 3.0)  # valores de 0.52 (predicción sin ajuste fino)
            j_eq, m_eq = jerk(eq, 0.4, 1.8)
            j_old, m_old = jerk(old, 0.4, 1.8)
            j_52, _m = jerk(v052, 0.4, 1.8)
            self.assertLess(j_eq, j_old)
            self.assertLess(m_eq, m_old)
            if j_eq < j_52:
                better += 1
        self.assertGreaterEqual(better, 6)


class Interfaz(unittest.TestCase):
    def test_renombrado(self) -> None:
        self.assertNotIn("Modo stats", HTML + JS)
        self.assertIn("Ajuste fino / stats", HTML)
        self.assertIn('localStorage.getItem("lazo-diag")', JS)  # migración de la clave antigua
        self.assertIn('"lazo-fino"', JS)
        for f in ("README.md", "AGENTS.md"):
            self.assertIn("Ajuste fino / stats", (ROOT / f).read_text(encoding="utf-8"))

    def test_controles(self) -> None:
        fino = HTML[HTML.index('id="fino"'):HTML.index("</section>", HTML.index('id="fino"'))]
        self.assertGreater(HTML.index('id="fino"'), HTML.index('id="diag-extra"'))  # visible solo con el modo
        for k in control.AJUSTE_RANGOS:
            if k not in ("prediccion", "inercia"):
                self.assertIn(f'data-op="{k}"', fino)
        for p in PRESETS:
            self.assertIn(f'data-preset="{p}"', fino)
        self.assertIn('id="fino-reset"', fino)
        self.assertEqual(fino.count("<small>"), len(control.AJUSTE_RANGOS) - 2)  # ayuda de una línea por opción
        # todos los valores de los <select> son válidos para el PC
        import re
        for k, vals in re.findall(r'data-op="(\w+)">((?:<option value="[^"]*">[^<]*</option>)+)', fino):
            for v in re.findall(r'value="([^"]*)"', vals):
                val = v if k == "colchon_modo" else int(v)
                control.validar_ajuste({k: val})
        for needle in ("/api/ajuste", "lazo-ajuste", "Correcciones suaves/s", "Pasos interpolados/s", "Colchón rango", "sendMinMs"):
            self.assertIn(needle, JS)

    @unittest.skipUnless(shutil.which("node"), "sin node")
    def test_js(self) -> None:
        subprocess.run(["node", "--check", str(ROOT / "static" / "app.js")], check=True)
        a = JS.index("function diagStats"); b = JS.index("window.__lzDiagSummary")
        st = control.CONTINUO.status()
        row = {"fps": 60, "cont": st, "drift": 0, "corr": 1, "corrSteps": 3, "interp": 20}
        src = "const fmt=(v,d=0)=>(v===null||v===undefined?'—':Number(v).toFixed(d));\n" + JS[a:b] + \
            f"\nconsole.log(diagSummary([{json.dumps(row)}],10,{{version:'0.53'}}))"
        out = subprocess.run(["node", "-e", src], capture_output=True, text=True, check=True).stdout
        for needle in ("Ajuste fino: Equilibrado", "corrección 3 pasos", "interpolación sí", "200 Hz", "Colchón rango: adaptativo 15-40 ms",
                       "Pasos interpolados/s", "Deriva acumulada: 0 px"):
            self.assertIn(needle, out)


class Api(unittest.TestCase):
    def test_diag(self) -> None:
        d = lazo.mouse_diag()["continuo"]
        for k in ("preset", "opciones", "colchon_ms", "colchon_min_ms", "colchon_max_ms", "pasos_s", "correcciones_s",
                  "interpolados_s", "error_medio_px", "deriva_px", "cola_max_ms"):
            self.assertIn(k, d)


if __name__ == "__main__":
    unittest.main()
