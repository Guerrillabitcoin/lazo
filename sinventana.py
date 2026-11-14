"""LaZoo 0.45: ningún programa auxiliar abre ventana de consola en Windows.

Con LaZoo.pyw / LaZoo.exe (sin consola propia), cada `ipconfig`, `powershell` o
`cmd` lanzado sin CREATE_NO_WINDOW creaba una ventana negra efímera: la barra de
tareas y Chrome parpadeaban y el foco saltaba. `install()` pone CREATE_NO_WINDOW
por defecto en todo subprocess.Popen (y por tanto run/check_output) de LaZoo.

0.75: además apunta qué programas lanza LaZoo (solo el nombre del programa, la hora y el hilo;
nunca argumentos) para `python3 linux_kvm.py --diagnostico`: «procesos del último minuto». En
Linux se guarda en ~/.cache/lazoo/procesos-recientes.txt (las últimas 200 líneas).
"""
from __future__ import annotations

import collections
import os
import subprocess
import sys
import threading
import time

CREATE_NO_WINDOW = 0x08000000
_installed = False


def flags() -> int:
    return CREATE_NO_WINDOW if sys.platform == "win32" else 0


MAX = 200
_lanzados: collections.deque = collections.deque(maxlen=MAX)  # (hora, programa, hilo)
_lock = threading.Lock()
_registrando = False


def ruta_registro() -> str:
    propia = os.environ.get("LAZO_REGISTRO_PROCESOS", "")
    if propia:
        return propia
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "lazoo", "procesos-recientes.txt")


def _programa(args: tuple, kwargs: dict) -> str:
    cmd = kwargs.get("args", args[0] if args else "")
    if isinstance(cmd, (list, tuple)):
        cmd = cmd[0] if cmd else ""
    elif kwargs.get("shell") and isinstance(cmd, str):
        cmd = cmd.split()[0] if cmd.split() else ""
    nombre = os.path.basename(os.fsdecode(cmd)) if cmd else "?"
    return "".join(c for c in nombre if c.isprintable() and c not in " \t")[:40] or "?"


def apuntar(programa: str, hilo: str | None = None, ahora: float | None = None) -> None:
    fila = (time.time() if ahora is None else ahora, programa, hilo or threading.current_thread().name)
    with _lock:
        _lanzados.append(fila)
        filas = list(_lanzados)
    escribir = os.environ.get("LAZO_REGISTRO_PROCESOS") or (
        sys.platform.startswith("linux") and "unittest" not in sys.modules and "pytest" not in sys.modules)
    if escribir:
        try:
            ruta = ruta_registro()
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            tmp = ruta + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(f"# LaZoo pid {os.getpid()}\n")
                for t, prog, h in filas:
                    f.write(f"{t:.3f}\t{prog}\t{h}\n")
            os.replace(tmp, ruta)
        except OSError:
            pass


def recientes(segundos: float = 60.0, ahora: float | None = None) -> list[tuple[float, str, str]]:
    ahora = time.time() if ahora is None else ahora
    with _lock:
        return [f for f in _lanzados if ahora - f[0] <= segundos]


def install() -> None:
    global _installed
    if _installed:
        return
    original = subprocess.Popen.__init__
    windows = sys.platform == "win32"

    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        if windows and not kwargs.get("creationflags"):
            kwargs["creationflags"] = CREATE_NO_WINDOW
        try:
            apuntar(_programa(args, kwargs))
        except Exception:  # noqa: BLE001 (apuntar nunca impide lanzar)
            pass
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = __init__  # type: ignore[method-assign]
    _installed = True
