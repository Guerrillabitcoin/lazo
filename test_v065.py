"""LaZoo 0.65: mando de YouTube con el estado real del vídeo y «Seguir viendo en el móvil».

    python3 test_v065.py

- Barra de progreso: posición y duración de Windows; al arrastrar, «Ir a m:ss de m:ss»; el
  salto va a Windows y, si el navegador no lo deja, a las teclas de YouTube (cifra + flechas).
- Velocidad real en el estado; volumen y silencio leídos del reproductor (solo lectura).
- Tamaño de los subtítulos con + y - del teclado numérico (cualquier distribución).
- «Seguir en el móvil»: pausa, id de la barra (o el de patrocinios en pantalla completa),
  enlace con el minuto 2 s antes; la APK (App 2) lo abre fuera, solo YouTube y solo https.
- Nada nuevo sale a internet y nada toca la página de YouTube.
"""
from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("LAZO_DATOS", tempfile.mkdtemp())

ROOT = Path(__file__).resolve().parent

import control  # noqa: E402
import lazo  # noqa: E402
import mando  # noqa: E402
import patrocinios  # noqa: E402

JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
MESA = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
JAVA = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "android" / "src").rglob("*.java"))
APK = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
ROW = {"id": "77", "title": "Receta de lentejas - YouTube - Brave"}


class Silencio(unittest.TestCase):
    def test_nombre_del_boton(self):
        self.assertTrue(mando.es_silencio("Activar sonido (m)"))
        self.assertTrue(mando.es_silencio("Unmute (m)"))
        self.assertFalse(mando.es_silencio("Silenciar (m)"))
        self.assertFalse(mando.es_silencio("Mute (m)"))
        self.assertIsNone(mando.es_silencio("Ajustes"))
        self.assertIsNone(mando.es_silencio(""))


class PlanDeTeclas(unittest.TestCase):
    def test_con_duracion_cifra_y_flechas(self):
        self.assertEqual(mando.plan_teclas(10, 600, 125), {"cifra": "2", "diez": 0, "cinco": 1})
        self.assertEqual(mando.plan_teclas(None, 600, 0), {"cifra": "0", "diez": 0, "cinco": 0})
        self.assertEqual(mando.plan_teclas(None, 600, 5000)["cifra"], "9")  # nunca pasado el final
        self.assertEqual(mando.teclas(mando.plan_teclas(10, 600, 125)), [["2"], ["right"]])
        self.assertEqual(mando.teclas({"cifra": "3", "diez": 0, "cinco": -2}), [["3"], ["left"], ["left"]])

    def test_sin_duracion_desde_la_posicion(self):
        plan = mando.plan_teclas(30, 0, 75)
        self.assertEqual(plan, {"cifra": None, "diez": 4, "cinco": 1})
        self.assertEqual(mando.teclas(plan), [["l"]] * 4 + [["right"]])
        self.assertEqual(mando.teclas(mando.plan_teclas(100, 0, 60)), [["j"]] * 4)
        self.assertEqual(mando.teclas(mando.plan_teclas(None, 0, 60)), [])

    def test_como_mucho_24_pulsaciones(self):
        self.assertLessEqual(len(mando.teclas(mando.plan_teclas(0, 0, 100000))), 26)


class Enlace(unittest.TestCase):
    def test_minuto_dos_segundos_antes(self):
        self.assertEqual(mando.enlace("dQw4w9WgXcQ", 125.7), "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=123s")
        self.assertEqual(mando.enlace("dQw4w9WgXcQ", 1), "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(mando.enlace("dQw4w9WgXcQ", None), "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_solo_ids_validos(self):
        for malo in ("", "abc", "dQw4w9WgXcQ&x=1", "../../etc/pa"):
            with self.assertRaises(ValueError):
                mando.enlace(malo, 10)


class Lecturas(unittest.TestCase):
    def setUp(self):
        self.t = [100.0]
        self.pedidos: list[str] = []
        self.respuesta = {"ok": True, "vol": {"hay": True, "nivel": 35.4, "boton": "Silenciar (m)"}}

        def probe(line: str) -> dict:
            self.pedidos.append(line)
            return self.respuesta

        self.m = mando.Mando(probe=probe, clock=lambda: self.t[0])

    def test_volumen_y_cache(self):
        self.assertEqual(self.m.volumen("77"), {"level": 35, "muted": False})
        self.m.volumen("77")
        self.assertEqual(len(self.pedidos), 1)  # 3 s de caché: el móvil pregunta cada 2,5 s
        self.t[0] += mando.CACHE_VOL + 0.1
        self.respuesta = {"ok": True, "vol": {"hay": True, "nivel": 0, "boton": "Activar sonido (m)"}}
        self.assertEqual(self.m.volumen("77"), {"level": 0, "muted": True})
        self.m.volumen("77", fresco=True)
        self.assertEqual(len(self.pedidos), 3)
        self.assertIn('"c": "vol"', self.pedidos[0])

    def test_el_sondeo_no_espera_al_powershell(self):
        import threading

        lento = threading.Event()
        m = mando.Mando(clock=lambda: self.t[0])
        m.available = lambda: True  # type: ignore[method-assign]
        m.volumen = lambda hwnd, fresco=False: lento.wait(2) and None  # type: ignore[method-assign]
        self.assertIsNone(m.volumen_sin_esperar("77"))  # vuelve al momento
        self.assertTrue(m.leyendo.is_set())
        lento.set()
        m.vol_cache = {"77": (self.t[0] - 10, {"level": 20, "muted": False})}
        self.assertEqual(m.volumen_sin_esperar("77"), {"level": 20, "muted": False})  # la vieja, mientras llega

    def test_sin_reproductor_no_inventa(self):
        self.respuesta = {"ok": True, "vol": {"hay": False}}
        self.assertIsNone(self.m.volumen("77"))
        self.respuesta = {"ok": False, "error": "sin respuesta"}
        self.assertIsNone(self.m.volumen("78"))

    def test_ir_verificado(self):
        self.respuesta = {"ok": True, "aceptado": True, "verificado": True, "deja": True, "pos": 120.2}
        self.assertTrue(self.m.ir("Receta", 120)["ok"])
        self.respuesta = {"ok": True, "aceptado": True, "verificado": False, "deja": True}
        self.assertFalse(self.m.ir("Receta", 120)["ok"])

    def test_fuera_de_windows_no_hace_nada(self):
        with mock.patch.object(mando.platform, "system", return_value="Linux"):
            m = mando.Mando()
            self.assertFalse(m.available())
            self.assertIsNone(m.volumen("1"))
            self.assertEqual(m.direccion("1"), "")


class ScriptSoloLee(unittest.TestCase):
    def test_volumen_solo_lectura_y_dentro_del_reproductor(self):
        ps = mando.ps_script()
        self.assertIn("RangeValuePattern", ps)
        self.assertIn("reproductor de vídeo de youtube", ps)
        self.assertNotIn("InvokePattern", ps)       # no pulsa nada
        self.assertNotIn("SetValue", ps)
        self.assertNotIn("SetForegroundWindow", ps)  # no trae la ventana delante
        self.assertNotIn("SetCursorPos", ps)
        self.assertIn("TryChangePlaybackPositionAsync", ps)
        self.assertNotIn("http", ps.replace("youtu", ""))  # no sale a internet
        self.assertTrue(mando.encoded())

    def test_mando_no_abre_conexiones(self):
        src = (ROOT / "mando.py").read_text(encoding="utf-8")
        for prohibido in ("urllib.request", "urlopen", "socket", "http.client"):
            self.assertNotIn(prohibido, src)


class Control(unittest.TestCase):
    def setUp(self):
        self.keys: list[list[str]] = []
        self.patches = [
            mock.patch.object(control, "_find_youtube_unlocked", lambda: dict(ROW)),
            mock.patch.object(control, "_focus_for_keys", lambda _id: True),
            mock.patch.object(control, "_yt_keys", lambda k: self.keys.append(list(k))),
            mock.patch.object(control.time, "sleep", lambda _s: None),
            mock.patch.object(control, "_win_is_fullscreen", lambda _id: False),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def estado(self, **kw):
        base = {"playing": True, "pos": 100.0, "len": 600.0, "real": True, "rate": 1.25}
        base.update(kw)
        return mock.patch.object(control, "_yt_state", lambda _row: dict(base))

    def test_status_con_velocidad_y_volumen_reales(self):
        with self.estado(), mock.patch.object(control, "SYSTEM", "Windows"), \
                mock.patch.object(mando.MANDO, "volumen_sin_esperar", lambda hwnd: {"level": 40, "muted": True}):
            st = control.youtube("status")
        self.assertEqual((st["rate"], st["level"], st["muted"], st["vol_real"]), (1.25, 40, True, True))
        self.assertEqual((st["pos"], st["len"]), (100.0, 600.0))
        with self.estado(), mock.patch.object(control, "SYSTEM", "Linux"):
            self.assertFalse(control.youtube("status")["vol_real"])

    def test_seek_por_windows_sin_teclas(self):
        with self.estado(), mock.patch.object(control, "SYSTEM", "Windows"), \
                mock.patch.object(mando.MANDO, "ir", lambda t, s: {"ok": True}) as _:
            out = control.youtube("seek", {"to": 125})
        self.assertEqual((out["via"], out["pos"], self.keys), ("windows", 125.0, []))
        self.assertEqual(out["detail"], "Ir a 2:05")

    def test_seek_con_teclas_si_windows_no_deja(self):
        with self.estado(), mock.patch.object(control, "SYSTEM", "Windows"), \
                mock.patch.object(mando.MANDO, "ir", lambda t, s: {"ok": False}):
            out = control.youtube("seek", {"to": 125})
        self.assertEqual(out["via"], "teclas")
        self.assertEqual(self.keys, [["2"], ["right"]])

    def test_seek_valida_el_minuto(self):
        with self.estado():
            for malo in (None, "x", -3, float("nan")):
                with self.assertRaises(control.ControlError):
                    control.youtube("seek", {"to": malo})
            out = control.youtube("seek", {"to": 9999})
        self.assertEqual(out["pos"], 599.0)  # nunca pasado el final

    def test_subtitulos_mas_y_menos(self):
        with self.estado():
            control.youtube("subs_up")
            control.youtube("subs_down")
        self.assertEqual(self.keys, [["add"], ["subtract"]])
        self.assertEqual((control._WIN_VK["add"], control._WIN_VK["subtract"]), (0x6B, 0x6D))

    def test_teclas_mas_y_menos_fuera_de_windows(self):
        self.patches[2].stop()
        try:
            sent = []
            with mock.patch.object(control, "SYSTEM", "Linux"), mock.patch.object(control, "_chord", sent.append):
                control._yt_keys(["add"])
                control._yt_keys(["subtract"])
            self.assertEqual(sent, [["+"], ["-"]])
        finally:
            self.patches[2].start()

    def test_handoff_pausa_y_da_el_enlace(self):
        llamadas = []
        real = control.youtube

        def youtube(action, extra=None):
            if action == "play":
                llamadas.append(action)
                return {}
            return real(action, extra)

        with self.estado(pos=125.7), mock.patch.object(control, "SYSTEM", "Windows"), \
                mock.patch.object(control, "youtube", youtube), \
                mock.patch.object(mando.MANDO, "direccion", lambda h: "youtube.com/watch?v=dQw4w9WgXcQ&list=x"):
            out = real("handoff")
        self.assertEqual(out["url"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=123s")
        self.assertEqual((out["paused"], out["playing"], llamadas), (True, False, ["play"]))

    def test_handoff_en_pausa_no_toca_nada_y_usa_patrocinios_si_no_ve_la_barra(self):
        with self.estado(playing=False, pos=10.0), mock.patch.object(control, "SYSTEM", "Windows"), \
                mock.patch.object(mando.MANDO, "direccion", lambda h: ""), \
                mock.patch.dict(patrocinios.PATROCINIOS.v, {"hwnd": "77", "titulo": ROW["title"], "vid": "abcdefghijk"}, clear=True):
            out = control.youtube("handoff")
        self.assertEqual(out["url"], "https://www.youtube.com/watch?v=abcdefghijk&t=8s")
        self.assertFalse(out["paused"])
        self.assertEqual(self.keys, [])

    def test_handoff_sin_id_avisa(self):
        with self.estado(), mock.patch.object(control, "SYSTEM", "Windows"), \
                mock.patch.object(mando.MANDO, "direccion", lambda h: ""), \
                mock.patch.dict(patrocinios.PATROCINIOS.v, {}, clear=True):
            with self.assertRaises(control.ControlError):
                control.youtube("handoff")
        self.assertEqual(self.keys, [])  # no pausa si no puede dar el enlace
        with self.estado(), mock.patch.object(control, "SYSTEM", "Linux"):
            with self.assertRaises(control.ControlError):
                control.youtube("handoff")

    def test_revision_seek_con_tope_sin_duracion(self):
        with self.estado(len=0, real=False, pos=None), mock.patch.object(control, "SYSTEM", "Windows"), \
                mock.patch.object(mando.MANDO, "ir", lambda t, s: {"ok": True}):
            out = control.youtube("seek", {"to": 1e300})
        self.assertEqual(out["pos"], 86400.0)

    def test_revision_handoff_id_raro_no_pausa(self):
        with self.estado(), mock.patch.object(control, "SYSTEM", "Windows"), \
                mock.patch.object(mando.MANDO, "direccion", lambda h: ""), \
                mock.patch.dict(patrocinios.PATROCINIOS.v, {"hwnd": "77", "titulo": ROW["title"], "vid": "no<valido>"}, clear=True):
            with self.assertRaises(control.ControlError):
                control.youtube("handoff")
        self.assertEqual(self.keys, [])


class PatrociniosApagadoDeSerie(unittest.TestCase):
    """0.65: decisión del dueño, la casilla de patrocinios viene apagada; encendida se recuerda."""

    def test_apagado_de_serie_y_se_recuerda(self):
        import tempfile
        from pathlib import Path
        self.assertFalse(patrocinios.DEFAULT_ON)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "ajustes.json"
            p = patrocinios.Patrocinios(find=lambda: None, probe=lambda line: {}, file=f)
            self.assertFalse(p.on)
            self.assertFalse(p.status()["on"])
            p.set_on(True)
            self.assertTrue(patrocinios.Patrocinios(find=lambda: None, probe=lambda line: {}, file=f).on)
            p.set_on(False)
            self.assertFalse(patrocinios.Patrocinios(find=lambda: None, probe=lambda line: {}, file=f).on)

    def test_casilla_del_movil_sin_marcar_y_flags(self):
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<input id="yt-patrocinios" type="checkbox" />', html)
        src = (ROOT / "lazo.py").read_text(encoding="utf-8")
        self.assertIn("--con-patrocinios", src)
        self.assertIn("--sin-patrocinios", src)
        self.assertIn("LAZO_CON_PATROCINIOS", (ROOT / "patrocinios.py").read_text(encoding="utf-8"))


class Movil(unittest.TestCase):
    def test_barra_con_vista_previa(self):
        for id_ in ("yt-pos", "yt-pos-now", "yt-pos-len", "yt-pos-preview", "yt-movil", "yt-movil-link"):
            self.assertIn(f'id="{id_}"', HTML)
        self.assertIn("Ir a ${fmtTime(to)} de ${fmtTime(ytPos.len)}", JS)
        self.assertIn('action: "seek", to', JS)
        # mientras se arrastra, el sondeo no mueve la barra; solo salta al soltar
        self.assertIn("if (!data || ytPos.drag || Date.now() < ytPos.hold) return;", JS)
        self.assertIn('addEventListener("change", async (event) => {\n  const to = Number(event.target.value);', JS)

    def test_subtitulos_velocidad_y_volumen(self):
        self.assertIn('data-yt="subs_up"', HTML)
        self.assertIn('data-yt="subs_down"', HTML)
        self.assertIn('typeof data.rate === "number" && !ytSpeedDrag', JS)
        self.assertIn("`≈${level}`", JS)
        self.assertIn('classList.toggle("muted", data.muted)', JS)

    def test_seguir_en_el_movil_con_y_sin_app(self):
        self.assertIn('action: "handoff"', JS)
        self.assertIn('appBridge.abrirFuera(data.url, "com.brave.browser")', JS)
        self.assertIn('window.open("", "_blank")', JS)  # al tocar, para que no lo bloquee
        self.assertIn("hace falta la app nueva de LaZoo (App 2)", JS)
        i = JS.index('document.querySelector("#yt-movil").addEventListener')
        blk = JS[i:JS.index("mediaButtons(", i)]
        self.assertLess(blk.index("App 2"), blk.index('action: "handoff"'))  # APK vieja: no pausa el PC


class App2(unittest.TestCase):
    def test_abrir_fuera_solo_youtube_https(self):
        self.assertIn("public String abrirFuera(String url, String paquete)", JAVA)
        cuerpo = JAVA[JAVA.index("static boolean youtubeUrl"):][:500]
        self.assertIn('"https".equals(u.getScheme())', cuerpo)
        for host in ("www.youtube.com", "m.youtube.com", "youtu.be"):
            self.assertIn(f'"{host}"', cuerpo)
        self.assertIn("if (!youtubeUrl(url)) return \"\";", JAVA)
        self.assertIn('<package android:name="com.brave.browser" />', APK)

    def test_numero(self):
        self.assertIn('android:versionName="3"', APK)
        self.assertIn('android:versionCode="66"', APK)


class Version(unittest.TestCase):
    def test_065(self):
        self.assertEqual(lazo.VERSION, "0.70")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.70")
        self.assertIn('const PAGE_VERSION = "0.70"', JS)
        self.assertIn("<title>LaZoo 0.70</title>", HTML)
        self.assertIn('<p class="ver">0.70', MESA)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("# LaZoo 0.70", readme)
        self.assertIn("**Novedad 0.65:**", readme)
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("mando.py", agents)
        self.assertIn("test_v065.py", agents)


if __name__ == "__main__":
    unittest.main()
