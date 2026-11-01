"""LaZoo 0.45: sin consolas que parpadean en Windows (python3 test_v045.py)."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import control  # noqa: E402
import lazo  # noqa: E402
import sinventana  # noqa: E402


class SinVentana(unittest.TestCase):
    def test_version(self) -> None:
        v = tuple(int(x) for x in lazo.VERSION.split("."))
        self.assertGreaterEqual(v, (0, 45))
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), lazo.VERSION)

    def test_install_pone_create_no_window(self) -> None:
        seen = {}
        orig = subprocess.Popen.__init__

        def fake(self, *a, **k):  # type: ignore[no-untyped-def]
            seen.update(k)
            raise OSError("no lanzar")

        with mock.patch.object(subprocess.Popen, "__init__", fake), \
             mock.patch.object(sys, "platform", "win32"), \
             mock.patch.object(sinventana, "_installed", False):
            sinventana.install()
            with self.assertRaises(OSError):
                subprocess.Popen(["ipconfig"])
            self.assertEqual(seen.get("creationflags"), 0x08000000)
        self.assertIs(subprocess.Popen.__init__, orig)

    def test_control_run_sin_ventana(self) -> None:
        with mock.patch.object(control, "_NO_WINDOW", 0x08000000), \
             mock.patch.object(control.subprocess, "run") as run:
            control._run_raw(["powershell"], 1)
            self.assertEqual(run.call_args.kwargs["creationflags"], 0x08000000)

    def test_ipconfig_cacheado(self) -> None:
        calls = []
        with mock.patch.object(lazo, "_ips_from_system_now", lambda: calls.append(1) or [("Wi-Fi", "192.168.1.5")]), \
             mock.patch.object(lazo, "_IPS_CACHE", (0.0, [])):
            for _ in range(20):
                lazo.connection_info()
        self.assertEqual(len(calls), 1, "la ventana del PC no debe lanzar ipconfig en cada sondeo")

    def test_ventana_no_sondea_oculta(self) -> None:
        html = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
        self.assertIn("if (!document.hidden) watchConn();", html)
        self.assertNotIn("setInterval(watchConn, 1500)", html)

    def test_lazo_carga_sinventana_primero(self) -> None:
        src = (ROOT / "lazo.py").read_text(encoding="utf-8")
        self.assertLess(src.index("sinventana.install()"), src.index("import control"))


if __name__ == "__main__":
    unittest.main()
