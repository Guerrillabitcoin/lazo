"""Pruebas de la 0.74: el ratón entre PCs sin tirones y la prueba de fluidez.

    python3 test_v074.py

- fluidez.py: medir ritmos (Hz, huecos, jitter), el reloj del PC, el Suavizador (reparte cada
  movimiento en pasos de 4 ms en su tiempo, sin predecir, sin perder decimales) y el veredicto.
- Canal /kvm: MOVER_T (con la hora del emisor), PIDE_MEDIDA y MEDIDA solo si el receptor dice
  X-LaZoo-KVM: 2; con un receptor anterior se sigue mandando MOVER.
- El emisor manda a ritmo fijo (tandas de 4 ms), no una trama por evento.
- Panel: «Suavizar ratón entre PCs» (encendido de serie) y «Probar fluidez».
- APK sin cambios (App 3), versión 0.74.
"""
from __future__ import annotations

import json
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ.setdefault("LAZO_DATOS", tempfile.mkdtemp())

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import fluidez as F  # noqa: E402
import lazo  # noqa: E402
import pcapc  # noqa: E402
import protocol  # noqa: E402
import test_v070  # noqa: E402
from test_v070 import CapturaFalsa, Falso, esperar  # noqa: E402

MESA = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
LAZO = (ROOT / "lazo.py").read_text(encoding="utf-8")
PCAPC = (ROOT / "pcapc.py").read_text(encoding="utf-8")
FLU = (ROOT / "fluidez.py").read_text(encoding="utf-8")


# --- 1. Medir --------------------------------------------------------------------------------


class Medir(unittest.TestCase):
    def test_resumen_sin_pausas(self):
        t = [i * 0.008 for i in range(100)] + [0.792 + 1.0 + i * 0.008 for i in range(50)]  # 1 s quieto en medio
        r = F.resumen(t)
        self.assertEqual(r["hz"], 125)
        self.assertLess(r["hueco_max_ms"], 9)   # la pausa de 1 s no es un tirón
        t2 = [i * 0.008 for i in range(50)] + [0.392 + 0.060] + [0.452 + i * 0.008 for i in range(1, 50)]
        self.assertAlmostEqual(F.resumen(t2)["hueco_max_ms"], 60.0, delta=0.5)
        self.assertEqual(F.resumen([])["n"], 0)

    def test_ritmo(self):
        r = F.Ritmo(maximo=3)
        for t in (0.0, 0.01, 0.02, 0.03):
            r.apunta(t)
        self.assertEqual(len(r.t), 3)
        self.assertEqual(r.resumen()["hz"], 100)
        r.vaciar()
        self.assertEqual(r.t, [])

    def test_reloj_detecta_saltos(self):
        t = [0.0]
        pasos = iter([0.004] * 50 + [0.030] + [0.004] * 1000)

        def dormir(s):
            t[0] += next(pasos)

        r = F.reloj(0.5, dormir=dormir, ahora=lambda: t[0])
        self.assertAlmostEqual(r["retraso_max_ms"], 26.0, delta=0.1)
        self.assertLess(r["retraso_p95_ms"], 1)
        self.assertGreater(F.reloj(0.05)["n"], 3)  # el de verdad también funciona

    def test_acelerar_cuenta_quien_lo_pide(self):
        antes = sys.getswitchinterval()
        self.assertEqual(F.acelerar(True), 0.001)
        F.acelerar(True)
        F.acelerar(False)
        self.assertEqual(sys.getswitchinterval(), 0.001)
        F.acelerar(False)
        self.assertEqual(sys.getswitchinterval(), antes)
        F.acelerar(False)  # de más: no rompe nada
        self.assertEqual(sys.getswitchinterval(), antes)

    def test_windows_solo_en_windows(self):
        if sys.platform != "win32":
            self.assertFalse(F.no_frenar_proceso())
            self.assertFalse(F.prioridad_hilo(2))
        self.assertIn("SetProcessInformation", FLU)
        self.assertIn("0x1 | 0x4", FLU)  # EXECUTION_SPEED | IGNORE_TIMER_RESOLUTION
        self.assertNotIn("TIME_CRITICAL =", FLU)


# --- 2. Suavizador ---------------------------------------------------------------------------


def simular(suave: bool, llegadas: list[tuple[float, int, int]], fin: float = 1.5):
    """llegadas: (instante, dx, ms_emisor). Devuelve [(t, dx)] aplicados y lo recibido acumulado."""
    t = [0.0]
    out: list[tuple[float, int]] = []
    s = F.Suavizador(lambda x, y: out.append((t[0], x)), reloj=lambda: t[0], hilo=False)
    llegadas = sorted(llegadas)
    k = 0
    recibido: list[tuple[float, int]] = []
    while t[0] < fin:
        while k < len(llegadas) and llegadas[k][0] <= t[0]:
            _, dx, te = llegadas[k]
            recibido.append((t[0], dx))
            if suave:
                s.meter(dx, 0, te)
            else:
                out.append((t[0], dx))
            k += 1
        if suave:
            s.paso()
        t[0] = round(t[0] + 0.004, 6)
    if suave:
        s.vaciar()
    return out, recibido


def con_tirones(n=150, cada=0.008, px=8):
    """El emisor manda cada 8 ms; la red retiene una de cada cinco 24 ms (Wi-Fi). Es TCP: lo que
    va detrás de una trama retenida llega con ella, de golpe."""
    out, antes = [], 0.0
    for i in range(n):
        llega = max(antes, i * cada + 0.003 + (0.024 if i % 5 == 0 else 0.0))
        out.append((llega, px, int(i * cada * 1000) & 0xFFFF))
        antes = llega
    return out


class Suavizador(unittest.TestCase):
    def test_no_se_pierde_nada(self):
        out, _ = simular(True, con_tirones())
        self.assertEqual(sum(x for _t, x in out), 150 * 8)
        # decimales: 1 px cada 8 ms repartido en pasos de 4 ms sigue sumando exacto
        out, _ = simular(True, [(i * 0.008, 1, i * 8) for i in range(101)])
        self.assertEqual(sum(x for _t, x in out), 101)

    def test_mas_regular_que_sin_suavizar(self):
        def baile(out):
            por = {}
            for t, x in out:
                por[round(t / 0.016)] = por.get(round(t / 0.016), 0) + x
            v = list(por.values())[5:-5]
            return statistics.pstdev(v)

        crudo, _ = simular(False, con_tirones())
        suave, _ = simular(True, con_tirones())
        self.assertLess(baile(suave), baile(crudo) / 2, (baile(suave), baile(crudo)))

    def test_no_predice(self):
        out, recibido = simular(True, con_tirones())
        hecho = 0
        for t, x in out:
            hecho += x
            llegado = sum(dx for tr, dx in recibido if tr <= t)
            self.assertLessEqual(hecho, llegado + 1, "nunca se aplica algo que aún no ha llegado")  # +1: redondeo

    def test_poco_retraso(self):
        out, recibido = simular(True, [(i * 0.008 + 0.003, 8, i * 8) for i in range(100)])
        # lo último llega en 0.795 s; a los 50 ms ya está todo aplicado
        self.assertLessEqual(max(t for t, _ in out), 0.795 + 0.050)

    def test_vaciar_antes_de_un_clic(self):
        aplicados = []
        t = [0.0]
        s = F.Suavizador(lambda x, y: aplicados.append((x, y)), reloj=lambda: t[0], hilo=False)
        s.meter(10, -4, 0)
        self.assertEqual(s.vaciar(), (10, -4))
        self.assertFalse(s.pendiente())

    def test_se_pone_al_dia(self):
        t = [0.0]
        out = []
        s = F.Suavizador(lambda x, y: out.append(x), reloj=lambda: t[0], hilo=False)
        for i in range(200):  # llega todo de golpe, con horas de 1,6 s de movimiento
            s.meter(1, 0, i * 8)
        span = s.cola[-1][1] - s.cola[0][0]
        self.assertLessEqual(span, F.MAX_COLA + F.COLCHON_MAX + 0.01, "nunca va más de ~0,12 s por detrás")

    def test_ms_de_16_bits_dan_la_vuelta(self):
        s = F.Suavizador(lambda x, y: None, hilo=False)
        a = s._desenrollar(65530)
        b = s._desenrollar(4)
        self.assertAlmostEqual(b - a, 0.010)

    def test_hilo_de_verdad(self):
        out = []
        s = F.Suavizador(lambda x, y: out.append((x, y)))
        for i in range(10):
            s.meter(3, 1, int(time.monotonic() * 1000) & 0xFFFF)
            time.sleep(0.008)
        self.assertTrue(esperar(lambda: sum(x for x, _ in out) == 30, 2))
        self.assertEqual(sum(y for _, y in out), 10)
        s.cerrar()


# --- 3. Canal --------------------------------------------------------------------------------


class Canal(unittest.TestCase):
    def test_nuevos_eventos(self):
        evs = [(pcapc.MOVER_T, 5, -7, 65535), (pcapc.PIDE_MEDIDA, 3, 1), (pcapc.MEDIDA, 3, 125, 87, 12, 40, True)]
        _n, out = pcapc.decodificar(pcapc.codificar(9, evs))
        self.assertEqual(out, [(pcapc.MOVER_T, 5, -7, 65535), (pcapc.PIDE_MEDIDA, 3, 1), (pcapc.MEDIDA, 3, 125, 87, 12, 40, 1)])
        _n, out = pcapc.decodificar(pcapc.codificar(1, [(pcapc.MOVER_T, 70000, 0, 77)]))
        self.assertEqual(sum(e[1] for e in out), 70000)
        self.assertEqual({e[3] for e in out}, {77})
        with self.assertRaises(protocol.ProtocolError):
            pcapc.decodificar(pcapc.CABECERA + b"\x01\x00\x00\x00" + bytes([pcapc.PIDE_MEDIDA]) + b"\x01\x00\x00\x00\x07")
        self.assertEqual(pcapc.LOTE, 0.004)

    def test_receptor_suave_y_clic_en_su_sitio(self):
        f = Falso()
        r = pcapc.Receptor(f, suavizar=True, hilo_suave=False)
        r.tratar(pcapc.codificar(1, [(pcapc.MOVER_T, 7, 2, 100)]))
        r.tratar(pcapc.codificar(2, [(pcapc.MOVER_T, 5, 0, 108), (pcapc.BOTON, 1, 1)]))
        hechos = f.ver()
        self.assertEqual(sum(h[1] for h in hechos if h[0] == "mover"), 12, "antes del clic, todo el movimiento")
        self.assertEqual(hechos[-1], ("boton", 1, True))
        r.cerrar()

    def test_receptor_sin_suavizar_como_antes(self):
        f = Falso()
        r = pcapc.Receptor(f)
        self.assertIsNone(r.suave)
        r.tratar(pcapc.codificar(1, [(pcapc.MOVER_T, 7, 2, 100)]))
        self.assertEqual(f.ver(), [("mover", 7, 2)])

    def test_receptor_mide(self):
        r = pcapc.Receptor(Falso())
        r.tratar(pcapc.codificar(1, [(pcapc.PIDE_MEDIDA, 5, 0)]))
        for i in range(2, 30):
            r.tratar(pcapc.codificar(i, [(pcapc.MOVER_T, 1, 0, i)]))
            time.sleep(0.004)
        out = r.tratar(pcapc.codificar(40, [(pcapc.PIDE_MEDIDA, 5, 1)]))
        self.assertEqual(out[0][0], pcapc.MEDIDA)
        self.assertEqual(out[0][1], 5)
        self.assertGreater(out[0][2], 50)
        self.assertFalse(r.midiendo)
        _n, ev = pcapc.decodificar(pcapc.codificar(1, out))
        self.assertEqual(ev[0][0], pcapc.MEDIDA)

    def test_emisor_sin_v2_manda_mover(self):
        c = pcapc.Control(pcapc.PCs(Path(tempfile.mkdtemp())), fabrica=CapturaFalsa)
        c.mover(3, 4)
        c.boton(1, True)
        self.assertEqual(c._cola[0], (pcapc.MOVER, 3, 4))
        self.assertFalse(c.pedir_medida(1, 0))
        c.v2 = True
        c._cola = []
        c.mover(1, 1)
        c.boton(1, False)
        self.assertEqual(c._cola[0][0], pcapc.MOVER_T)

    def test_ritmo_fijo_no_una_trama_por_evento(self):
        a, b = socket.socketpair()
        pcs = pcapc.PCs(Path(tempfile.mkdtemp()))
        kd = os.urandom(32)
        pcs.guardar({"id": "ef" * 8, "host": "127.0.0.1", "puerto": 1, "nombre": "x"}, kd)
        sello = pcapc.claves(kd)[1]
        ctl = pcapc.Control(pcs, fabrica=CapturaFalsa, conectar_fn=lambda *a_, **k: a)
        pcapc._VERSIONES["ef" * 8] = 2
        ctl.iniciar("ef" * 8)
        self.assertTrue(ctl.v2)
        tramas: list[tuple[float, list]] = []
        fin = threading.Event()

        def leer():
            b.settimeout(2)
            try:
                while not fin.is_set():
                    op, data = protocol.ws_read(b, pcapc.MAX_TRAMA)
                    if op != 2:
                        continue
                    _n, evs = pcapc.decodificar(protocol.open_sealed(data, sello))
                    movs = [e for e in evs if e[0] == pcapc.MOVER_T]
                    if movs:
                        tramas.append((time.monotonic(), movs))
                    for e in evs:
                        if e[0] == pcapc.LATIDO_EV:
                            protocol.ws_send(b, 2, protocol.seal(pcapc.codificar(len(tramas) + 1000, [(pcapc.RESPUESTA, e[1])]), sello))
            except (OSError, protocol.ProtocolError):
                pass

        th = threading.Thread(target=leer, daemon=True)
        th.start()
        n = 0
        t0 = time.monotonic()
        while time.monotonic() - t0 < 0.6:
            ctl.mover(1, 0)
            n += 1
            time.sleep(0.001)
        time.sleep(0.1)
        ctl.parar("")
        fin.set()
        b.close()
        total = sum(m[1] for _t, ms in tramas for m in ms)
        self.assertEqual(total, n, "nada se pierde")
        self.assertLess(len(tramas), n * 0.6, "se juntan: no una trama por evento")
        huecos = [y[0] - x[0] for x, y in zip(tramas, tramas[1:])]
        self.assertGreater(statistics.median(huecos), 0.0025)
        self.assertLess(statistics.median(huecos), 0.012)


# --- 4. De punta a punta (servidor de verdad) --------------------------------------------------


class PuntaAPunta(unittest.TestCase):
    # El servidor de verdad de test_v070, sin volver a correr sus pruebas.
    setUp = test_v070.ConServidor.setUp
    tearDown = test_v070.ConServidor.tearDown
    emparejar = test_v070.ConServidor.emparejar

    def test_cabecera_y_prueba_completa(self):
        who, _ = self.emparejar()
        ctl = pcapc.Control(self.pcs, fabrica=CapturaFalsa)
        ctl.iniciar(who)
        self.assertEqual(pcapc._VERSIONES.get(who), 2)
        self.assertTrue(ctl.v2)
        self.assertTrue(esperar(lambda: pcapc.RECEPCION.nombre_actual() != ""))

        def mover_un_rato(_s):
            t0 = time.monotonic()
            while time.monotonic() - t0 < 0.8:
                ctl.mover(2, 1)
                time.sleep(0.004)

        prueba = pcapc.Prueba(ctl, dormir=mover_un_rato, medir_reloj=lambda: {"retraso_max_ms": 1.0, "retraso_p95_ms": 0.5})
        prueba.empezar(hilo=False)
        v = prueba.ver()
        self.assertEqual(v["estado"], "hecho", v)
        m = v["medidas"]
        self.assertGreater(m["gancho"]["n"], 40)
        self.assertIsNotNone(m["receptor"], "el otro PC contestó con lo que midió")
        self.assertTrue(m["receptor"]["suavizar"])
        self.assertGreater(m["rtt"]["n"], 2)
        self.assertIn(v["nivel"], ("bien", "mal"))
        self.assertTrue(v["texto"])
        self.assertIsNone(ctl.medida)
        total = sum(h[1] for h in self.falso.ver() if h[0] == "mover")
        ctl.parar("")
        self.assertTrue(esperar(lambda: sum(h[1] for h in self.falso.ver() if h[0] == "mover") == 2 * m["gancho"]["n"]),
                        (total, m["gancho"]["n"]))

    def test_sin_pasar_al_otro_pc_solo_el_reloj(self):
        ctl = pcapc.Control(self.pcs, fabrica=CapturaFalsa)
        prueba = pcapc.Prueba(ctl, dormir=lambda s: None, medir_reloj=lambda: {"retraso_max_ms": 30.0, "retraso_p95_ms": 2.0})
        prueba.ESPERA = 0.0
        prueba.empezar(hilo=False)
        v = prueba.ver()
        self.assertEqual((v["estado"], v["nivel"]), ("hecho", "mal"))
        self.assertIn("reloj", v["texto"])
        self.assertIn("móvil", v["texto"])

    def test_suavizar_desde_el_panel(self):
        st, raw = self._local("/api/pcapc/suavizar", {"on": False})
        self.assertEqual(st, 200)
        self.assertFalse(json.loads(raw)["suavizar"])
        self.assertFalse(json.loads((self.tmp / "ajustes.json").read_text())["otro_pc_suavizar"])
        st, raw = self._local("/api/pcapc/suavizar", {"on": True})
        self.assertTrue(json.loads(raw)["suavizar"])
        self.assertIn("fluidez", json.loads(raw))

    def _local(self, ruta, cuerpo):
        import urllib.error
        import urllib.request

        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{ruta}", data=json.dumps(cuerpo).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-Lazo-Local": "1"})
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.status, res.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()


# --- 5. Veredicto ------------------------------------------------------------------------------


BIEN_GANCHO = {"n": 600, "hz": 125, "hueco_max_ms": 12.0, "p95_ms": 9.0, "jitter_ms": 1.0}


class Veredicto(unittest.TestCase):
    def v(self, **kw):
        r = {"modo": "completa", "reloj": {"retraso_max_ms": 2.0, "retraso_p95_ms": 1.0}, "gancho": BIEN_GANCHO,
             "envio": {"n": 600, "hz": 125, "hueco_max_ms": 12.0}, "rtt": {"n": 40, "medio_ms": 3.0, "max_ms": 9.0, "jitter_ms": 1.5},
             "receptor": {"llegadas_hz": 125, "hueco_max_ms": 14.0, "jitter_ms": 2.0, "aplicado_hueco_max_ms": 8.0, "suavizar": True}}
        r.update(kw)
        return F.veredicto(r, sistema="Windows")

    def test_todo_fino(self):
        v = self.v()
        self.assertEqual(v["nivel"], "bien")
        self.assertTrue(v["texto"].startswith("Todo fino"))
        self.assertTrue(any("Red" in d for d in v["datos"]))

    def test_windows_a_tirones(self):
        v = self.v(gancho={**BIEN_GANCHO, "hueco_max_ms": 80.0})
        self.assertEqual(v["nivel"], "mal")
        self.assertIn("Tu Windows entrega el ratón a tirones: huecos de 80 ms", v["texto"])
        self.assertTrue(any("Alto rendimiento" in c for c in v["consejos"]))
        self.assertEqual(self.v(tarde_max_ms=90.0)["nivel"], "mal")
        self.assertIn("Tu Windows", self.v(reloj={"retraso_max_ms": 20.0})["texto"])

    def test_la_red(self):
        v = self.v(rtt={"n": 40, "medio_ms": 8.0, "max_ms": 120.0, "jitter_ms": 20.0},
                   receptor={"llegadas_hz": 125, "hueco_max_ms": 110.0, "jitter_ms": 9.0, "aplicado_hueco_max_ms": 9.0, "suavizar": False})
        self.assertEqual(v["nivel"], "mal")
        self.assertIn("La red da tirones", v["texto"])
        self.assertIn("Suavizar ratón entre PCs", v["consejos"][0])

    def test_el_otro_pc(self):
        v = self.v(receptor={"llegadas_hz": 125, "hueco_max_ms": 14.0, "jitter_ms": 2.0, "aplicado_hueco_max_ms": 70.0, "suavizar": True})
        self.assertIn("El otro PC aplica el ratón a tirones", v["texto"])

    def test_sin_movimiento(self):
        self.assertEqual(self.v(gancho={"n": 3})["nivel"], "aviso")

    def test_solo_este_pc(self):
        v = F.veredicto({"modo": "local", "reloj": {"retraso_max_ms": 1.0, "retraso_p95_ms": 0.4}}, sistema="Windows", tecla="Ctrl+Alt+K")
        self.assertEqual(v["nivel"], "bien")
        self.assertIn("Ctrl+Alt+K", v["texto"])


# --- 6. Ajuste, Panel y entrega -----------------------------------------------------------------


class AjusteYPanel(unittest.TestCase):
    def test_suavizar_de_serie(self):
        a = pcapc.Ajustes()
        self.assertTrue(a.suavizar)
        d = Path(tempfile.mkdtemp())
        a.archivo = lambda: d / "ajustes.json"
        (d / "ajustes.json").write_text(json.dumps({"otro_pc_permitir": True}))
        self.assertTrue(a.cargar().suavizar, "quien venía de la 0.73 lo tiene encendido")
        a.set_suavizar(False)
        b = pcapc.Ajustes()
        b.archivo = a.archivo
        self.assertFalse(b.cargar().suavizar)

    def test_panel(self):
        self.assertIn('id="pc-suave" type="checkbox" checked /> Suavizar ratón entre PCs', MESA)
        self.assertIn('id="pc-fluidez-ok"', MESA)
        self.assertIn(">Probar fluidez<", MESA)
        self.assertIn('pcCall("suavizar"', MESA)
        self.assertIn('pcCall("fluidez"', MESA)
        self.assertIn("function pintaFluidez", MESA)
        i = MESA.index('id="otro-pc"')
        self.assertGreater(MESA.index('id="pc-fluidez-ok"'), i, "la prueba va en la sección PC a PC")

    def test_servidor(self):
        self.assertIn('self.send_header("X-LaZoo-KVM", str(pcapc.KVM_VERSION))', LAZO)
        self.assertIn("fluidez.no_frenar_proceso()", LAZO)
        self.assertIn('elif step == "fluidez":', LAZO)
        self.assertIn('elif step == "suavizar":', LAZO)

    def test_gancho_rapido(self):
        bloque = PCAPC[PCAPC.index("class CapturaWindows"):PCAPC.index("def captura_para_este_pc")]
        self.assertIn("fluidez.prioridad_hilo(2)", bloque)
        self.assertIn("GetTickCount", bloque)
        self.assertIn("timeBeginPeriod(1)", bloque)
        i = PCAPC.index("    def _enviar(")
        envio = PCAPC[i:PCAPC.index("    def _leer(", i)]
        self.assertIn("plazo + LOTE", envio)
        self.assertIn("fluidez.prioridad_hilo(1)", envio)
        self.assertIn("TCP_NODELAY", PCAPC[PCAPC.index("def conectar("):PCAPC.index("class Control")])

    def test_estado(self):
        e = pcapc.estado()
        self.assertIn("suavizar", e)
        self.assertEqual(e["fluidez"]["estado"], "nada")


class Entrega(unittest.TestCase):
    def test_version(self):
        self.assertEqual(lazo.VERSION, "0.74")
        self.assertEqual(pcapc.VERSION, "0.74")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.74")
        self.assertIn('<p class="ver">0.74', MESA)

    def test_apk_sin_cambios(self):
        texto = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:versionCode="66"', texto)
        self.assertIn('android:versionName="3"', texto)
        r = subprocess.run(["git", "diff", "--quiet", "faf9096", "--", "android"], cwd=ROOT, capture_output=True)
        if r.returncode in (0, 1):
            self.assertEqual(r.returncode, 0, "android/ cambió: la APK dejaría de ser la App 3")

    def test_solo_stdlib(self):
        import ast

        permitidos = set(sys.stdlib_module_names)
        for nodo in ast.walk(ast.parse(FLU)):
            if isinstance(nodo, ast.Import):
                for a in nodo.names:
                    self.assertIn(a.name.split(".")[0], permitidos)
            elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                self.assertIn(nodo.module.split(".")[0], permitidos)


if __name__ == "__main__":
    unittest.main()
