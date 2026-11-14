"""LaZoo 0.73: SponsorBlock salta más que «sponsor» (lo pidió el dueño): autobombo / promo del
canal, recordatorios de suscribirse y like… cada uno con su casilla.

    python3 test_v073.py

- Categorías: sponsor, selfpromo, interaction (de serie) e intro, outro, preview, filler,
  music_offtopic (opcionales). poi_highlight nunca; actionType «full» no se salta: solo se avisa.
- Privacidad: la consulta sigue llevando solo el prefijo de 4 del sha256 y siempre pide todas las
  categorías (no dice cuáles saltas). Sin ratón, sin teclas, sin traer ventanas delante.
- Ajuste guardado y migración: sin elegir nunca (≤0.72) = las tres de serie.
- El aviso, el historial y el contador dicen qué categoría se saltó.
- Rutas (Panel y móvil), interfaz en español, APK sin cambios (App 3), versión 0.73.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from contextlib import redirect_stdout
from pathlib import Path

os.environ.setdefault("LAZO_DATOS", tempfile.mkdtemp())

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import historial  # noqa: E402
import lazo  # noqa: E402
import patrocinios as P  # noqa: E402
import pcapc  # noqa: E402
from test_v062 import Base, Phone, _req  # noqa: E402
from test_v064 import TITULO, VENTANA, VID, FakePS  # noqa: E402

JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
MESA = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
LOCAL = {"Content-Type": "application/json", "X-Lazo-Local": "1"}

ETIQUETAS = {
    "sponsor": "Patrocinios",
    "selfpromo": "Autobombo / promo del canal",
    "interaction": "Recordatorios de suscribirse y like",
    "intro": "Intros",
    "outro": "Outros / créditos",
    "preview": "Avances / resúmenes",
    "filler": "Relleno / desvíos",
    "music_offtopic": "Partes sin música en vídeos musicales",
}


def seg(a, b, cat, accion="skip", dur=600):
    return {"segment": [a, b], "category": cat, "actionType": accion, "videoDuration": dur}


RESPUESTA = [{"videoID": VID, "segments": [
    seg(0.0, 12.0, "intro"),
    seg(30.0, 90.0, "sponsor"),
    seg(89.5, 100.0, "selfpromo"),          # pegado al patrocinio: un solo salto con las dos
    seg(150.0, 150.0, "poi_highlight", "poi"),
    seg(160.0, 200.0, "poi_highlight"),     # aunque viniera como «skip»: nunca
    seg(250.0, 262.0, "interaction"),
    seg(300.0, 340.0, "filler"),
    seg(400.0, 420.0, "music_offtopic"),
    seg(560.0, 600.0, "outro"),
    seg(0.0, 0.0, "sponsor", "full"),
]}]


class Categorias(unittest.TestCase):
    def test_las_ocho_y_las_de_serie(self):
        self.assertEqual(P.CATEGORIAS, tuple(ETIQUETAS))
        self.assertEqual(P.NOMBRES, ETIQUETAS)
        self.assertEqual(P.DEFECTO, ("sponsor", "selfpromo", "interaction"))
        self.assertNotIn("poi_highlight", P.CATEGORIAS)
        self.assertNotIn("chapter", P.CATEGORIAS)

    def test_limpiar(self):
        self.assertEqual(P.limpiar_categorias(["interaction", "sponsor"]), ["sponsor", "interaction"])
        self.assertEqual(P.limpiar_categorias({"intro": True, "sponsor": False, "outro": 1}), ["intro"])
        for malo in (["poi_highlight"], ["<script>"], "sponsor", None, 3, ["sponsor"] * 30):
            with self.assertRaises(ValueError):
                P.limpiar_categorias(malo)


class Privacidad(unittest.TestCase):
    def test_solo_prefijo_y_todas_las_categorias(self):
        url = P.url_consulta(VID)
        self.assertTrue(url.startswith(f"https://sponsor.ajay.app/api/skipSegments/{P.prefijo(VID)}?"))
        self.assertEqual(len(P.prefijo(VID)), 4)
        self.assertNotIn(VID, url)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        for c in P.CATEGORIAS:
            self.assertIn(c, q["category"])
        self.assertNotIn("poi_highlight", q["category"])
        self.assertEqual(set(q["actionType"]), {"skip", "full"})
        self.assertEqual(set(q), {"category", "actionType"})  # nada más: ni id, ni elegidas

    def test_la_consulta_no_cambia_con_lo_elegido(self):
        p = P.Patrocinios(file=Path(tempfile.mkdtemp()) / "a.json")
        antes = P.url_consulta(VID)
        p.set_categorias(["intro"])
        self.assertEqual(P.url_consulta(VID), antes)

    def test_sin_raton_teclas_ni_foco(self):
        ps = P.ps_script()
        for malo in ("SetCursorPos", "SendKeys", "mouse_event", "SendInput", "SetForegroundWindow", "BringWindowToTop"):
            self.assertNotIn(malo, ps)


class Tramos(unittest.TestCase):
    def test_con_categoria_sin_poi_y_entero_aparte(self):
        out = P.tramos(RESPUESTA, VID)
        cats = [t["categoria"] for t in out if not t.get("entero")]
        self.assertEqual(cats, ["intro", "sponsor", "selfpromo", "interaction", "filler", "music_offtopic", "outro"])
        self.assertNotIn("poi_highlight", [t["categoria"] for t in out])
        self.assertEqual(P.entero(out), "patrocinado")
        self.assertEqual(P.entero([t for t in out if not t.get("entero")]), "")
        auto = P.tramos([{"videoID": VID, "segments": [seg(0, 0, "selfpromo", "full")]}], VID)
        self.assertEqual(P.entero(auto), "autopromoción del canal")

    def test_solo_las_elegidas_y_unidas_con_sus_categorias(self):
        out = P.tramos(RESPUESTA, VID)
        self.assertEqual(P.validos(out, 600.0, categorias=P.DEFECTO, con_categoria=True),
                         [(30.0, 100.0, ("sponsor", "selfpromo")), (250.0, 262.0, ("interaction",))])
        self.assertEqual(P.validos(out, 600.0, categorias=["outro", "intro"]), [(0.0, 12.0), (560.0, 600.0)])
        self.assertEqual(P.validos(out, 600.0, categorias=[]), [])
        self.assertEqual(P.validos(out, 600.0), [(30.0, 90.0)])  # sin decir nada: como hasta la 0.72
        # el «full» nunca entra, ni con todas
        todas = P.validos(out, 600.0, categorias=P.CATEGORIAS, con_categoria=True)
        self.assertNotIn((0.0, 0.0), [(a, b) for a, b, _ in todas])
        self.assertFalse(any(a == 0.0 and b == 600.0 for a, b, _ in todas))

    def test_decidir_dice_la_categoria(self):
        lista = P.validos(P.tramos(RESPUESTA, VID), 600.0, categorias=P.DEFECTO, con_categoria=True)
        d = P.decidir(lista, 250.2, 600, True)
        self.assertEqual((d["accion"], d["categorias"]), ("saltar", ["interaction"]))
        self.assertNotIn("categorias", P.decidir([(30.0, 90.0)], 30.2, 600, True))
        self.assertEqual(P.nombre_de(["sponsor", "selfpromo"]), "Patrocinios + Autobombo / promo del canal")
        self.assertEqual(P.nombre_de([]), "Patrocinios")


class Ajuste(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.file = Path(self.dir.name) / "ajustes.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_migracion_quien_lo_tenia_encendido(self):
        self.file.write_text(json.dumps({"patrocinios": True, "sigues": False,
                                         "patrocinios_contador": {"total": 4, "ahorrado": 120}}))
        p = P.Patrocinios(file=self.file)
        self.assertTrue(p.on)
        self.assertEqual(p.categorias, ["sponsor", "selfpromo", "interaction"])
        self.assertEqual((p.total, p.ahorrado), (4, 120.0))

    def test_de_serie_apagado_y_tres_categorias(self):
        p = P.Patrocinios(file=self.file)
        self.assertFalse(p.on)  # el interruptor general sigue como en 0.65
        self.assertEqual(p.status()["categorias"], list(P.DEFECTO))
        self.assertEqual([c["id"] for c in p.status()["todas"]], list(P.CATEGORIAS))

    def test_se_respeta_lo_guardado(self):
        p = P.Patrocinios(file=self.file)
        p.set_categorias({"selfpromo": False, "intro": True})  # solo cambian las que vienen
        self.assertEqual(p.categorias, ["sponsor", "interaction", "intro"])
        data = json.loads(self.file.read_text())
        self.assertEqual(data["patrocinios_categorias"], ["sponsor", "interaction", "intro"])
        self.assertEqual(P.Patrocinios(file=self.file).categorias, ["sponsor", "interaction", "intro"])
        p.set_categorias([])
        self.assertEqual(P.Patrocinios(file=self.file).categorias, [])  # ninguna también se respeta
        p.set_on(False)  # otro guardado no la pisa
        self.assertEqual(json.loads(self.file.read_text())["patrocinios_categorias"], [])

    def test_archivo_raro(self):
        self.file.write_text(json.dumps({"patrocinios_categorias": ["nada"]}))
        self.assertEqual(P.Patrocinios(file=self.file).categorias, list(P.DEFECTO))
        self.file.write_text("{roto")
        self.assertEqual(P.Patrocinios(file=self.file).categorias, list(P.DEFECTO))


class Vigilante(unittest.TestCase):
    def make(self, pos):
        self.tmp = tempfile.TemporaryDirectory()
        self.ps = FakePS(pos=pos)
        self.t = [1000.0]
        self.teclas = []
        self.row = {"id": "77", "title": VENTANA, "active": False}
        p = P.Patrocinios(find=lambda: dict(self.row), probe=self.ps, file=Path(self.tmp.name) / "ajustes.json",
                          fetch=lambda vid: P.tramos(RESPUESTA, vid), keys=lambda *a: self.teclas.append(a) or True,
                          clock=lambda: self.t[0])
        p.on = True
        self.hist = historial.Historial(file=Path(self.tmp.name) / "historial.json")
        self.antes = historial.HISTORIAL
        historial.HISTORIAL = self.hist
        return p

    def tearDown(self):
        historial.HISTORIAL = self.antes
        self.tmp.cleanup()

    def test_salta_autobombo_y_lo_dice(self):
        p = self.make(250.1)
        out = io.StringIO()
        with redirect_stdout(out):
            p.check_once()
        self.assertEqual([(s["desde"], s["hasta"]) for s in self.ps.saltos()], [(250.0, 262.0)])
        self.assertIn("Recordatorios de suscribirse y like saltado sin tocar el ratón", out.getvalue())
        st = p.status()
        self.assertEqual(st["por_categoria"], {"interaction": 1})
        self.assertEqual(st["ultimo_salto"]["nombre"], "Recordatorios de suscribirse y like")
        self.assertEqual(st["entero"], "patrocinado")  # aviso del «full», sin saltar nada por él
        e = self.hist.status()["entradas"][0]
        self.assertEqual((e["tipo"], e["cat"]), ("patrocinio", "interaction"))
        self.assertEqual(self.teclas, [])
        self.assertEqual(json.loads(p.file.read_text())["patrocinios_contador"]["por_categoria"], {"interaction": 1})

    def test_patrocinio_y_promo_juntos(self):
        p = self.make(30.1)
        with redirect_stdout(io.StringIO()):
            p.check_once()
        self.assertEqual([(s["desde"], s["hasta"]) for s in self.ps.saltos()], [(30.0, 100.0)])
        self.assertEqual(p.status()["por_categoria"], {"sponsor": 1, "selfpromo": 1})
        self.assertEqual(p.status()["ultimo_salto"]["nombre"], "Patrocinios + Autobombo / promo del canal")

    def test_lo_no_elegido_no_se_salta(self):
        for pos in (5.0, 310.0, 405.0, 570.0, 160.5):  # intro, relleno, sin música, outro, poi
            p = self.make(pos)
            with redirect_stdout(io.StringIO()):
                p.check_once()
            self.assertEqual(self.ps.saltos(), [], pos)
            self.tearDown()

    def test_opcional_al_encenderla(self):
        p = self.make(300.2)
        p.set_categorias({"filler": True})
        with redirect_stdout(io.StringIO()):
            p.check_once()
        self.assertEqual([(s["desde"], s["hasta"]) for s in self.ps.saltos()], [(300.0, 340.0)])
        self.assertEqual(self.hist.status()["entradas"][0]["cat"], "filler")
        p.reset()
        self.assertEqual(p.status()["por_categoria"], {})

    def test_historial_sin_categoria_rara(self):
        self.make(0.0)
        i = historial.patrocinio_saltado(TITULO, VID, 1.0, 2.0, 1.0, "windows", categoria="<b>")
        e = next(x for x in self.hist.status()["entradas"] if x["id"] == i)
        self.assertNotIn("cat", e)


class Rutas(Base):
    def setUp(self):
        super().setUp()
        self.antes = (P.PATROCINIOS.file, P.PATROCINIOS.on, P.PATROCINIOS.categorias)
        P.PATROCINIOS.file = self.tmp / "ajustes-patrocinios.json"
        P.PATROCINIOS.categorias = list(P.DEFECTO)

    def tearDown(self):
        P.PATROCINIOS.file, P.PATROCINIOS.on, P.PATROCINIOS.categorias = self.antes
        super().tearDown()

    def test_movil_elige(self):
        phone = Phone(self.port)
        phone.pair_and_get_key()
        st, raw = phone.signed_post("/api/patrocinios", {"categorias": {"intro": True, "interaction": False}})
        self.assertEqual(st, 200)
        out = phone.open(raw)
        self.assertEqual(out["categorias"], ["sponsor", "selfpromo", "intro"])
        st, _raw = phone.signed_post("/api/patrocinios", {"categorias": ["poi_highlight"]})
        self.assertEqual(st, 400)
        self.assertEqual(P.PATROCINIOS.categorias, ["sponsor", "selfpromo", "intro"])

    def test_panel_elige_y_sin_permiso_no(self):
        lazo.Handler._loopback = lambda self: True  # el Panel, desde este PC (Base lo repone)
        body = json.dumps({"categorias": ["sponsor"]}).encode()
        st, raw = _req(self.port, "POST", "/api/patrocinios", body, LOCAL)
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(raw)["categorias"], ["sponsor"])
        st, _ = _req(self.port, "POST", "/api/patrocinios", json.dumps({"categorias": []}).encode(),
                     {"Content-Type": "application/json"})
        self.assertIn(st, (401, 403))
        self.assertEqual(P.PATROCINIOS.categorias, ["sponsor"])
        info = lazo.connection_info()["patrocinios_info"]
        self.assertEqual(info["categorias"], ["sponsor"])
        self.assertIn("todas", info)


class Interfaz(unittest.TestCase):
    def test_panel(self):
        bloque = MESA[MESA.index('id="patrocinios-cats"'):]
        bloque = bloque[:bloque.index("</div>")]
        for c, nombre in ETIQUETAS.items():
            self.assertIn(f'data-cat="{c}"', bloque)
            self.assertIn(nombre, bloque)
        for c in P.DEFECTO:
            self.assertIn(f'<input type="checkbox" data-cat="{c}" checked />', bloque)
        self.assertIn('devCall("/api/patrocinios", { categorias:', MESA)
        self.assertIn('id="patrocinios-ultimo"', MESA)
        self.assertIn("Autobombo", MESA[MESA.index("const CAT_CORTO"):][:300])

    def test_movil(self):
        i = HTML.index('id="yt-patrocinios"')
        bloque = HTML[i:HTML.index("</details>", i)]
        self.assertIn("Qué saltar", bloque)
        for c, nombre in ETIQUETAS.items():
            self.assertIn(f'data-cat="{c}"', bloque)
            self.assertIn(nombre, bloque)
        self.assertIn('api("/api/patrocinios", { categorias:', JS)
        self.assertIn("pide siempre todas las categorías", HTML)
        self.assertNotIn("(activado de serie)", HTML)

    @unittest.skipUnless(shutil.which("node"), "sin node")
    def test_texto_del_ultimo_salto(self):
        fns = MESA[MESA.index("function ahorradoTexto"):MESA.index("function pintaCategorias")]
        js = fns + """
console.log(JSON.stringify([
  patrociniosDetalle({}),
  patrociniosDetalle({ultimo_salto: {nombre: "Autobombo / promo del canal", seg: 42}}),
  patrociniosDetalle({entero: "patrocinado"}),
]));"""
        out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out, ["", "Último salto: Autobombo / promo del canal (42 s)",
                               "Este vídeo entero está marcado como patrocinado: no se salta nada"])


class Entrega(unittest.TestCase):
    def test_version(self):
        self.assertEqual(lazo.VERSION, "0.73")
        self.assertEqual(pcapc.VERSION, "0.73")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.73")
        self.assertIn('<p class="ver">0.73', MESA)
        self.assertIn("<title>LaZoo 0.73</title>", HTML)
        self.assertIn('const PAGE_VERSION = "0.73"', JS)

    def test_apk_sin_cambios(self):
        texto = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:versionCode="66"', texto)
        self.assertIn('android:versionName="3"', texto)
        r = subprocess.run(["git", "diff", "--quiet", "e881b1b", "--", "android"], cwd=ROOT, capture_output=True)
        if r.returncode in (0, 1):
            self.assertEqual(r.returncode, 0, "android/ cambió: la APK dejaría de ser la App 3")

    def test_solo_stdlib(self):
        src = (ROOT / "patrocinios.py").read_text(encoding="utf-8")
        for malo in ("import requests", "import aiohttp"):
            self.assertNotIn(malo, src)


if __name__ == "__main__":
    unittest.main()
