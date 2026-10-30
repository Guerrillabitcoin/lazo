"""Pruebas de la 0.40: intercambiar pantallas, regla de 5 s en Anterior, iconos y pestañas."""

import unittest

import time

import control

_REAL_SLEEP = time.sleep

TWO = [{"x": 0, "y": 0, "w": 1920, "h": 1080, "primary": True}, {"x": 1920, "y": 0, "w": 1280, "h": 1024}]


class Swap(unittest.TestCase):
    def setUp(self):
        self.moves = []
        wins = [("a", (100, 100, 800, 600)), ("b", (2000, 50, 600, 400)), ("c", (5000, 0, 10, 10))]
        control.set_screens_hook(lambda: TWO)
        control.set_swap_hook(lambda what, *args: wins if what == "list" else self.moves.append(args))

    def tearDown(self):
        control.set_screens_hook(None)
        control.set_swap_hook(None)

    def test_swap(self):
        out = control.swap_screens(1, 2)
        self.assertEqual(sorted(self.moves), [("a", 2), ("b", 1)])
        self.assertEqual(out["moved"], 2)

    def test_one_screen(self):
        control.set_screens_hook(lambda: TWO[:1])
        with self.assertRaisesRegex(control.ControlError, "Solo hay una pantalla"):
            control.swap_screens()

    def test_bad_pair(self):
        with self.assertRaises(control.ControlError):
            control.swap_screens(1, 1)


class YoutubePrev(unittest.TestCase):
    def setUp(self):
        self.keys = []
        self.saved = {n: getattr(control, n) for n in ("_find_youtube_unlocked", "_focus_for_keys", "_yt_keys", "_yt_state")}
        control._find_youtube_unlocked = lambda: {"id": "1", "title": "Vídeo - YouTube - Google Chrome"}
        control._focus_for_keys = lambda _id: True
        control._yt_keys = lambda keys: self.keys.append(keys)
        self.pos = 30.0
        control._yt_state = lambda row: {"playing": True, "pos": self.pos, "len": 100, "real": True}
        control.time.sleep = lambda _s: None

    def tearDown(self):
        for n, v in self.saved.items():
            setattr(control, n, v)
        control.time.sleep = _REAL_SLEEP

    def test_restart_after_5s(self):
        out = control.youtube("prev")
        self.assertEqual(self.keys[-1], ["0"])
        self.assertEqual(out["detail"], "Al inicio del vídeo")

    def test_previous_before_5s(self):
        self.pos = 2.0
        out = control.youtube("prev")
        self.assertEqual(self.keys[-1], ["alt", "left"])
        self.assertEqual(out["detail"], "Vídeo anterior")

    def test_next_and_play(self):
        control.youtube("next")
        self.assertEqual(self.keys[-1], ["shift", "n"])
        out = control.youtube("play")
        self.assertIs(out["playing"], False)

    def test_status_no_keys(self):
        out = control.youtube("status")
        self.assertEqual(self.keys, [])
        self.assertIs(out["playing"], True)


class Tabs(unittest.TestCase):
    def test_uia_skips_page(self):
        self.assertIn("Document", control._UIA_PS)
        self.assertIn("Chrome_RenderWidgetHostHWND", control._UIA_PS)
        self.assertNotIn("TreeScope]::Descendants", control._UIA_PS)


if __name__ == "__main__":
    unittest.main()
