"""LaZoo 0.47: ratón fino al ir despacio, suavizado en el PC y eco de diagnóstico (python3 test_v047.py)."""
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


class Version(unittest.TestCase):
    def test_version(self) -> None:
        self.assertGreaterEqual(tuple(int(x) for x in lazo.VERSION.split(".")), (0, 47))
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), lazo.VERSION)


class Reparto(unittest.TestCase):
    def test_suma_exacta(self) -> None:
        for dx, dy, n in [(4, 0, 4), (7, -3, 4), (-2, 1, 2), (3, 3, 3), (0, -4, 4)]:
            steps = control.split_move(dx, dy, n)
            self.assertEqual(sum(a for a, _ in steps), dx)
            self.assertEqual(sum(b for _, b in steps), dy)
            self.assertLessEqual(len(steps), n)


class Suavizado(unittest.TestCase):
    def setUp(self) -> None:
        self.sent: list[tuple[int, int]] = []
        self.p = mock.patch.object(control, "_dispatch_move", side_effect=lambda dx, dy: self.sent.append((dx, dy)))
        self.p.start()
        self.s = control.Smoother()
        self.s.set(True)

    def tearDown(self) -> None:
        self.s.set(False)
        self.p.stop()

    def test_reparte_en_pasos(self) -> None:
        self.assertTrue(self.s.push(8, 0))
        time.sleep(0.1)
        self.assertEqual(sum(a for a, _ in self.sent), 8)
        self.assertGreater(len(self.sent), 1)

    def test_un_pixel_va_directo(self) -> None:
        self.assertFalse(self.s.push(1, 0))  # 1 px: el llamador lo aplica tal cual

    def test_sin_retraso_acumulado(self) -> None:
        for _ in range(50):
            self.s.push(4, 4)
        self.s.flush()
        self.assertEqual(sum(a for a, _ in self.sent), 200)
        self.assertEqual(sum(b for _, b in self.sent), 200)

    def test_clic_vacia_antes(self) -> None:
        order = []
        self.s.push(40, 0)
        with mock.patch.object(control, "SMOOTHER", self.s), mock.patch.object(control, "_input") as inp:
            inp.return_value = (mock.Mock(click=lambda *a: order.append(sum(x for x, _ in self.sent))), None)
            control.mouse_click("left")
        self.assertEqual(order, [40])  # el clic llega con todo el movimiento ya hecho


class EcoPing(unittest.TestCase):
    def test_ping(self) -> None:
        a, b = socket.socketpair()
        pairing = mock.Mock(open=lambda blob: blob)
        moves = []
        t = threading.Thread(target=protocol.pointer_loop, args=(b, pairing, lambda x, y: moves.append((x, y)), "", False))
        t.start()
        ping = b"PING" + struct.pack("<d", 123.5)
        protocol.ws_send(a, 0x2, ping)
        op, data = protocol.ws_read(a)
        self.assertEqual((op, data), (0x2, ping))
        protocol.ws_send(a, 0x2, struct.pack("<ii", 1, 0))
        protocol.ws_send(a, 0x8, b"")
        t.join(2)
        self.assertEqual(moves, [(1, 0)])  # el ping NO mueve el ratón
        a.close(); b.close()


class Interfaz(unittest.TestCase):
    def test_controles(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        for needle in ('data-aim="fina"', 'data-aim="normal"', 'data-aim="rapida"', 'id="diag-out"', 'id="aim-smooth"'):
            self.assertIn(needle, html)
        self.assertIn("lazo-aim", js)
        self.assertIn('"smooth"', (ROOT / "lazo.py").read_text(encoding="utf-8"))

    def test_workflow(self) -> None:
        wf = ROOT / ".github" / "workflows" / "construir.yml"
        self.assertTrue(wf.exists())
        text = wf.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch", text)
        self.assertIn("windows-latest", text)


if __name__ == "__main__":
    unittest.main()
