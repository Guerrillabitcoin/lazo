"""Pruebas de la 0.78: YouTube se manda desde el móvil sin traer la ventana delante.

Elegir a qué YouTube van las órdenes (única > la que suena > la última activa/mandada >
la de antes), recordarla entre reinicios y mandar por controles multimedia / accesibilidad
antes de las teclas (que sí traen la ventana delante, solo como último recurso)."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import control
import mando
import medios

ROOT = Path(__file__).resolve().parent
A = {"id": "1", "title": "Gatos - YouTube - Google Chrome", "process": "chrome"}
B = {"id": "2", "title": "Perros - YouTube - Google Chrome", "process": "chrome"}
OTRA = {"id": "3", "title": "Documento - Word", "process": "winword"}


def ses(title, status="Paused", app="chrome.exe"):
    return {"app": app, "status": status, "title": title, "artist": "", "pos": 0, "len": 100, "rate": 1}


class Elegir(unittest.TestCase):
    def test_unica(self):
        row, why = control.elegir_youtube([OTRA, A], [], {"id": "", "title": ""})
        self.assertEqual((row["id"], why), ("1", "unica"))

    def test_la_que_suena_gana_a_la_recordada(self):
        row, why = control.elegir_youtube([A, B], [ses("Gatos"), ses("Perros", "Playing")], {"id": "1", "title": A["title"]})
        self.assertEqual((row["id"], why), ("2", "sonando"))

    def test_dos_sonando_la_recordada(self):
        row, why = control.elegir_youtube([A, B], [ses("Gatos", "Playing"), ses("Perros", "Playing")], {"id": "2", "title": ""})
        self.assertEqual((row["id"], why), ("2", "recordada"))

    def test_ninguna_suena_la_ultima_activa(self):
        row, why = control.elegir_youtube([A, B], [ses("Gatos"), ses("Perros")], {"id": "2", "title": "Otro - YouTube"})
        self.assertEqual((row["id"], why), ("2", "recordada"))
        row, why = control.elegir_youtube([A, B], [], {"id": "", "title": ""})
        self.assertEqual((row["id"], why), ("1", "primera"))
        row, why = control.elegir_youtube([A, dict(B, active=True)], [], {"id": "", "title": ""})
        self.assertEqual((row["id"], why), ("2", "activa"))

    def test_otro_navegador_o_spotify_no_cuentan(self):
        row, why = control.elegir_youtube([A, B], [ses("Perros", "Playing", app="Spotify.exe")], {})
        self.assertEqual(why, "primera")

    def test_youtube_music_fuera(self):
        self.assertEqual(control.elegir_youtube([{"id": "4", "title": "Canción - YouTube Music"}], [], {}), (None, ""))

    def test_pestana_de_fondo(self):
        # Chrome enseña otra pestaña delante: la sesión «Gatos» no es de ninguna ventana con YouTube.
        rows = [{"id": "5", "title": "Correo - Google Chrome", "process": "chrome"}]
        row, why = control.elegir_youtube(rows, [ses("Gatos", "Playing")], {})
        self.assertEqual(why, "fondo")
        self.assertTrue(row["fondo"])
        self.assertEqual(row["id"], "")
        self.assertIn("Gatos", row["title"])
        # Parada, solo si es el vídeo recordado.
        self.assertEqual(control.elegir_youtube(rows, [ses("Gatos")], {}), (None, ""))
        row, why = control.elegir_youtube(rows, [ses("Gatos")], {"id": "", "title": "Gatos - YouTube - Google Chrome"})
        self.assertEqual(why, "fondo")
        # pick_youtube (compatibilidad) nunca devuelve una pestaña sin ventana.
        self.assertIsNone(control.pick_youtube(rows))

    def test_seleccion_sin_foco_en_el_codigo(self):
        src = (ROOT / "control.py").read_text(encoding="utf-8")
        trozo = src[src.index("def _yt_tubes"):src.index("def remember_youtube")]
        self.assertNotIn("_focus", trozo)
        self.assertNotIn("_activate_window", trozo)


class Memoria(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = dict(control._YT_MEM), dict(control._YT_MEM_GUARDADA)
        control._YT_MEM.update(id="", title="", speed=None)
        control._YT_MEM_GUARDADA.update(cargada=False, id="", title="", disco=True)
        self.p = mock.patch.dict("os.environ", {"LAZO_DATOS": self.tmp.name})
        self.p.start()

    def tearDown(self):
        self.p.stop()
        control._YT_MEM.clear()
        control._YT_MEM.update(self.saved[0])
        control._YT_MEM_GUARDADA.update(self.saved[1])
        self.tmp.cleanup()

    def test_sobrevive_al_reinicio_y_respeta_otros_ajustes(self):
        f = Path(self.tmp.name) / "ajustes.json"
        f.write_text(json.dumps({"despierto": True}), encoding="utf-8")
        control.remember_youtube(B)
        data = json.loads(f.read_text(encoding="utf-8"))
        self.assertEqual(data["youtube_ultima"], {"id": "2", "title": B["title"]})
        self.assertTrue(data["despierto"])
        # «Reinicio»
        control._YT_MEM.update(id="", title="")
        control._YT_MEM_GUARDADA.update(cargada=False, id="", title="")
        control._yt_mem_load()
        self.assertEqual(control._YT_MEM["id"], "2")
        mtime = f.stat().st_mtime_ns
        control.remember_youtube(B)  # lo mismo: no reescribe
        self.assertEqual(f.stat().st_mtime_ns, mtime)

    def test_en_pruebas_no_toca_disco_por_defecto(self):
        control._YT_MEM_GUARDADA["disco"] = False
        control.remember_youtube(A)
        self.assertFalse((Path(self.tmp.name) / "ajustes.json").exists())

    def test_la_que_esta_delante_queda_recordada(self):
        rows = [A, dict(B, active=True)]
        with mock.patch.object(control, "SYSTEM", "Windows"), \
                mock.patch.object(control, "_windows_list", return_value=rows), \
                mock.patch.object(medios, "sesiones_ya", return_value=[]):
            row = control._find_youtube_unlocked()
        self.assertEqual(row["id"], "2")
        self.assertEqual(control._YT_MEM["id"], "2")
        # Luego otra ventana delante (no YouTube): se sigue mandando a la última activa.
        rows = [A, B, dict(OTRA, active=True)]
        with mock.patch.object(control, "SYSTEM", "Windows"), \
                mock.patch.object(control, "_windows_list", return_value=rows), \
                mock.patch.object(medios, "sesiones_ya", return_value=[]):
            row = control._find_youtube_unlocked()
        self.assertEqual((row["id"], row["motivo"]), ("2", "recordada"))


class FakeMando:
    def __init__(self, smtc=True, boton="Silenciar (m)", vol=None):
        self.calls = []
        self._smtc, self._boton, self._vol = smtc, boton, vol

    def available(self):
        return True

    def smtc(self, titulo, accion, segundos=0.0):
        self.calls.append(("smtc", accion, segundos))
        return self._smtc

    def boton(self, hwnd, atajo):
        self.calls.append(("boton", hwnd, atajo))
        return self._boton

    def volumen(self, hwnd, fresco=False):
        return {"level": 40, "muted": False}

    def volumen_sin_esperar(self, hwnd):
        return None

    def fijar_volumen(self, hwnd, nivel):
        self.calls.append(("fijavol", hwnd, nivel))
        return self._vol and {"level": nivel, "muted": False}


class SinFocoWindows(unittest.TestCase):
    def setUp(self):
        self.focus, self.keys = [], []
        self.row = dict(B)
        self.ps = [
            mock.patch.object(control, "SYSTEM", "Windows"),
            mock.patch.object(control, "_find_youtube_unlocked", lambda: dict(self.row)),
            mock.patch.object(control, "_focus_for_keys", lambda i: self.focus.append(i) or True),
            mock.patch.object(control, "_yt_keys", lambda k: self.keys.append(k)),
            mock.patch.object(control, "_chord", lambda k: self.keys.append(k)),
            mock.patch.object(control, "_yt_state", lambda r: {"playing": True, "pos": 30.0, "len": 100, "real": True}),
            mock.patch.object(control, "_skip_ad_now", lambda: False),
            mock.patch.object(control, "_win_is_fullscreen", lambda _i: None),
            mock.patch.object(control.time, "sleep", lambda _s: None),
        ]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in reversed(self.ps):
            p.stop()

    def use(self, fake):
        p = mock.patch.object(mando, "MANDO", fake)
        p.start()
        self.addCleanup(p.stop)
        return fake

    def test_play_next_saltos_por_multimedia(self):
        m = self.use(FakeMando())
        for act in ("play", "next", "back", "forward", "prev"):
            out = control.youtube(act)
            self.assertEqual(out["via"], "multimedia", act)
        self.assertEqual(self.focus, [])
        self.assertEqual(self.keys, [])
        self.assertIn(("smtc", "toggle", 0.0), m.calls)
        self.assertIn(("smtc", "rel", -10.0), m.calls)
        self.assertIn(("smtc", "pos", 0.0), m.calls)  # «Anterior» con más de 5 s: al inicio

    def test_si_multimedia_no_deja_boton_del_reproductor(self):
        m = self.use(FakeMando(smtc=False, boton="Siguiente (Mayús+N)"))
        out = control.youtube("next")
        self.assertEqual(out["via"], "accesibilidad")
        self.assertIn(("boton", "2", "(shift+n)"), m.calls)
        self.assertEqual(self.focus, [])

    def test_silencio_subtitulos_cine_por_boton(self):
        m = self.use(FakeMando())
        for act, atajo in (("mute", "(m)"), ("captions", "(c)"), ("theater", "(t)")):
            control.youtube(act)
            self.assertIn(("boton", "2", atajo), m.calls)
        self.assertEqual(self.focus, [])

    def test_volumen_por_deslizador(self):
        m = self.use(FakeMando(vol=True))
        out = control.youtube("volup")
        self.assertEqual((out["via"], out["level"]), ("volumen", 45))
        out = control._youtube_volume(70)
        self.assertEqual((out["via"], out["level"]), ("volumen", 70))
        self.assertIn(("fijavol", "2", 70), m.calls)
        self.assertEqual(self.focus, [])

    def test_ultimo_recurso_teclas_como_antes(self):
        self.use(FakeMando(smtc=False, boton="", vol=None))
        out = control.youtube("mute")
        self.assertEqual((out["via"], self.focus, self.keys[-1]), ("teclas", ["2"], ["m"]))

    def test_pestana_de_fondo_no_trae_nada(self):
        self.row = {"id": "", "title": "Gatos - YouTube", "fondo": True, "motivo": "fondo"}
        self.use(FakeMando(smtc=True, boton=""))
        out = control.youtube("play")
        self.assertEqual((out["via"], out["fondo"]), ("multimedia", True))
        with self.assertRaisesRegex(control.ControlError, "pestaña de fondo"):
            control.youtube("mute")
        with self.assertRaisesRegex(control.ControlError, "pestaña de fondo"):
            control._youtube_fullscreen()
        self.assertEqual(self.focus, [])

    def test_estado_de_pestana_de_fondo(self):
        self.row = {"id": "", "title": "Gatos - YouTube", "fondo": True, "motivo": "fondo"}
        m = self.use(FakeMando())
        out = control.youtube("status")
        self.assertTrue(out["fondo"])
        self.assertFalse(out["vol_real"])
        self.assertEqual(m.calls, [])


class Script(unittest.TestCase):
    def test_pulsar_solo_dentro_del_reproductor(self):
        ps = mando.ps_script()
        boton = ps[ps.index("function Boton"):ps.index("function FijaVol")]
        self.assertIn("InvokePattern", boton)
        self.assertIn("if (-not $p) { return '' }", boton)
        fija = ps[ps.index("function FijaVol"):ps.index("function Smtc")]
        self.assertIn("$condRepro", fija)
        for malo in ("SetForegroundWindow", "SetCursorPos", "SetFocus", "mouse_event", "SendInput"):
            self.assertNotIn(malo, ps)

    def test_ordenes_al_proceso(self):
        lines = []
        m = mando.Mando(probe=lambda line: lines.append(json.loads(line)) or {"ok": True, "aceptado": True, "boton": "Silenciar (m)"})
        with mock.patch.object(m, "available", return_value=True):
            self.assertTrue(m.smtc("Gatos - YouTube", "rel", -10))
            self.assertFalse(m.smtc("Gatos", "borrar"))
            self.assertEqual(m.boton("12", "(M)"), "Silenciar (m)")
            self.assertEqual(m.boton("no-num", "(m)"), "")
        self.assertEqual(lines[0], {"c": "smtc", "titulo": "Gatos - YouTube", "a": "rel", "s": -10.0})
        self.assertEqual(lines[1], {"c": "boton", "hwnd": "12", "atajo": "(m)"})
        self.assertEqual(len(lines), 2)


class SesionesYa(unittest.TestCase):
    def test_windows_no_espera(self):
        w = medios._Watch()
        started = []

        class T:
            def __init__(self, target, name, daemon):
                started.append(name)

            def start(self):
                pass

        with mock.patch.object(medios, "SYSTEM", "Windows"), mock.patch.object(medios, "WATCH", w), \
                mock.patch.object(medios.threading, "Thread", T):
            t0 = time.time()
            self.assertEqual(medios.sesiones_ya(), [])
            self.assertLess(time.time() - t0, 0.5)
        self.assertEqual(started, ["lazo-medios"])


class Version(unittest.TestCase):
    def test_version(self):
        import lazo

        self.assertEqual(lazo.VERSION, "0.78")
        self.assertIn("0.78", (ROOT / "static" / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
