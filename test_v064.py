"""LaZoo 0.64: saltar los patrocinios que van dentro del vídeo de YouTube (SponsorBlock).

    python3 test_v064.py

- Privacidad: a SponsorBlock solo sale el prefijo de 4 letras del SHA-256 del id, sin cookies
  ni nada personal; el PowerShell no sale a internet, no toca el ratón, el teclado ni el foco.
- Id del vídeo desde la barra del navegador (con o sin https, youtu.be, shorts…).
- Tramos: solo los del vídeo y de patrocinio; si la duración no cuadra (otra versión, o suena
  un anuncio) no se salta; los que se tocan se saltan de una vez.
- El vigilante (con un Windows de mentira): salta justo al empezar, una vez por vídeo, sin
  teclas ni foco; nunca dos saltos si Windows tarda en notarlo; teclas solo con YouTube ya
  delante y sin escribir en un campo; minirreproductor; Spotify no cuenta; sin red no pasa nada.
- Contador con el tiempo ahorrado, aparte de «¿Sigues ahí?» y anuncios; rutas, Panel y móvil.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

os.environ.setdefault("LAZO_DATOS", tempfile.mkdtemp())

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import lazo  # noqa: E402
import patrocinios as P  # noqa: E402
import sigues  # noqa: E402
from test_v062 import Base, Phone  # noqa: E402

JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
MESA = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
LAZO = (ROOT / "lazo.py").read_text(encoding="utf-8")

VID = "dQw4w9WgXcQ"
VID2 = "9bZkp7q19f0"
TITULO = "Vídeo de prueba"
VENTANA = f"(2) {TITULO} - YouTube - Google Chrome"

# Lo que contesta SponsorBlock a /api/skipSegments/<prefijo>: todos los vídeos con ese prefijo.
RESPUESTA = [
    {"videoID": "otroVideo00", "segments": [{"segment": [5, 50], "category": "sponsor", "actionType": "skip",
                                               "videoDuration": 600}]},
    {"videoID": VID, "segments": [
        {"segment": [30.0, 90.0], "category": "sponsor", "actionType": "skip", "UUID": "a", "videoDuration": 600},
        {"segment": [0.0, 12.0], "category": "intro", "actionType": "skip", "videoDuration": 600},
        {"segment": [200.0, 230.0], "category": "selfpromo", "actionType": "skip", "videoDuration": 600},
        {"segment": [300.0, 330.0], "category": "sponsor", "actionType": "mute", "videoDuration": 600},
        {"segment": [0.0, 600.0], "category": "sponsor", "actionType": "full", "videoDuration": 600},
        {"segment": [400.0, 400.5], "category": "sponsor", "actionType": "skip", "videoDuration": 600},
        {"segment": "roto", "category": "sponsor"},
        {"segment": [480.0, 510.0], "category": "sponsor", "actionType": "skip", "videoDuration": 600.4},
    ]},
]


class FakePS:
    """El PowerShell de mentira: un navegador con YouTube y un Windows que obedece al salto."""

    def __init__(self, **kw):
        self.url = kw.get("url", f"youtube.com/watch?v={VID}&t=3s")
        self.titulo = kw.get("titulo", TITULO)
        self.app = kw.get("app", "Chrome")
        self.pos = kw.get("pos", 0.0)
        self.len = kw.get("len", 600.0)
        self.estado = kw.get("estado", "Playing")
        self.saltar = kw.get("saltar", True)
        self.texto = kw.get("texto", False)
        self.acepta = kw.get("acepta", True)
        self.se_nota = kw.get("se_nota", True)
        self.otras: list[dict] = []
        self.ordenes: list[dict] = []

    def fila(self):
        return {"app": self.app, "titulo": self.titulo, "estado": self.estado, "pos": self.pos, "len": self.len,
                "vel": 1.0, "saltar": self.saltar}

    def __call__(self, line):
        cmd = json.loads(line)
        self.ordenes.append(cmd)
        if cmd["c"] == "mira":
            out = {"ok": True, "ms": 20, "sesiones": [self.fila()] + self.otras}
            if cmd.get("url"):
                out["url"] = self.url
            if cmd.get("foco"):
                out["texto"] = self.texto
            return out
        assert cmd["c"] == "salta", cmd
        r = {"ok": True, "ms": 300, "aceptado": False, "verificado": False, "fuera": False, "no_deja": False,
             "antes": self.pos}
        if self.estado != "Playing" or self.pos < cmd["desde"] - 0.6 or self.pos >= cmd["hasta"] - 1.5:
            r["fuera"] = True
        elif not self.saltar:
            r["no_deja"] = True
        else:
            r["aceptado"] = self.acepta
            if self.acepta and self.se_nota:
                self.pos = cmd["hasta"]
                r.update(verificado=True, pos=self.pos)
        return r

    def saltos(self):
        return [o for o in self.ordenes if o["c"] == "salta"]


class IdDelVideo(unittest.TestCase):
    def test_formas_de_la_barra(self):
        for url in [f"https://www.youtube.com/watch?v={VID}", f"youtube.com/watch?v={VID}&t=42s",
                    f"www.youtube.com/watch?app=desktop&v={VID}&list=PLx", f"m.youtube.com/watch?v={VID}",
                    f"https://youtu.be/{VID}?si=abc", f"youtube.com/shorts/{VID}", f"youtube.com/live/{VID}",
                    f"  https://www.youtube.com/watch/?v={VID}  "]:
            self.assertEqual(P.video_id(url), VID, url)

    def test_lo_que_no_es_un_video(self):
        for url in ["", "youtube.com", "https://www.youtube.com/", "youtube.com/results?search_query=x",
                    "youtube.com/watch?v=corto", f"https://evil.com/watch?v={VID}", f"notyoutube.com/watch?v={VID}",
                    f"youtube.com.evil.com/watch?v={VID}", VID, f"youtube.com/@canal/{VID}", "http://[::1"]:
            self.assertIsNone(P.video_id(url), url)


class Privacidad(unittest.TestCase):
    def test_solo_sale_el_prefijo(self):
        url = P.url_consulta(VID)
        self.assertEqual(P.prefijo(VID), "5f6b")  # sha256("dQw4w9WgXcQ")[:4]
        self.assertTrue(url.startswith("https://sponsor.ajay.app/api/skipSegments/5f6b?"))
        self.assertNotIn(VID, url)
        self.assertIn("category=sponsor", url)
        self.assertIn("actionType=skip", url)

    def test_consulta_sin_cookies_ni_nada_personal(self):
        vista = {}

        class Res:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, _n):
                return json.dumps(RESPUESTA).encode()

        def abrir(req, timeout):
            vista.update(url=req.full_url, headers=dict(req.header_items()), timeout=timeout)
            return Res()

        out = P.consultar(VID, abrir=abrir)
        self.assertNotIn(VID, vista["url"])
        self.assertEqual(vista["headers"].get("User-agent"), "LaZoo")
        self.assertNotIn("Cookie", vista["headers"])
        self.assertLessEqual(vista["timeout"], 10)
        self.assertEqual([(t["inicio"], t["fin"]) for t in out], [(30.0, 90.0), (480.0, 510.0)])

    def test_404_es_que_no_hay_tramos(self):
        def abrir(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

        self.assertEqual(P.consultar(VID, abrir=abrir), [])

    def test_red_caida_lanza(self):
        def abrir(req, timeout):
            raise urllib.error.URLError("sin red")

        with self.assertRaises(OSError):
            P.consultar(VID, abrir=abrir)

    def test_powershell_sin_internet_raton_teclas_ni_foco(self):
        ps = P.ps_script()
        for bueno in ("TryChangePlaybackPositionAsync", "IsPlaybackPositionEnabled", "ValuePattern",
                      "Chrome_RenderWidgetHostHWND", "$CT::Document", "$CT::TabItem", "LastUpdatedTime", "ConvertFrom-Json"):
            self.assertIn(bueno, ps)
        for malo in ("http", "WebRequest", "WebClient", "SetCursorPos", "SendKeys", "keybd_event", "mouse_event",
                     "SendInput", "SetForegroundWindow", "BringWindowToTop", "SetFocus", "InvokePattern", "ShowWindow"):
            self.assertNotIn(malo, ps)
        self.assertLess(len(P.encoded()), 30000)  # cabe en la línea de órdenes de Windows (32 767)


class Tramos(unittest.TestCase):
    def test_solo_los_del_video_y_de_patrocinio(self):
        out = P.tramos(RESPUESTA, VID)
        self.assertEqual([(t["inicio"], t["fin"], t["duracion"]) for t in out], [(30.0, 90.0, 600.0), (480.0, 510.0, 600.4)])
        self.assertEqual(P.tramos(RESPUESTA, VID2), [])

    def test_respuestas_raras(self):
        for data in (None, "x", {}, [None], [{"videoID": VID, "segments": "x"}], [{"videoID": VID}]):
            self.assertEqual(P.tramos(data, VID), [])

    def test_duracion_que_no_cuadra_no_se_salta(self):
        lista = P.tramos(RESPUESTA, VID)
        self.assertEqual(P.validos(lista, 600.8), [(30.0, 90.0), (480.0, 510.0)])
        self.assertEqual(P.validos(lista, 15.0), [])     # suena un anuncio de 15 s
        self.assertEqual(P.validos(lista, 640.0), [])    # otra versión del vídeo
        self.assertEqual(P.validos(lista, 0.0), [])      # sin duración no se sabe: no se salta
        sin = [{"inicio": 10.0, "fin": 20.0, "duracion": 0.0}]  # tramo antiguo sin duración
        self.assertEqual(P.validos(sin, 300.0), [(10.0, 20.0)])

    def test_unir_y_recortar(self):
        lista = [{"inicio": a, "fin": b, "duracion": 0.0} for a, b in [(50, 70), (10, 20), (20.5, 30), (15, 18), (295, 330), (299.8, 310)]]
        self.assertEqual(P.validos(lista, 300.0), [(10, 30), (50, 70), (295, 300.0)])


class Decidir(unittest.TestCase):
    T = [(30.0, 90.0), (480.0, 510.0)]

    def test_dentro_salta_al_final(self):
        d = P.decidir(self.T, 30.1, 600, True)
        self.assertEqual((d["accion"], d["desde"], d["hasta"]), ("saltar", 30.0, 90.0))
        self.assertEqual(P.decidir(self.T, 29.7, 600, True)["accion"], "saltar")  # 0,3 s antes vale

    def test_antes_espera_justo_hasta_el_inicio(self):
        d = P.decidir(self.T, 28.0, 600, True)
        self.assertEqual(d["accion"], "esperar")
        self.assertAlmostEqual(d["s"], 30.0 - P.ADELANTO - 28.0)
        self.assertAlmostEqual(P.decidir(self.T, 26.0, 600, True, velocidad=2.0)["s"], (30.0 - P.ADELANTO - 26.0) / 2)
        self.assertLessEqual(P.decidir(self.T, 100.0, 600, True)["s"], P.PASO)

    def test_pausado_hecho_o_casi_acabado_no(self):
        self.assertEqual(P.decidir(self.T, 40.0, 600, False)["accion"], "esperar")
        self.assertEqual(P.decidir(self.T, 40.0, 600, True, hechos={P.clave(30.0)})["accion"], "esperar")
        self.assertEqual(P.decidir(self.T, 88.5, 600, True)["accion"], "esperar")
        self.assertEqual(P.decidir([], 40.0, 600, True)["accion"], "esperar")

    def test_teclas_sin_pasarse(self):
        self.assertEqual(P.pasos(59.8), (5, 1))  # 55 s de 59,8
        self.assertEqual(P.pasos(95.0), (9, 0))
        self.assertEqual(P.pasos(4.0), (0, 0))
        self.assertEqual(P.pasos(5000.0)[0], 60)


class Vigilante(unittest.TestCase):
    def make(self, ps=None, fetch=None, active=False, ventana=VENTANA):
        self.tmp = tempfile.TemporaryDirectory()
        self.ps = ps or FakePS()
        self.row = {"id": "77", "title": ventana, "active": active}
        self.t = [1000.0]
        self.pedidos: list[str] = []
        self.teclas: list[tuple] = []

        def buscar(vid):
            self.pedidos.append(vid)
            return P.tramos(RESPUESTA, vid)

        def keys(hwnd, n10, n5):
            self.teclas.append((hwnd, n10, n5))
            return True

        return P.Patrocinios(find=lambda: dict(self.row) if self.row else None, probe=self.ps, file=Path(self.tmp.name) / "ajustes.json",
                             fetch=fetch or buscar, keys=keys, clock=lambda: self.t[0])

    def tearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def paso(self, p, segundos=1.0, pos=None):
        self.t[0] += segundos
        if pos is not None:
            self.ps.pos = pos
        return p.check_once()

    def test_salta_al_empezar_sin_teclas_ni_foco(self):
        p = self.make(ps=FakePS(pos=10.0))
        self.assertTrue(p.on)
        out = p.check_once()
        self.assertEqual(out["vid"], VID)
        self.assertEqual(self.ps.ordenes[0], {"c": "mira", "hwnd": "77", "url": True, "foco": False})
        self.assertLessEqual(p.interval(), P.PASO)
        self.assertEqual(p.n_video, 2)
        self.paso(p, pos=30.1)
        self.assertEqual(self.ps.ordenes[1]["url"], False)  # la dirección solo se lee al cambiar el título
        self.assertEqual([(s["desde"], s["hasta"], s["app"], s["titulo"]) for s in self.ps.saltos()], [(30.0, 90.0, "Chrome", TITULO)])
        self.assertEqual(self.ps.pos, 90.0)
        self.assertEqual((p.total, p.metodo, round(p.ahorrado, 1)), (1, "windows", 59.9))
        self.assertEqual(self.teclas, [])
        self.assertEqual(self.pedidos, [VID])  # una sola pregunta a SponsorBlock por vídeo

    def test_espera_exacta_hasta_el_inicio(self):
        p = self.make(ps=FakePS(pos=29.0))
        p.check_once()
        self.assertAlmostEqual(p.interval(), 30.0 - P.ADELANTO - 29.0)
        p = self.make(ps=FakePS(pos=28.0))  # más lejos: nunca más de PASO, para ver a tiempo otro vídeo
        p.check_once()
        self.assertEqual(p.interval(), P.PASO)

    def test_una_vez_por_video_y_al_volver_al_principio_otra(self):
        p = self.make(ps=FakePS(pos=30.2))
        p.check_once()
        self.paso(p, pos=40.0)  # vuelves atrás para verlo: se queda
        self.paso(p, pos=45.0)
        self.assertEqual(len(self.ps.saltos()), 1)
        self.paso(p, pos=1.0)   # al principio otra vez
        self.paso(p, pos=30.3)
        self.assertEqual(len(self.ps.saltos()), 2)
        self.assertEqual(p.total, 2)

    def test_otro_video(self):
        p = self.make(ps=FakePS(pos=30.2))
        p.check_once()
        self.row["title"] = "Otro vídeo - YouTube - Google Chrome"
        self.ps.url, self.ps.titulo, self.ps.pos = f"youtube.com/watch?v={VID2}", "Otro vídeo", 10.0
        self.paso(p)
        self.assertEqual(self.ps.ordenes[-1]["url"], True)
        self.assertEqual(self.pedidos, [VID, VID2])
        self.assertEqual(p.n_video, 0)  # VID2 no tiene tramos
        self.paso(p)
        self.assertEqual(self.pedidos, [VID, VID2])  # caché

    def test_pausado_no_salta(self):
        p = self.make(ps=FakePS(pos=40.0, estado="Paused"))
        p.check_once()
        self.assertEqual(self.ps.saltos(), [])

    def test_si_suena_un_anuncio_no_salta(self):
        p = self.make(ps=FakePS(pos=5.0, len=15.0))  # el anuncio de YouTube dura 15 s
        p.check_once()
        self.assertEqual((self.ps.saltos(), p.n_video), ([], 0))

    def test_minirreproductor(self):
        p = self.make(ps=FakePS(pos=10.0))
        p.check_once()
        self.row["title"] = "YouTube - Google Chrome"   # sigues por YouTube; el vídeo suena abajo
        self.ps.url = "youtube.com/"
        self.paso(p)
        self.paso(p, pos=30.2)
        self.assertEqual(len(self.ps.saltos()), 1)

    def test_sesion_que_no_es_este_youtube(self):
        p = self.make(ps=FakePS(pos=30.2, titulo="Canción de otra pestaña"))
        p.check_once()
        self.assertEqual((self.ps.saltos(), self.pedidos), ([], []))

    def test_spotify_con_el_mismo_titulo_no_cuenta(self):
        ps = FakePS(pos=5.0, estado="Paused")
        ps.otras = [{"app": "Spotify.exe", "titulo": TITULO, "estado": "Playing", "pos": 30.2, "len": 600.0, "vel": 1.0, "saltar": True}]
        p = self.make(ps=ps)
        p.check_once()
        self.assertEqual(ps.saltos(), [])

    def test_navegador_que_no_deja_con_youtube_detras_no_hace_nada(self):
        p = self.make(ps=FakePS(pos=30.2, saltar=False), active=False)
        p.check_once()
        self.paso(p, pos=31.2)
        self.assertEqual((self.ps.saltos(), self.teclas, p.total), ([], [], 0))
        self.assertIn("delante", p.status()["error"])

    def test_navegador_que_no_deja_con_youtube_delante_usa_sus_teclas(self):
        p = self.make(ps=FakePS(pos=30.2, saltar=False), active=True)
        p.check_once()
        self.assertEqual(self.ps.ordenes[0]["foco"], True)
        self.assertEqual(self.teclas, [("77", 5, 1)])  # 55 s de 59,8: nunca más allá del final
        self.paso(p, pos=85.4)
        self.paso(p, pos=86.4)
        self.assertEqual(self.teclas, [("77", 5, 1)])  # una sola vez
        self.assertEqual((p.total, p.metodo, round(p.ahorrado)), (1, "teclas", 55))

    def test_escribiendo_en_un_campo_no_pulsa_teclas(self):
        p = self.make(ps=FakePS(pos=30.2, saltar=False, texto=True), active=True)
        p.check_once()
        self.assertEqual(self.teclas, [])

    def test_windows_tarda_en_notarlo_nunca_dos_saltos(self):
        ps = FakePS(pos=30.2, acepta=True, se_nota=False)
        p = self.make(ps=ps, active=True)
        p.check_once()
        self.assertEqual(len(ps.saltos()), 1)
        self.assertEqual(p.total, 0)
        self.paso(p, 0.5, pos=30.7)  # aún no se ve el salto
        self.assertEqual((len(ps.saltos()), self.teclas), (1, []))
        self.paso(p, 0.5, pos=90.3)  # ya está
        self.assertEqual((p.total, p.metodo), (1, "windows"))
        for _ in range(4):
            self.paso(p, pos=ps.pos + 1)
        self.assertEqual((len(ps.saltos()), self.teclas, p.total), (1, [], 1))

    def test_sin_red_no_pasa_nada_y_reintenta(self):
        def falla(vid):
            self.pedidos.append(vid)
            raise urllib.error.URLError("sin red")

        p = self.make(ps=FakePS(pos=30.2), fetch=falla)
        p.check_once()
        self.paso(p)
        self.assertEqual((self.pedidos, p.consulta, self.ps.saltos()), ([VID], "sin red", []))
        self.paso(p, P.CACHE_ERROR + 1)
        self.assertEqual(self.pedidos, [VID, VID])

    def test_cuenta_y_guarda_aparte(self):
        p = self.make(ps=FakePS(pos=30.2))
        p.check_once()
        data = json.loads(p.file.read_text())
        self.assertEqual(data["patrocinios"], True)
        self.assertEqual(data["patrocinios_contador"]["total"], 1)
        self.assertAlmostEqual(data["patrocinios_contador"]["ahorrado"], 59.8)
        sigues.Sigues(find=lambda: None, probe=lambda h: {}, file=p.file).set_on(False)
        otra = P.Patrocinios(file=p.file)
        self.assertEqual((otra.total, round(otra.ahorrado, 1), otra.on), (1, 59.8, True))
        self.assertFalse(json.loads(p.file.read_text())["sigues"])
        st = p.status()
        self.assertEqual((st["ahorrado"], st["ahorrado_hoy"], st["video"], st["consulta"]), (60, 60, 2, "ok"))
        p.reset()
        self.assertEqual((p.total, p.ahorrado), (0, 0.0))

    def test_apagado_y_sin_youtube(self):
        p = self.make()
        p.set_on(False)
        self.assertEqual(p.check_once(), {"skip": "apagado"})
        self.assertEqual(p.interval(), P.SIN_YOUTUBE)
        p.set_on(True)
        self.row = None
        self.assertEqual(p.check_once(), {"skip": "sin youtube"})
        self.assertEqual(p.interval(), P.SIN_YOUTUBE)
        self.assertEqual(self.ps.ordenes, [])  # sin YouTube no se pregunta nada a PowerShell
        p.proc = mock.Mock()
        with mock.patch.object(p, "_close") as cerrar:
            self.paso(p, P.CERRAR + 1)
        cerrar.assert_called_once()

    def test_no_arranca_en_pruebas(self):
        self.assertFalse(P.watch())
        with mock.patch.dict(os.environ, {"LAZO_SIN_PATROCINIOS": "1"}), \
                mock.patch.dict(sys.modules, {"unittest": None, "pytest": None}), \
                mock.patch.object(P.PATROCINIOS, "disabled", False):
            del sys.modules["unittest"], sys.modules["pytest"]
            self.assertFalse(P.watch())
            self.assertTrue(P.PATROCINIOS.disabled)

    def test_teclas_de_verdad_solo_con_youtube_delante(self):
        import control

        with mock.patch.object(control, "SYSTEM", "Windows"), \
                mock.patch.object(control, "_is_foreground", return_value=False), \
                mock.patch.object(control, "_yt_keys") as keys:
            self.assertFalse(P._teclas("77", 3, 1))
        keys.assert_not_called()
        with mock.patch.object(control, "SYSTEM", "Windows"), \
                mock.patch.object(control, "_is_foreground", return_value=True), \
                mock.patch.object(control, "_focus_for_keys") as focus, \
                mock.patch.object(P.time, "sleep"), \
                mock.patch.object(control, "_yt_keys") as keys:
            self.assertTrue(P._teclas("77", 3, 1))
        focus.assert_not_called()
        self.assertEqual([c.args[0] for c in keys.call_args_list], [["l"], ["l"], ["l"], ["right"]])


class Rutas(Base):
    def setUp(self):
        super().setUp()
        self.antes = (P.PATROCINIOS.file, P.PATROCINIOS.on)
        P.PATROCINIOS.file = self.tmp / "ajustes-patrocinios.json"

    def tearDown(self):
        P.PATROCINIOS.file, P.PATROCINIOS.on = self.antes
        super().tearDown()

    def test_movil_lo_apaga_y_lo_enciende(self):
        phone = Phone(self.port)
        phone.pair_and_get_key()
        st, raw = phone.signed_post("/api/patrocinios", {"on": False})
        self.assertEqual(st, 200)
        self.assertFalse(phone.open(raw)["on"])
        st, raw = phone.signed_post("/api/patrocinios", {})
        self.assertFalse(phone.open(raw)["on"])
        P.PATROCINIOS.total = 3
        st, raw = phone.signed_post("/api/patrocinios", {"on": True, "reset": True})
        out = phone.open(raw)
        self.assertTrue(out["on"])
        self.assertEqual(out["total"], 3)  # poner a cero solo desde el propio PC

    def test_panel(self):
        info = lazo.connection_info()
        self.assertIn("patrocinios", info)
        self.assertEqual(set(info["patrocinios_info"]), {"total", "hoy", "sesion", "ultimo", "ahorrado", "ahorrado_hoy"})


class Interfaz(unittest.TestCase):
    def test_rutas_e_interfaz(self):
        self.assertIn('"/api/patrocinios"', LAZO)
        self.assertIn("patrocinios.watch()", LAZO)
        self.assertIn("--sin-patrocinios", LAZO)
        self.assertIn('id="yt-patrocinios"', HTML)
        self.assertIn("PREF_PUSH.push(syncPatrocinios)", JS)
        self.assertIn('id="patrocinios"', MESA)
        self.assertIn('id="patrocinios-cuenta"', MESA)
        self.assertIn('devCall("/api/patrocinios"', MESA)

    @unittest.skipUnless(shutil.which("node"), "sin node")
    def test_texto_del_panel(self):
        fns = MESA[MESA.index("function ahorradoTexto"):MESA.index("function siguesTexto")]
        code = fns + """
console.log(JSON.stringify([
  patrociniosTexto({total: 0}),
  patrociniosTexto({total: 3, hoy: 1, ahorrado: 245}),
  patrociniosTexto({total: 9, hoy: 2, ahorrado: 42}),
  patrociniosTexto({total: 90, hoy: 0, ahorrado: 3900}),
]));"""
        out = json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out, ["Patrocinios saltados: 0",
                               "Patrocinios saltados: 3 · hoy: 1 · ahorrado: 4 min",
                               "Patrocinios saltados: 9 · hoy: 2 · ahorrado: 42 s",
                               "Patrocinios saltados: 90 · hoy: 0 · ahorrado: 1 h 05 min"])


class ApkRetrocompatible(unittest.TestCase):
    """APK nueva con .exe viejo y al revés: la APK no habla con /api/* y la web nunca da por
    hecho que existe una función de LaZooApp."""

    def test_la_apk_no_llama_a_la_api_del_pc(self):
        for f in (ROOT / "android").rglob("*"):
            if f.suffix in (".java", ".html", ".js", ".xml") and "jsqr" not in f.name:
                self.assertNotIn("/api/", f.read_text(encoding="utf-8", errors="ignore"), f)

    def test_cada_funcion_de_la_apk_se_comprueba_antes(self):
        java = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "android" / "src").rglob("*.java"))
        import re

        metodos = set(re.findall(r"@JavascriptInterface\s+public \w+ (\w+)\(", java))
        self.assertTrue({"deviceId", "scan", "version"} <= metodos)
        web = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "static").glob("*.js"))
        for m in sorted(metodos):
            for llamada in re.finditer(r"\b(app|appBridge|LaZooApp)\.%s\(" % m, web):
                antes = web[max(0, llamada.start() - 300):llamada.start()]
                self.assertRegex(antes, r'typeof [\w.]*\.%s === "function"' % m, f"{m} sin comprobar")


class NumeroDeLaApp(unittest.TestCase):
    def test_app_n_y_codigo_63_mas_n(self):
        import re

        apk = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
        n = int(re.search(r'android:versionName="(\d+)"', apk).group(1))
        self.assertEqual(int(re.search(r'android:versionCode="(\d+)"', apk).group(1)), 63 + n)
        self.assertIn('"salida/LaZoo-App-$APP.apk"', (ROOT / "ci" / "construir.yml").read_text(encoding="utf-8"))
        self.assertIn('id="about-app"', HTML)
        self.assertIn('"App " + appNum', JS)

    def test_sobre_dice_cuando_sale_algo_a_internet(self):
        caja = HTML[HTML.index('id="about-internet"'):]
        caja = caja[:caja.index("</section>")]
        for texto in ("SponsorBlock", "IP", "youtube.com", "GitHub", "Saltar anuncios"):
            self.assertIn(texto, caja)
        self.assertIn("sponsor.ajay.app", HTML[HTML.index('id="yt-patrocinios"'):][:600])
        self.assertIn("SponsorBlock", MESA[MESA.index('id="patrocinios"'):][:200])


class Version(unittest.TestCase):
    """La versión actual la comprueba la prueba de la última versión (test_v065.py)."""

    def test_064_sigue_documentada(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("**Novedad 0.64:**", readme)
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("0.64", agents)
        self.assertIn("patrocinios.py", agents)


if __name__ == "__main__":
    unittest.main()
