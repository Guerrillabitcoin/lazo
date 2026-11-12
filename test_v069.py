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
