"""LaZoo 0.48: diagnóstico de llegada, eco PIN2, vigilante y suavizado (python3 test_v048.py)."""
from __future__ import annotations

import socket
import struct
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import control  # noqa: E402
import lazo  # noqa: E402
import protocol  # noqa: E402


def run_loop(frames, gap_fn):
    """Cliente WS simulado: manda `frames` movimientos esperando gap_fn(i) segundos entre ellos."""
    a, b = socket.socketpair()
    arr = protocol.Arrivals()
    moves = []
    t = threading.Thread(target=protocol.pointer_loop, args=(b, mock.Mock(), lambda x, y: moves.append((x, y)), "", False, arr))
    t.start()
    for i in range(frames):
        protocol.ws_send(a, 0x2, struct.pack("<ii", 1, 0))
        time.sleep(gap_fn(i))
    time.sleep(0.05)
    snap = arr.snapshot(window=10)
    protocol.ws_send(a, 0x8, b"")
    t.join(2)
    a.close(); b.close()
    return snap, moves


class Version(unittest.TestCase):
    def test_version(self) -> None:
        self.assertEqual(lazo.VERSION, "0.48")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.48")


class Llegada(unittest.TestCase):
    def test_60hz_regular(self) -> None:
        snap, moves = run_loop(120, lambda i: 1 / 60)
        self.assertEqual(len(moves), 120)
        self.assertEqual(snap["frames"], 120)
        self.assertLess(snap["burst"], 0.2)
        self.assertEqual(snap["gaps100"], 0)
        self.assertGreater(snap["median_ms"], 10)

    def test_detecta_rafagas(self) -> None:
        # 6 tramas pegadas y luego 120 ms de silencio, como una Wi-Fi que retiene paquetes
        snap, moves = run_loop(60, lambda i: 0.12 if i % 6 == 5 else 0)
        self.assertEqual(len(moves), 60)
        self.assertGreater(snap["burst"], 0.5)
        self.assertGreaterEqual(snap["burst_max"], 5)
        self.assertGreaterEqual(snap["gaps100"], 8)
        self.assertGreaterEqual(snap["gaps50"], snap["gaps100"])

    def test_vacio(self) -> None:
        snap = protocol.Arrivals().snapshot()
        self.assertEqual(snap["frames"], 0)
        self.assertIsNone(snap["median_ms"])


class EcoPin2(unittest.TestCase):
    def test_horas_del_pc(self) -> None:
        a, b = socket.socketpair()
        moves = []
        t = threading.Thread(target=protocol.pointer_loop, args=(b, mock.Mock(), lambda x, y: moves.append((x, y)), "", False))
        t.start()
        ping = b"PIN2" + struct.pack("<d", 9.0)
        protocol.ws_send(a, 0x2, ping)
        op, data = protocol.ws_read(a)
        self.assertEqual(len(data), 28)
        self.assertEqual(data[:12], ping)
        recv, sent = struct.unpack("<dd", data[12:])
        self.assertGreaterEqual(sent, recv)
        protocol.ws_send(a, 0x8, b"")
        t.join(2)
        self.assertEqual(moves, [])
        a.close(); b.close()


class Vigilante(unittest.TestCase):
    def test_interruptor(self) -> None:
        v = control.Vigilante()
        self.assertFalse(v.set(False)["enabled"])
        self.assertFalse(v.status()["installed"])
        self.assertTrue(v.set(True)["enabled"])
        self.assertIn("avg_us", v.status())

    def test_variable_de_entorno(self) -> None:
        with mock.patch.dict("os.environ", {"LAZO_SIN_VIGILANTE": "1"}):
            self.assertFalse(control.Vigilante().enabled)

    def test_solo_con_cursor_grande(self) -> None:
        v = control.Vigilante()
        with mock.patch.object(control, "SYSTEM", "Windows"):
            with mock.patch.object(control, "_cursor_mode", "normal"):
                self.assertFalse(v.wanted())
            with mock.patch.object(control, "_cursor_mode", "large"):
                self.assertTrue(v.wanted())
                v.enabled = False
                self.assertFalse(v.wanted())

    def test_accion_y_ratón_siguen(self) -> None:
        self.assertIn("vigilante", lazo.ACTIONS)
        sent = []
        inp = mock.Mock()
        with mock.patch.object(control, "_dispatch_move", side_effect=lambda dx, dy: sent.append((dx, dy))), \
             mock.patch.object(control, "_input", return_value=(inp, None)):
            for on in (False, True, False):
                lazo.ACTIONS["vigilante"]({"on": on})
                control.move_mouse(3, -2)
                control.mouse_click("left")
                control.mouse_down("left"); control.move_mouse(5, 0); control.mouse_up("left")
                control.scroll_mouse(2)
        self.assertEqual(sent, [(3, -2), (5, 0)] * 3)
        control.VIGILANTE.enabled = True

    def test_diag_endpoint(self) -> None:
        data = lazo.mouse_diag()
        self.assertIn("llegada", data)
        self.assertIn("vigilante", data)


class Pausa(unittest.TestCase):
    def test_5ms(self) -> None:
        s = control.Smoother()
        s.set(True)  # en Windows sube la resolución del reloj (timeBeginPeriod)
        t0 = time.perf_counter()
        for _ in range(20):
            control._pause(0.005)
        per = (time.perf_counter() - t0) / 20
        s.set(False)
        self.assertLess(per, 0.0075)
        self.assertGreaterEqual(per, 0.0049)


class Interfaz(unittest.TestCase):
    def test_controles(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="diag-vigilante"', html)
        for needle in ("/api/diag/raton", "/api/vigilante", "PIN2", "lagWatch"):
            self.assertIn(needle, js)


if __name__ == "__main__":
    unittest.main()
