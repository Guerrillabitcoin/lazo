"""LaZoo 0.45: ningún programa auxiliar abre ventana de consola en Windows.

Con LaZoo.pyw / LaZoo.exe (sin consola propia), cada `ipconfig`, `powershell` o
`cmd` lanzado sin CREATE_NO_WINDOW creaba una ventana negra efímera: la barra de
tareas y Chrome parpadeaban y el foco saltaba. `install()` pone CREATE_NO_WINDOW
por defecto en todo subprocess.Popen (y por tanto run/check_output) de LaZoo.
"""
from __future__ import annotations

import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000
_installed = False


def flags() -> int:
    return CREATE_NO_WINDOW if sys.platform == "win32" else 0


def install() -> None:
    global _installed
    if _installed or sys.platform != "win32":
        return
    original = subprocess.Popen.__init__

    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = CREATE_NO_WINDOW
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = __init__  # type: ignore[method-assign]
    _installed = True
