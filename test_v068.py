"""LaZoo 0.68: Linux con Wayland (Ubuntu GNOME de hoy).

    python3 test_v068.py

- ydo.py: ratón y teclado por ydotool con los mismos métodos que pynput; texto raro pegado.
- control usa ydotool en Wayland aunque haya DISPLAY (XWayland) y busca YouTube por accesibilidad.
- YouTube en Linux sin teclas: MPRIS para play/±10 s/siguiente/anterior/inicio y botones del
  reproductor (silencio, subtítulos, cine, pantalla completa), volumen exacto con el deslizador.
- Sin pestaña Ventanas con un PC Linux; instalar-linux.sh prepara ydotool sin el grupo «input».
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("LAZO_DATOS", tempfile.mkdtemp())

ROOT = Path(__file__).resolve().parent

import control  # noqa: E402
import lazo  # noqa: E402
import linux_yt  # noqa: E402
import ydo  # noqa: E402
from test_v067 import N, T, pagina  # noqa: E402

JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
INST = (ROOT / "instalar-linux.sh").read_text(encoding="utf-8")


class Ydo(unittest.TestCase):
    def setUp(self):
        self.cmds = []
        self.run = lambda cmd, **kw: self.cmds.append(cmd) or SimpleNamespace(returncode=0)

    def test_raton(self):
        r = ydo.Raton(run=self.run, env={})
        r.move(5, -3)
        r.click("left", 2)
        r.click(SimpleNamespace(name="right"), 1)
        r.press("left")
        r.release("left")
        r.scroll(0, -1)
        self.assertEqual(self.cmds, [
            ["ydotool", "mousemove", "-x", "5", "-y", "-3"],
            ["ydotool", "click", "-r", "2", "-D", "60", "0xC0"],
            ["ydotool", "click", "-r", "1", "-D", "60", "0xC1"],
            ["ydotool", "click", "0x40"], ["ydotool", "click", "0x80"],
            ["ydotool", "mousemove", "-w", "-x", "0", "-y", "-1"]])

    def test_teclado_y_texto(self):
        pegados = []
        k = ydo.Teclado(run=self.run, env={}, pegar=lambda t: pegados.append(t) or True)
        k.press(SimpleNamespace(name="ctrl"))
        k.release("ctrl")
        k.tap("k")
        k.tap("+")
        k.type("hola 123")
        k.type(".")
        k.type("año, ¿qué?")
        self.assertEqual(self.cmds[:4], [["ydotool", "key", "29:1"], ["ydotool", "key", "29:0"],
                                         ["ydotool", "key", "37:1", "37:0"], ["ydotool", "key", "78:1", "78:0"]])
        self.assertIn(["ydotool", "type", "-d", "4", "--", "hola 123"], self.cmds)
        self.assertIn(["ydotool", "key", "52:1", "52:0"], self.cmds)
        self.assertEqual(pegados, ["año, ¿qué?"])  # con ñ y signos se pega, no se teclea

    def test_codigos_por_posicion(self):
        self.assertEqual((ydo.TECLAS["q"], ydo.TECLAS["a"], ydo.TECLAS["z"], ydo.TECLAS["m"]), (16, 30, 44, 50))
        self.assertEqual((ydo.TECLAS["1"], ydo.TECLAS["0"]), (2, 11))
        with self.assertRaises(OSError):
            ydo.Teclado(run=self.run, env={}).tap("é")

    def test_error_de_ydotool(self):
        r = ydo.Raton(run=lambda cmd, **kw: SimpleNamespace(returncode=1), env={})
        with self.assertRaises(OSError):
            r.move(1, 1)

    def test_socket_y_usable(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, ".ydotool_socket").write_text("")
            env = {"XDG_SESSION_TYPE": "wayland", "XDG_RUNTIME_DIR": d}
            self.assertEqual(ydo.socket_path(env), str(Path(d, ".ydotool_socket")))
            self.assertTrue(ydo.usable(env, which=lambda n: "/usr/bin/ydotool"))
            self.assertFalse(ydo.usable({**env, "XDG_SESSION_TYPE": "x11"}, which=lambda n: "/usr/bin/ydotool"))
            self.assertFalse(ydo.usable(env, which=lambda n: None))
        self.assertEqual(ydo.socket_path({"YDOTOOL_SOCKET": "/x/s"}), "/x/s")

    def test_control_lo_usa_en_wayland(self):
        self.assertEqual(control.backend_for("Linux", ":0", "wayland-0", True), "ydotool")
        self.assertEqual(control.backend_for("Linux", ":0", "wayland-0", False), "xtest")
        self.assertEqual(control.backend_for("Linux", ":0", None), "xtest")
        viejo = (control._mouse, control._keyboard)
        try:
            control._mouse = control._keyboard = None
            with mock.patch.object(control, "SYSTEM", "Linux"), mock.patch.object(ydo, "usable", lambda: True):
                m, k = control._input()
                self.assertIsInstance(m, ydo.Raton)
                self.assertIsInstance(k, ydo.Teclado)
                self.assertEqual(control._button("right"), "right")
        finally:
            control._mouse, control._keyboard = viejo


class YouTubeLinux(unittest.TestCase):
    def setUp(self):
        self.p = pagina()
        self.p.repro.kids += [N("push button", "Subtítulos (c)"), N("push button", "Modo cine (t)"),
                              N("push button", "Pantalla completa (f)")]
        self.t = T(self.p.raiz)
        self.t.fijar = lambda n, v: setattr(n, "val", (float(v), n.val[1])) or True
        self.l = linux_yt.Linux(arbol=self.t, sesiones=lambda: [], saltar=lambda *a: True, espera=lambda _s: None)
        self.mpris = []
        self.patches = [
            mock.patch.object(control, "SYSTEM", "Linux"),
            mock.patch.object(linux_yt, "LINUX", self.l),
            mock.patch.object(control, "_linux_windows", side_effect=control.ControlError("sin wmctrl")),
            mock.patch.object(control, "_mpris", lambda title, *a: self.mpris.append(a) or True),
            mock.patch.object(control, "_yt_state", lambda _r: {"playing": True, "pos": 100.0, "len": 600.0, "real": True}),
            mock.patch.object(control, "_focus_for_keys", lambda _i: self.fail("sin foco ni teclas")),
            mock.patch.object(control.time, "sleep", lambda _s: None),
        ]
        for x in self.patches:
            x.start()

    def tearDown(self):
        for x in self.patches:
            x.stop()

    def test_encuentra_youtube_sin_wmctrl(self):
        self.assertEqual(control.youtube("status")["title"], "Lentejas - YouTube - Brave")

    def test_mpris(self):
        for accion in ("play", "back", "forward", "next", "prev"):
            control.youtube(accion)
        self.assertEqual(self.mpris, [("play-pause",), ("position", "10-"), ("position", "10+"), ("next",), ("position", "0")])

    def test_botones_del_reproductor(self):
        btn = {n.name: n for n in self.p.repro.kids}
        control.youtube("captions")
        control.youtube("theater")
        control.youtube("mute")
        control.youtube("fullscreen")
        for nombre in ("Subtítulos (c)", "Modo cine (t)", "Silenciar (m)", "Pantalla completa (f)"):
            self.assertEqual(btn[nombre].pulsado, 1, nombre)

    def test_volumen_exacto(self):
        out = control.youtube("volume", {"level": 62})
        self.assertEqual((out["level"], out["vol_real"]), (62, True))
        self.assertEqual(self.p.vol.val[0], 62.0)
        control.youtube("volup")
        self.assertEqual(self.p.vol.val[0], 67.0)

    def test_wayland_avisa_en_lo_que_aun_no_va(self):
        with mock.patch.object(control, "_wayland", lambda: True):
            with self.assertRaises(control.ControlError) as e:
                control.youtube("subs_up")
            self.assertIn("Wayland", str(e.exception))


class Movil(unittest.TestCase):
    def test_sin_ventanas_en_linux(self):
        self.assertIn('const want = platform === "Linux" ? ["windows"] : [];', JS)
        self.assertIn("order.filter((id) => !hiddenTools.has(id))", JS)
        self.assertIn("// 0.68: las ocultas no se pierden", JS)
        self.assertEqual(JS.count("applyPlatform(data.platform);"), 2)


class Instalador(unittest.TestCase):
    def test_ydotool_sin_grupo_input(self):
        self.assertEqual(subprocess.run(["sh", "-n", str(ROOT / "instalar-linux.sh")]).returncode, 0)
        for pkg in ("wl-clipboard", "ydotool"):
            self.assertGreaterEqual(INST.count(pkg), 4, pkg)
        self.assertIn('GROUP="uinput"', INST)
        self.assertIn('usermod -aG uinput "$USER"', INST)
        self.assertNotIn("usermod -aG input ", INST)
        self.assertIn("--socket-path=%t/.ydotool_socket --socket-own=%U:%G", INST)
        self.assertIn("¿Lo preparo ahora? [s/N]", INST)
        self.assertIn("CIERRA SESIÓN", INST)
        self.assertTrue((ROOT / "docs" / "PRUEBAS-LINUX.md").is_file())


class Version(unittest.TestCase):
    def test_068(self):
        self.assertEqual(lazo.VERSION, "0.69")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("# LaZoo 0.69", readme)
        self.assertIn("**Novedad 0.68 (Linux con Wayland):**", readme)
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("ydo.py", agents)
        self.assertIn("test_v068.py", agents)


if __name__ == "__main__":
    unittest.main()
