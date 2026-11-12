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
