"""LaZoo 0.66: Panel con «Configuración» e historial de anuncios y patrocinios saltados.

    python3 test_v066.py

- Los ajustes que iban sueltos en la barra superior del Panel están en la caja «Configuración»,
  con los mismos ids (el JS de siempre sigue valiendo).
- Historial: solo saltos verificados, la última arriba, máximo MAX, título limpio, id válido.
- Borrar la lista (entera o una) NO toca lo ahorrado desde siempre; ponerlo a cero es aparte.
- Anuncios: los segundos solo si Windows dio una duración que luego cambió (ya suena el vídeo).
- Patrocinios: el tramo m:ss → m:ss y los segundos del salto.
- Rutas solo del Panel de este PC; el móvil no las ve. Nada sale a internet.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("LAZO_DATOS", tempfile.mkdtemp())

ROOT = Path(__file__).resolve().parent

import anuncios  # noqa: E402
import historial  # noqa: E402
import lazo  # noqa: E402
import patrocinios  # noqa: E402

MESA = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "historial.json"
        self.t = [1_700_000_000.0]
        self.h = historial.Historial(file=self.file, clock=lambda: self.t[0])

    def tearDown(self):
        self.tmp.cleanup()


class Titulo(unittest.TestCase):
    def test_limpio(self):
        self.assertEqual(historial.titulo_limpio("(3) Receta de lentejas - YouTube - Brave"), "Receta de lentejas")
        self.assertEqual(historial.titulo_limpio("Lentejas — YouTube"), "Lentejas")
        self.assertEqual(historial.titulo_limpio("Un vídeo - con guion"), "Un vídeo - con guion")
        self.assertEqual(len(historial.titulo_limpio("x" * 500)), 160)


class Entradas(Base):
    def test_apuntar_y_guardar(self):
        self.h.apuntar("patrocinio", titulo="Lentejas - YouTube - Brave", video="dQw4w9WgXcQ",
                       desde=61.24, hasta=95.0, seg=33.76, metodo="windows")
        self.t[0] += 60
        self.h.apuntar("anuncio", titulo="Lentejas - YouTube")
        st = self.h.status()
        self.assertEqual([e["tipo"] for e in st["entradas"]], ["anuncio", "patrocinio"])  # la última arriba
        p = st["entradas"][1]
        self.assertEqual((p["titulo"], p["video"], p["desde"], p["hasta"], p["seg"]), ("Lentejas", "dQw4w9WgXcQ", 61.2, 95.0, 33.8))
        self.assertIsNone(st["entradas"][0]["seg"])
        self.assertEqual(st["acumulado"]["patrocinio"], {"n": 1, "seg": 33.8, "con_tiempo": 1})
        self.assertEqual(st["acumulado"]["anuncio"], {"n": 1, "seg": 0.0, "con_tiempo": 0})
        otro = historial.Historial(file=self.file)  # se recuerda tras reiniciar
        self.assertEqual(otro.status()["entradas"], st["entradas"])
        self.assertEqual(otro.status()["acumulado"], st["acumulado"])

    def test_id_raro_no_se_guarda_y_tipo_valido(self):
        self.h.apuntar("patrocinio", video="<script>", seg=1)
        self.assertEqual(self.h.status()["entradas"][0]["video"], "")
        with self.assertRaises(ValueError):
            self.h.apuntar("spam")

    def test_maximo(self):
        for i in range(historial.MAX + 15):
            self.h.apuntar("anuncio", titulo=f"v{i}")
        st = self.h.status()
        self.assertEqual(len(st["entradas"]), historial.MAX)
        self.assertEqual(st["entradas"][0]["titulo"], f"v{historial.MAX + 14}")
        self.assertEqual(st["acumulado"]["anuncio"]["n"], historial.MAX + 15)  # el acumulado no se recorta
        self.assertEqual(len({e["id"] for e in st["entradas"]}), historial.MAX)

    def test_archivo_roto_empieza_de_cero(self):
        self.file.write_text("{roto", encoding="utf-8")
        h = historial.Historial(file=self.file)
        self.assertEqual(h.status()["entradas"], [])


class Borrar(Base):
    def test_borrar_no_toca_lo_ahorrado(self):
        a = self.h.apuntar("patrocinio", seg=40)
        self.h.apuntar("patrocinio", seg=20)
        self.h.borrar(a)
        st = self.h.status()
        self.assertEqual(len(st["entradas"]), 1)
        self.h.borrar()
        st = self.h.status()
        self.assertEqual(st["entradas"], [])
        self.assertEqual(st["acumulado"]["patrocinio"], {"n": 2, "seg": 60.0, "con_tiempo": 2})
        self.assertTrue(st["desde"])
        self.h.borrar_acumulado()
        self.assertEqual(self.h.status()["acumulado"]["patrocinio"], {"n": 0, "seg": 0.0, "con_tiempo": 0})
        with self.assertRaises(ValueError):
            self.h.borrar("x")

    def test_completar_una_sola_vez(self):
        i = self.h.apuntar("anuncio")
        self.assertTrue(self.h.completar(i, 22.04))
        self.assertFalse(self.h.completar(i, 22))
        self.assertEqual(self.h.status()["acumulado"]["anuncio"], {"n": 1, "seg": 22.0, "con_tiempo": 1})
        self.h.borrar()
        self.assertFalse(self.h.completar(i, 5))  # ya no está: no suma


class Anuncio(Base):
    def test_estimar(self):
        est = historial.estimar_anuncio
        self.assertEqual(est({"len": 30, "pos": 6}, {"len": 640}), 24.0)
        self.assertIsNone(est({"len": 640, "pos": 6}, {"len": 640}))   # misma duración: era el vídeo
        self.assertIsNone(est({"len": 900, "pos": 6}, {"len": 640}))   # demasiado largo para un anuncio
        self.assertIsNone(est({"len": 30, "pos": 40}, {"len": 640}))
        self.assertIsNone(est({}, {"len": 640}))
        self.assertIsNone(est({"len": 30, "pos": 6}, {}))

    def test_anuncio_saltado_completa_despues(self):
        fotos = iter([{"len": 30, "pos": 5}, {"len": 600, "pos": 0}])
        timers = []

        class T:
            def __init__(self, s, fn):
                self.s, self.fn, self.daemon = s, fn, False
                timers.append(self)

            def start(self):
                pass

        i = historial.anuncio_saltado(self.h, row={"title": "Lentejas - YouTube"}, foto=lambda _t: next(fotos), timer=T)
        self.assertIsNone(self.h.status()["entradas"][0]["seg"])
        self.assertEqual(timers[0].s, historial.ESPERA_ANUNCIO)
        timers[0].fn()
        e = self.h.status()["entradas"][0]
        self.assertEqual((e["id"], e["seg"], e["titulo"]), (i, 25.0, "Lentejas"))

    def test_sin_windows_no_inventa(self):
        historial.anuncio_saltado(self.h, row=None, foto=lambda _t: {}, timer=mock.Mock())
        e = self.h.status()["entradas"][0]
        self.assertEqual((e["tipo"], e["seg"]), ("anuncio", None))

    def test_contar_del_vigilante_apunta(self):
        llamadas = []
        a = anuncios.Anuncios(find=lambda: "1", probe=lambda _h: {"pulsado": True, "verificado": True},
                              file=Path(self.tmp.name) / "ajustes.json")
        a.on = True
        with mock.patch.object(historial, "anuncio_saltado", lambda: llamadas.append(1)):
            a.check_once()
            a.probe = lambda _h: {"pulsado": True, "verificado": False}
            a.check_once()  # sin verificar: no cuenta ni se apunta
        self.assertEqual(llamadas, [1])
        self.assertEqual(a.total, 1)

    def test_el_historial_nunca_rompe_el_salto(self):
        a = anuncios.Anuncios(find=lambda: "1", probe=lambda _h: {"pulsado": True, "verificado": True},
                              file=Path(self.tmp.name) / "ajustes.json")
        a.on = True
        with mock.patch.object(historial, "anuncio_saltado", side_effect=RuntimeError("x")):
            a.check_once()
        self.assertEqual(a.total, 1)


class Patrocinio(Base):
    def test_hecho_apunta_el_tramo(self):
        p = patrocinios.Patrocinios(file=Path(self.tmp.name) / "ajustes.json")
        p.v = {"titulo": "Lentejas - YouTube - Brave", "vid": "dQw4w9WgXcQ", "tramo": {"k1": (61.0, 95.0)}}
        with mock.patch.object(historial, "HISTORIAL", self.h):
            p._hecho("k1", 34.0, "windows")
        e = self.h.status()["entradas"][0]
        self.assertEqual((e["tipo"], e["titulo"], e["video"], e["desde"], e["hasta"], e["seg"], e["metodo"]),
                         ("patrocinio", "Lentejas", "dQw4w9WgXcQ", 61.0, 95.0, 34.0, "windows"))
        self.assertEqual(p.total, 1)

    def test_saltar_guarda_el_tramo(self):
        src = (ROOT / "patrocinios.py").read_text(encoding="utf-8")
        self.assertIn('self.v.setdefault("tramo", {})[k] = (pos, d["hasta"])', src)


class Rutas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.h = historial.Historial(file=Path(self.tmp.name) / "h.json")
        self.patch = mock.patch.object(historial, "HISTORIAL", self.h)
        self.patch.start()
        self.h.apuntar("patrocinio", titulo="A", seg=10)
        self.h.apuntar("anuncio", titulo="B")
        self.server = lazo.LazoServer(("127.0.0.1", 0), lazo.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.patch.stop()
        self.tmp.cleanup()

    def req(self, method, path, body=None, local=True):
        from test_v054 import _req

        headers = {"Content-Type": "application/json"}
        if local:
            headers["X-Lazo-Local"] = "1"
        data = json.dumps(body).encode() if body is not None else b""
        st, raw = _req(self.port, method, path, data, headers)
        return st, json.loads(raw or b"{}")

    def test_leer_y_borrar_desde_el_panel(self):
        st, data = self.req("GET", "/api/historial")
        self.assertEqual(st, 200)
        self.assertEqual([e["titulo"] for e in data["entradas"]], ["B", "A"])
        st, data = self.req("POST", "/api/historial/borrar", {"id": data["entradas"][0]["id"]})
        self.assertEqual((st, [e["titulo"] for e in data["entradas"]]), (200, ["A"]))
        st, data = self.req("POST", "/api/historial/borrar", {})
        self.assertEqual(st, 400)  # sin id ni all: no borra nada
        self.assertEqual(len(self.h.status()["entradas"]), 1)
        st, data = self.req("POST", "/api/historial/borrar", {"all": True})
        self.assertEqual((st, data["entradas"], data["acumulado"]["patrocinio"]["seg"]), (200, [], 10.0))
        st, data = self.req("POST", "/api/historial/borrar", {"acumulado": True})
        self.assertEqual((st, data["acumulado"]["patrocinio"]["n"]), (200, 0))

    def test_el_movil_no_lo_ve(self):
        st, _ = self.req("POST", "/api/historial/borrar", {"all": True}, local=False)
        self.assertIn(st, (401, 403))
        self.assertEqual(len(self.h.status()["entradas"]), 2)


class Panel(unittest.TestCase):
    def test_configuracion_con_los_ajustes_de_arriba(self):
        cab = MESA[MESA.index('<header id="status"'):MESA.index("</header>")]
        cfg = MESA[MESA.index('<section id="config"'):]
        cfg = cfg[:cfg.index("</section>")]
        for id_ in ("recordar", "sigues", "sigues-cuenta", "sigues-cero", "anuncios", "anuncios-cuenta",
                    "patrocinios", "patrocinios-cuenta", "despierto"):
            self.assertNotIn(f'id="{id_}"', cab)
            self.assertIn(f'id="{id_}"', cfg)
            self.assertEqual(MESA.count(f'id="{id_}"'), 1)
        self.assertIn("<h2>Configuración</h2>", cfg)

    def test_historial(self):
        for id_ in ("historial", "hist-total", "hist-lista", "hist-borrar", "hist-cero", "hist-vacio"):
            self.assertIn(f'id="{id_}"', MESA)
        self.assertIn('fetch("/api/historial")', MESA)
        self.assertIn("{ all: true }", MESA)
        self.assertIn("{ acumulado: true }", MESA)
        self.assertIn("Lo ahorrado desde siempre se queda", MESA)
        js = MESA[MESA.index("function histFila"):MESA.index("function histPinta")]
        self.assertNotIn("innerHTML", js)  # el título del vídeo nunca como HTML
        self.assertIn('want === "configuracion"', MESA)

    def test_sin_internet(self):
        src = (ROOT / "historial.py").read_text(encoding="utf-8")
        for prohibido in ("urllib", "urlopen", "socket", "http.client"):
            self.assertNotIn(prohibido, src)


class Version(unittest.TestCase):
    def test_066(self):
        self.assertEqual(lazo.VERSION, "0.74")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.74")
        self.assertIn('<p class="ver">0.74', MESA)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("# LaZoo 0.74", readme)
        self.assertIn("**Novedad 0.66:**", readme)
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("historial.py", agents)
        self.assertIn("test_v066.py", agents)
        apk = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:versionName="3"', apk)  # la APK no cambia


if __name__ == "__main__":
    unittest.main()
