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
        self.assertIn('id="pc-top"', HTML)
        self.assertIn('id="pcs-salir"', HTML)
        self.assertIn('.top[data-link="on"] .pc-top', (ROOT / "static" / "app.css").read_text(encoding="utf-8"))

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
