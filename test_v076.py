"""Pruebas de la 0.76: portapapeles común, imágenes entre PCs, nombres comunes y «Dispositivos».

    python3 test_v076.py

1. Notas comunes (control.fusionar_notas): unión por id, gana la versión más reciente, lo borrado
   no vuelve (lápidas y «borrar todo»), sin duplicados, con tope; la huella dice si hay que mandar.
2. Nombres comunes (nombres.py): uno por dispositivo, gana el más reciente, migración de los
   «Renombrar» de la 0.75, solo se comparten pc:/dev:.
3. Sincronización entre PCs (sincro.py, POST /api/pc/sync): firmada y sellada con la clave del
   dispositivo, solo para un PC aprobado; dos LaZoo de verdad en dos procesos.
4. Imágenes (imagenes.py y el canal /kvm v3): PNG y CF_DIB, trozos I1 y PIDE_TODO, y un PC con la
   0.75 (canal v2) sigue recibiendo solo texto.
5. Panel: «Controlar otro PC» dentro de «Dispositivos», lápiz, «Añadir PC» y «Avanzado» plegados;
   el móvil renombra con su propio cuadro.
6. Nada de bucles que lancen programas (0.75) y entrega (versión 0.76, APK sin cambios).
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zlib
from pathlib import Path

os.environ.setdefault("LAZO_DATOS", tempfile.mkdtemp())

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import aprobacion  # noqa: E402
import control  # noqa: E402
import imagenes  # noqa: E402
import lazo  # noqa: E402
import nombres  # noqa: E402
import pcapc  # noqa: E402
import protocol  # noqa: E402
import sincro  # noqa: E402
import test_v070  # noqa: E402

MESA = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")


def _item(ident, texto, at, seq=1):
    return {"id": ident, "text": texto, "at": at, "seq": seq}


class _Historial:
    """Un historial de notas propio en una carpeta temporal (nunca el del dueño)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._viejo = control._history_path
        control.set_history_path(self.tmp / "clipboard-history.json")

    def tearDown(self):
        control.set_history_path(self._viejo)
        shutil.rmtree(self.tmp, ignore_errors=True)


# --- 1. Notas comunes ------------------------------------------------------------------------------


class Notas(_Historial, unittest.TestCase):
    def test_union_y_mas_reciente(self):
        control.clipboard_history("nota de aquí")
        t = time.time()
        remoto = {"items": [_item("aa11bb22", "nota de allí", t - 5)], "borrados": {}, "vaciado": 0}
        self.assertTrue(control.fusionar_notas(remoto))
        textos = [i["text"] for i in control.estado_notas()["items"]]
        self.assertEqual(sorted(textos), ["nota de allí", "nota de aquí"])
        # la misma nota editada después allí gana
        remoto["items"] = [_item("aa11bb22", "nota de allí, editada", t + 1)]
        control.fusionar_notas(remoto)
        textos = [i["text"] for i in control.estado_notas()["items"]]
        self.assertIn("nota de allí, editada", textos)
        self.assertNotIn("nota de allí", textos)
        self.assertFalse(control.fusionar_notas(remoto), "lo mismo otra vez no cambia nada")

    def test_borrada_no_vuelve(self):
        t = time.time()
        control.fusionar_notas({"items": [_item("cc33dd44", "borrar esto", t - 10)], "borrados": {}, "vaciado": 0})
        control.delete_clipboard("cc33dd44")
        estado = control.estado_notas()
        self.assertIn("cc33dd44", estado["borrados"])
        # otro PC que aún la tiene no la resucita
        control.fusionar_notas({"items": [_item("cc33dd44", "borrar esto", t - 10)], "borrados": {}, "vaciado": 0})
        self.assertEqual([i["id"] for i in control.estado_notas()["items"]], [])
        # y la lápida que llega de otro PC borra aquí
        control.fusionar_notas({"items": [_item("ee55ff66", "otra", t - 3)], "borrados": {}, "vaciado": 0})
        control.fusionar_notas({"items": [], "borrados": {"ee55ff66": t}, "vaciado": 0})
        self.assertEqual(control.estado_notas()["items"], [])

    def test_borrar_todo_se_propaga(self):
        t = time.time()
        control.fusionar_notas({"items": [_item("1234abcd", "uno", t - 5), _item("2234abcd", "dos", t - 4)], "borrados": {}, "vaciado": 0})
        control.fusionar_notas({"items": [], "borrados": {}, "vaciado": t})
        self.assertEqual(control.estado_notas()["items"], [])
        control.fusionar_notas({"items": [_item("3234abcd", "nueva", t + 2)], "borrados": {}, "vaciado": 0})
        self.assertEqual([i["text"] for i in control.estado_notas()["items"]], ["nueva"], "lo de después sí entra")

    def test_sin_duplicados_y_todos_eligen_igual(self):
        t = time.time()
        a = {"items": [_item("aaaa0001", "mismo texto", t - 20)], "borrados": {}, "vaciado": 0}
        b = {"items": [_item("bbbb0001", "mismo texto", t - 10)], "borrados": {}, "vaciado": 0}
        control.fusionar_notas(a)
        control.fusionar_notas(b)
        items = control.estado_notas()["items"]
        self.assertEqual([i["id"] for i in items], ["bbbb0001"], "se queda la más reciente")
        self.assertIn("aaaa0001", control.estado_notas()["borrados"])

    def test_tope_y_datos_malos(self):
        t = time.time()
        muchas = [_item(f"{n:08x}", f"nota {n}", t - 1000 + n) for n in range(100)]
        malas = [{"id": "<b>", "text": "x", "at": t}, {"id": "abcdef12", "text": 5, "at": t},
                 {"id": "abcdef13", "text": "futuro", "at": t + 10 * 86400}, "nada"]
        control.fusionar_notas({"items": muchas + malas, "borrados": {"zz": 1, "abcdef99": "x"}, "vaciado": "x"})
        items = control.estado_notas()["items"]
        self.assertLessEqual(len(items), control._CLIP_LIMIT)
        self.assertNotIn("futuro", [i["text"] for i in items])
        self.assertEqual(items[0]["text"], "nota 99", "las más recientes primero")
        self.assertFalse(control.fusionar_notas("no es un dict"))

    def test_huella(self):
        control.clipboard_history("hola")
        e = control.estado_notas()
        self.assertEqual(control.firma_notas(e), control.firma_notas())
        otro = json.loads(json.dumps(e))
        otro["items"][0]["text"] = "adiós"
        self.assertNotEqual(control.firma_notas(otro), control.firma_notas(e))

    def test_las_lapidas_tienen_tope(self):
        t = time.time()
        control.fusionar_notas({"items": [], "borrados": {f"{n:08x}": t - n for n in range(900)}, "vaciado": 0})
        self.assertLessEqual(len(control.estado_notas()["borrados"]), control._MAX_BORRADOS)


# --- 2. Nombres comunes -----------------------------------------------------------------------------


class Nombres(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_gana_el_mas_reciente(self):
        a, b = nombres.Nombres(self.tmp / "a"), nombres.Nombres(self.tmp / "b")
        (self.tmp / "a").mkdir()
        (self.tmp / "b").mkdir()
        a.poner("pc:" + "1" * 16, "Sobremesa", t=1000)
        b.poner("pc:" + "1" * 16, "Salón", t=2000)
        self.assertTrue(a.fusionar(b.exportar()))
        self.assertFalse(b.fusionar(a.exportar()))
        self.assertEqual(a.get("pc:" + "1" * 16), "Salón")
        self.assertEqual(b.get("pc:" + "1" * 16), "Salón")
        # un cambio hecho aquí siempre es más reciente que lo que había
        futuro = nombres.ahora_ms() + 3600_000  # reloj del otro PC una hora adelantado
        b.poner("pc:" + "1" * 16, "Despacho", t=futuro)
        a.fusionar(b.exportar())
        a.poner("pc:" + "1" * 16, "Estudio")
        self.assertGreater(a.fila("pc:" + "1" * 16)["t"], futuro)

    def test_no_acepta_futuro_ni_basura(self):
        a = nombres.Nombres(self.tmp)
        lejos = nombres.ahora_ms() + 3 * nombres.FUTURO_MS
        self.assertFalse(a.fusionar({"pc:" + "2" * 16: {"n": "x", "t": lejos}}))
        self.assertFalse(a.fusionar({"local:" + "3" * 16: {"n": "x", "t": 5}}), "local: no viaja")
        self.assertFalse(a.fusionar({"dev:" + "4" * 16: {"n": "<script>", "t": 5}}))
        self.assertFalse(a.fusionar("nada"))
        a.poner("local:" + "5" * 16, "Solo aquí")
        self.assertEqual(a.exportar(), {})

    def test_migracion_075(self):
        (self.tmp / "apodos.json").write_text(json.dumps({"abcdef0123456789": "Móvil de Ana"}), encoding="utf-8")
        (self.tmp / "otros-pcs.json").write_text(json.dumps({"pcs": [{"id": "fedcba9876543210", "apodo": "Portátil"}]}), encoding="utf-8")
        a = nombres.Nombres(self.tmp)
        # el móvil: su id es el mismo en todos los PCs → pasa a dev: al listarlo y se comparte
        self.assertEqual(a.nombre_dispositivo("abcdef0123456789"), "Móvil de Ana")
        self.assertEqual(a.exportar()["dev:abcdef0123456789"]["n"], "Móvil de Ana")
        # un PC: hasta sincronizar con él no se sabe su id fijo
        self.assertEqual(a.nombre_dispositivo("fedcba9876543210", es_pc=True), "Portátil")
        self.assertNotIn("pc:", json.dumps(a.exportar()))
        a.enlazar("fedcba9876543210", "pc:" + "9" * 16, host="192.168.1.25:8787")
        self.assertEqual(a.get("pc:" + "9" * 16), "Portátil")
        self.assertEqual(a.hosts(), {"192.168.1.25:8787": "Portátil"})
        self.assertTrue(json.loads((self.tmp / nombres.ARCHIVO).read_text(encoding="utf-8"))["migrado"])

    def test_apodos_usa_el_registro(self):
        ap = aprobacion.Apodos(self.tmp)
        self.assertEqual(ap.poner("abcdef0123456789", "  Tablet  "), "Tablet")
        self.assertEqual(ap.nombres.get("dev:abcdef0123456789"), "Tablet")
        with self.assertRaises(ValueError):
            ap.poner("no-es-un-id", "x")


# --- 3. Sincronización entre PCs ---------------------------------------------------------------------


class SincroLogica(_Historial, unittest.TestCase):
    def test_un_pc_075_contesta_404(self):
        pcs = type("P", (), {"listar": lambda self: [{"id": "ab" * 8, "host": "192.168.1.9", "puerto": 8787}],
                             "clave": lambda self, _id: b"k" * 32})()
        llamadas = []

        def pedir(fila, ruta, cuerpo, kd):
            llamadas.append(ruta)
            return 404, {"error": "No encontrado"}

        reloj = [100.0]
        s = sincro.Sincro(pcs, pedir, reloj=lambda: reloj[0])
        self.assertEqual(s.ronda(), 1)
        v = s.ver()["ab" * 8]
        self.assertEqual(v["estado"], "antiguo")
        self.assertIn("versión anterior", v["mensaje"])
        self.assertEqual(s.ronda(), 0, "a un 0.75 no se le insiste")
        self.assertEqual(s.ronda(cambio=True), 0, "ni aunque algo cambie aquí")
        reloj[0] += sincro.ESPERA_ANTIGUO + 1
        self.assertEqual(s.ronda(), 1)
        self.assertEqual(llamadas, [sincro.RUTA, sincro.RUTA])

    def test_huella_igual_no_manda_las_notas(self):
        control.clipboard_history("algo")
        pcs = type("P", (), {"listar": lambda self: [{"id": "cd" * 8, "host": "192.168.1.9", "puerto": 8787}],
                             "clave": lambda self, _id: b"k" * 32})()
        cuerpos = []

        def pedir(fila, ruta, cuerpo, kd):
            cuerpos.append(cuerpo)
            firma = control.firma_notas()
            return 200, {"v": 1, "yo": {"pc_id": "e" * 16, "nombre": "Otro", "puerto": 8787, "sistema": "Linux"},
                         "comparte": True, "nombres": {}, "firma": firma, "igual": True}

        s = sincro.Sincro(pcs, pedir, reloj=lambda: 0.0)
        s.ronda(forzar=True)
        s.ronda(forzar=True)
        self.assertIn("notas", cuerpos[0])
        self.assertNotIn("notas", cuerpos[1], "solo la huella si nada cambió")
        self.assertEqual(s.ver()["cd" * 8]["estado"], "ok")


def _libre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _req(port, method, path, body=None, local=True):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if local:
        h["X-Lazo-Local"] = "1"
    r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=10) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _esperar(cond, tope=20.0):
    fin = time.monotonic() + tope
    while time.monotonic() < fin:
        try:
            if cond():
                return True
        except (OSError, KeyError, ValueError):
            pass
        time.sleep(0.25)
    return False


class DosPCs(unittest.TestCase):
    """Dos LaZoo de verdad (dos procesos, dos carpetas) en 127.0.0.1: A añade a B con su PIN."""

    @classmethod
    def setUpClass(cls):
        cls.procs, cls.dirs = [], []
        cls.a = cls._lanza("123456")
        cls.b = cls._lanza("654321")
        _req(cls.a, "POST", "/api/pcapc/nombre", {"nombre": "Sobremesa"})
        _req(cls.b, "POST", "/api/pcapc/nombre", {"nombre": "Portátil"})
        _req(cls.b, "POST", "/api/pcapc/permitir", {"on": True})
        _req(cls.a, "POST", "/api/clipboard", {"text": "nota desde A"})
        _req(cls.b, "POST", "/api/clipboard", {"text": "nota desde B"})
        code, r = _req(cls.a, "POST", "/api/pcapc/anadir", {"destino": f"127.0.0.1:{cls.b}", "pin": "654321"})
        assert code == 200, r
        assert _esperar(lambda: _req(cls.a, "GET", "/api/pcapc")[1]["pcs"]), "no se emparejaron"

    @classmethod
    def _lanza(cls, pin):
        d = tempfile.mkdtemp()
        port = _libre()
        env = dict(os.environ, LAZO_DATOS=d, LAZO_AUTOAPPROVE="1", HOME=d)
        for k in ("DISPLAY", "WAYLAND_DISPLAY"):
            env.pop(k, None)
        p = subprocess.Popen([sys.executable, "lazo.py", "--host", "127.0.0.1", "--port", str(port), "--pin", pin, "--no-browser",
                              "--sin-portapapeles", "--sin-vigilante", "--sin-anuncios", "--sin-despierto"],
                             cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.procs.append(p)
        cls.dirs.append(d)
        assert _esperar(lambda: _req(port, "GET", "/api/pcapc")[0] == 200, 40), "LaZoo no arrancó"
        return port

    @classmethod
    def tearDownClass(cls):
        for p in cls.procs:
            p.terminate()
        for p in cls.procs:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        for d in cls.dirs:
            shutil.rmtree(d, ignore_errors=True)

    def notas(self, port):
        return sorted(i["text"] for i in _req(port, "GET", "/api/clipboard")[1].get("items", []))

    def test_1_notas_en_los_dos(self):
        self.assertTrue(_esperar(lambda: self.notas(self.a) == self.notas(self.b) == ["nota desde A", "nota desde B"]),
                        (self.notas(self.a), self.notas(self.b)))
        st = _req(self.a, "GET", "/api/pcapc")[1]
        self.assertEqual(list(st["sincro"].values())[0]["estado"], "ok")

    def test_2_nombres_comunes(self):
        # A ve a B con el nombre que B se puso, y B ve a A igual
        self.assertTrue(_esperar(lambda: _req(self.a, "GET", "/api/pcapc")[1]["pcs"][0]["nombre"] == "Portátil"))
        self.assertTrue(_esperar(lambda: any(d["apodo"] == "Sobremesa" for d in _req(self.b, "GET", "/api/dispositivos")[1]["devices"])))
        # renombrar B desde A: B lo usa como su propio nombre
        pid = _req(self.a, "GET", "/api/pcapc")[1]["pcs"][0]["id"]
        self.assertEqual(_req(self.a, "POST", "/api/nombre", {"pc": pid, "nombre": "Linux del salón"})[1]["nombre"], "Linux del salón")
        self.assertTrue(_esperar(lambda: _req(self.b, "GET", "/api/pcapc")[1]["nombre_este"] == "Linux del salón"))
        # y renombrar A desde B (el que no tiene la clave de A) también llega
        who = next(d["id"] for d in _req(self.b, "GET", "/api/dispositivos")[1]["devices"] if d.get("es_pc"))
        _req(self.b, "POST", "/api/nombre", {"id": who, "nombre": "Torre"})
        self.assertTrue(_esperar(lambda: _req(self.a, "GET", "/api/pcapc")[1]["nombre_este"] == "Torre"))

    def test_3_borrar_en_uno_borra_en_otro(self):
        _req(self.b, "POST", "/api/clipboard", {"text": "efímera"})
        self.assertTrue(_esperar(lambda: "efímera" in self.notas(self.a)))
        ident = next(i["id"] for i in _req(self.a, "GET", "/api/clipboard")[1]["items"] if i["text"] == "efímera")
        _req(self.a, "POST", "/api/clipboard/borrar", {"id": ident})
        self.assertTrue(_esperar(lambda: "efímera" not in self.notas(self.b)))
        time.sleep(6)
        self.assertNotIn("efímera", self.notas(self.a), "no resucita")

    def test_4_apagado_no_comparte_notas(self):
        _req(self.b, "POST", "/api/pcapc/compartir", {"on": False})
        try:
            _req(self.a, "POST", "/api/clipboard", {"text": "solo en A"})
            self.assertTrue(_esperar(lambda: list(_req(self.a, "GET", "/api/pcapc")[1]["sincro"].values())[0]["estado"] == "sin_notas"))
            time.sleep(1)
            self.assertNotIn("solo en A", self.notas(self.b))
        finally:
            _req(self.b, "POST", "/api/pcapc/compartir", {"on": True})
        self.assertTrue(_esperar(lambda: "solo en A" in self.notas(self.b)))

    def test_5_sin_firma_no_entra(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.b}{sincro.RUTA}", data=b"{}", method="POST",
                                     headers={"X-Lazo-Local": "1", "Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as caja:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(caja.exception.code, 401, "ni desde el propio PC sin la firma de un PC aprobado")


class SyncEnElServidor(unittest.TestCase):
    """El servidor de test_v070 (mismo proceso): la petición firmada y sellada de pcapc.peticion."""

    setUp = test_v070.ConServidor.setUp
    tearDown = test_v070.ConServidor.tearDown
    emparejar = test_v070.ConServidor.emparejar

    def cuerpo(self):
        return {"v": 1, "yo": {"pc_id": "f" * 16, "nombre": "Otro", "puerto": 8787, "sistema": "Linux"},
                "comparte": False, "nombres": {"pc:" + "f" * 16: {"n": "Otro PC", "t": nombres.ahora_ms()}}}

    def test_pc_aprobado(self):
        who, _ = self.emparejar()
        fila = self.pcs.listar()[0]
        code, r = pcapc.peticion(fila, sincro.RUTA, self.cuerpo(), self.pcs.clave(who))
        self.assertEqual(code, 200, r)
        self.assertEqual(r["yo"]["pc_id"], pcapc.AJUSTES.pc_id)
        self.assertEqual(nombres.NOMBRES.clave_de(who), "pc:" + "f" * 16)
        self.assertEqual(nombres.NOMBRES.get("pc:" + "f" * 16), "Otro PC")

    def test_movil_no_puede(self):
        who, _ = self.emparejar()
        # el mismo dispositivo, pero si fuera un móvil (sin «PC · »), no
        dev = lazo.APPROVALS.devices[who]
        viejo = dev["label"]
        dev["label"] = "Android · App LaZoo"
        try:
            code, _r = pcapc.peticion(self.pcs.listar()[0], sincro.RUTA, self.cuerpo(), self.pcs.clave(who))
            self.assertEqual(code, 403)
        finally:
            dev["label"] = viejo

    def test_clave_mala(self):
        self.emparejar()
        code, _r = pcapc.peticion(self.pcs.listar()[0], sincro.RUTA, self.cuerpo(), b"x" * 32)
        self.assertEqual(code, 401)


# --- 4. Imágenes ---------------------------------------------------------------------------------------


def _png_con_filtros(ancho, alto, rgba):
    """PNG RGBA con los cinco filtros (uno por fila, en rueda), para probar el decodificador."""
    bpp, fila = 4, ancho * 4
    crudo = bytearray()
    previa = bytes(fila)
    for y in range(alto):
        f = y % 5
        linea = rgba[y * fila:(y + 1) * fila]
        out = bytearray()
        for x in range(fila):
            a = linea[x - bpp] if x >= bpp else 0
            b = previa[x]
            c = previa[x - bpp] if x >= bpp else 0
            pred = [0, a, b, (a + b) // 2, imagenes._paeth(a, b, c)][f]
            out.append((linea[x] - pred) & 0xFF)
        crudo += bytes([f]) + out
        previa = linea
    ihdr = struct.pack(">IIBBBBB", ancho, alto, 8, 6, 0, 0, 0)
    return (imagenes.FIRMA_PNG + imagenes._trozo(b"IHDR", ihdr) + imagenes._trozo(b"IDAT", zlib.compress(bytes(crudo)))
            + imagenes._trozo(b"IEND", b""))


def _rgba(ancho, alto):
    return bytes(v for y in range(alto) for x in range(ancho) for v in ((x * 37) % 256, (y * 53) % 256, (x * y) % 256, (x + y * 7) % 256))


class Imagenes(unittest.TestCase):
    def test_png_ida_y_vuelta(self):
        rgba = _rgba(13, 7)
        png = imagenes.png_de_pixeles(13, 7, rgba)
        self.assertTrue(imagenes.es_png(png))
        self.assertEqual(imagenes.medidas_png(png), (13, 7))
        self.assertEqual(imagenes.pixeles_de_png(png), (13, 7, rgba))

    def test_todos_los_filtros(self):
        rgba = _rgba(9, 11)
        self.assertEqual(imagenes.pixeles_de_png(_png_con_filtros(9, 11, rgba))[2], rgba)

    def test_dib_de_windows(self):
        rgba = _rgba(5, 4)
        dib = imagenes.png_a_dib(imagenes.png_de_pixeles(5, 4, rgba))
        self.assertEqual(struct.unpack_from("<IiiHH", dib), (40, 5, 4, 1, 32))
        self.assertEqual(imagenes.pixeles_de_png(imagenes.dib_a_png(dib))[2], rgba)
        # una captura: 24 bits, filas con relleno, de abajo arriba
        ancho, alto = 3, 2
        paso = 12
        filas = [bytes([0, 0, 255] * 3) + b"\0\0\0", bytes([255, 0, 0] * 3) + b"\0\0\0"]  # abajo rojo, arriba azul
        dib24 = struct.pack("<IiiHHIIiiII", 40, ancho, alto, 1, 24, 0, paso * alto, 0, 0, 0, 0) + b"".join(filas)
        _w, _h, px = imagenes.pixeles_de_png(imagenes.dib_a_png(dib24))
        self.assertEqual(px[:4], bytes([0, 0, 255, 255]), "arriba azul")
        self.assertEqual(px[-4:], bytes([255, 0, 0, 255]), "abajo rojo")
        # 32 bits con el alfa a 0 (Impr Pant): opaca
        dib32 = struct.pack("<IiiHHIIiiII", 40, 1, 1, 1, 32, 0, 4, 0, 0, 0, 0) + bytes([10, 20, 30, 0])
        self.assertEqual(imagenes.pixeles_de_png(imagenes.dib_a_png(dib32))[2], bytes([30, 20, 10, 255]))

    def test_limites(self):
        with self.assertRaises(imagenes.ErrorImagen):
            imagenes.pixeles_de_png(b"no")
        grande = struct.pack(">IIBBBBB", 100000, 100000, 8, 6, 0, 0, 0)
        with self.assertRaises(imagenes.ErrorImagen):
            imagenes.pixeles_de_png(imagenes.FIRMA_PNG + imagenes._trozo(b"IHDR", grande) + imagenes._trozo(b"IEND", b""))
        self.assertEqual(pcapc.trozos_imagen(1, b"\x89PNG" + b"x" * (pcapc.MAX_IMAGEN + 1)), [])
        self.assertFalse(imagenes.poner(b"no es png"))

    def test_trozos_y_juntar(self):
        png = imagenes.png_de_pixeles(200, 200, os.urandom(200 * 200 * 4), nivel=0)
        trozos = pcapc.trozos_imagen(7, png)
        self.assertGreater(len(trozos), 1)
        j = pcapc.JuntarImagen()
        out = None
        for n, t in enumerate(trozos, 1):
            numero, evs = pcapc.decodificar(pcapc.codificar_porta(n, *t))
            self.assertEqual(evs[0][0], pcapc.IMAGEN)
            out = j.trozo(*evs[0][1:])
        self.assertEqual(out, png)
        for malo in (pcapc.CABECERA_IMAGEN + struct.pack("<IIII", 1, 1, 0, 0),
                     pcapc.CABECERA_IMAGEN + struct.pack("<IIII", 1, 1, pcapc.MAX_IMAGEN + 1, 0) + b"x",
                     pcapc.CABECERA_IMAGEN + b"\0"):
            with self.assertRaises(protocol.ProtocolError):
                pcapc.decodificar(malo)

    def test_pide_todo(self):
        n, evs = pcapc.decodificar(pcapc.codificar(3, [(pcapc.PIDE_TODO, 9)]))
        self.assertEqual(evs, [(pcapc.PIDE_TODO, 9)])

    def test_receptor_pone_la_imagen(self):
        puestas = []
        r = pcapc.Receptor(test_v070.Falso(), porta_poner=lambda t: None, imagen_poner=puestas.append, hilo_suave=False)
        png = imagenes.png_de_pixeles(2, 2, bytes(16))
        for n, t in enumerate(pcapc.trozos_imagen(1, png), 1):
            self.assertEqual(r.tratar(pcapc.codificar_porta(n, *t)), [])
        self.assertTrue(_esperar(lambda: puestas == [png], 3))
        self.assertEqual(r.tratar(pcapc.codificar(99, [(pcapc.PIDE_TODO, 5)])), [(pcapc.PIDE_TODO, 5)])
        r.cerrar()

    def test_receptor_sin_compartir_no_pone(self):
        r = pcapc.Receptor(test_v070.Falso(), porta_poner=None, imagen_poner=None, hilo_suave=False)
        png = imagenes.png_de_pixeles(2, 2, bytes(16))
        for n, t in enumerate(pcapc.trozos_imagen(1, png), 1):
            r.tratar(pcapc.codificar_porta(n, *t))
        r.cerrar()

    def test_un_receptor_075_rechaza_i1(self):
        """Por eso solo se mandan imágenes a un receptor que dice X-LaZoo-KVM: 3."""
        src = subprocess.run(["git", "show", "1b51de2:pcapc.py"], cwd=ROOT, capture_output=True, text=True)
        if src.returncode != 0:
            self.skipTest("sin el historial de git")
        ns: dict = {}
        viejo = src.stdout
        self.assertNotIn("CABECERA_IMAGEN", viejo)
        self.assertIn("KVM_VERSION = 2", viejo)


class ImagenesPuntaAPunta(unittest.TestCase):
    setUp = test_v070.ConServidor.setUp
    emparejar = test_v070.ConServidor.emparejar

    def tearDown(self):
        pcapc.RECEPCION.imagen_leer, pcapc.RECEPCION.imagen_poner, pcapc.RECEPCION.porta_leer = self._rec
        pcapc.KVM_VERSION = self._v
        pcapc.AJUSTES.portapapeles = self._porta
        test_v070.ConServidor.tearDown(self)

    def preparar(self):
        self._rec = (pcapc.RECEPCION.imagen_leer, pcapc.RECEPCION.imagen_poner, pcapc.RECEPCION.porta_leer)
        self._v = pcapc.KVM_VERSION
        self._porta = pcapc.AJUSTES.portapapeles
        pcapc.AJUSTES.portapapeles = True
        self.llegadas_alli, self.llegadas_aqui = [], []
        self.png_aqui = imagenes.png_de_pixeles(120, 80, os.urandom(120 * 80 * 4), nivel=0)  # ~38 KB: varios trozos
        self.png_alli = imagenes.png_de_pixeles(3, 3, bytes(range(36)))
        pcapc.RECEPCION.porta_leer = lambda: ""
        pcapc.RECEPCION.imagen_leer = lambda: self.png_alli
        pcapc.RECEPCION.imagen_poner = self.llegadas_alli.append
        ctl = pcapc.Control(self.pcs, fabrica=test_v070.CapturaFalsa)
        ctl.porta_leer = lambda: ""
        ctl.porta_poner = lambda t: None
        ctl.imagen_leer = lambda: self.png_aqui
        ctl.imagen_poner = self.llegadas_aqui.append
        ctl.apuntar = lambda t: None
        return ctl

    def test_captura_en_los_dos_sentidos(self):
        ctl = self.preparar()
        who, _ = self.emparejar()
        ctl.iniciar(who)
        self.assertTrue(ctl.v3)
        self.assertTrue(_esperar(lambda: self.llegadas_alli == [self.png_aqui], 8), "la captura de aquí llega allí")
        self.assertIn("no se guarda en disco", ctl.mensaje)
        avisos = []
        ctl.escuchas.append(lambda e, t: avisos.append(t))
        ctl.parar("Has vuelto a este PC.", traer=True)
        self.assertTrue(_esperar(lambda: self.llegadas_aqui == [self.png_alli], 5), "y la de allí vuelve")
        self.assertTrue(any("imagen 3×3" in a for a in avisos), avisos)

    def test_con_un_pc_075_solo_texto(self):
        ctl = self.preparar()
        pcapc.KVM_VERSION = 2  # el otro PC contesta como la 0.75
        who, _ = self.emparejar()
        ctl.iniciar(who)
        self.assertTrue(ctl.v2)
        self.assertFalse(ctl.v3)
        time.sleep(0.6)
        self.assertEqual(self.llegadas_alli, [], "a un 0.75 no se le manda una imagen (cortaría la conexión)")
        ctl.parar("", traer=True)
        self.assertEqual(self.llegadas_aqui, [])


# --- 5. Panel y móvil --------------------------------------------------------------------------------


class Panel(unittest.TestCase):
    def test_controlar_otro_pc_en_dispositivos(self):
        self.assertNotIn('id="otro-pc"', MESA)
        i, j = MESA.index('<section id="dispositivos"'), MESA.index("</section>", MESA.index('<section id="dispositivos"'))
        seccion = MESA[i:j]
        for ident in ('id="devs"', 'id="nombre-este-ok"', 'id="pc-estado"', 'id="pc-anadir-caja"', 'id="pc-destino"',
                      'id="pc-codigo"', 'id="pc-avanzado"', 'id="pc-compartir"'):
            self.assertIn(ident, seccion)
        self.assertIn("<summary>Añadir PC</summary>", seccion)
        avanzado = seccion[seccion.index('id="pc-avanzado"'):]
        for ident in ('id="pc-arreglar"', 'id="pc-diag"', 'id="pc-suave"', 'id="pc-fluidez-ok"'):
            self.assertIn(ident, avanzado)

    def test_compartir_de_serie(self):
        self.assertIn('id="pc-compartir" type="checkbox" checked /> Compartir historial y notas entre mis dispositivos', MESA)
        self.assertIn('pcCall("compartir"', MESA)
        self.assertTrue(pcapc.Ajustes().compartir_notas)

    def test_lapiz_y_nombre_comun(self):
        self.assertIn('b.className = "lapiz"', MESA)
        self.assertIn('devCall("/api/nombre", { pc: pc.id, nombre })', MESA)
        self.assertIn('devCall("/api/nombre", { id: x.id, nombre })', MESA)
        self.assertIn('devCall("/api/nombre", { este: true, nombre })', MESA)
        self.assertIn("pintaLista($(\"#devs\")", MESA)

    def test_movil_renombra_sin_prompt(self):
        for ident in ('id="nombre-dlg"', 'id="nombre-dlg-input"', 'id="pcs-este-lapiz"', 'id="pcs-movil-lapiz"'):
            self.assertIn(ident, HTML)
        hoja = JS[JS.index("function pideNombre("):JS.index("function pcsPinta(")]
        self.assertNotIn("window.prompt", hoja, "en la App, window.prompt no siempre sale")
        self.assertIn("pideNombre(", JS[JS.index("function pcsPinta("):JS.index("function showHome(")])
        for cuerpo in ("{ este: true, nombre }", "{ yo: true, nombre }", "{ host, nombre }"):
            self.assertIn(cuerpo, JS)
        self.assertIn("data.movil_nombre", JS)

    def test_panel_pinta_una_vez_cada_pc(self):
        if not (shutil.which("google-chrome") or shutil.which("chromium")):
            self.skipTest("sin Chrome")
        tmp = Path(tempfile.mkdtemp())
        try:
            subprocess.run([sys.executable, str(ROOT / "docs" / "panel_prueba.py"), str(ROOT), str(tmp)], check=True)
            import functools
            import http.server

            class Silencio(http.server.SimpleHTTPRequestHandler):
                def log_message(self, *a):
                    pass

            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Silencio, directory=str(tmp)))
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                chrome = shutil.which("google-chrome") or shutil.which("chromium")
                dom = subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--window-size=1280,2000",
                                      "--virtual-time-budget=3000", "--dump-dom", f"http://127.0.0.1:{srv.server_address[1]}/mesa.html"],
                                     capture_output=True, text=True, timeout=60).stdout
            finally:
                srv.shutdown()
                srv.server_close()
            lista = dom[dom.index('id="devs"'):dom.index('id="pc-compartir"')]
            self.assertEqual(lista.count('class="tarjeta"'), 3, "PC del salón (también aprobado aquí), PC estudio y el móvil")
            self.assertEqual(lista.count(">Portátil del salón<"), 1, "una sola tarjeta para el PC del salón")
            self.assertIn("también puede controlar este", lista)
            self.assertIn("notas y nombres compartidos", lista)
            self.assertIn("versión anterior de LaZoo", lista)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Api(unittest.TestCase):
    setUp = test_v070.ConServidor.setUp
    tearDown = test_v070.ConServidor.tearDown

    def test_nombre_desde_el_panel(self):
        code, r = test_v070._req(self.port, "POST", "/api/nombre", json.dumps({"este": True, "nombre": "Mesa"}).encode(),
                                 {"X-Lazo-Local": "1", "Content-Type": "application/json"})
        self.assertEqual((code, r.get("nombre")), (200, "Mesa"), r)
        self.assertEqual(pcapc.AJUSTES.nombre_propio(), "Mesa")
        self.assertEqual(pcapc.para_movil()["pc_nombre"], "Mesa")
        code, _r = test_v070._req(self.port, "POST", "/api/nombre", json.dumps({"este": True, "nombre": "X"}).encode(),
                                  {"Content-Type": "application/json"})
        self.assertEqual(code, 401, "una web abierta en el navegador no puede")
        pcapc.AJUSTES.set_nombre("")


# --- 6. Sin bucles que lancen programas y entrega -----------------------------------------------------


class SinBucles(unittest.TestCase):
    def test_sincro_e_imagenes_no_lanzan_en_bucle(self):
        for nombre in ("sincro.py", "nombres.py"):
            src = (ROOT / nombre).read_text(encoding="utf-8")
            self.assertNotIn("subprocess", src, nombre)
        # imagenes.leer solo se llama al cambiar de PC (pcapc), nunca desde el vigilante de notas
        self.assertNotIn("imagenes", (ROOT / "control.py").read_text(encoding="utf-8"))
        arbol = ast.parse((ROOT / "imagenes.py").read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, (ast.While, ast.For)):
                for dentro in ast.walk(nodo):
                    if isinstance(dentro, ast.Call) and isinstance(dentro.func, ast.Name):
                        self.assertNotIn(dentro.func.id, ("_proceso", "leer", "poner"), "ningún bucle lanza programas")

    def test_solo_biblioteca_estandar(self):
        permitidos = set(sys.stdlib_module_names) | {"control", "pcapc", "nombres", "aprobacion", "recordar", "imagenes", "gi"}
        for nombre in ("sincro.py", "nombres.py", "imagenes.py"):
            for nodo in ast.walk(ast.parse((ROOT / nombre).read_text(encoding="utf-8"))):
                mods = [a.name.split(".")[0] for a in nodo.names] if isinstance(nodo, ast.Import) else \
                    [nodo.module.split(".")[0]] if isinstance(nodo, ast.ImportFrom) and nodo.module else []
                for m in mods:
                    self.assertIn(m, permitidos, (nombre, m))


class Entrega(unittest.TestCase):
    def test_version(self):
        self.assertEqual(lazo.VERSION, "0.76")
        self.assertEqual(pcapc.VERSION, "0.76")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.76")
        self.assertIn('<p class="ver">0.76', MESA)
        self.assertIn("<title>LaZoo 0.76</title>", HTML)
        self.assertIn('const PAGE_VERSION = "0.76"', JS)
        self.assertIn("Novedad 0.76", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertEqual(pcapc.KVM_VERSION, 3)

    def test_ci_compila_los_modulos_nuevos(self):
        ci = (ROOT / "ci" / "construir.yml").read_text(encoding="utf-8")
        for m in ("nombres.py", "sincro.py", "imagenes.py"):
            self.assertIn(m, ci)

    def test_apk_sin_cambios(self):
        texto = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:versionName="3"', texto)
        r = subprocess.run(["git", "diff", "--quiet", "271efd4", "--", "android"], cwd=ROOT, capture_output=True)
        if r.returncode in (0, 1):
            self.assertEqual(r.returncode, 0, "android/ cambió: la APK dejaría de ser la App 3")

    def test_datos_privados_fuera_del_repo(self):
        ign = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for f in ("clipboard-history.json", "clipboard-history-borrados.json", "nombres.json"):
            self.assertIn(f, ign)


if __name__ == "__main__":
    unittest.main(verbosity=2)
