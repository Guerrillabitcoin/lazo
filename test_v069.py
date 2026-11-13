"""LaZoo 0.69: Panel con Configuración en el sitio del QR al conectar, e historial debajo."""
import re
import unittest
from pathlib import Path

MESA = (Path(__file__).parent / "static" / "mesa.html").read_text(encoding="utf-8")


class PanelColumna(unittest.TestCase):
    def columna(self):
        a = MESA.index('<div class="col-a">')
        b = MESA.index('<div class="side">')
        return MESA[a:b]

    def test_conectar_configuracion_e_historial_en_la_primera_columna_y_en_orden(self):
        col = self.columna()
        i = [col.index(x) for x in ('id="conexion"', 'id="config"', 'id="historial"')]
        self.assertEqual(i, sorted(i))

    def test_al_conectar_solo_se_oculta_conectar(self):
        self.assertIn("body.connected #conexion { display: none !important; }", MESA)
        self.assertNotIn("body.connected .board", MESA)  # la rejilla no cambia: Configuración sube sola
        self.assertNotIn("body.connected #config", MESA)

    def test_configuracion_e_historial_fuera_de_side(self):
        a = MESA.index('<div class="side">')
        b = MESA.index('<section id="pasar"')
        self.assertNotIn('id="config"', MESA[a:b])
        self.assertNotIn('id="historial"', MESA[a:b])

    def test_rejilla_con_la_columna(self):
        self.assertRegex(MESA, r'\.col-a \{ grid-area: cola;')
        for areas in re.findall(r'grid-template-areas: ([^;]+);', MESA):
            if "side" in areas:
                self.assertIn("cola", areas)
                self.assertNotIn("conn", areas)

    def test_historial_en_dos_lineas_para_la_columna(self):
        self.assertIn(".hist-lista .vid { grid-column: 1 / -1; grid-row: 2;", MESA)


if __name__ == "__main__":
    unittest.main()


class PortapapelesLinux(unittest.TestCase):
    ROOT = Path(__file__).parent

    def test_instalador_pone_xclip_en_las_cuatro_familias(self):
        inst = (self.ROOT / "instalar-linux.sh").read_text(encoding="utf-8")
        self.assertEqual(inst.count("wl-clipboard xclip ydotool"), 4)

    def test_iniciar_avisa_sin_herramienta_y_sin_venv(self):
        import subprocess
        ini = (self.ROOT / "iniciar.sh").read_text(encoding="utf-8")
        self.assertEqual(subprocess.run(["sh", "-n", str(self.ROOT / "iniciar.sh")]).returncode, 0)
        self.assertIn("command -v xclip", ini)
        self.assertIn("sudo apt install xclip wl-clipboard", ini)
        self.assertIn('python$v-venv', ini)
        self.assertIn("rm -rf .venv  # 0.69", ini)

    def test_xorg_escribe_con_xclip(self):
        from unittest import mock
        import control
        with mock.patch.object(control, "SYSTEM", "Linux"), \
             mock.patch.dict(control.os.environ, {"WAYLAND_DISPLAY": ""}), \
             mock.patch.object(control, "_which", lambda n: n == "xclip"), \
             mock.patch.object(control, "_run_input", return_value=True) as run:
            self.assertTrue(control._write_clipboard_text("hola"))
        run.assert_called_once_with(["xclip", "-selection", "clipboard", "-i"], "hola")


ROOT = Path(__file__).parent
JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JAVA = (ROOT / "android" / "src" / "net" / "lazoo" / "app" / "MainActivity.java").read_text(encoding="utf-8")
ESC = (ROOT / "android" / "assets" / "escaner.html").read_text(encoding="utf-8")


class VariosPc(unittest.TestCase):
    def test_nombre_del_pc_solo_en_status_firmado(self):
        import control
        import lazo
        st = control.status()
        self.assertTrue(st["pc"])
        self.assertLessEqual(len(st["pc"]), 40)
        src = (ROOT / "lazo.py").read_text(encoding="utf-8")
        linea = next(l for l in src.splitlines() if 'path == "/api/time"' in l)
        bloque = src[src.index(linea):src.index(linea) + 300]
        self.assertNotIn("pc_name", bloque)
        self.assertNotIn("gethostname", bloque)

    def test_pc_name_limpio(self):
        from unittest import mock
        import control
        with mock.patch.object(control.socket, "gethostname", return_value="vaio<script>.local"):
            self.assertEqual(control.pc_name(), "vaioscript")
        with mock.patch.object(control.socket, "gethostname", side_effect=OSError):
            self.assertEqual(control.pc_name(), "PC")

    def test_web_usa_el_puente_solo_si_existe(self):
        self.assertIn('typeof b[name] === "function"', JS)
        for fn in ("recordarPc", "pcs", "olvidarPc", "anadirPc"):
            self.assertIn(f'pcBridge("{fn}")', JS)
        self.assertNotIn("LaZooApp.pcs(", JS)
        # 0.72: sin botón arriba; la hoja «Este PC» se abre desde la pastilla del PC actual.
        self.assertNotIn('id="pc-top"', HTML)
        self.assertIn('id="pcs-salir"', HTML)
        self.assertIn('este.addEventListener("click", () => { pcsPinta(); pcsBox.hidden = false; });', JS)

    def test_salir_expulsa_y_olvida_la_clave(self):
        i = JS.index('querySelector("#pcs-salir")')
        bloque = JS[i:i + 900]
        self.assertIn('"/api/dispositivos/expulsar", { id: deviceId }', bloque)
        self.assertIn("forgetKey();", bloque)
        self.assertIn("showPin(", bloque)
        self.assertIn("askConfirm(", bloque)

    def test_apk_app3(self):
        apk = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:versionCode="66"', apk)
        self.assertIn('android:versionName="3"', apk)
        for fn in ("pcs()", "recordarPc(", "olvidarPc(", "anadirPc()", "probar("):
            self.assertIn("public ", JAVA[JAVA.index(fn) - 40:JAVA.index(fn)])
        self.assertIn('o.equals(pageOrigin)', JAVA)  # un PC no renombra a otro
        self.assertIn('new URL(base + "/")', JAVA)  # sin /api/: la APK no depende del PC por dentro
        self.assertIn('"<title>LaZoo"', JAVA)
        self.assertIn("setConnectTimeout(1500)", JAVA)
        self.assertIn('SCANNER + "#inicio"', JAVA)
        self.assertIn("MAX_PCS = 12", JAVA)
        self.assertNotIn("lazo-key", JAVA)  # la lista nunca guarda claves

    def test_inicio_de_la_apk(self):
        self.assertIn('location.hash === "#inicio"', ESC)
        self.assertIn("window.lazooProbado", ESC)
        self.assertIn('if (!pcs.length) start();', ESC)  # con PC guardados, la cámara solo al añadir
        self.assertIn("privateHost(url.hostname)", ESC)


class ArreglosTrasPrueba(unittest.TestCase):
    """12 nov, prueba del dueño con la App 3: notas con el teclado abierto, «Al PC» en Linux y
    la barra de PC bajo la de arriba."""

    def test_cajas_no_se_encogen_con_teclado(self):
        css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".view > .deck:not(:only-child) { flex: none; }", css)

    def test_barra_de_pc_bajo_la_de_arriba(self):
        self.assertIn('</header>\n      <nav id="pc-bar" class="pc-bar"', HTML)
        css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
        self.assertIn('.top[data-link="on"] + .pc-bar:not(:empty) { display: flex; }', css)
        i = JS.index("function pcBarPinta()")
        bloque = JS[i:i + 1600]
        self.assertIn('pc.url !== location.origin', bloque)
        self.assertIn('pcIrA(pc.url)', bloque)

    def test_gtk_clip_en_xorg(self):
        from unittest import mock
        import control
        import bandeja_linux

        hechos = []

        class Clip:
            texto = None

            def set_text(self, t, n):
                Clip.texto = t

            def store(self):
                hechos.append("store")

            def wait_for_text(self):
                return Clip.texto

        class Gtk:
            class Clipboard:
                @staticmethod
                def get(_sel):
                    return Clip()

        class GLib:
            @staticmethod
            def idle_add(fn):
                fn()

        c = bandeja_linux.GtkClip.__new__(bandeja_linux.GtkClip)
        c.Gtk, c.GLib, c.Gdk = Gtk, GLib, type("Gdk", (), {"SELECTION_CLIPBOARD": 1})
        self.assertTrue(c.escribir("hola ñ"))
        self.assertEqual(c.leer(), "hola ñ")
        self.assertEqual(hechos, ["store"])
        with mock.patch.object(control, "SYSTEM", "Linux"), \
             mock.patch.dict(control.os.environ, {"WAYLAND_DISPLAY": ""}), \
             mock.patch.object(control, "GTK_CLIP", c), \
             mock.patch.object(control, "_which", lambda n: False):
            self.assertTrue(control._write_clipboard_text("al pc"))  # sin xclip
            self.assertEqual(control._read_clipboard_text(), "al pc")

    def test_bandeja_pone_gtk_clip_solo_en_xorg(self):
        src = (ROOT / "bandeja_linux.py").read_text(encoding="utf-8")
        self.assertIn('if not os.environ.get("WAYLAND_DISPLAY"):', src)
        self.assertIn("self.lazo.control.GTK_CLIP = GtkClip(self.Gtk, self.GLib)", src)


class NombrePortapapelesWifi(unittest.TestCase):
    def test_nombre_y_aviso(self):
        import bandeja
        self.assertEqual(dict(bandeja.CUBES)["bridge"], "Portapapeles Wifi")
        self.assertIn('{ id: "bridge", name: "Portapapeles Wifi" }', JS)
        mesa = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
        for page in (HTML, mesa):
            self.assertNotIn("Pasar por wifi", page)
            self.assertIn("va encriptado", page)
            self.assertIn("nunca por internet", page)


class MovilEnOtroPc(unittest.TestCase):
    """Al cambiar de PC desde el móvil, el PC que deja se queda en naranja, no en rojo."""

    def test_protocolo(self):
        import protocol
        p = protocol.Pairing()
        p.note_phone("a")
        self.assertEqual((p.phone_count(), p.away_count()), (1, 0))
        p.phone_away("a")
        self.assertEqual((p.phone_count(), p.away_count()), (0, 1))
        p.phone_gone("a")  # el /api/bye de la página que se cierra no lo borra
        self.assertEqual(p.away_count(), 1)
        p.note_phone("a")  # vuelve
        self.assertEqual((p.phone_count(), p.away_count()), (1, 0))
        p.phone_away("a")
        p.away_gone("a")  # expulsado
        self.assertEqual(p.away_count(), 0)
        p.phone_away("b")
        p._away["b"] -= protocol.AWAY_SECONDS + 1
        self.assertEqual(p.away_count(), 0)
        p.phone_away("c")
        p.forget_phones()
        self.assertEqual(p.away_count(), 0)

    def test_bandeja(self):
        import bandeja
        import bandeja_linux
        self.assertEqual(bandeja.tray_state(0, 1)[0], "lazoo.ico")
        self.assertIn("otro PC", bandeja.tray_state(0, 1)[1])
        self.assertEqual(bandeja.tray_state(1, 1)[0], "lazoo-verde.ico")  # conectado manda
        self.assertEqual(bandeja.tray_state(0, 0)[0], "lazoo-rojo.ico")
        self.assertEqual(bandeja_linux.state(0, 1)[0].name, "infinito-naranja.svg")
        self.assertTrue(bandeja_linux.state(0, 1)[0].exists())

    def test_logo_y_paneles(self):
        logo = (ROOT / "static" / "logo.js").read_text(encoding="utf-8")
        self.assertIn('estado === "otro" ? "rgb(" + NARANJA.join(",") + ")" : "#fff"', logo)
        self.assertIn('estado === "conectado" || estado === "otro" ? 1 : 0', logo)
        self.assertIn('getAttribute("data-link") === "otro") return "otro"', logo)
        mesa = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
        self.assertIn('otro ? "Móvil en otro PC"', mesa)
        import lazo
        self.assertIn('otro ? "Móvil en otro PC"', lazo.connect_page().decode())
        self.assertIn('api("/api/ausente", {}).catch', JS)

    def test_ruta_firmada(self):
        import shutil, tempfile, threading
        import lazo, recordar
        from test_v062 import Phone
        tmp = Path(tempfile.mkdtemp())
        server = lazo.LazoServer(("127.0.0.1", 0), lazo.Handler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        saved = (lazo.Handler._loopback, lazo.APPROVALS.auto, lazo.maybe_open_mesa, lazo.STORE, list(lazo.APPROVALS.on_change))
        try:
            lazo.APPROVALS.auto = True
            lazo.maybe_open_mesa = lambda: None
            lazo.STORE = recordar.Store(tmp)
            lazo.Handler._loopback = lambda self: False
            lazo.PAIRING.rekey()
            lazo.PAIRING.forget_phones()
            a = Phone(port)
            a.pair_and_get_key()
            self.assertEqual(a.get("/api/status")[0], 200)
            self.assertEqual(lazo.PAIRING.phone_count(), 1)
            status, _ = a.signed_post("/api/ausente", {})
            self.assertEqual(status, 200)
            self.assertEqual((lazo.PAIRING.phone_count(), lazo.PAIRING.away_count()), (0, 1))
            self.assertEqual(lazo.connection_info()["otro_pc"], 1)
            self.assertEqual(a.get("/api/status")[0], 200)  # vuelve: verde otra vez
            self.assertEqual(lazo.PAIRING.away_count(), 0)
            a.signed_post("/api/ausente", {})
            lazo.kick_device(a.who)
            self.assertEqual(lazo.PAIRING.away_count(), 0)
        finally:
            lazo.Handler._loopback, lazo.APPROVALS.auto, lazo.maybe_open_mesa, lazo.STORE, hooks = saved
            lazo.APPROVALS.on_change[:] = hooks
            lazo.APPROVALS.devices.clear()
            lazo.KICKED.clear()
            lazo.PAIRING.rekey()
            lazo.PAIRING.forget_phones()
            server.shutdown()
            server.server_close()
            shutil.rmtree(tmp, ignore_errors=True)
