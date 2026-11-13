"""Pruebas de la 0.71: tarjetas del Panel, «Renombrar», el ratón de Linux (uinput, XTest,
xdotool y ydotool según su versión, con diagnóstico), Linux como emisor (evdev con EVIOCGRAB y
X11) y el portapapeles al cambiar de PC. Sin hardware: dispositivos de mentira (tuberías) y, si
están, Xvfb y Chrome sin pantalla para lo de X11 y el render del Panel.
"""

from __future__ import annotations

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
from pathlib import Path

os.environ.setdefault("LAZO_DATOS", tempfile.mkdtemp())

import aprobacion  # noqa: E402
import bandeja  # noqa: E402
import bandeja_linux  # noqa: E402
import lazo  # noqa: E402
import linux_kvm as lk  # noqa: E402
import pcapc  # noqa: E402
import protocol  # noqa: E402
import recordar  # noqa: E402
from test_v070 import CapturaFalsa, Falso, _req, esperar  # noqa: E402

ROOT = Path(__file__).resolve().parent
MESA = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
LOCAL = {"Content-Type": "application/json", "X-Lazo-Local": "1"}


# --- 1. Panel: tarjetas ---------------------------------------------------------------------------


class PanelTarjetas(unittest.TestCase):
    def test_css_sin_columnas_de_un_caracter(self):
        self.assertNotIn("#pc-lista li { grid-template-columns", MESA, "la rejilla que partía la huella letra a letra")
        self.assertIn('<ul id="pc-lista" class="tarjetas">', MESA)
        self.assertIn('<ul id="devs" class="tarjetas">', MESA)
        css = MESA[MESA.index(".tarjetas {"):MESA.index("</style>")]
        self.assertIn("text-overflow: ellipsis", css)
        self.assertIn("white-space: nowrap", css)
        self.assertIn("min-width: 0", css)
        self.assertNotIn("anywhere", css)
        self.assertIn("flex-wrap: wrap", css)  # los botones bajan si no caben

    def test_nombres_con_textcontent(self):
        js = MESA[MESA.index("function tarjeta("):MESA.index("function tarjetaVacia(")]
        self.assertNotIn("innerHTML", js)
        self.assertIn("textContent = nombre", js)

    @unittest.skipUnless(shutil.which("google-chrome") or shutil.which("chromium"), "sin Chrome")
    def test_render_estrecho_y_ancho(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            subprocess.run([sys.executable, str(ROOT / "docs" / "panel_prueba.py"), str(ROOT), str(tmp)], check=True)
            import functools
            import http.server

            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Silencioso, directory=str(tmp)))
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            port = srv.server_address[1]
            try:
                chrome = shutil.which("google-chrome") or shutil.which("chromium")
                for ancho in (460, 1400):
                    dom = subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", f"--window-size={ancho},2600",
                                          "--virtual-time-budget=3000", "--dump-dom", f"http://127.0.0.1:{port}/mesa.html"],
                                         capture_output=True, text=True, timeout=60).stdout
                    import html as h
                    import re

                    m = re.search(r'data-medidas="([^"]*)"', dom)
                    self.assertIsNotNone(m, "el Panel no se pintó")
                    d = json.loads(h.unescape(m.group(1)))
                    self.assertEqual(d["tarjetas"], 4)
                    self.assertEqual(d["malos"], [], f"a {ancho} px")
                    for texto, w, _h in d["medidas"]:
                        if texto.startswith("huella") or ":8787" in texto:
                            self.assertGreater(w, 150, (ancho, texto, w))
            finally:
                srv.shutdown()
                srv.server_close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


import http.server  # noqa: E402


class _Silencioso(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


# --- 2. Renombrar ----------------------------------------------------------------------------------


class Renombrar(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = aprobacion.APODOS
        aprobacion.APODOS = aprobacion.Apodos(self.tmp)

    def tearDown(self):
        aprobacion.APODOS = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_validacion(self):
        L = aprobacion.limpiar_apodo
        self.assertEqual(L("  Portátil   del salón "), "Portátil del salón")
        self.assertEqual(L(""), "")
        self.assertEqual(L("x" * 40), "x" * 40)
        for malo in ("x" * 41, "<b>hola</b>", "a&b", 'di "hola"', "it's", "a\x00b", "tab\x07", "rtl\u202eabc", "`x`"):
            with self.assertRaises(ValueError, msg=repr(malo)):
                L(malo)

    def test_aprobados_con_nombre_propio(self):
        ap = aprobacion.Approvals()
        who = "ab" * 8
        ap.check(who, "Mozilla/5.0 (Linux; Android 14) Chrome/120 Mobile", "192.168.1.30")
        aprobacion.APODOS.poner(who, "Móvil de Ana")
        fila = ap.listing()[0]
        self.assertEqual((fila["label"], fila["apodo"], fila["tipo"]), ("Móvil de Ana", "Móvil de Ana", "Android · Chrome"))
        self.assertIn("Móvil de Ana", aprobacion.ask_text(who, ap.devices[who]), "el aviso de aprobación lo usa")
        self.assertEqual(ap.approved_rows(), [], "pendiente")
        ap.decide(who, True)
        self.assertEqual(ap.approved_rows()[0]["label"], "Android · Chrome", "lo que se guarda (Recordar) no cambia")
        # Se guarda en apodos.json y se vuelve a leer
        self.assertEqual(aprobacion.Apodos(self.tmp).get(who), "Móvil de Ana")
        aprobacion.APODOS.poner(who, "")
        self.assertEqual(ap.listing()[0]["label"], "Android · Chrome")
        with self.assertRaises(ValueError):
            aprobacion.APODOS.poner("no-es-un-id", "x")

    def test_pcs_renombrar(self):
        pcs = pcapc.PCs(self.tmp)
        pcs.guardar({"id": "c" * 16, "nombre": "DESKTOP-1", "host": "192.168.1.9", "puerto": 8787, "fp": "AAAA"}, b"k" * 32)
        r = pcs.renombrar("c" * 16, "Estudio")
        self.assertEqual((r["nombre"], r["apodo"], r["nombre_pc"]), ("Estudio", "Estudio", "DESKTOP-1"))
        self.assertIn("Estudio", bandeja.pc_label(pcs.listar()[0]), "el submenú de la bandeja lo usa")
        with self.assertRaises(pcapc.ErrorPC):
            pcs.renombrar("c" * 16, "<script>")
        with self.assertRaises(pcapc.ErrorPC):
            pcs.renombrar("d" * 16, "x")
        # Al volver a añadirlo (misma IP:puerto, id nuevo) conserva el nombre propio
        pcs.guardar({"id": "e" * 16, "nombre": "DESKTOP-1", "host": "192.168.1.9", "puerto": 8787, "fp": "BBBB"}, b"k" * 32)
        self.assertEqual([(p["id"], p["nombre"]) for p in pcs.listar()], [("e" * 16, "Estudio")])
        self.assertEqual(pcs.renombrar("e" * 16, "")["nombre"], "DESKTOP-1")


# --- 3. El ratón de Linux: método y sintaxis --------------------------------------------------------

AYUDA_1X = """Usage: mousemove [OPTION]... [-x <xpos> -y <ypos>] [-- <xpos> <ypos>]
Move mouse pointer or wheel.

Options:
  -w, --wheel                Move mouse wheel relatively
  -a, --absolute             Use absolute position, not applicable to wheel
  -x, --xpos                 X position
  -y, --ypos                 Y position
"""
AYUDA_01 = "Usage: mousemove [--delay <ms>] <x> <y>\n  --help                Show this help\n"


class InyeccionLinux(unittest.TestCase):
    def test_version_de_ydotool(self):
        self.assertEqual(lk.version_ydotool(AYUDA_1X), "1")
        self.assertEqual(lk.version_ydotool(AYUDA_01), "0.1")
        self.assertEqual(lk.version_ydotool("command not found"), "")

        class R:
            def __init__(self, out):
                self.stdout, self.stderr = out, ""

        saved = shutil.which
        try:
            lk.shutil.which = lambda n: "/usr/bin/" + n
            self.assertEqual(lk.detectar_ydotool(lambda cmd: R(AYUDA_01)), "0.1")
            self.assertEqual(lk.detectar_ydotool(lambda cmd: R(AYUDA_1X)), "1")
        finally:
            lk.shutil.which = saved

    def test_ordenes_por_version(self):
        o = lk.orden_ydotool
        self.assertEqual(o("1", "mover", -5, 3), ["mousemove", "-x", "-5", "-y", "3"])  # 1.x: relativo
        self.assertNotIn("-a", o("1", "mover", 1, 1))
        self.assertNotIn("--absolute", o("1", "mover", 1, 1))
        self.assertEqual(o("1", "boton", 1, True), ["click", "0x40"])
        self.assertEqual(o("1", "boton", 2, False), ["click", "0x81"])
        self.assertEqual(o("1", "tecla", 30, True), ["key", "30:1"])
        self.assertEqual(o("1", "rueda", 0, -2), ["mousemove", "-w", "-x", "0", "-y", "-2"])
        # 0.1.x: `mousemove X Y` es ABSOLUTO (esquina + X,Y): nunca se usa; el relativo lleva `--`
        mov = o("0.1", "mover", -5, 3)
        self.assertEqual(mov[0], "mousemove_relative")
        self.assertEqual(mov[-3:], ["--", "-5", "3"])
        self.assertIn("--delay", mov)
        self.assertEqual(o("0.1", "boton", 2, True), ["click", "--delay", "0", "2"])
        for cosa in (("boton", 1, False), ("tecla", 30, True), ("rueda", 0, 1)):
            self.assertIsNone(o("0.1", *cosa))
        self.assertIsNone(o("", "mover", 1, 1))

    def test_xdotool_con_negativos(self):
        self.assertEqual(lk.orden_xdotool("mover", -7, -2), ["xdotool", "mousemove_relative", "--", "-7", "-2"])
        self.assertEqual(lk.orden_xdotool("boton", 2, True), ["xdotool", "mousedown", "3"])
        self.assertEqual(lk.orden_xdotool("rueda", 5, 2), ["xdotool", "click", "--repeat", "2", "5"])

    def test_ydotool_hace_lo_que_dice_su_version(self):
        hechos = []

        class Base:
            def ydo(self, *a):
                hechos.append(a)

        i = lk.InyectorYdotool("0.1", Base())
        i.mover(10, -4)
        i.boton(1, True)
        i.boton(1, False)
        i.tecla(0x41, 0x1E, False, True)
        self.assertEqual(hechos, [("mousemove_relative", "--delay", "0", "--", "10", "-4"), ("click", "--delay", "0", "1")])

    def test_cadena_de_metodos(self):
        e = lk.elegir_receptor
        self.assertEqual(e("x11", True, True, "", False, True)[0], "xtest", "Xorg: XTest primero (sin permisos)")
        self.assertEqual(e("x11", True, False, "", False, True)[0], "uinput")
        self.assertEqual(e("x11", False, False, "", False, True)[0], "xdotool")
        self.assertEqual(e("wayland", True, True, "1", True, True)[0], "uinput", "Wayland: uinput primero")
        self.assertEqual(e("wayland", False, True, "1", True, True)[0], "ydotool")
        self.assertIn("SOLO mover y clic", e("wayland", False, True, "0.1", True, True)[1])
        metodo, por = e("wayland", False, True, "", False, True)
        self.assertEqual(metodo, "", "en Wayland NUNCA XTest: movería un puntero invisible")
        self.assertIn("Arreglar", por)
        self.assertEqual(lk.elegir_emisor("x11", 5, True)[0], "x11", "Xorg: X11 primero (sin el grupo input)")
        self.assertEqual(lk.elegir_emisor("x11", 5, False)[0], "evdev")
        self.assertEqual(lk.elegir_emisor("wayland", 3, True)[0], "evdev")
        self.assertEqual(lk.elegir_emisor("wayland", 0, True)[0], "")

    def test_wayland_sin_permisos_lo_dice(self):
        saved = (dict(os.environ), lk.uinput_escribible, lk.detectar_ydotool)
        try:
            os.environ.pop("DISPLAY", None)
            os.environ["WAYLAND_DISPLAY"] = "wayland-0"
            lk.uinput_escribible = lambda ruta="/dev/uinput": False
            lk.detectar_ydotool = lambda run=None: ""
            with self.assertRaises(pcapc.ErrorPC) as cm:
                lk.inyector_linux()
            self.assertIn("instalar-linux.sh --pcapc", str(cm.exception))
            d = lk.diagnostico()
            self.assertEqual(d["receptor"], "ninguno")
            self.assertTrue(d["arreglable"])
            self.assertTrue(lk.falta(d))
            self.assertIn("Que otro PC controle este: ninguno", lk.texto_diagnostico(d))
        finally:
            os.environ.clear()
            os.environ.update(saved[0])
            lk.uinput_escribible, lk.detectar_ydotool = saved[1], saved[2]

    def test_diagnostico_por_terminal(self):
        out = subprocess.run([sys.executable, str(ROOT / "linux_kvm.py"), "--diagnostico"], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0)
        self.assertIn("Que otro PC controle este:", out.stdout)
        self.assertIn("Controlar otro PC desde este:", out.stdout)

    def test_arreglar_con_pkexec(self):
        llamadas = []
        r = lk.arreglar(popen=lambda cmd, **kw: llamadas.append(cmd), which=lambda n: "/usr/bin/pkexec")
        self.assertTrue(r["ok"])
        self.assertEqual(llamadas[0][:3], ["pkexec", "sh", str(ROOT / "instalar-linux.sh")])
        self.assertEqual(llamadas[0][3], "--permisos-root")
        r = lk.arreglar(popen=lambda cmd, **kw: llamadas.append(cmd), which=lambda n: None)
        self.assertFalse(r["ok"])
        self.assertIn("--pcapc", r["mensaje"])
        script = (ROOT / "instalar-linux.sh").read_text(encoding="utf-8")
        self.assertIn("--permisos-root", script)
        self.assertIn('usermod -aG uinput,input "$U"', script)
        self.assertIn("80-lazoo-uinput.rules", script)

    def test_uinput_relativo_de_verdad(self):
        llamadas, escrito = [], []
        i = lk.InyectorUinput(ioctl=lambda fd, req, arg=0: llamadas.append((req, arg)), abrir=lambda r, f: 99,
                              escribir=lambda fd, b: escrito.append(b) or len(b), esperar=0)
        reqs = [r for r, _ in llamadas]
        self.assertIn(lk.UI_DEV_CREATE, reqs)
        self.assertIn((lk.UI_SET_RELBIT, lk.REL_X), llamadas)
        self.assertIn((lk.UI_SET_KEYBIT, lk.BTN_LEFT), llamadas)
        self.assertIn((lk.UI_SET_KEYBIT, 30), llamadas)
        self.assertNotIn(3, [a for r, a in llamadas if r == lk.UI_SET_EVBIT], "sin ejes absolutos: nada de esquinas")

        def eventos(b):
            return [lk.EVENTO.unpack_from(b, k)[2:] for k in range(0, len(b), lk.EVENTO.size)]

        escrito.clear()
        i.mover(-7, 4)
        self.assertEqual(eventos(escrito[-1]), [(lk.EV_REL, lk.REL_X, -7), (lk.EV_REL, lk.REL_Y, 4), (0, 0, 0)])
        i.boton(2, True)
        self.assertEqual(eventos(escrito[-1])[0], (lk.EV_KEY, lk.BTN_RIGHT, 1))
        i.rueda(0, 60)
        self.assertEqual(eventos(escrito[-1])[:-1], [(lk.EV_REL, lk.REL_WHEEL_HI_RES, 60)])
        i.rueda(0, 60)
        self.assertEqual(eventos(escrito[-1])[:-1], [(lk.EV_REL, lk.REL_WHEEL_HI_RES, 60), (lk.EV_REL, lk.REL_WHEEL, 1)])
        i.tecla(0, 0x1E, False, True)
        self.assertEqual(eventos(escrito[-1])[0], (lk.EV_KEY, 30, 1))
        i.tecla(0, 0x48, True, False)  # flecha arriba (extendida)
        self.assertEqual(eventos(escrito[-1])[0], (lk.EV_KEY, 103, 0))

    @unittest.skipUnless(shutil.which("Xvfb") and shutil.which("xdotool"), "sin Xvfb")
    def test_xtest_relativo_en_xorg(self):
        with Xvfb() as disp:
            os.environ["DISPLAY"] = disp
            i = pcapc.InyectorX11()
            subprocess.run(["xdotool", "mousemove", "100", "100"], check=True)
            for _ in range(10):
                i.mover(7, -3)
            time.sleep(0.2)
            pos = subprocess.run(["xdotool", "getmouselocation"], capture_output=True, text=True).stdout
            self.assertTrue(pos.startswith("x:170 y:70"), pos)


class Xvfb:
    """Una pantalla X de mentira, propia (nunca la del escritorio de quien prueba)."""

    def __enter__(self):
        self.antes = os.environ.get("DISPLAY")
        for n in range(91, 140):
            if not os.path.exists(f"/tmp/.X11-unix/X{n}") and not os.path.exists(f"/tmp/.X{n}-lock"):
                break
        self.proc = subprocess.Popen(["Xvfb", f":{n}", "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        esperar(lambda: os.path.exists(f"/tmp/.X11-unix/X{n}"), 5)
        time.sleep(0.2)
        return f":{n}"

    def __exit__(self, *a):
        self.proc.terminate()
        self.proc.wait(5)
        if self.antes is None:
            os.environ.pop("DISPLAY", None)
        else:
            os.environ["DISPLAY"] = self.antes


# --- 4. Linux como emisor --------------------------------------------------------------------------


class Teclas(unittest.TestCase):
    def test_evdev_a_scancode(self):
        w = lk.windows_de_evdev
        self.assertEqual(w(30), (0x41, 0x1E, False))       # A
        self.assertEqual(w(1), (0x1B, 0x01, False))        # Esc
        self.assertEqual(w(29), (0xA2, 0x1D, False))       # Ctrl izq.
        self.assertEqual(w(97), (0xA3, 0x1D, True))        # Ctrl der.
        self.assertEqual(w(100), (0xA5, 0x38, True))       # AltGr
        self.assertEqual(w(103), (0x26, 0x48, True))       # flecha arriba
        self.assertEqual(w(125), (0x5B, 0x5B, True))       # Win
        self.assertEqual(w(69), (0x90, 0x45, True))        # Bloq Num
        self.assertEqual(w(119), (0x13, 0x45, False))      # Pausa
        self.assertEqual(w(86)[1:], (0x56, False))         # < > de los teclados españoles
        self.assertEqual(w(164), (0xB3, 0x22, True))       # play/pausa
        self.assertIsNone(w(0x110))                        # un botón no es una tecla

    def test_ida_y_vuelta_con_el_receptor_de_linux(self):
        for code in list(range(1, 89)) + [96, 97, 98, 99, 100, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 113, 114, 115, 119, 125, 126, 127, 163, 164, 165]:
            vk, scan, ext = lk.windows_de_evdev(code)
            self.assertEqual(pcapc.evdev(vk, scan, ext), code, code)

    def test_tecla_rapida(self):
        self.assertEqual(lk.evdev_de_vk(ord("L")), 38)
        self.assertEqual(lk.evdev_de_vk(ord("Q")), 16)
        self.assertEqual(lk.evdev_de_vk(ord("1")), 2)
        self.assertEqual(lk.evdev_de_vk(ord("0")), 11)
        self.assertEqual(lk.evdev_de_vk(0x70), 59)
        self.assertEqual(lk.evdev_de_vk(0x7B), 88)


class Sink:
    """Hace de Control para la captura."""

    def __init__(self):
        self.ev, self.pedidos, self.vivo_ok = [], [], True

    def pedir(self, o):
        self.pedidos.append(o)

    def vivo(self):
        return self.vivo_ok

    def mover(self, dx, dy):
        self.ev.append(("m", dx, dy))

    def boton(self, b, a):
        self.ev.append(("b", b, a))

    def rueda(self, e, d):
        self.ev.append(("r", e, d))

    def tecla(self, vk, scan, ext, abajo):
        self.ev.append(("t", vk, scan, ext, abajo))


class DispositivosFalsos:
    """Un teclado y un ratón hechos con tuberías; el ioctl apunta los EVIOCGRAB."""

    def __init__(self):
        self.pipes = {"/dev/input/event0": os.pipe(), "/dev/input/event1": os.pipe()}
        for r, _w in self.pipes.values():
            os.set_blocking(r, False)
        self.grabs = []
        self.pulsado = False

    def rutas(self):
        return sorted(self.pipes)

    def abrir(self, ruta):
        return os.dup(self.pipes[ruta][0])

    def ioctl(self, fd, req, arg=0):
        if req == lk.EVIOCGRAB:
            self.grabs.append(arg)
            return 0
        if req == lk.EVIOCGKEY(96):
            b = bytearray(96)
            if self.pulsado:
                b[29 // 8] |= 1 << (29 % 8)
            return bytes(b)
        raise OSError("no")

    def clasificar(self, fd, ruta, ioctl):
        teclado = ruta.endswith("0")
        return lk.Dispositivo(fd, ruta, "falso", teclado, not teclado, False, hires=False)

    def mandar(self, ruta, *eventos):
        w = self.pipes[ruta][1]
        os.write(w, b"".join(lk.EVENTO.pack(0, 0, *e) for e in eventos) + lk.EVENTO.pack(0, 0, 0, 0, 0))

    def tecla(self, code, valor):
        self.mandar("/dev/input/event0", (lk.EV_KEY, code, valor))

    def cerrar(self):
        for r, w in self.pipes.values():
            os.close(r)
            os.close(w)


class EmisorEvdev(unittest.TestCase):
    def setUp(self):
        self.f = DispositivosFalsos()
        self.sink = Sink()
        self.cap = lk.CapturaEvdev(self.sink, rutas=self.f.rutas, abrir=self.f.abrir, ioctl=self.f.ioctl,
                                   clasificar_fn=self.f.clasificar)
        mods, vk, _ = pcapc.leer_tecla("Ctrl+Alt+L")
        self.cap.trad.configurar(mods, lk.evdev_de_vk(vk))
        self.cap.escanear()

    def tearDown(self):
        self.cap._fin = True
        self.cap.cerrar()
        self.f.cerrar()

    def vueltas(self, n=3):
        for _ in range(n):
            self.cap.paso(0.01)

    def entrar(self):
        self.assertTrue(self.cap.empezar(self.sink))
        self.vueltas()
        self.assertTrue(self.cap.cogido)

    def test_tecla_rapida_libre_no_coge_nada(self):
        for code in (29, 56, 38):
            self.f.tecla(code, 1)
        for code in (38, 56, 29):
            self.f.tecla(code, 0)
        self.vueltas()
        self.assertEqual(self.sink.pedidos, ["alternar"])
        self.assertEqual(self.f.grabs, [], "libre: el escritorio lo recibe todo")
        self.assertEqual(self.sink.ev, [])

    def test_espera_a_que_sueltes_antes_de_coger(self):
        self.f.pulsado = True  # aún tienes el Ctrl de la tecla rápida pulsado
        self.cap.empezar(self.sink)
        self.vueltas()
        self.assertFalse(self.cap.cogido)
        self.f.pulsado = False
        self.vueltas()
        self.assertTrue(self.cap.cogido)
        self.assertEqual(self.f.grabs, [1, 1])

    def test_manda_teclas_raton_y_rueda(self):
        self.entrar()
        self.f.tecla(30, 1)
        self.f.tecla(30, 2)
        self.f.tecla(30, 0)
        self.vueltas()  # cada dispositivo es un fd: el orden entre dos fds no está garantizado
        self.f.mandar("/dev/input/event1", (lk.EV_REL, lk.REL_X, 5), (lk.EV_REL, lk.REL_Y, -3))
        self.f.mandar("/dev/input/event1", (lk.EV_KEY, lk.BTN_LEFT, 1))
        self.f.mandar("/dev/input/event1", (lk.EV_KEY, lk.BTN_LEFT, 0))
        self.f.mandar("/dev/input/event1", (lk.EV_REL, lk.REL_WHEEL, -1))
        self.vueltas()
        self.assertEqual(self.sink.ev, [("t", 0x41, 0x1E, False, True), ("t", 0x41, 0x1E, False, True),
                                        ("t", 0x41, 0x1E, False, False), ("m", 5, -3), ("b", 1, True), ("b", 1, False),
                                        ("r", 0, -120)])

    def test_emergencia_suelta_el_grab_al_momento(self):
        self.entrar()
        for code in (29, 56, 1):
            self.f.tecla(code, 1)
        self.cap.paso(0.01)
        self.assertFalse(self.cap.cogido, "Ctrl+Alt+Esc suelta en el mismo hilo que lee")
        self.assertEqual(self.f.grabs[-2:], [0, 0])
        self.assertEqual(self.sink.pedidos, ["emergencia"])
        self.assertNotIn(("t", 0x1B, 0x01, False, True), self.sink.ev, "el Esc no llega al otro PC")

    def test_tecla_rapida_para_volver(self):
        self.entrar()
        for code in (29, 56, 38):
            self.f.tecla(code, 1)
        self.cap.paso(0.01)
        self.assertFalse(self.cap.cogido)
        self.assertEqual(self.sink.pedidos, ["alternar"])
        self.assertNotIn(38, [e[2] for e in self.sink.ev if e[0] == "t"], "la L no se manda")

    def test_sin_latido_suelta(self):
        self.entrar()
        self.sink.vivo_ok = False
        self.cap.paso(0.01)
        self.assertFalse(self.cap.cogido)
        self.assertEqual(self.sink.pedidos, ["parar"])

    def test_parar_desde_otro_hilo_y_al_cerrar(self):
        self.entrar()
        t = threading.Thread(target=self.cap.parar)
        t.start()
        t.join(2)
        self.assertFalse(self.cap.cogido)
        self.assertEqual(self.f.grabs[-2:], [0, 0])
        self.entrar()
        self.cap._hilo = None
        hilo = threading.Thread(target=self.cap._bucle)
        self.cap._fin = True  # el bucle sale enseguida...
        hilo.start()
        hilo.join(2)
        self.assertFalse(self.cap.cogido, "...y SIEMPRE suelta al salir")

    def test_touchpad_dos_dedos_es_rueda(self):
        t = lk.Traductor()
        s = Sink()
        t.empezar(s)
        pad = lk.Dispositivo(0, "x", "pad", False, False, True, res=(10.0, 10.0))
        for tipo, code, v in ((lk.EV_KEY, lk.BTN_TOUCH, 1), (lk.EV_KEY, lk.BTN_TOOL_FINGER, 1), (lk.EV_ABS, 0, 100), (lk.EV_ABS, 1, 100), (0, 0, 0),
                              (lk.EV_ABS, 0, 150), (0, 0, 0)):
            t.evento(pad, tipo, code, v)
        self.assertEqual(s.ev, [("m", 40, 0)])  # 5 mm a 8 px/mm
        s.ev.clear()
        for tipo, code, v in ((lk.EV_KEY, lk.BTN_TOOL_FINGER, 0), (lk.EV_KEY, lk.BTN_TOOL_DOUBLETAP, 1), (0, 0, 0),
                              (lk.EV_ABS, 1, 0), (0, 0, 0)):
            t.evento(pad, tipo, code, v)
        self.assertEqual(s.ev, [("r", 0, -120)])  # 10 mm hacia arriba con dos dedos
        t.evento(pad, lk.EV_KEY, lk.BTN_LEFT, 1)
        self.assertEqual(s.ev[-1], ("b", 2, True), "clic con dos dedos = derecho")
        t.evento(pad, lk.EV_KEY, lk.BTN_LEFT, 0)
        self.assertEqual(s.ev[-1], ("b", 2, False))

    def test_raton_de_alta_resolucion_sin_doble_rueda(self):
        t = lk.Traductor()
        s = Sink()
        t.empezar(s)
        raton = lk.Dispositivo(0, "x", "r", False, True, False, hires=True)
        t.evento(raton, lk.EV_REL, lk.REL_WHEEL_HI_RES, 60)
        t.evento(raton, lk.EV_REL, lk.REL_WHEEL, 1)
        self.assertEqual(s.ev, [("r", 0, 60)])


@unittest.skipUnless(shutil.which("Xvfb") and shutil.which("xdotool"), "sin Xvfb")
class EmisorX11(unittest.TestCase):
    def test_coge_y_suelta_en_xorg(self):
        with Xvfb() as disp:
            os.environ["DISPLAY"] = disp
            X = lambda *a: subprocess.run(["xdotool", *a], check=True)  # noqa: E731
            s = Sink()
            cap = lk.CapturaX11(s)
            mods, vk, _ = pcapc.leer_tecla("Ctrl+Alt+L")
            self.assertTrue(cap.registrar(mods, vk))
            X("key", "ctrl+alt+l")
            self.assertTrue(esperar(lambda: s.pedidos == ["alternar"]))
            self.assertTrue(cap.empezar(s))
            X("mousemove_relative", "--", "15", "-4")
            X("click", "1")
            X("click", "4")
            X("key", "a")
            self.assertTrue(esperar(lambda: ("t", 0x41, 0x1E, False, False) in s.ev))
            self.assertIn(("m", 15, -4), s.ev)
            self.assertIn(("b", 1, True), s.ev)
            self.assertIn(("r", 0, 120), s.ev)
            X("key", "ctrl+alt+Escape")
            self.assertTrue(esperar(lambda: "emergencia" in s.pedidos))
            self.assertTrue(esperar(lambda: not cap.cogido))
            cap.parar()
            cap._fin = True
            cap._hilo.join(3)  # antes de cerrar la pantalla de mentira
            self.assertFalse(cap._hilo.is_alive())


# --- 5. Portapapeles -------------------------------------------------------------------------------


class PortapapelesMensajes(unittest.TestCase):
    def test_trozos_y_juntar(self):
        texto = "ñandú «hola» 🙂 " * 5000  # > 32 KB: varios trozos
        trozos = pcapc.trozos_porta(7, texto)
        self.assertGreater(len(trozos), 2)
        j = pcapc.Juntar()
        res = None
        for n, tr in enumerate(trozos, 1):
            numero, evs = pcapc.decodificar(pcapc.codificar_porta(n, *tr))
            self.assertEqual(numero, n)
            res = j.trozo(*evs[0][1:])
        self.assertEqual(res, texto)
        self.assertEqual(pcapc.trozos_porta(1, ""), [(1, 0, 0, b"")])
        self.assertEqual(pcapc.trozos_porta(1, "x" * (pcapc.MAX_PORTA + 1)), [(1, 0, 0, b"")], "más de 1 MB no se manda")
        self.assertEqual(j.trozo(1, 0, 0, b""), "")

    def test_rechaza_lo_raro(self):
        for malo in (pcapc.codificar_porta(1, 1, pcapc.MAX_PORTA + 1, 0, b"x"), pcapc.codificar_porta(1, 1, 3, 2, b"xx"),
                     pcapc.codificar_porta(1, 1, 0, 0, b"x"), b"P1" + b"\0" * 5):
            with self.assertRaises(protocol.ProtocolError):
                pcapc.decodificar(malo)
        j = pcapc.Juntar()
        self.assertIsNone(j.trozo(1, 10, 5, b"xxxxx"), "un trozo fuera de orden se descarta")

    def test_pide_portapapeles_en_k1(self):
        n, evs = pcapc.decodificar(pcapc.codificar(3, [(pcapc.PIDE_PORTA, 9)]))
        self.assertEqual(evs, [(pcapc.PIDE_PORTA, 9)])

    def test_ws_send_tramas_largas(self):
        a, b = socket.socketpair()
        try:
            for n in (10, 300, 70000):
                protocol.ws_send(a, 0x2, b"z" * n)
                self.assertEqual(_leer_servidor(b), (0x2, b"z" * n))
        finally:
            a.close()
            b.close()

    def test_ajuste_encendido_de_serie_y_guardado(self):
        tmp = tempfile.mkdtemp()
        saved = os.environ.get("LAZO_DATOS")
        os.environ["LAZO_DATOS"] = tmp
        try:
            a = pcapc.Ajustes().cargar()
            self.assertTrue(a.portapapeles)
            a.set_portapapeles(False)
            self.assertFalse(pcapc.Ajustes().cargar().portapapeles)
        finally:
            os.environ["LAZO_DATOS"] = saved or ""
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_va_al_historial(self):
        import control

        llamadas = []
        saved = (control._mark_injected, control._write_clipboard_text)
        control._mark_injected = lambda t=None: llamadas.append(("marca", t))
        control._write_clipboard_text = lambda t: llamadas.append(("pon", t)) or True
        try:
            self.assertTrue(pcapc.poner_portapapeles("a\r\nb"))
        finally:
            control._mark_injected, control._write_clipboard_text = saved
        esperado = "a\r\nb" if sys.platform == "win32" else "a\nb"
        self.assertEqual(llamadas, [("marca", esperado), ("pon", esperado)], "marcado como de LaZoo: el historial no lo apunta")
        src = (ROOT / "pcapc.py").read_text(encoding="utf-8")
        self.assertNotIn("clipboard-history", src)


def _leer_servidor(sock):
    """ws_read espera tramas enmascaradas (del cliente): esto lee una sin máscara (del servidor)."""
    def leer(n):
        b = b""
        while len(b) < n:
            b += sock.recv(n - len(b))
        return b

    h = leer(2)
    n = h[1] & 0x7F
    if n == 126:
        n = int.from_bytes(leer(2), "big")
    elif n == 127:
        n = int.from_bytes(leer(8), "big")
    return h[0] & 0x0F, leer(n)


import test_v070  # noqa: E402


class ConServidor(unittest.TestCase):
    setUp = test_v070.ConServidor.setUp
    tearDown = test_v070.ConServidor.tearDown
    emparejar = test_v070.ConServidor.emparejar
    control = test_v070.ConServidor.control

    def preparar_porta(self, del_receptor="del otro PC ñ"):
        self.puesto_receptor, self.puesto_emisor = [], []
        self.saved_porta = (pcapc.RECEPCION.porta_leer, pcapc.RECEPCION.porta_poner, pcapc.AJUSTES.portapapeles)
        pcapc.RECEPCION.porta_leer = lambda: del_receptor
        pcapc.RECEPCION.porta_poner = self.puesto_receptor.append
        self.addCleanup(self.deshacer_porta)

    def deshacer_porta(self):
        pcapc.RECEPCION.porta_leer, pcapc.RECEPCION.porta_poner, pcapc.AJUSTES.portapapeles = self.saved_porta

    def iniciar(self, del_emisor):
        who, _ = self.emparejar()
        ctl = pcapc.Control(self.pcs, fabrica=CapturaFalsa)
        ctl.porta_leer = lambda: del_emisor
        ctl.porta_poner = self.puesto_emisor.append
        ctl.iniciar(who)
        return ctl

    def test_portapapeles_va_y_vuelve(self):
        self.preparar_porta("copiado ALLÍ")
        largo = "copiado aquí " + "x" * 70000  # varios trozos
        ctl = self.iniciar(largo)
        self.assertTrue(esperar(lambda: self.puesto_receptor == [largo]), "al entrar, el texto de este PC va al otro")
        ctl.alternar()  # la tecla rápida para volver
        self.assertEqual(ctl.estado, "libre")
        self.assertEqual(self.puesto_emisor, ["copiado ALLÍ"], "al volver, el del otro PC vuelve a este")
        self.assertFalse(ctl.captura.activa)

    def test_sin_texto_no_espera(self):
        self.preparar_porta("")
        ctl = self.iniciar("")
        t = time.monotonic()
        ctl.alternar()
        self.assertLess(time.monotonic() - t, 1.0, "«no hay nada» llega enseguida")
        self.assertEqual((self.puesto_emisor, self.puesto_receptor), ([], []))

    def test_interruptor_apagado(self):
        self.preparar_porta("secreto")
        pcapc.AJUSTES.portapapeles = False
        ctl = self.iniciar("otro secreto")
        time.sleep(0.3)
        t = time.monotonic()
        ctl.alternar()
        self.assertLess(time.monotonic() - t, 0.5)
        self.assertEqual((self.puesto_emisor, self.puesto_receptor), ([], []))

    def test_emergencia_no_espera_el_portapapeles(self):
        self.preparar_porta("x")
        ctl = self.iniciar("")
        t = time.monotonic()
        ctl.parar("emergencia")
        self.assertLess(time.monotonic() - t, 0.5)
        self.assertEqual(self.puesto_emisor, [])

    def test_receptor_sin_compartir_no_pone_nada(self):
        r = pcapc.Receptor(Falso(), porta_poner=None)
        r.tratar(pcapc.codificar_porta(1, 1, 4, 0, b"hola"))
        self.assertEqual(r.juntar.ident, -1)

    def test_api_renombrar(self):
        aprobacion_saved = aprobacion.APODOS
        aprobacion.APODOS = aprobacion.Apodos(self.tmp)
        try:
            who, _ = self.emparejar()
            code, data = _req(self.port, "POST", "/api/dispositivos/renombrar", json.dumps({"id": who, "nombre": "PC del salón"}).encode(), LOCAL)
            self.assertEqual((code, data["apodo"]), (200, "PC del salón"))
            self.assertEqual(next(d for d in lazo.APPROVALS.listing() if d["id"] == who)["label"], "PC del salón")
            code, data = _req(self.port, "POST", "/api/dispositivos/renombrar", json.dumps({"id": who, "nombre": "<img src=x>"}).encode(), LOCAL)
            self.assertEqual(code, 400)
            code, _ = _req(self.port, "POST", "/api/dispositivos/renombrar", json.dumps({"id": "f" * 16, "nombre": "x"}).encode(), LOCAL)
            self.assertEqual(code, 400)
            pid = self.pcs.listar()[0]["id"]
            saved = pcapc.PCS
            pcapc.PCS = self.pcs
            try:
                code, data = _req(self.port, "POST", "/api/pcapc/renombrar", json.dumps({"id": pid, "nombre": "Estudio"}).encode(), LOCAL)
                self.assertEqual(code, 200)
                self.assertEqual(data["pcs"][0]["nombre"], "Estudio")
                code, data = _req(self.port, "POST", "/api/pcapc/renombrar", json.dumps({"id": pid, "nombre": "x" * 41}).encode(), LOCAL)
                self.assertEqual(code, 400)
                code, data = _req(self.port, "POST", "/api/pcapc/portapapeles", json.dumps({"on": False}).encode(), LOCAL)
                self.assertFalse(data["portapapeles"])
                code, data = _req(self.port, "POST", "/api/pcapc/portapapeles", json.dumps({"on": True}).encode(), LOCAL)
                self.assertTrue(data["portapapeles"])
            finally:
                pcapc.PCS = saved
            saved_lb = lazo.Handler._loopback
            lazo.Handler._loopback = lambda self: False
            try:
                for ruta in ("/api/dispositivos/renombrar", "/api/pcapc/renombrar", "/api/pcapc/arreglar", "/api/pcapc/portapapeles"):
                    code, _ = _req(self.port, "POST", ruta, json.dumps({"id": who, "nombre": "x"}).encode(), LOCAL)
                    self.assertEqual(code, 403, ruta)
            finally:
                lazo.Handler._loopback = saved_lb
        finally:
            aprobacion.APODOS = aprobacion_saved

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux")
    def test_api_arreglar_y_diagnostico(self):
        saved = lk.arreglar
        lk.arreglar = lambda: {"ok": True, "mensaje": "Escribe tu contraseña"}
        try:
            code, data = _req(self.port, "POST", "/api/pcapc/arreglar", b"{}", LOCAL)
            self.assertEqual(code, 200)
            self.assertEqual(data["arreglo"]["mensaje"], "Escribe tu contraseña")
            self.assertIn("Que otro PC controle este", data["diagnostico"])
            self.assertIn("falta", data)
        finally:
            lk.arreglar = saved


class Ventanas(unittest.TestCase):
    def test_centro_medido_con_el_gancho(self):
        src = (ROOT / "pcapc.py").read_text(encoding="utf-8")
        self.assertIn("SetThreadDpiAwarenessContext", src)
        self.assertIn("CALIBRA", src)
        self.assertIn("extra=CALIBRA", src)

    def test_teclas_de_linux_con_vk_cero_no_se_pisan(self):
        f = Falso()
        r = pcapc.Receptor(f)
        r.tratar(pcapc.codificar(1, [(pcapc.TECLA, 0, 0x1E, 2), (pcapc.TECLA, 0, 0x30, 2)]))
        r.tratar(pcapc.codificar(2, [(pcapc.TECLA, 0, 0x1E, 0), (pcapc.TECLA, 0, 0x30, 0)]))
        self.assertEqual([h for h in f.ver() if not h[4]], [("tecla", 0, 0x1E, False, False), ("tecla", 0, 0x30, False, False)])


class BandejaLinux(unittest.TestCase):
    def test_menu_con_nombre_propio(self):
        pcs = [{"id": "a" * 16, "nombre": "Estudio", "host": "192.168.1.9", "puerto": 8787}]
        items = bandeja_linux.menu_items([], False, False, pcs, {"estado": "libre", "id": ""}, True, "Ctrl+Alt+L")
        sub = next(i for i in items if i[0] == "sub" and i[1] == "Controlar otro PC")
        self.assertTrue(any("Estudio" in str(x) for x in sub[2]))


class Entrega(unittest.TestCase):
    def test_version(self):
        self.assertEqual(lazo.VERSION, "0.72")
        self.assertEqual(pcapc.VERSION, "0.72")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.72")
        self.assertIn('<p class="ver">0.72', MESA)
        for ident in ('id="pc-porta"', 'id="pc-arreglar"', 'id="pc-diag"', "/api/dispositivos/renombrar"):
            self.assertIn(ident, MESA)

    def test_apk_sin_cambios(self):
        manifest = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:versionCode="66"', manifest)

    def test_solo_biblioteca_estandar(self):
        import ast

        permitidos = set(sys.stdlib_module_names) | {"pcapc", "linux_kvm", "control", "ydo", "aprobacion", "recordar", "protocol"}
        for nombre in ("linux_kvm.py", "pcapc.py"):
            arbol = ast.parse((ROOT / nombre).read_text(encoding="utf-8"))
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.Import):
                    mods = [a.name.split(".")[0] for a in nodo.names]
                elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                    mods = [nodo.module.split(".")[0]]
                else:
                    continue
                for m in mods:
                    self.assertIn(m, permitidos, (nombre, m))


if __name__ == "__main__":
    unittest.main()
