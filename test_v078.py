"""Pruebas de la 0.78: arreglos de la revisión de «PC a PC» (0.70–0.77) antes de la Beta 1.

    python3 test_v078.py

Cada clase reproduce un fallo de la revisión: con el código de la 0.77 falla, con la 0.78 pasa.

1. SinSello: `pcapc.peticion` aceptaba un 200 en claro y sincro lo fusionaba. Cualquier equipo de
   la red que contestara en la IP:puerto del otro PC podía vaciar las notas o meter notas falsas.
2. RelojAdelantado: un «vaciado», una lápida o una nota de hasta 24 h en el futuro se aceptaban:
   un «Borrar todo» hecho con el reloj adelantado borraba las notas de todos los PCs durante horas.
3. SincroNoInsiste: si las notas de dos PCs no llegaban a coincidir, se sincronizaba 3 veces por
   segundo para siempre.
4. DespedidaConPlazo: con la red caída a media imagen, `Control.parar` se quedaba colgado en la
   despedida (y con él la tecla rápida y la de emergencia).
5. DosEmisores: dos conexiones `/kvm` usaban a la vez el mismo inyector (Xlib no lo aguanta).
6. PermisosLinux: «Arreglar» y `--permisos-root` metían siempre al usuario en el grupo «input»
   (cualquier programa suyo puede leer el teclado) sin avisar en el Panel.
7. PegarSinArgumento: `wl-copy` recibía el texto escrito desde el móvil como argumento (se ve en ps).
8. Compatibilidad: un PC 0.70–0.75 de verdad contesta su 404 SELLADO con otra clave: salía como
   «error» cada 30 s con un mensaje raro en vez de «actualízalo» cada 10 min. Un 0.67 decía «no está».
   Con los relojes distintos, el motivo de la sincronización llegaba ilegible. Y entrega: versión 0.78.
"""
from __future__ import annotations

import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

os.environ.setdefault("LAZO_DATOS", tempfile.mkdtemp())

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import control  # noqa: E402
import lazo  # noqa: E402
import linux_kvm  # noqa: E402
import pcapc  # noqa: E402
import protocol  # noqa: E402
import sincro  # noqa: E402
import test_v070  # noqa: E402
import ydo  # noqa: E402

DESPEDIDA = getattr(pcapc, "DESPEDIDA", 1.0)        # con getattr: así esta prueba también corre
MAX_SEGUIDAS = getattr(sincro, "MAX_SEGUIDAS", 3)  # (y falla por lo que debe) sobre la 0.77
MESA = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "instalar-linux.sh").read_text(encoding="utf-8")
YO = {"pc_id": "e" * 16, "nombre": "Otro", "puerto": 8787, "sistema": "Linux"}


def _item(ident, texto, at, seq=1):
    return {"id": ident, "text": texto, "at": at, "seq": seq}


def _textos():
    return sorted(i["text"] for i in control.clipboard_history()["items"])


class _Historial:
    """Un historial de notas propio en una carpeta temporal (nunca el del dueño)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._viejo = control._history_path
        control.set_history_path(self.tmp / "clipboard-history.json")

    def tearDown(self):
        control.set_history_path(self._viejo)
        shutil.rmtree(self.tmp, ignore_errors=True)


class _Falso(http.server.BaseHTTPRequestHandler):
    """Un «LaZoo» de mentira: contesta lo que diga `respuesta` (código, bytes), sin sellar."""

    respuesta = (200, b"{}")
    vistas: list = []

    def log_message(self, *a):
        return

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", "0") or 0)
        type(self).vistas.append((self.path, self.rfile.read(n)))
        code, cuerpo = type(self).respuesta
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)


class _ConFalso(_Historial):
    def setUp(self):
        super().setUp()
        _Falso.vistas = []
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Falso)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.fila = {"id": "ab" * 16, "host": "127.0.0.1", "puerto": self.srv.server_address[1]}
        self.kd = os.urandom(32)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()


# --- 1. Una respuesta 200 sin sellar no vale ------------------------------------------------------


class SinSello(_ConFalso, unittest.TestCase):
    def malo(self):
        """Lo que mandaría un equipo cualquiera de la red: «bórralo todo» y una nota falsa."""
        return {"v": 1, "yo": YO, "comparte": True, "nombres": {"pc:" + "e" * 16: {"n": "Falso", "t": 1}},
                "notas": {"items": [_item("bad0bad0", "nota falsa", time.time())], "borrados": {}, "vaciado": 9e18}}

    def test_un_200_en_claro_se_rechaza(self):
        _Falso.respuesta = (200, json.dumps(self.malo()).encode())
        with self.assertRaises(pcapc.ErrorPC) as caja:
            pcapc.peticion(self.fila, sincro.RUTA, {"v": 1}, self.kd)
        self.assertIn("sin sellar", str(caja.exception))
        self.assertTrue(_Falso.vistas, "la petición llegó al falso")
        self.assertTrue(_Falso.vistas[0][1].startswith(protocol.MAGIC), "y lo que salió de aquí iba sellado")

    def test_sincro_no_fusiona_lo_de_un_impostor(self):
        control.clipboard_history("mi nota")
        _Falso.respuesta = (200, json.dumps(self.malo()).encode())
        pcs = type("P", (), {"listar": lambda s: [self.fila], "clave": lambda s, _id: self.kd})()
        s = sincro.Sincro(pcs)  # con el pcapc.peticion de verdad
        self.assertEqual(s.uno(self.fila), "error")
        self.assertEqual(_textos(), ["mi nota"], "ni se borra lo mío ni entra la nota falsa")
        self.assertEqual(control.estado_notas()["vaciado"], 0)
        self.assertIn("sin sellar", s.ver()[self.fila["id"]]["mensaje"])

    def test_un_200_sellado_con_otra_clave_tampoco(self):
        _Falso.respuesta = (200, protocol.seal(json.dumps(self.malo()).encode(), pcapc.claves(os.urandom(32))[1]))
        with self.assertRaises(pcapc.ErrorPC):
            pcapc.peticion(self.fila, sincro.RUTA, {"v": 1}, self.kd)

    def test_un_200_sellado_con_su_clave_si(self):
        bueno = {"v": 1, "yo": YO, "comparte": False, "nombres": {}}
        _Falso.respuesta = (200, protocol.seal(json.dumps(bueno).encode(), pcapc.claves(self.kd)[1]))
        self.assertEqual(pcapc.peticion(self.fila, sincro.RUTA, {"v": 1}, self.kd), (200, bueno))


# --- 2. Nada del futuro ---------------------------------------------------------------------------


class RelojAdelantado(_Historial, unittest.TestCase):
    def test_vaciado_futuro_de_otro_pc_no_borra(self):
        control.clipboard_history("nota de este PC")
        t = time.time()
        # el otro PC pulsó «Borrar todo» con el reloj dos horas adelantado
        control.fusionar_notas({"items": [], "borrados": {}, "vaciado": t + 7200})
        self.assertEqual(_textos(), ["nota de este PC"])
        self.assertEqual(control.estado_notas()["vaciado"], 0, "ni se guarda: no borrará las notas de las próximas horas")
        control.clipboard_history("otra, después")
        control.fusionar_notas({"items": [], "borrados": {}, "vaciado": t + 7200})
        self.assertEqual(_textos(), ["nota de este PC", "otra, después"])

    def test_lapida_y_nota_futuras_no_entran(self):
        control.clipboard_history("se queda")
        ident = control.clipboard_history()["items"][0]["id"]
        t = time.time()
        control.fusionar_notas({"items": [_item("f00df00d", "del futuro", t + 7200)], "borrados": {ident: t + 7200}, "vaciado": 0})
        self.assertEqual(_textos(), ["se queda"])
        self.assertEqual(control.estado_notas()["borrados"], {})

    def test_el_margen_de_las_firmas_si_vale(self):
        # relojes a menos de 60 s (lo que ya exigen las firmas): un «Borrar todo» del otro PC sí llega
        control.clipboard_history("vieja")
        t = time.time()
        self.assertTrue(control.fusionar_notas({"items": [], "borrados": {}, "vaciado": t + 20}))
        self.assertEqual(_textos(), [])
        self.assertAlmostEqual(control.estado_notas()["vaciado"], t + 20, places=3)
        self.assertEqual(control._FUTURO_NOTAS, protocol.CLOCK_SECONDS)

    def test_este_pc_se_cura_de_su_propio_vaciado_futuro(self):
        # Este PC pulsó «Borrar todo» con el reloj adelantado; luego se puso en hora y copió algo.
        with mock.patch.object(control.time, "time", lambda: time.monotonic() + 9e9):
            control.clear_clipboard()
        self.assertGreater(control.estado_notas()["vaciado"], time.time() + 3600)
        control.clipboard_history("copiada después, ya en hora")
        t = time.time()
        # el otro PC trae una nota de antes de aquel «Borrar todo» (no debe volver) y otra de después
        control.fusionar_notas({"items": [_item("aa11bb22", "de antes del borrado", t - 3600), _item("cc33dd44", "del otro PC, después", t + 1)],
                                "borrados": {}, "vaciado": 0})
        self.assertEqual(_textos(), ["copiada después, ya en hora", "del otro PC, después"], "antes: se borraban todas, una y otra vez")
        e = control.estado_notas()
        self.assertLessEqual(e["vaciado"], time.time())
        self.assertLess(e["vaciado"], min(i["at"] for i in e["items"]))
        self.assertGreater(e["vaciado"], t - 60, "el «Borrar todo» sigue valiendo para lo anterior")
        # lo que ahora manda este PC ya no hace daño en otro, ni cuando «llegue su hora»
        self.assertLessEqual(e["vaciado"], t + control._FUTURO_NOTAS)
        control.clipboard_history("otra más")
        control.fusionar_notas({"items": [], "borrados": {}, "vaciado": 0})
        self.assertEqual(len(_textos()), 3, "y las siguientes ya no se borran")

    def test_notas_y_lapidas_propias_del_futuro_se_ponen_en_hora(self):
        control.clipboard_history("hecha con el reloj mal")
        with control._clip_lock:
            control._history[0]["at"] = time.time() + 7200
            control._borrados["0123abcd"] = time.time() + 7200
        control.fusionar_notas({"items": [], "borrados": {}, "vaciado": 0})
        e = control.estado_notas()
        self.assertEqual(_textos(), ["hecha con el reloj mal"])
        self.assertLessEqual(e["items"][0]["at"], time.time())
        self.assertLessEqual(e["borrados"]["0123abcd"], time.time())

    def test_numeros_raros_no_rompen(self):
        control.clipboard_history("sigue")
        for raro in (float("nan"), float("inf"), -5, "x", None, [1]):
            control.fusionar_notas({"items": [], "borrados": {"0123abcd": raro}, "vaciado": raro})
        self.assertEqual(_textos(), ["sigue"])


# --- 3. Sin rondas en bucle -----------------------------------------------------------------------


class SincroNoInsiste(_Historial, unittest.TestCase):
    def test_si_nunca_coinciden_deja_de_insistir(self):
        control.clipboard_history("la de aquí")
        fila = {"id": "cd" * 8, "host": "192.168.1.9", "puerto": 8787}
        pcs = type("P", (), {"listar": lambda s: [fila], "clave": lambda s, _id: b"k" * 32})()
        llamadas = []

        def pedir(_fila, _ruta, cuerpo, _kd):
            llamadas.append(cuerpo)
            # el otro PC tiene una nota que este no acepta (fechada mañana): las huellas nunca coinciden
            return 200, {"v": 1, "yo": YO, "comparte": True, "nombres": {}, "firma": "0" * 64,
                         "notas": {"items": [_item("f00df00d", "de mañana", time.time() + 86400)], "borrados": {}, "vaciado": 0}}

        reloj = [100.0]
        s = sincro.Sincro(pcs, pedir, reloj=lambda: reloj[0])
        rondas = 0
        for _ in range(50):  # lo que haría el hilo: mientras «algo cambió», otra vuelta
            s.ev.clear()
            if not s.ronda(cambio=True):
                break
            rondas += 1
            if not s.ev.is_set():
                break
        self.assertLessEqual(rondas, MAX_SEGUIDAS + 1, "antes: sin fin, 3 veces por segundo")
        self.assertFalse(s.ev.is_set())
        self.assertEqual(s.ronda(cambio=True), 0, "ni aunque cambie algo aquí, hasta que pase la espera")
        self.assertEqual(s.ver()[fila["id"]]["estado"], "ok")
        self.assertIn("no acaban de coincidir", s.ver()[fila["id"]]["mensaje"])
        reloj[0] += sincro.ESPERA_ERROR + 1
        self.assertEqual(s.ronda(), 1, "pasada la espera, se vuelve a probar")
        self.assertEqual(_textos(), ["la de aquí"])

    def test_al_coincidir_vuelve_al_ritmo_normal(self):
        fila = {"id": "cd" * 8, "host": "192.168.1.9", "puerto": 8787}
        pcs = type("P", (), {"listar": lambda s: [fila], "clave": lambda s, _id: b"k" * 32})()
        igual = [False]

        def pedir(_fila, _ruta, _cuerpo, _kd):
            r = {"v": 1, "yo": YO, "comparte": True, "nombres": {}, "firma": control.firma_notas()}
            if igual[0]:
                r["igual"] = True
            return 200, r

        reloj = [0.0]
        s = sincro.Sincro(pcs, pedir, reloj=lambda: reloj[0])
        for _ in range(MAX_SEGUIDAS + 2):
            s.uno(fila)
        self.assertGreater(s.pares[fila["id"]].get("desacuerdos", 0), MAX_SEGUIDAS)
        self.assertIn("no acaban de coincidir", s.ver()[fila["id"]]["mensaje"])
        igual[0] = True
        s.uno(fila)
        self.assertEqual(s.pares[fila["id"]]["desacuerdos"], 0)
        self.assertEqual(s.ver()[fila["id"]]["mensaje"], "")
        self.assertNotIn("desacuerdos", s.ver()[fila["id"]], "es un dato interno: no va al Panel")


# --- 4. Volver a este PC nunca se queda colgado ---------------------------------------------------


class DespedidaConPlazo(unittest.TestCase):
    def test_parar_con_la_red_caida_a_media_imagen(self):
        tmp = Path(tempfile.mkdtemp())
        a, b = socket.socketpair()  # `b` es el otro PC: no lee nunca (red caída o PC dormido)
        for s, opt in ((a, socket.SO_SNDBUF), (b, socket.SO_RCVBUF)):
            s.setsockopt(socket.SOL_SOCKET, opt, 4096)
        pcs = pcapc.PCs(tmp)
        pcs.guardar({"id": "ab" * 8, "host": "127.0.0.1", "puerto": 1, "nombre": "dormido"}, os.urandom(32))
        ctl = pcapc.Control(pcs, fabrica=test_v070.CapturaFalsa, conectar_fn=lambda *x, **k: a)
        ctl.porta_leer = lambda: "x" * 900_000  # un texto largo (o una imagen) saliendo hacia el otro PC
        ctl.apuntar = lambda _t: None
        viejo = pcapc.AJUSTES.portapapeles
        pcapc.AJUSTES.portapapeles = True
        try:
            ctl.iniciar("ab" * 8)
            self.assertEqual(ctl.estado, "controlando")
            time.sleep(0.6)  # el hilo que manda ya está atascado: el búfer está lleno
            hilo = threading.Thread(target=ctl.parar, args=("vuelta",), daemon=True)
            t0 = time.monotonic()
            hilo.start()
            self.assertTrue(test_v070.esperar(lambda: not ctl.captura.activa, 2), "lo primero: el teclado vuelve a este PC")
            hilo.join(DESPEDIDA + 3)
            self.assertFalse(hilo.is_alive(), "antes: colgado en la despedida (y la tecla rápida con él)")
            self.assertLess(time.monotonic() - t0, DESPEDIDA + 3)
            self.assertEqual(ctl.estado, "libre")
        finally:
            pcapc.AJUSTES.portapapeles = viejo
            for s in (a, b):
                try:
                    s.close()
                except OSError:
                    pass
            shutil.rmtree(tmp, ignore_errors=True)

    def test_la_tecla_rapida_sigue_viva_despues(self):
        tmp = Path(tempfile.mkdtemp())
        a, b = socket.socketpair()
        for s, opt in ((a, socket.SO_SNDBUF), (b, socket.SO_RCVBUF)):
            s.setsockopt(socket.SOL_SOCKET, opt, 4096)
        pcs = pcapc.PCs(tmp)
        pcs.guardar({"id": "ab" * 8, "host": "127.0.0.1", "puerto": 1, "nombre": "dormido"}, os.urandom(32))
        ctl = pcapc.Control(pcs, fabrica=test_v070.CapturaFalsa, conectar_fn=lambda *x, **k: a)
        ctl.porta_leer = lambda: "x" * 900_000
        ctl.apuntar = lambda _t: None
        avisos = []
        ctl.escuchas.append(lambda ev, txt: avisos.append(ev))
        viejo = pcapc.AJUSTES.portapapeles
        pcapc.AJUSTES.portapapeles = True
        try:
            ctl.iniciar("ab" * 8)
            time.sleep(0.6)
            ctl.pedir("emergencia")  # Ctrl+Alt+Esc
            self.assertTrue(test_v070.esperar(lambda: ctl.estado == "libre", 2))
            hecho = threading.Event()
            with ctl._buf:  # otra orden detrás (la siguiente pulsación de la tecla rápida)
                ctl._ordenes.append(hecho.set)
            ctl._ordenes_ev.set()
            self.assertTrue(hecho.wait(DESPEDIDA + 3), "antes: el hilo de las órdenes seguía colgado en la despedida")
            self.assertEqual(avisos[-1], "libre")
        finally:
            pcapc.AJUSTES.portapapeles = viejo
            for s in (a, b):
                try:
                    s.close()
                except OSError:
                    pass
            shutil.rmtree(tmp, ignore_errors=True)


# --- 5. Dos PCs sobre el mismo receptor -----------------------------------------------------------


class _Despacio(test_v070.Falso):
    """Inyector que tarda y cuenta si dos hilos entran a la vez (lo que Xlib no aguanta)."""

    def __init__(self):
        super().__init__()
        self.dentro = 0
        self.solapes = 0

    def _n(self, *x):
        with self.lock:
            self.dentro += 1
            if self.dentro > 1:
                self.solapes += 1
        time.sleep(0.12)
        with self.lock:
            self.dentro -= 1
            self.hechos.append(x)


class DosEmisores(unittest.TestCase):
    def test_el_nuevo_sustituye_al_viejo_sin_pisarse_en_el_inyector(self):
        iny = _Despacio()
        rec = pcapc.Recepcion(fabrica=lambda: iny, porta_leer=lambda: "", porta_poner=lambda _t: True,
                              imagen_leer=lambda: None, imagen_poner=lambda _p: True)
        abrir = lambda p: p[len(protocol.MAGIC):]  # noqa: E731 (sin cifrar: aquí se prueba el candado)
        sellar = lambda d: protocol.MAGIC + d  # noqa: E731
        trama = lambda n, evs: pcapc.trama_cliente(0x2, protocol.MAGIC + pcapc.codificar(n, evs))  # noqa: E731
        a_cli, a_srv = socket.socketpair()
        b_cli, b_srv = socket.socketpair()
        motivos = {}
        h1 = threading.Thread(target=lambda: motivos.__setitem__("a", rec.atender(a_srv, "a" * 32, "Sobremesa", abrir, sellar, lambda: True)), daemon=True)
        h1.start()
        teclas = [(0xA2, 0x1D), (0xA4, 0x38), (0x41, 0x1E)]  # el primero deja pulsadas Ctrl, Alt y A
        a_cli.sendall(trama(1, [(pcapc.TECLA, vk, sc, 2) for vk, sc in teclas]))
        self.assertTrue(test_v070.esperar(lambda: len(iny.ver()) == 3, 4))
        b_cli.sendall(trama(1, [(pcapc.BOTON, 1, 1), (pcapc.BOTON, 1, 0), (pcapc.BOTON, 2, 1), (pcapc.BOTON, 2, 0)]))
        h2 = threading.Thread(target=lambda: motivos.__setitem__("b", rec.atender(b_srv, "b" * 32, "Portátil", abrir, sellar, lambda: True)), daemon=True)
        h2.start()  # llega el segundo PC: corta al primero, que suelta sus teclas mientras el nuevo ya hace clic
        h1.join(6)
        self.assertFalse(h1.is_alive())
        self.assertTrue(test_v070.esperar(lambda: ("boton", 2, False) in iny.ver(), 4))
        hechos = iny.ver()
        for vk, sc in teclas:
            self.assertIn(("tecla", vk, sc, False, False), hechos, "lo del primero se suelta")
        self.assertEqual(rec.nombre_actual(), "Portátil", "manda el último que llegó")
        self.assertEqual(iny.solapes, 0, "antes: los dos hilos entraban a la vez en el mismo inyector")
        b_cli.close()
        h2.join(6)
        self.assertFalse(h2.is_alive())
        self.assertEqual(rec.nombre_actual(), "")
        a_cli.close()

    def test_el_inyector_lento_tambien_usa_el_candado(self):
        iny = _Despacio()
        iny.lento = True
        candado = threading.Lock()
        r1 = pcapc.Receptor(iny, candado=candado)
        r2 = pcapc.Receptor(iny, candado=candado)
        try:
            r1.tratar(pcapc.codificar(1, [(pcapc.MOVER, 5, 5)]))
            r2.tratar(pcapc.codificar(1, [(pcapc.BOTON, 1, 1), (pcapc.BOTON, 1, 0)]))
            self.assertTrue(test_v070.esperar(lambda: ("mover", 5, 5) in iny.ver(), 3))
            self.assertEqual(iny.solapes, 0)
        finally:
            r1.cerrar()
            r2.cerrar()


# --- 6. Linux: el grupo «input» solo si se pide, y con aviso --------------------------------------


class PermisosLinux(unittest.TestCase):
    def test_arreglar_no_pide_input_de_serie(self):
        llamadas = []
        r = linux_kvm.arreglar(popen=lambda cmd, **kw: llamadas.append(cmd), which=lambda n: "/usr/bin/pkexec")
        self.assertTrue(r["ok"])
        self.assertEqual(llamadas[0][3], "--permisos-root")
        self.assertNotIn("--emisor", llamadas[0])
        linux_kvm.arreglar(popen=lambda cmd, **kw: llamadas.append(cmd), which=lambda n: "/usr/bin/pkexec", emisor=True)
        self.assertEqual(llamadas[1][-1], "--emisor")
        r = linux_kvm.arreglar(popen=lambda cmd, **kw: llamadas.append(cmd), which=lambda n: None, emisor=True)
        self.assertIn("--pcapc --emisor", r["mensaje"])

    def test_el_script_solo_mete_en_input_con_emisor(self):
        raiz = SCRIPT[SCRIPT.index('if [ "$1" = "--permisos-root" ]'):SCRIPT.index("permisos_pcapc() {")]
        con, sin = raiz.split('if [ "$3" = "--emisor" ]; then', 1)[1].split("else", 1)
        self.assertIn('usermod -aG uinput,input "$U"', con)
        self.assertIn('usermod -aG uinput "$U"', sin)
        self.assertNotIn("input", sin.replace("uinput", ""), "sin --emisor, ni se nombra el grupo input")
        self.assertNotIn("usermod", raiz.split('if [ "$3" = "--emisor" ]; then', 1)[0])
        self.assertEqual(subprocess.run(["sh", "-n", str(ROOT / "instalar-linux.sh")]).returncode, 0)

    def _pcapc(self, *args):
        """`sh instalar-linux.sh --pcapc …` con un pkexec de mentira que apunta sus argumentos."""
        tmp = Path(tempfile.mkdtemp())
        try:
            falso = tmp / "pkexec"
            falso.write_text(f'#!/bin/sh\necho "$@" > "{tmp}/args"\n')
            falso.chmod(0o755)
            env = dict(os.environ, PATH=f"{tmp}:{os.environ.get('PATH', '')}", USER="prueba")
            out = subprocess.run(["sh", str(ROOT / "instalar-linux.sh"), "--pcapc", *args], env=env, stdin=subprocess.DEVNULL,
                                 capture_output=True, text=True, timeout=20)
            self.assertEqual(out.returncode, 0, out.stderr)
            return (tmp / "args").read_text().split() if (tmp / "args").exists() else [], out.stdout
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux")
    def test_pcapc_si_es_solo_uinput(self):
        args, salida = self._pcapc("--si")
        self.assertEqual(args[1:], [str(ROOT / "instalar-linux.sh"), "--permisos-root", "prueba"])
        self.assertIn("contraseñas incluidas", salida, "el aviso también sale en la terminal")
        args, _ = self._pcapc("--si", "--emisor")
        self.assertEqual(args[-2:], ["prueba", "--emisor"])
        args, _ = self._pcapc("--emisor", "--si")
        self.assertEqual(args[-2:], ["prueba", "--emisor"])
        args, salida = self._pcapc()  # sin --si y sin nadie que conteste: no hace nada
        self.assertEqual(args, [])
        self.assertIn("Sin preparar", salida)

    def test_el_panel_avisa_antes_de_pedir_input(self):
        self.assertIn("contraseñas incluidas", linux_kvm.AVISO_INPUT)
        i = MESA.index('$("#pc-arreglar").addEventListener')
        trozo = MESA[i:i + 900]
        self.assertIn("window.confirm((d.aviso_input", trozo)
        self.assertIn("d.falta_emisor", trozo)
        self.assertIn('devCall("/api/pcapc/arreglar", { emisor })', trozo)

    def test_el_estado_dice_si_falta_el_emisor(self):
        d = {"receptor": "uinput", "receptor_por": "x", "emisor": "ninguno", "emisor_por": "y", "arreglable": True}
        with mock.patch.object(linux_kvm, "diagnostico", lambda: d):
            e = pcapc.diagnostico_linux(forzar=True)
        self.assertIs(e["falta_emisor"], True)
        self.assertEqual(e["aviso_input"], linux_kvm.AVISO_INPUT)
        with mock.patch.object(linux_kvm, "diagnostico", lambda: dict(d, emisor="x11")):
            self.assertIs(pcapc.diagnostico_linux(forzar=True)["falta_emisor"], False)
        pcapc._DIAG[0] = 0.0


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux")
class PermisosLinuxApi(unittest.TestCase):
    setUp = test_v070.ConServidor.setUp
    tearDown = test_v070.ConServidor.tearDown

    def test_la_api_solo_pasa_emisor_si_viene_true(self):
        h = {"Content-Type": "application/json", "X-Lazo-Local": "1"}
        vistos = []

        def falso(emisor=False, **_k):
            vistos.append(emisor)
            return {"ok": True, "mensaje": "ok"}

        with mock.patch.object(linux_kvm, "arreglar", falso):
            for cuerpo in ({}, {"emisor": "1"}, {"emisor": 1}, {"emisor": True}):
                code, data = test_v070._req(self.port, "POST", "/api/pcapc/arreglar", json.dumps(cuerpo).encode(), h)
                self.assertEqual(code, 200, data)
        self.assertEqual(vistos, [False, False, False, True])


# --- 7. wl-copy por la entrada, no como argumento -------------------------------------------------


class PegarSinArgumento(unittest.TestCase):
    def test_el_texto_no_va_en_la_linea_de_ordenes(self):
        secreto = "contraseña-ñ-€-muy-secreta"
        llamadas = []

        def run(cmd, **kw):
            llamadas.append((list(cmd), kw))
            return subprocess.CompletedProcess(cmd, 0, stdout=b"lo de antes", stderr=b"")

        t = ydo.Teclado(run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0), env={"XDG_RUNTIME_DIR": "/nonexistent"})
        with mock.patch.object(ydo.shutil, "which", lambda n: "/usr/bin/" + n), mock.patch.object(ydo.subprocess, "run", run), \
                mock.patch.object(ydo.time, "sleep", lambda _s: None), mock.patch.object(control, "_mark_injected", lambda *_a: None):
            self.assertTrue(t._pegar(secreto))
        copias = [(cmd, kw) for cmd, kw in llamadas if cmd[0] == "wl-copy"]
        self.assertEqual(len(copias), 2, "el texto y, después, lo que había antes")
        for cmd, kw in llamadas:
            self.assertFalse(any(secreto in str(a) for a in cmd), f"el texto no puede ir como argumento: {cmd[0]}")
        self.assertEqual(copias[0][1]["input"], secreto.encode("utf-8"))
        self.assertEqual(copias[1][1]["input"], b"lo de antes")


# --- 8. Compatibilidad y entrega ------------------------------------------------------------------


class Compatibilidad(_ConFalso, unittest.TestCase):
    def test_un_pc_075_o_067_contesta_404_en_claro(self):
        _Falso.respuesta = (404, json.dumps({"error": "no está"}).encode())
        self.assertEqual(pcapc.peticion(self.fila, sincro.RUTA, {"v": 1}, self.kd), (404, {"error": "no está"}))
        pcs = type("P", (), {"listar": lambda s: [self.fila], "clave": lambda s, _id: self.kd})()
        s = sincro.Sincro(pcs)
        self.assertEqual(s.uno(self.fila), "antiguo")
        self.assertIn("versión anterior", s.ver()[self.fila["id"]]["mensaje"])

    def test_un_pc_075_de_verdad_sella_su_404_con_otra_clave(self):
        # Lo que hace un LaZoo 0.70–0.75 real (visto con dos procesos): no conoce /api/pc/sync y
        # contesta 404 sellado con su clave general. Antes: «error» cada 30 s y un mensaje raro.
        _Falso.respuesta = (404, protocol.seal(b'{"error": "no est\u00e1"}', pcapc.claves(os.urandom(32))[1]))
        self.assertEqual(pcapc.peticion(self.fila, sincro.RUTA, {"v": 1}, self.kd), (404, {}))
        pcs = type("P", (), {"listar": lambda s: [self.fila], "clave": lambda s, _id: self.kd})()
        reloj = [0.0]
        s = sincro.Sincro(pcs, reloj=lambda: reloj[0])
        self.assertEqual(s.uno(self.fila), "antiguo")
        self.assertIn("actualízalo", s.ver()[self.fila["id"]]["mensaje"])
        reloj[0] += sincro.ESPERA_ERROR + 5
        self.assertEqual(s.ronda(), 0, "a un PC antiguo se le deja 10 minutos, no 30 s")

    def test_un_lazoo_sin_controlar_otro_pc_lo_dice(self):
        self.assertIn("versión de LaZoo anterior", pcapc.mensaje_error(404, {"error": "no está"}))
        self.assertIn("ponlos en hora", pcapc.mensaje_error(401, {"clock": True}))

    def test_los_errores_en_claro_se_siguen_entendiendo(self):
        for code, cuerpo, frase in ((401, {"error": "x", "stale": True}, "ya no reconoce"),
                                    (401, {"error": "x", "kicked": True}, "ya no reconoce"),
                                    (403, {"error": "x", "pending": True}, "aún no ha aceptado")):
            _Falso.respuesta = (code, json.dumps(cuerpo).encode())
            got, data = pcapc.peticion(self.fila, sincro.RUTA, {"v": 1}, self.kd)
            self.assertEqual(got, code)
            self.assertIn(frase, pcapc.mensaje_error(got, data))


class ConUnLaZooDeVerdad(unittest.TestCase):
    """El servidor de test_v070 (mismo proceso): el 200 de un LaZoo 0.78 llega sellado y vale."""

    setUp = test_v070.ConServidor.setUp
    tearDown = test_v070.ConServidor.tearDown
    emparejar = test_v070.ConServidor.emparejar

    def test_sync_sellado_de_ida_y_vuelta(self):
        who, _ = self.emparejar()
        cuerpo = {"v": 1, "yo": {"pc_id": "f" * 16, "nombre": "Otro", "puerto": 8787, "sistema": "Linux"}, "comparte": False, "nombres": {}}
        code, r = pcapc.peticion(self.pcs.listar()[0], sincro.RUTA, cuerpo, self.pcs.clave(who))
        self.assertEqual(code, 200, r)
        self.assertEqual(r["yo"]["pc_id"], pcapc.AJUSTES.pc_id)

    def test_el_servidor_sin_x_seal_no_sirve_para_fusionar(self):
        # Aunque alguien quitara X-Seal, lo que vuelve en claro ya no se acepta como 200.
        who, _ = self.emparejar()
        fila = self.pcs.listar()[0]
        firma_k, sello = pcapc.claves(self.pcs.clave(who))
        cuerpo = {"v": 1, "yo": {"pc_id": "f" * 16, "nombre": "Otro", "puerto": 8787, "sistema": "Linux"}, "comparte": False, "nombres": {}}
        raw = protocol.seal(json.dumps(cuerpo).encode(), sello)
        stamp, nonce = int(time.time() * 1000), os.urandom(16).hex()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{sincro.RUTA}", data=raw, method="POST", headers={
            "Content-Type": "application/octet-stream", "User-Agent": pcapc.user_agent(), protocol.H_ID: fila["id"],
            protocol.H_T: str(stamp), protocol.H_N: nonce,
            protocol.H_S: protocol.sign_request(firma_k, "POST", sincro.RUTA, stamp, nonce, len(raw))})
        with urllib.request.urlopen(req, timeout=5) as res:
            datos = res.read()
        self.assertFalse(datos.startswith(protocol.MAGIC), "sin X-Seal el servidor contesta en claro (por eso el cliente lo exige)")


class RelojDistintoAlSincronizar(unittest.TestCase):
    """Con los relojes a más de 60 s no se sincroniza, y el otro PC tiene que poder leer por qué."""

    setUp = test_v070.ConServidor.setUp
    tearDown = test_v070.ConServidor.tearDown
    emparejar = test_v070.ConServidor.emparejar

    def test_el_motivo_llega_sellado_para_ese_pc(self):
        who, _ = self.emparejar()
        fila = self.pcs.listar()[0]
        firma_k, sello = pcapc.claves(self.pcs.clave(who))
        raw = protocol.seal(b'{"v": 1}', sello)
        stamp, nonce = int((time.time() - 300) * 1000), os.urandom(16).hex()  # este PC va 5 minutos atrasado
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{sincro.RUTA}", data=raw, method="POST", headers={
            "Content-Type": "application/octet-stream", "User-Agent": pcapc.user_agent(), "X-Seal": "1", protocol.H_ID: fila["id"],
            protocol.H_T: str(stamp), protocol.H_N: nonce,
            protocol.H_S: protocol.sign_request(firma_k, "POST", sincro.RUTA, stamp, nonce, len(raw))})
        with self.assertRaises(urllib.error.HTTPError) as caja:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(caja.exception.code, 401)
        cuerpo = caja.exception.read()
        self.assertTrue(cuerpo.startswith(protocol.MAGIC))
        data = json.loads(protocol.open_sealed(cuerpo, sello))  # antes: sellado con la clave general, ilegible
        self.assertIs(data.get("clock"), True)
        self.assertIn("ponlos en hora", pcapc.mensaje_error(401, data))

    def test_y_peticion_lo_entiende(self):
        who, _ = self.emparejar()
        fila = self.pcs.listar()[0]
        ahora = time.time()
        real = protocol.Pairing.verify

        def verify(self_, method, path, length, stamp, nonce, sig, who=None):  # el servidor, 5 min adelantado
            with mock.patch.object(protocol.time, "time", lambda: ahora + 300):
                return real(self_, method, path, length, stamp, nonce, sig, who=who)

        with mock.patch.object(protocol.Pairing, "verify", verify):
            code, data = pcapc.peticion(fila, sincro.RUTA, {"v": 1}, self.pcs.clave(who))
        self.assertEqual(code, 401)
        self.assertIn("ponlos en hora", pcapc.mensaje_error(code, data))


class Entrega(unittest.TestCase):
    def test_version(self):
        self.assertEqual(lazo.VERSION, "0.78")
        self.assertEqual(pcapc.VERSION, "0.78")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.78")
        self.assertIn('<p class="ver">0.78', MESA)
        self.assertIn("<title>LaZoo 0.78</title>", (ROOT / "static" / "index.html").read_text(encoding="utf-8"))
        self.assertIn('PAGE_VERSION = "0.78"', (ROOT / "static" / "app.js").read_text(encoding="utf-8"))
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertTrue(readme.startswith("# LaZoo 0.78"))
        self.assertIn("Novedad 0.78", readme)
        self.assertIn("- 0.78", (ROOT / "AGENTS.md").read_text(encoding="utf-8"))

    def test_el_canal_no_cambia(self):
        # 0.78 no toca el protocolo: un PC 0.76/0.77 y uno 0.78 se entienden igual.
        self.assertEqual(pcapc.KVM_VERSION, 3)
        self.assertEqual(sincro.VERSION_SYNC, 1)
        self.assertEqual(sincro.RUTA, "/api/pc/sync")

    def test_hoja_de_ruta_de_betas(self):
        doc = (ROOT / "docs" / "BETAS-PC-A-PC.md").read_text(encoding="utf-8")
        for trozo in ("Beta 1", "Beta 2", "Beta 3", "Estable", "Plantilla de feedback", "Criterio de salida"):
            self.assertIn(trozo, doc)

    def test_apk_sin_cambios(self):
        try:
            out = subprocess.run(["git", "diff", "--quiet", "ca4ce85", "--", "android"], cwd=ROOT, capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            self.skipTest("sin git")
        if out.returncode not in (0, 1):
            self.skipTest("sin el historial de git")
        self.assertEqual(out.returncode, 0, "la 0.78 no toca la APK (App 3)")

    def test_solo_biblioteca_estandar(self):
        import ast

        permitidos = set(sys.stdlib_module_names) | {"control", "lazo", "pcapc", "protocol", "sincro", "nombres", "aprobacion",
                                                     "recordar", "fluidez", "linux_kvm", "ydo", "imagenes", "sinventana"}
        for nombre in ("sincro.py", "pcapc.py", "linux_kvm.py", "ydo.py"):
            arbol = ast.parse((ROOT / nombre).read_text(encoding="utf-8"))
            for nodo in ast.walk(arbol):
                mods = [a.name for a in nodo.names] if isinstance(nodo, ast.Import) else [nodo.module or ""] if isinstance(nodo, ast.ImportFrom) else []
                for m in mods:
                    self.assertIn(m.split(".")[0], permitidos, f"{nombre} importa {m}")


if __name__ == "__main__":
    unittest.main()
