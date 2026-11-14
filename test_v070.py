"""Pruebas de la 0.70: «Controlar otro PC» (pcapc.py).

Mensajes, firma y sello del canal `/kvm`, que solo entren emisores aprobados en este PC, que se
suelten las teclas al dejar de controlar o al cortarse, y el latido en los dos sentidos. En Linux
sin pantalla: el inyector y la captura son de mentira, el servidor y la red son los de verdad.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault("LAZO_DATOS", tempfile.mkdtemp())

import aprobacion  # noqa: E402
import bandeja  # noqa: E402
import bandeja_linux  # noqa: E402
import lazo  # noqa: E402
import pcapc  # noqa: E402
import protocol  # noqa: E402
import recordar  # noqa: E402

ROOT = Path(__file__).resolve().parent
UA = "LaZoo-PC/0.70 (Windows; SALON)"


class Falso:
    """Inyector que apunta lo que haría."""

    lento = False

    def __init__(self):
        self.hechos = []
        self.lock = threading.Lock()

    def _n(self, *x):
        with self.lock:
            self.hechos.append(x)

    def mover(self, dx, dy):
        self._n("mover", dx, dy)

    def boton(self, b, abajo):
        self._n("boton", b, abajo)

    def rueda(self, eje, delta):
        self._n("rueda", eje, delta)

    def tecla(self, vk, scan, ext, abajo):
        self._n("tecla", vk, scan, ext, abajo)

    def ver(self):
        with self.lock:
            return list(self.hechos)


class CapturaFalsa:
    def __init__(self, control):
        self.control = control
        self.activa = False

    def empezar(self, sink):
        self.activa = True
        return True

    def parar(self):
        self.activa = False


def esperar(cond, tope=4.0):
    fin = time.time() + tope
    while time.time() < fin:
        if cond():
            return True
        time.sleep(0.02)
    return False


# --- Mensajes -----------------------------------------------------------------------------


class Mensajes(unittest.TestCase):
    def test_ida_y_vuelta(self):
        evs = [(pcapc.MOVER, 5, -7), (pcapc.BOTON, 1, 1), (pcapc.RUEDA, 1, -120), (pcapc.TECLA, 0x41, 0x1E, 2),
               (pcapc.SOLTAR,), (pcapc.LATIDO_EV, 9), (pcapc.RESPUESTA, 9)]
        n, out = pcapc.decodificar(pcapc.codificar(42, evs))
        self.assertEqual(n, 42)
        self.assertEqual(out, evs)

    def test_movimiento_grande_se_parte(self):
        _n, out = pcapc.decodificar(pcapc.codificar(1, [(pcapc.MOVER, 70000, -5)]))
        self.assertGreater(len(out), 1)
        self.assertEqual(sum(e[1] for e in out), 70000)
        self.assertEqual(sum(e[2] for e in out), -5)

    def test_rechaza_lo_raro(self):
        for raw in (b"", b"XX\x00\x00\x00\x00", pcapc.CABECERA + b"\x01\x00\x00\x00" + b"\x09",
                    pcapc.CABECERA + b"\x01\x00\x00\x00" + bytes([pcapc.BOTON, 9, 1]),
                    pcapc.CABECERA + b"\x01\x00\x00\x00" + bytes([pcapc.MOVER, 1])):
            with self.assertRaises(protocol.ProtocolError):
                pcapc.decodificar(raw)

    def test_trama_cliente_enmascarada_la_lee_el_servidor(self):
        a, b = socket.socketpair()
        try:
            datos = os.urandom(900)
            a.sendall(pcapc.trama_cliente(0x2, datos))
            self.assertEqual(protocol.ws_read(b, pcapc.MAX_TRAMA), (0x2, datos))
            a.sendall(pcapc.trama_cliente(0x2, datos))
            with self.assertRaises(protocol.ProtocolError):
                protocol.ws_read(b)  # el ratón del móvil sigue con su tope de 64
        finally:
            a.close()
            b.close()

    def test_tecla_rapida(self):
        self.assertEqual(pcapc.leer_tecla("Ctrl+Alt+L"), (pcapc.MOD_CONTROL | pcapc.MOD_ALT, 0x4C, "Ctrl+Alt+L"))
        self.assertEqual(pcapc.leer_tecla("alt + ctrl + f9")[1:], (0x78, "Ctrl+Alt+F9"))
        for mal in ("L", "Shift+L", "Ctrl+Alt+Esc", "Ctrl+Alt+Supr", "Foo+L", ""):
            with self.assertRaises(pcapc.ErrorPC, msg=mal):
                pcapc.leer_tecla(mal)

    def test_teclas_de_windows_a_linux(self):
        self.assertEqual(pcapc.evdev(0x41, 0x1E, False), 30)       # A
        self.assertEqual(pcapc.evdev(0x26, 0x48, True), 103)       # flecha arriba
        self.assertEqual(pcapc.evdev(0xA5, 0x38, True), 100)       # AltGr
        self.assertEqual(pcapc.evdev(0x5B, 0x5B, True), 125)       # Win
        self.assertEqual(pcapc.evdev(0x90, 0x45, True), 69)        # Bloq Num
        self.assertEqual(pcapc.evdev(0xC0, 0x27, False), 39)       # ñ (posición física)
        self.assertEqual(pcapc.evdev(0x7A, 0x57, False), 87)       # F11

    def test_rueda_en_muescas(self):
        resto = [0, 0]
        self.assertEqual(pcapc.pasos_rueda(resto, 0, 60, x11=True), [])
        self.assertEqual(pcapc.pasos_rueda(resto, 0, 60, x11=True), [4])
        self.assertEqual(pcapc.pasos_rueda(resto, 0, -240, x11=True), [5, 5])
        self.assertEqual(pcapc.pasos_rueda(resto, 1, 120, x11=True), [7])
        self.assertEqual(pcapc.pasos_rueda(resto, 1, -120), [-1])


# --- Receptor -------------------------------------------------------------------------------


class ReceptorSolo(unittest.TestCase):
    def test_suelta_lo_pulsado(self):
        f = Falso()
        r = pcapc.Receptor(f)
        r.tratar(pcapc.codificar(1, [(pcapc.TECLA, 0x11, 0x1D, 2), (pcapc.TECLA, 0x41, 0x1E, 2), (pcapc.BOTON, 1, 1)]))
        self.assertEqual(r.soltar_todo(), 3)
        hechos = f.ver()
        self.assertIn(("tecla", 0x41, 0x1E, False, False), hechos)
        self.assertIn(("tecla", 0x11, 0x1D, False, False), hechos)
        self.assertIn(("boton", 1, False), hechos)
        self.assertEqual(r.soltar_todo(), 0)

    def test_soltar_de_algo_no_pulsado_no_se_inyecta(self):
        f = Falso()
        r = pcapc.Receptor(f)
        r.tratar(pcapc.codificar(1, [(pcapc.TECLA, 0x41, 0x1E, 0), (pcapc.BOTON, 2, 0)]))
        self.assertEqual(f.ver(), [])

    def test_trama_repetida_fuera_y_latido_contestado(self):
        r = pcapc.Receptor(Falso())
        trama = pcapc.codificar(5, [(pcapc.LATIDO_EV, 77)])
        self.assertEqual(r.tratar(trama), [(pcapc.RESPUESTA, 77)])
        with self.assertRaises(protocol.ProtocolError):
            r.tratar(trama)

    def test_movimientos_juntos_y_en_orden(self):
        f = Falso()
        r = pcapc.Receptor(f)
        r.tratar(pcapc.codificar(1, [(pcapc.MOVER, 1, 1), (pcapc.MOVER, 2, 3), (pcapc.BOTON, 1, 1), (pcapc.MOVER, 4, 4)]))
        self.assertEqual(f.ver(), [("mover", 3, 4), ("boton", 1, True), ("mover", 4, 4)])

    def test_inyector_lento_no_acumula_retraso(self):
        f = Falso()
        f.lento = True
        r = pcapc.Receptor(f)
        for i in range(1, 30):
            r.tratar(pcapc.codificar(i, [(pcapc.MOVER, 1, 0)]))
        r.tratar(pcapc.codificar(40, [(pcapc.BOTON, 1, 1)]))
        self.assertTrue(esperar(lambda: sum(h[1] for h in f.ver() if h[0] == "mover") == 29))
        orden = [h[0] for h in f.ver()]
        self.assertLess(orden.index("mover"), orden.index("boton"))
        r.cerrar()

    def test_ydotool_ordenes(self):
        hechas = []

        class Base:
            def ydo(self, *a):
                hechas.append(a)

        y = pcapc.InyectorYdotool(Base())
        y.tecla(0x41, 0x1E, False, True)
        y.boton(2, False)
        y.rueda(0, 240)
        self.assertEqual(hechas, [("key", "30:1"), ("click", "0x81"), ("mousemove", "-w", "-x", "0", "-y", "2")])


class FiltroDelGancho(unittest.TestCase):
    class Sink:
        def __init__(self):
            self.ev, self.pedidos = [], []

        def tecla(self, *a):
            self.ev.append(("tecla",) + a)

        def boton(self, *a):
            self.ev.append(("boton",) + a)

        def pedir(self, orden):
            self.pedidos.append(orden)

    def filtro(self, abajo=()):
        s = self.Sink()
        mods, vk, _ = pcapc.leer_tecla("Ctrl+Alt+L")
        return s, pcapc.Filtro(s, mods, vk, set(abajo))

    def test_lo_pulsado_antes_se_suelta_aqui(self):
        s, f = self.filtro(abajo={0xA2, 0xA4})  # Ctrl+Alt de la propia tecla rápida
        self.assertFalse(f.tecla(0xA2, 0x1D, 0, False))
        self.assertFalse(f.tecla(0x4C, 0x26, 0, False))
        self.assertEqual(s.ev, [])
        self.assertTrue(f.tecla(0x41, 0x1E, 0, True))
        self.assertTrue(f.tecla(0x41, 0x1E, 0, False))
        self.assertEqual([e[-1] for e in s.ev], [True, False])
        self.assertFalse(f.boton(1, False))
        self.assertTrue(f.boton(1, True) and f.boton(1, False))

    def test_tecla_rapida_y_emergencia(self):
        s, f = self.filtro()
        for vk in (0xA2, 0xA4):
            f.tecla(vk, 0x1D, 0, True)
        self.assertTrue(f.tecla(0x4C, 0x26, 0, True))
        self.assertEqual(s.pedidos, ["alternar"])
        self.assertIsNone(f.sink, "desde ese momento todo pasa a este PC")
        self.assertFalse(f.tecla(0x41, 0x1E, 0, True))
        s, f = self.filtro()
        for vk in (0xA3, 0xA5):
            f.tecla(vk, 0x1D, 1, True)
        self.assertTrue(f.tecla(0x1B, 0x01, 0, True))
        self.assertEqual(s.pedidos, ["emergencia"])
        self.assertIsNone(f.sink)

    def test_ctrl_falso_de_altgr(self):
        s, f = self.filtro()
        self.assertTrue(f.tecla(0xA2, 0x21D, 0, True))
        self.assertEqual(s.ev, [])
        self.assertTrue(f.tecla(0xA5, 0x38, 1, True))
        self.assertEqual(s.ev, [("tecla", 0xA5, 0x38, True, True)])


# --- Con el servidor de verdad -----------------------------------------------------------------


def _req(port, method, path, body=None, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


class ConServidor(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.server = lazo.LazoServer(("127.0.0.1", 0), lazo.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.saved = (lazo.APPROVALS.auto, lazo.maybe_open_mesa, lazo.STORE, pcapc.RECEPCION.fabrica, pcapc.RECEPCION._iny,
                      pcapc.AJUSTES.permitir, pcapc.SIN_RESPUESTA, list(lazo.APPROVALS.on_new))
        os.environ["LAZO_DATOS"] = str(self.tmp)
        lazo.APPROVALS.auto = False
        lazo.APPROVALS.on_new[:] = []
        lazo.maybe_open_mesa = lambda: None
        lazo.STORE = recordar.Store(self.tmp)
        lazo.PAIRING.rekey()
        lazo.APPROVALS.devices.clear()
        lazo.KICKED.clear()
        self.falso = Falso()
        pcapc.RECEPCION.fabrica = lambda: self.falso
        pcapc.RECEPCION._iny = None
        pcapc.AJUSTES.permitir = True
        self.pcs = pcapc.PCs(self.tmp / "emisor")
        self.par = pcapc.Emparejar(self.pcs)

    def tearDown(self):
        (lazo.APPROVALS.auto, lazo.maybe_open_mesa, lazo.STORE, pcapc.RECEPCION.fabrica, pcapc.RECEPCION._iny,
         pcapc.AJUSTES.permitir, pcapc.SIN_RESPUESTA, hooks) = self.saved
        lazo.APPROVALS.on_new[:] = hooks
        lazo.APPROVALS.devices.clear()
        lazo.KICKED.clear()
        lazo.PAIRING.rekey()
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # Emparejar ---------------------------------------------------------------------------
    def emparejar(self, aceptar=True):
        out = self.par.empezar(f"127.0.0.1:{self.port}", lazo.PAIRING.pin, esperar=False)
        args = out.pop("args")
        who = args[-1]["id"]
        fila = next(d for d in lazo.APPROVALS.listing() if d["id"] == who)
        self.assertEqual(fila["state"], "pendiente", "un PC nuevo NUNCA entra sin aceptarlo")
        self.assertTrue(fila["label"].startswith("PC · "), fila["label"])
        self.assertTrue(lazo.APPROVALS.decide(who, aceptar))
        final = self.par.esperar(*args, dormir=lambda _s: None, plazo=5)
        return who, final

    def test_emparejar_con_pin_y_aprobacion(self):
        who, final = self.emparejar()
        self.assertEqual(final["estado"], "hecho", final)
        filas = self.pcs.listar()
        self.assertEqual([f["id"] for f in filas], [who])
        self.assertTrue(filas[0]["nombre"])
        self.assertEqual(self.pcs.clave(who), lazo.PAIRING.device_key(who), "la clave de ESE dispositivo, no la maestra")
        crudo = (self.tmp / "emisor" / pcapc.ARCHIVO_PCS).read_text()
        self.assertNotIn(lazo.PAIRING.device_key_text(who), crudo, "la clave se guarda cifrada")

    def test_rechazado_no_recibe_clave(self):
        _who, final = self.emparejar(aceptar=False)
        self.assertEqual(final["estado"], "error")
        self.assertEqual(self.pcs.listar(), [])

    def test_pin_malo(self):
        malo = "000000" if lazo.PAIRING.pin != "000000" else "111111"
        with self.assertRaises(pcapc.ErrorPC):
            self.par.empezar(f"127.0.0.1:{self.port}", malo, esperar=False)

    def test_apagado_no_deja_ni_emparejar_ni_conectar(self):
        who, _ = self.emparejar()
        pcapc.AJUSTES.permitir = False
        with self.assertRaises(pcapc.ErrorPC) as caja:
            self.par.empezar(f"127.0.0.1:{self.port}", lazo.PAIRING.pin, esperar=False)
        self.assertIn("Permitir que otro PC me controle", str(caja.exception))
        with self.assertRaises(pcapc.ErrorPC) as caja:
            pcapc.conectar("127.0.0.1", self.port, who, self.pcs.clave(who))
        self.assertIn("Permitir que otro PC me controle", str(caja.exception))

    def test_solo_red_local(self):
        with self.assertRaises(pcapc.ErrorPC):
            pcapc.ip_de_lan("8.8.8.8", 8787)
        self.assertEqual(pcapc.partir_destino("192.168.1.20"), ("192.168.1.20", 8787))
        self.assertEqual(pcapc.partir_destino("http://192.168.1.20:9000/mesa"), ("192.168.1.20", 9000))

    # Quién entra -------------------------------------------------------------------------
    def test_sin_aprobar_o_sin_clave_no_entra(self):
        import secrets

        extraño = secrets.token_hex(16)
        with self.assertRaises(pcapc.ErrorPC) as caja:
            pcapc.conectar("127.0.0.1", self.port, extraño, os.urandom(32))
        self.assertIn("ya no reconoce", str(caja.exception))
        # Con la clave buena de un id que aún no se ha aceptado: pendiente, no entra.
        pendiente = secrets.token_hex(16)
        with self.assertRaises(pcapc.ErrorPC) as caja:
            pcapc.conectar("127.0.0.1", self.port, pendiente, lazo.PAIRING.device_key(pendiente))
        self.assertIn("aún no ha aceptado", str(caja.exception))
        self.assertEqual(self.falso.ver(), [])

    def test_la_firma_de_otro_id_no_vale(self):
        a, _ = self.emparejar()
        b, _ = self.emparejar()
        with self.assertRaises(pcapc.ErrorPC):
            pcapc.conectar("127.0.0.1", self.port, b, self.pcs.clave(a))

    def test_expulsado_no_entra(self):
        who, _ = self.emparejar()
        lazo.kick_device(who)
        with self.assertRaises(pcapc.ErrorPC) as caja:
            pcapc.conectar("127.0.0.1", self.port, who, self.pcs.clave(who))
        self.assertIn("ya no reconoce", str(caja.exception))

    def test_trama_sin_sellar_corta(self):
        who, _ = self.emparejar()
        sock = pcapc.conectar("127.0.0.1", self.port, who, self.pcs.clave(who))
        sock.sendall(pcapc.trama_cliente(0x2, pcapc.codificar(1, [(pcapc.TECLA, 0x41, 0x1E, 2)])))
        sock.settimeout(3)
        self.assertEqual(sock.recv(10), b"")
        sock.close()
        self.assertEqual(self.falso.ver(), [])

    # Control de verdad ------------------------------------------------------------------
    def control(self):
        who, _ = self.emparejar()
        ctl = pcapc.Control(self.pcs, fabrica=CapturaFalsa)
        avisos = []
        ctl.escuchas.append(lambda ev, txt: avisos.append(ev))
        ctl.iniciar(who)
        self.assertEqual(ctl.estado, "controlando")
        self.assertTrue(ctl.captura.activa)
        return who, ctl, avisos

    def test_teclas_raton_y_soltar_al_parar(self):
        who, ctl, avisos = self.control()
        self.assertTrue(esperar(lambda: pcapc.RECEPCION.nombre_actual() != ""))
        ctl.tecla(0xA2, 0x1D, False, True)
        ctl.tecla(0x41, 0x1E, False, True)
        for _ in range(10):
            ctl.mover(3, -2)
        ctl.boton(1, True)
        ctl.rueda(0, 120)
        self.assertTrue(esperar(lambda: ("rueda", 0, 120) in self.falso.ver()))
        hechos = self.falso.ver()
        self.assertEqual(sum(h[1] for h in hechos if h[0] == "mover"), 30)
        self.assertEqual(sum(h[2] for h in hechos if h[0] == "mover"), -20)
        self.assertIn(("tecla", 0x41, 0x1E, False, True), hechos)
        ctl.parar("fin")
        self.assertFalse(ctl.captura.activa, "lo primero al parar: la entrada vuelve a este PC")
        self.assertTrue(esperar(lambda: ("tecla", 0x41, 0x1E, False, False) in self.falso.ver()))
        hechos = self.falso.ver()
        self.assertIn(("tecla", 0xA2, 0x1D, False, False), hechos)
        self.assertIn(("boton", 1, False), hechos)
        self.assertEqual(avisos[0], "controlando")
        self.assertEqual(avisos[-1], "libre")
        self.assertTrue(esperar(lambda: pcapc.RECEPCION.nombre_actual() == ""))

    def test_latido_del_emisor_mantiene_vivo(self):
        _who, ctl, _ = self.control()
        pcapc.SIN_RESPUESTA = 1.0
        time.sleep(1.6)
        self.assertEqual(ctl.estado, "controlando", "las respuestas a los latidos llegan")
        self.assertTrue(ctl.vivo())
        ctl.parar("")

    def test_receptor_suelta_si_el_emisor_calla(self):
        who, _ = self.emparejar()
        pcapc.SIN_RESPUESTA = 0.6
        kd = self.pcs.clave(who)
        sello = pcapc.claves(kd)[1]
        sock = pcapc.conectar("127.0.0.1", self.port, who, kd)
        sock.sendall(pcapc.trama_cliente(0x2, protocol.seal(pcapc.codificar(1, [(pcapc.TECLA, 0x10, 0x2A, 2)]), sello)))
        self.assertTrue(esperar(lambda: ("tecla", 0x10, 0x2A, False, True) in self.falso.ver()))
        # Sin latidos: a los 0,6 s el receptor suelta Shift y cierra.
        self.assertTrue(esperar(lambda: ("tecla", 0x10, 0x2A, False, False) in self.falso.ver(), 3))
        sock.settimeout(3)
        self.assertEqual(sock.recv(10), b"")
        sock.close()

    def test_emisor_suelta_si_el_receptor_no_contesta(self):
        pcapc.SIN_RESPUESTA = 0.8
        mudo_a, mudo_b = socket.socketpair()
        self.pcs.guardar({"id": "ab" * 8, "host": "127.0.0.1", "puerto": 1, "nombre": "mudo"}, os.urandom(32))
        ctl = pcapc.Control(self.pcs, fabrica=CapturaFalsa, conectar_fn=lambda *a, **k: mudo_a)
        avisos = []
        ctl.escuchas.append(lambda ev, txt: avisos.append((ev, txt)))
        ctl.iniciar("ab" * 8)
        self.assertTrue(esperar(lambda: ctl.estado == "libre", 4), "sin respuesta a los latidos, vuelve solo")
        self.assertFalse(ctl.captura.activa)
        self.assertIn("no responde", avisos[-1][1])
        mudo_b.close()

    def test_emisor_suelta_si_se_corta(self):
        a, b = socket.socketpair()
        self.pcs.guardar({"id": "cd" * 8, "host": "127.0.0.1", "puerto": 1, "nombre": "x"}, os.urandom(32))
        ctl = pcapc.Control(self.pcs, fabrica=CapturaFalsa, conectar_fn=lambda *a_, **k: a)
        ctl.iniciar("cd" * 8)
        b.close()
        self.assertTrue(esperar(lambda: ctl.estado == "libre", 4))
        self.assertFalse(ctl.captura.activa)

    def test_expulsar_corta_la_sesion_y_suelta(self):
        who, ctl, _ = self.control()
        ctl.tecla(0x41, 0x1E, False, True)
        self.assertTrue(esperar(lambda: ("tecla", 0x41, 0x1E, False, True) in self.falso.ver()))
        lazo.kick_device(who)
        self.assertTrue(esperar(lambda: ("tecla", 0x41, 0x1E, False, False) in self.falso.ver()))
        self.assertTrue(esperar(lambda: ctl.estado == "libre", 4))

    def test_apagar_permitir_corta(self):
        _who, ctl, _ = self.control()
        self.assertTrue(esperar(lambda: pcapc.RECEPCION.nombre_actual() != ""))
        pcapc.AJUSTES.permitir = False
        pcapc.RECEPCION.cortar()
        self.assertTrue(esperar(lambda: ctl.estado == "libre", 4))

    def test_trama_repetida_corta_y_suelta(self):
        who, _ = self.emparejar()
        kd = self.pcs.clave(who)
        sello = pcapc.claves(kd)[1]
        sock = pcapc.conectar("127.0.0.1", self.port, who, kd)
        trama = pcapc.trama_cliente(0x2, protocol.seal(pcapc.codificar(1, [(pcapc.TECLA, 0x41, 0x1E, 2)]), sello))
        sock.sendall(trama)
        self.assertTrue(esperar(lambda: ("tecla", 0x41, 0x1E, False, True) in self.falso.ver()))
        sock.sendall(trama)  # la misma otra vez
        self.assertTrue(esperar(lambda: ("tecla", 0x41, 0x1E, False, False) in self.falso.ver()))
        sock.close()

    # Panel -----------------------------------------------------------------------------
    def test_api_solo_desde_este_pc(self):
        saved = lazo.Handler._loopback
        lazo.Handler._loopback = lambda self: False
        try:
            code, _ = _req(self.port, "POST", "/api/pcapc/permitir", json.dumps({"on": True}).encode(),
                           {"Content-Type": "application/json", "X-Lazo-Local": "1"})
            self.assertEqual(code, 403)
            code, _ = _req(self.port, "GET", "/api/pcapc", None, {"X-Lazo-Local": "1"})
            self.assertEqual(code, 403)
        finally:
            lazo.Handler._loopback = saved

    def test_api_del_panel(self):
        h = {"Content-Type": "application/json", "X-Lazo-Local": "1"}
        code, data = _req(self.port, "POST", "/api/pcapc/permitir", json.dumps({"on": False}).encode(), h)
        self.assertEqual(code, 200)
        self.assertFalse(data["permitir"])
        self.assertNotIn("pin", data)
        code, data = _req(self.port, "POST", "/api/pcapc/permitir", json.dumps({"on": True}).encode(), h)
        self.assertTrue(data["permitir"])
        self.assertEqual(data["pin"], lazo.PAIRING.pin)
        code, data = _req(self.port, "POST", "/api/pcapc/tecla", json.dumps({"tecla": "ctrl+alt+k"}).encode(), h)
        self.assertEqual((code, data["tecla"]), (200, "Ctrl+Alt+K"))
        code, data = _req(self.port, "POST", "/api/pcapc/tecla", json.dumps({"tecla": "k"}).encode(), h)
        self.assertEqual(code, 400)
        pcapc.AJUSTES.set_tecla("Ctrl+Alt+L")
        guardado = json.loads((self.tmp / "ajustes.json").read_text())
        self.assertIs(guardado["otro_pc_permitir"], True)


class Ajustes(unittest.TestCase):
    def test_apagado_de_serie(self):
        tmp = tempfile.mkdtemp()
        viejo = os.environ.get("LAZO_DATOS")
        os.environ["LAZO_DATOS"] = tmp
        try:
            a = pcapc.Ajustes().cargar()
            self.assertFalse(a.permitir)
            self.assertEqual(a.tecla, "Ctrl+Alt+L")
            a.set_permitir(True)
            self.assertTrue(pcapc.Ajustes().cargar().permitir)
        finally:
            os.environ["LAZO_DATOS"] = viejo or ""
            shutil.rmtree(tmp, ignore_errors=True)


class Bandeja(unittest.TestCase):
    PCS = [{"id": "aa" * 8, "nombre": "SALON", "host": "192.168.1.20", "puerto": 8787}]

    def test_menu_y_ordenes(self):
        model = bandeja.menu_model([], self.PCS)
        pid, d = model["pcs"][0]
        self.assertEqual(bandeja.resolve(pid, [], self.PCS), ("pc", "aa" * 8))
        for ident, name in ((bandeja.ID_PC_SOLTAR, "pc-soltar"), (bandeja.ID_PC_ANADIR, "pc-anadir"), (bandeja.ID_PC_PERMITIR, "pc-permitir")):
            self.assertEqual(bandeja.resolve(ident, [], self.PCS)[0], name)
        self.assertIn("SALON", bandeja.pc_label(d))

    def test_icono_y_texto_al_controlar(self):
        ico, text = bandeja.tray_state(0, 0, "SALON", "Ctrl+Alt+L")
        self.assertEqual(ico, "lazoo.ico")
        self.assertIn("controlando «SALON»", text)
        self.assertIn("Ctrl+Alt+L", text)
        self.assertLess(len(text), 128)
        self.assertEqual(bandeja.tray_state(0), ("lazoo-rojo.ico", "LaZoo · sin dispositivos"))

    def test_menu_de_linux(self):
        items = bandeja_linux.menu_items([], True, False, self.PCS, {"estado": "libre", "id": ""}, False)
        sub = next(it for it in items if it[0] == "sub" and it[1] == "Controlar otro PC")
        textos = [it[-1] if it[0] == "gray" else it[2] for it in sub[2] if it[0] != "sep"]
        self.assertTrue(any("SALON" in t for t in textos))
        self.assertIn("Añadir otro PC…", textos)
        self.assertIn("Permitir que otro PC controle este", textos)
        self.assertTrue(any(it[0] == "gray" and it[1].startswith("Dejar de controlar") for it in sub[2]))

    def test_etiqueta_del_aviso(self):
        self.assertEqual(aprobacion.device_label(UA), "PC · SALON")
        self.assertEqual(aprobacion.device_label("LaZoo-PC/0.70 (Linux; <script>)"), "PC · script")


class Entrega(unittest.TestCase):
    def test_version(self):
        self.assertEqual(lazo.VERSION, "0.74")
        self.assertEqual(pcapc.VERSION, "0.74")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.74")
        mesa = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
        self.assertIn('<p class="ver">0.74', mesa)
        for ident in ('id="pc-permitir"', 'id="pc-tecla"', 'id="otro-pc"', "/api/pcapc"):
            self.assertIn(ident, mesa)

    def test_apk_sin_cambios(self):
        manifest = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:versionCode="66"', manifest)

    def test_solo_biblioteca_estandar(self):
        src = (ROOT / "pcapc.py").read_text(encoding="utf-8")
        for mal in ("import pynput", "import requests", "import websocket"):
            self.assertNotIn(mal, src)


if __name__ == "__main__":
    unittest.main()
