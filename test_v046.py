"""LaZoo 0.46: botón «Pantalla completa» en YouTube (python3 test_v046.py)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import control  # noqa: E402
import lazo  # noqa: E402

ROW = {"id": "1234", "title": "Vídeo - YouTube"}


class PantallaCompleta(unittest.TestCase):
    def setUp(self) -> None:
        control._yt["full"] = False

    def test_version(self) -> None:
        self.assertEqual(lazo.VERSION, "0.46")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.46")

    def test_covers_monitor(self) -> None:
        self.assertTrue(control.covers_monitor((0, 0, 1920, 1080), (0, 0, 1920, 1080)))
        self.assertTrue(control.covers_monitor((1920, 0, 3840, 1080), (1920, 0, 3840, 1080)))
        # maximizada: sobresale 8 px y deja la barra de tareas
        self.assertFalse(control.covers_monitor((-8, -8, 1928, 1040), (0, 0, 1920, 1080)))
        self.assertFalse(control.covers_monitor((0, 0, 0, 0), (0, 0, 0, 0)))

    def test_teclas(self) -> None:
        self.assertEqual(control.fullscreen_keys(False), ["f"])
        self.assertEqual(control.fullscreen_keys(True), ["escape"])

    def _run(self, real):
        sent = []
        with mock.patch.object(control, "_find_youtube_unlocked", return_value=ROW), \
             mock.patch.object(control, "_focus_for_keys", return_value=True) as focus, \
             mock.patch.object(control, "_win_is_fullscreen", return_value=real), \
             mock.patch.object(control, "_yt_keys", side_effect=sent.append), \
             mock.patch.object(control.time, "sleep"):
            out = control.youtube("fullscreen")
        focus.assert_called_with("1234")
        return out, sent

    def test_alternar_sin_dato_real(self) -> None:
        out, sent = self._run(None)
        self.assertEqual(sent, [["f"]])
        self.assertTrue(out["full"])
        out, sent = self._run(None)
        self.assertEqual(sent, [["escape"]])
        self.assertFalse(out["full"])

    def test_dato_real_manda(self) -> None:
        control._yt["full"] = False
        _out, sent = self._run(True)  # Windows dice que YA está a pantalla completa
        self.assertEqual(sent, [["escape"]])

    def test_sin_youtube(self) -> None:
        with mock.patch.object(control, "_find_youtube_unlocked", return_value=None):
            with self.assertRaises(control.ControlError):
                control.youtube("fullscreen")

    def test_no_rompe_play(self) -> None:
        sent = []
        with mock.patch.object(control, "_find_youtube_unlocked", return_value=ROW), \
             mock.patch.object(control, "_focus_for_keys", return_value=True), \
             mock.patch.object(control, "_yt_state", return_value={"playing": True, "pos": 10, "len": 99, "real": True}), \
             mock.patch.object(control, "_yt_keys", side_effect=sent.append), \
             mock.patch.object(control.time, "sleep"):
            control.youtube("play")
            control.youtube("prev")  # >5 s: al inicio
        self.assertEqual(sent, [["k"], ["0"]])

    def test_escape_en_windows_usa_tecla_virtual(self) -> None:
        calls = []
        with mock.patch.object(control, "SYSTEM", "Windows"), \
             mock.patch.object(control, "_win_hotkey", side_effect=lambda *v: calls.append(v)):
            control._yt_keys(["escape"])
        self.assertEqual(calls, [(0x1B,)])

    def test_ui(self) -> None:
        html = (ROOT / "static/index.html").read_text(encoding="utf-8")
        js = (ROOT / "static/app.js").read_text(encoding="utf-8")
        self.assertIn('id="yt-full"', html)
        self.assertIn("Pantalla completa", html)
        self.assertIn('action: "fullscreen"', js)
        self.assertIn("Salir de pantalla completa", js)


if __name__ == "__main__":
    unittest.main()
