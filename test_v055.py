"""LaZoo 0.55: logotipo animado (anillo rojo -> infinito verde), iconos de bandeja, exe y APK."""

import re
import struct
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import bandeja
import lazo

ROOT = Path(__file__).resolve().parent
IMG = ROOT / "static" / "img"
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
MESA = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
JS = (ROOT / "static" / "logo.js").read_text(encoding="utf-8")
APK = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")


def ico_sizes(path: Path) -> set[int]:
    data = path.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1)
    return {(data[6 + 16 * i] or 256) for i in range(count)}


class Archivos(unittest.TestCase):
    def test_svg_validos(self):
        for name in ("logo-desconectado", "logo-conectado", "infinito-naranja", "infinito-rojo", "infinito-verde", "icono-app"):
            root = ET.parse(IMG / f"{name}.svg").getroot()
            self.assertTrue(root.tag.endswith("svg"), name)
            self.assertIn("viewBox", root.attrib)
        self.assertIn("#ea0918", (IMG / "logo-desconectado.svg").read_text())  # 0.57: color medido
        self.assertIn("#158941", (IMG / "logo-conectado.svg").read_text())

    def test_png(self):
        for name, size in (("icono-192", 192), ("icono-512", 512), ("apple-touch-icon", 180)):
            data = (IMG / f"{name}.png").read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", data[16:24]), (size, size))
        for name in ("logo-wordmark", "icono-apk-movil", "tray-desconectado", "tray-conectado"):
            self.assertTrue((IMG / "original" / f"{name}.png").is_file(), name)

    def test_ico_tamanos(self):
        for name in ("lazoo", "lazoo-rojo", "lazoo-verde"):
            self.assertEqual(ico_sizes(ROOT / "static" / f"{name}.ico"), {16, 24, 32, 48, 64, 128, 256}, name)

    def test_android(self):
        res = ROOT / "android" / "res"
        for d in ("mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi"):
            self.assertEqual((res / f"mipmap-{d}" / "ic_launcher.png").read_bytes()[:4], b"\x89PNG")
        for xml in ("mipmap-anydpi-v26/ic_launcher.xml", "drawable/ic_launcher_foreground.xml", "drawable/ic_notif.xml", "values/colors.xml"):
            ET.parse(res / xml)
        self.assertIn("R.drawable.ic_notif", (ROOT / "android/src/net/lazoo/app/MainActivity.java").read_text(encoding="utf-8"))
        self.assertIn('android:icon="@mipmap/ic_launcher"', APK)


class Bandeja(unittest.TestCase):
    def test_estado(self):
        self.assertEqual(bandeja.tray_state(0), ("lazoo-rojo.ico", "LaZoo · sin dispositivos"))
        self.assertEqual(bandeja.tray_state(1), ("lazoo-verde.ico", "LaZoo · 1 dispositivo conectado"))
        self.assertEqual(bandeja.tray_state(3), ("lazoo-verde.ico", "LaZoo · 3 dispositivos conectados"))

    def test_cambios_simulados(self):
        """Con conexiones que van y vienen, solo hay NIM_MODIFY cuando el estado cambia."""
        cambios, actual = [], bandeja.tray_state(0)
        for n in (0, 0, 1, 1, 2, 2, 0, 0):
            nuevo = bandeja.tray_state(n)
            if nuevo != actual:
                cambios.append(nuevo[0])
                actual = nuevo
        self.assertEqual(cambios, ["lazoo-verde.ico", "lazoo-verde.ico", "lazoo-rojo.ico"])

    def test_codigo(self):
        src = (ROOT / "bandeja.py").read_text(encoding="utf-8")
        self.assertIn("refresh_icon", src)
        self.assertIn("NIM_MODIFY", src)
        self.assertIn("LoadImageW", src)


class Web(unittest.TestCase):
    def test_html(self):
        for page in (HTML, MESA):
            self.assertIn('class="lz-logo', page)
            self.assertIn('data-estado="desconectado"', page)
            self.assertIn("/logo.js?v=0.67", page)
        self.assertIn('rel="manifest"', HTML)
        self.assertIn("data-dinamico", MESA)

    def test_estados_y_movimiento(self):
        for estado in ("desconectado", "esperando", "conectado"):
            self.assertIn(f'"{estado}"', JS)
        self.assertIn("prefers-reduced-motion", JS)
        self.assertIn("prefers-reduced-motion", CSS)
        self.assertIn("prefers-reduced-motion", MESA)
        self.assertRegex(JS, r'var LETRAS = "M[^"]{200,}"')

    def test_rutas(self):
        src = (ROOT / "lazo.py").read_text(encoding="utf-8")
        for ruta in ('"/logo.js"', '"/favicon.ico"', '"/manifest.webmanifest"', '"/img/"'):
            self.assertIn(ruta, src)
        self.assertTrue(re.fullmatch(r"[a-z0-9-]+\.(svg|png)", "logo-conectado.svg"))
        self.assertIsNone(re.fullmatch(r"[a-z0-9-]+\.(svg|png)", "../lazo.py"))


class Version(unittest.TestCase):
    def test_version(self):
        self.assertEqual(lazo.VERSION, "0.67")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.67")
        self.assertIn("<title>LaZoo 0.67</title>", HTML)
        self.assertIn("0.67", MESA)
        self.assertIn('android:versionName="2"', APK)
        self.assertIn('android:versionCode="65"', APK)
        self.assertIn("# LaZoo 0.67", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("## Estado (0.61)", (ROOT / "AGENTS.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
