"""Pruebas de la 0.72: la interfaz del móvil (cabecera, una sola fila de PCs con nombres enteros
o el puesto con «Renombrar», tarjetas que no se desbordan en ninguna pestaña a 360 y 460 px),
el Panel que ya no se repinta encima de lo que escribes ni pega solo, y los valores de serie
del ratón del móvil (predicción apagada, el resto de la fluidez encendida, sin pisar lo que
alguien eligió a mano). Con Chrome sin pantalla (y playwright) si están.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ.setdefault("LAZO_DATOS", tempfile.mkdtemp())

import control  # noqa: E402
import lazo  # noqa: E402
import pcapc  # noqa: E402
import test_v070  # noqa: E402
from test_v070 import _req  # noqa: E402

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "docs"))
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
MESA = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
LOCAL = {"Content-Type": "application/json", "X-Lazo-Local": "1"}
CHROME = next((p for p in ("/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser") if os.path.exists(p)), None)
CON_CHROME = bool(CHROME and importlib.util.find_spec("playwright"))


# --- 1. Móvil -------------------------------------------------------------------------------------


class Cabecera(unittest.TestCase):
    def test_una_sola_forma_de_elegir_pc(self):
        self.assertNotIn('id="pc-top"', HTML, "el botón con el nombre del PC repetía la fila de pastillas")
        self.assertNotIn("pcTop", JS)
        self.assertIn('<nav id="pc-bar" class="pc-bar"', HTML)
        self.assertIn('id="pcs-salir"', HTML)  # la hoja sigue: se abre desde la pastilla del PC actual
        bloque = JS[JS.index("function pcBarPinta()"):JS.index("function pcGuardados()")]
        self.assertIn("pcsBox.hidden = false", bloque)
        self.assertIn("pcIrA(pc.url)", bloque)
        self.assertIn('pcBridge("anadirPc")', bloque)

    def test_estado_en_una_linea_y_pastillas_enteras(self):
        self.assertIn("#link-label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis;", CSS)
        self.assertIn(".pc-chip { flex: none;", CSS)
        self.assertNotIn(".pc-chip { flex: 1 0 auto;", CSS)
        self.assertIn("-webkit-line-clamp: 2", CSS)

    def test_nombre_puesto_con_renombrar(self):
        self.assertIn("data.pc_nombre || data.pc", JS)
        self.assertIn("pcInfo.apodos[host]", JS)
        self.assertIn("**pcapc.para_movil()", (ROOT / "lazo.py").read_text(encoding="utf-8"))
        saved = (pcapc.AJUSTES.nombre, pcapc.PCS.listar)
        try:
            pcapc.AJUSTES.nombre = "Sobremesa"
            pcapc.PCS.listar = lambda: [{"host": "192.168.1.25", "puerto": 8787, "apodo": "Portátil"},
                                        {"host": "192.168.1.31", "puerto": 8787, "apodo": ""}]
            self.assertEqual(pcapc.para_movil(), {"pc_nombre": "Sobremesa", "pcs_apodos": {"192.168.1.25:8787": "Portátil"}})
        finally:
            pcapc.AJUSTES.nombre, pcapc.PCS.listar = saved

    def test_nombre_de_este_pc_valida(self):
        tmp = tempfile.mkdtemp()
        saved = (os.environ.get("LAZO_DATOS"), pcapc.AJUSTES.nombre)
        os.environ["LAZO_DATOS"] = tmp
        try:
            self.assertEqual(pcapc.AJUSTES.set_nombre("  Sobremesa   del  salón "), "Sobremesa del salón")
            self.assertEqual(pcapc.Ajustes().cargar().nombre, "Sobremesa del salón")
            for malo in ("<b>x</b>", "x" * 41, "a\u202eb"):
                with self.assertRaises(pcapc.ErrorPC):
                    pcapc.AJUSTES.set_nombre(malo)
            self.assertEqual(pcapc.AJUSTES.set_nombre(""), "")
        finally:
            os.environ["LAZO_DATOS"] = saved[0] or tmp
            pcapc.AJUSTES.nombre = saved[1]
            shutil.rmtree(tmp, ignore_errors=True)


class Pestanas(unittest.TestCase):
    def test_no_se_pierde_ninguna(self):
        ids = [t.split('"')[0] for t in JS[JS.index("const TOOLS = ["):JS.index("const PINNED")].split('id: "')[1:]]
        self.assertEqual(ids, ["mouse", "bridge", "windows", "youtube", "spotify", "system", "lab", "about"])
        for nombre in ("Ratón", "Portapapeles Wifi", "Ventanas", "YouTube", "Spotify", "Sistema"):
            self.assertIn(f'name: "{nombre}"', JS)
        self.assertIn(".dock-scroll { -webkit-mask-image", CSS)  # se ve que la barra sigue

    def test_youtube_conserva_sus_botones(self):
        for i in ('id="yt-full"', "Pantalla completa", 'id="yt-movil"', "Seguir viendo en el móvil", 'data-yt="captions"', 'data-yt="subs_up"'):
            self.assertIn(i, HTML)

    def test_tarjetas_crecen(self):
        self.assertIn(".view > .deck { flex: 1 0 auto; min-height: auto; }", CSS)
        self.assertIn(".view > .deck:not(:only-child) { flex: none; }", CSS)
        self.assertIn(".phrase input, .phrase textarea { min-width: 0; }", CSS)


@unittest.skipUnless(CON_CHROME, "sin Chrome/playwright")
class MovilEnChrome(unittest.TestCase):
    """El JS y el CSS reales a 360 y 460 px: nada fuera de su tarjeta ni cortado arriba."""

    @classmethod
    def setUpClass(cls):
        import movil_prueba

        cls.tmp = Path(tempfile.mkdtemp())
        cls.saved = (pcapc.AJUSTES.nombre, pcapc.PCS.listar, control.SMOOTHER.on, control.CONTINUO.pred)
        pcapc.AJUSTES.nombre = "Sobremesa"
        pcapc.PCS.listar = lambda: [{"host": "192.168.1.25", "puerto": 8787, "apodo": "Portátil del salón"}]
        try:
            cls.medidas = movil_prueba.capturar(cls.tmp, (360, 460), fotos=False)
        finally:
            pcapc.AJUSTES.nombre, pcapc.PCS.listar, control.SMOOTHER.on, control.CONTINUO.pred = cls.saved

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)
        control.SMOOTHER.set(False)

    def test_nada_fuera_ni_cortado(self):
        for ancho, tabs in self.medidas.items():
            self.assertEqual(tabs["errores"], [], ancho)
            for tab, m in tabs.items():
                if tab == "errores":
                    continue
                self.assertEqual(m["fuera"], [], f"{ancho} px, {tab}")
                self.assertEqual(m["cortados"], [], f"{ancho} px, {tab}")
                self.assertEqual(m["lineas_estado"], 1, f"{ancho} px: «{m['estado']}» en una línea")
                self.assertLessEqual(m["ancho_doc"], m["vw"])

    def test_pastillas_con_nombre_entero_y_sin_repetir(self):
        m = self.medidas[360]["mouse"]
        self.assertEqual(m["arriba"], [], "arriba ya no hay botón con el nombre del PC")
        self.assertEqual(m["pcs"][0], "SobremesaWindows")  # el nombre puesto en el Panel
        self.assertEqual(m["pcs"][1], "Portátil del salónLinux")  # «Renombrar» de «Controlar otro PC»
        self.assertEqual(m["pcs"][2], "PC-ESTUDIO-CON-UN-NOMBRE-LARGOWindows")  # entero, la fila se desliza
        self.assertEqual(m["pcs"][3], "+")
        self.assertEqual(m["dock"], ["Ratón", "Portapapeles Wifi", "Ventanas", "YouTube", "Spotify", "Sistema", "Pruebas", "Sobre LaZoo"])


# --- 2. Panel -------------------------------------------------------------------------------------


class _Silencioso(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class PanelSinPegarSolo(unittest.TestCase):
    def test_no_lee_el_portapapeles_solo(self):
        self.assertNotIn("watchClipboard", MESA)
        self.assertEqual(MESA.count("navigator.clipboard.readText"), 1)
        i = MESA.index("navigator.clipboard.readText")
        self.assertIn('querySelector("#pegar")', MESA[i - 300:i], "solo el botón «Pegar» lee el portapapeles")
        pegar = MESA[MESA.index('document.addEventListener("paste"'):]
        self.assertIn("if (editable(event.target)) return;", pegar[:300])

    def test_refresco_con_firma(self):
        for lista in ('$("#devs")', '$("#pc-lista")', "pintaLista(pin,", "pintaLista(clips,", "pintaLista(files,", "pintaLista(urls,", "pintaLista(lista,"):
            self.assertIn(lista if lista.startswith("pintaLista") else f"pintaLista({lista}", MESA)
        self.assertNotIn('$("#pc-lista").replaceChildren', MESA)
        self.assertNotIn('$("#devs").replaceChildren', MESA)
        self.assertNotIn("clips.replaceChildren();", MESA)
        self.assertIn('id="nombre-este-ok"', MESA)
        self.assertIn('id="pegar"', MESA)


@unittest.skipUnless(CON_CHROME, "sin Chrome/playwright")
class PanelEnChrome(unittest.TestCase):
    """El Panel de verdad con datos de mentira (docs/panel_prueba.py) refrescando cada 1,5 s."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        import subprocess

        subprocess.run([sys.executable, str(ROOT / "docs" / "panel_prueba.py"), str(ROOT), str(self.tmp)], check=True)
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Silencioso, directory=str(self.tmp)))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/mesa.html"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_escribir_seleccionar_y_copiar(self):
        asyncio.run(self._prueba())

    async def _prueba(self):
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            ctx = await b.new_context(viewport={"width": 1300, "height": 1400})
            pg = await ctx.new_page()
            await pg.add_init_script("""
              window.__leidas = 0;
              const falso = { readText: async () => { window.__leidas += 1; return "PEGADO"; },
                              writeText: async (t) => { window.__copiado = t; } };
              Object.defineProperty(navigator, "clipboard", { get: () => falso });
            """)
            errores = []
            pg.on("pageerror", lambda e: errores.append(str(e)))
            await pg.goto(self.url)
            await asyncio.sleep(1.2)
            await pg.evaluate("window.__li = document.querySelector('#pc-lista li'); window.__dev = document.querySelector('#devs li');")

            # Escribir la IP letra a letra mientras el Panel refresca (antes: un clic por letra).
            await pg.click("#pc-destino")
            await pg.keyboard.type("192.168.1.20:8787", delay=180)  # ~3 s: dos refrescos o más
            self.assertEqual(await pg.input_value("#pc-destino"), "192.168.1.20:8787")
            self.assertEqual(await pg.evaluate("document.activeElement.id"), "pc-destino")
            # Pegar en el campo: va al campo, no a las notas.
            await pg.evaluate("""(() => { const dt = new DataTransfer(); dt.setData('text/plain', '10.0.0.9:8787');
              document.querySelector('#pc-destino').dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true})); })()""")
            await asyncio.sleep(2.2)
            llamadas = await pg.evaluate("window.__llamadas")
            self.assertNotIn(["/api/clipboard", "POST"], llamadas, "pegar en la IP no guarda una nota")
            self.assertEqual(await pg.evaluate("window.__leidas"), 0, "el Panel no lee el portapapeles solo")
            self.assertTrue(await pg.evaluate("window.__li === document.querySelector('#pc-lista li')"), "la lista no se rehízo sin cambios")
            self.assertTrue(await pg.evaluate("window.__dev === document.querySelector('#devs li')"))

            # Seleccionar la IP propia: no se pierde aunque cambien los datos; luego se actualiza.
            await pg.evaluate("""(() => { const s = document.querySelector('#pc-pin .sel'); const r = document.createRange();
              r.selectNodeContents(s); getSelection().removeAllRanges(); getSelection().addRange(r); })()""")
            await pg.evaluate("window.__datos['/api/pcapc'].pin = '654321'")
            await asyncio.sleep(2.2)
            self.assertEqual(await pg.evaluate("getSelection().toString()"), "192.168.1.144:8787")
            self.assertIn("123456", await pg.text_content("#pc-pin"))
            await pg.evaluate("getSelection().removeAllRanges()")
            await asyncio.sleep(2.0)
            self.assertIn("654321", await pg.text_content("#pc-pin"))

            # «Copiar» de la IP y «Pegar» explícito.
            await pg.click("#pc-pin button.copiar")
            self.assertEqual(await pg.evaluate("window.__copiado"), "192.168.1.144:8787")
            await pg.click("#pegar")
            self.assertEqual(await pg.input_value("#paste"), "PEGADO")
            self.assertEqual(await pg.evaluate("window.__leidas"), 1)

            # Con datos nuevos la lista sí se repinta.
            await pg.evaluate("window.__datos['/api/pcapc'].pcs[0].apodo = window.__datos['/api/pcapc'].pcs[0].nombre = 'Nuevo nombre'")
            await asyncio.sleep(2.0)
            self.assertIn("Nuevo nombre", await pg.text_content("#pc-lista"))
            self.assertEqual(errores, [])
            await b.close()


class PanelApi(unittest.TestCase):
    setUp = test_v070.ConServidor.setUp
    tearDown = test_v070.ConServidor.tearDown

    def test_nombre_de_este_pc_solo_desde_el_panel(self):
        saved = pcapc.AJUSTES.nombre
        try:
            code, data = _req(self.port, "POST", "/api/pcapc/nombre", json.dumps({"nombre": "Sobremesa"}).encode(), LOCAL)
            self.assertEqual((code, data["nombre_este"]), (200, "Sobremesa"))
            self.assertIn("nombre_sistema", data)
            code, _ = _req(self.port, "POST", "/api/pcapc/nombre", json.dumps({"nombre": "<script>"}).encode(), LOCAL)
            self.assertEqual(code, 400)
            code, _ = _req(self.port, "POST", "/api/pcapc/nombre", json.dumps({"nombre": "x"}).encode(), {"Content-Type": "application/json"})
            self.assertIn(code, (401, 403), "sin la cabecera del Panel, no")
        finally:
            pcapc.AJUSTES.nombre = saved


# --- 3. Ratón del móvil ---------------------------------------------------------------------------


class RatonDeSerie(unittest.TestCase):
    def test_pc_sin_prediccion_de_serie(self):
        self.assertFalse(control.PRESETS["equilibrado"]["prediccion"])
        nuevo = control.Continuo(dispatch=lambda *a: None)
        nuevo.aplicar(control.PRESETS["equilibrado"], "equilibrado")
        self.assertFalse(nuevo.pred)
        self.assertTrue(nuevo.on, "movimiento continuo encendido")
        a = control.PRESETS["equilibrado"]
        self.assertTrue(a["interpolacion"] and a["subpixel"] and a["alta_resolucion"])
        self.assertEqual(a["colchon_modo"], "adaptativo")
        # Los que el usuario elige a propósito siguen prediciendo.
        self.assertTrue(control.PRESETS["fluidez"]["prediccion"])
        self.assertTrue(control.PRESETS["retraso"]["prediccion"])

    def test_casillas_de_serie(self):
        self.assertIn('<input id="aim-pred" type="checkbox" />', HTML)
        self.assertIn('<input id="aim-smooth" type="checkbox" checked />', HTML)
        self.assertIn('<input id="aim-continuo" type="checkbox" checked />', HTML)
        self.assertIn('smoothBox.checked = localStorage.getItem("lazo-smooth") !== "0";', JS)
        self.assertIn('predBox.checked = localStorage.getItem("lazo-pred") === "1";', JS)
        self.assertIn('localStorage.setItem("lazo-pred-mano", "1");', JS)


@unittest.skipUnless(CON_CHROME, "sin Chrome/playwright")
class RatonDeSerieEnChrome(unittest.TestCase):
    """El móvil de verdad: lo de serie llega al PC y lo elegido a mano se respeta."""

    def setUp(self):
        self.saved = (control.SMOOTHER.on, control.CONTINUO.pred, control.CONTINUO.preset, dict(control.CONTINUO.ajustes))
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        control.SMOOTHER.set(self.saved[0])
        control.CONTINUO.aplicar(self.saved[3], self.saved[2])
        control.CONTINUO.set_pred(self.saved[1])
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _con(self, almacen):
        import movil_prueba

        control.CONTINUO.set_pred(True)
        control.SMOOTHER.set(False)
        m = movil_prueba.capturar(self.tmp, (400,), pestanas=["mouse"], almacen=almacen, fotos=False, espera_pref=2.5)[400]["mouse"]
        return m, control.CONTINUO.pred, control.SMOOTHER.on

    def test_instalacion_nueva(self):
        m, pred, suave = self._con(None)
        self.assertEqual((m["pred"], m["suave"], m["continuo"]), (False, True, True))
        self.assertEqual((pred, suave), (False, True), "el PC recibe lo de serie")

    def test_migra_si_nadie_la_toco(self):
        # 0.71 guardaba "lazo-pred" = "1" solo por sincronizar con el preset.
        m, pred, _ = self._con({"lazo-pred": "1", "lazo-ajuste": json.dumps({"preset": "equilibrado"})})
        self.assertFalse(m["pred"])
        self.assertFalse(pred)

    def test_respeta_lo_elegido_a_mano(self):
        m, pred, suave = self._con({"lazo-pred": "1", "lazo-pred-mano": "1", "lazo-smooth": "0",
                                    "lazo-ajuste": json.dumps({"preset": "equilibrado"})})
        self.assertEqual((m["pred"], m["suave"]), (True, False))
        self.assertEqual((pred, suave), (True, False), "el preset ya no pisa la casilla al conectar")

    def test_preset_de_fluidez_guardado_sigue_prediciendo(self):
        m, pred, _ = self._con({"lazo-pred": "1", "lazo-ajuste": json.dumps({"preset": "fluidez"})})
        self.assertTrue(m["pred"])
        self.assertTrue(pred)


class Entrega(unittest.TestCase):
    def test_version(self):
        self.assertEqual(lazo.VERSION, "0.73")
        self.assertEqual(pcapc.VERSION, "0.73")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.73")
        self.assertIn('<p class="ver">0.73', MESA)
        self.assertIn("<title>LaZoo 0.73</title>", HTML)
        self.assertIn('const PAGE_VERSION = "0.73"', JS)

    def test_apk_sin_cambios(self):
        apk = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:versionCode="66"', apk)
        self.assertIn('android:versionName="3"', apk)


if __name__ == "__main__":
    unittest.main()
