"""LaZoo 0.68: ratón y teclado en Linux con Wayland, por ydotool.

En Wayland un programa no puede mover el ratón ni pulsar teclas de otros con X11 (pynput). ydotool
lo hace a través del kernel (/dev/uinput), con su servicio `ydotoold`, que deja preparado
instalar-linux.sh. Aquí van un `Raton` y un `Teclado` con los mismos métodos que los de pynput, así
control.py los usa sin cambiar nada más: clic, doble clic, arrastre, rueda, teclas y atajos.

- Escribir texto: con letras, números y espacios, `ydotool type`. Con cualquier otra cosa (ñ,
  acentos, símbolos, emoji) ydotool se equivoca si el teclado no es inglés, así que se pega: se
  deja en el portapapeles con `wl-copy` y se pulsa Ctrl+V; el portapapeles de antes se restaura.
- Las teclas van por su posición física (códigos de Linux); en un teclado español las letras, los
  números, «,» y «.» están donde en el inglés. «+» y «-» van por el teclado numérico.

Necesita ydotool 1.x (con `ydotoold`). Nada sale a internet.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

# Botones de ydotool 1.x: 0 izquierdo, 1 derecho, 2 central; 0x40 = bajar, 0x80 = subir.
BOTONES = {"left": 0x00, "right": 0x01, "middle": 0x02}

# Códigos de tecla de Linux (input-event-codes.h), por posición física.
TECLAS = {
    "esc": 1, "escape": 1, "enter": 28, "return": 28, "backspace": 14, "tab": 15, "space": 57,
    "left": 105, "right": 106, "up": 103, "down": 108, "home": 102, "end": 107,
    "page_up": 104, "page_down": 109, "delete": 111, "insert": 110,
    "shift": 42, "shift_l": 42, "shift_r": 54, "ctrl": 29, "ctrl_l": 29, "ctrl_r": 97,
    "alt": 56, "alt_l": 56, "alt_r": 100, "alt_gr": 100, "cmd": 125, "cmd_l": 125, "cmd_r": 126,
    "caps_lock": 58, "menu": 127, "print_screen": 99,
    "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64, "f7": 65, "f8": 66, "f9": 67,
    "f10": 68, "f11": 87, "f12": 88,
    "media_play_pause": 164, "media_next": 163, "media_previous": 165,
    "media_volume_up": 115, "media_volume_down": 114, "media_volume_mute": 113,
    "+": 78, "-": 74, ",": 51, ".": 52,  # + y - del teclado numérico: valen con cualquier distribución
}
_LETRAS = "qwertyuiop", "asdfghjkl", "zxcvbnm"
for _fila, _inicio in zip(_LETRAS, (16, 30, 44)):
    for _i, _c in enumerate(_fila):
        TECLAS[_c] = _inicio + _i
for _i, _c in enumerate("1234567890"):
    TECLAS[_c] = 2 + _i
_SEGURO = re.compile(r"[A-Za-z0-9 ]*")


def socket_path(env: dict[str, str] | None = None) -> str:
    """Dónde escucha ydotoold: el del usuario (instalar-linux.sh) o el de siempre."""
    env = os.environ if env is None else env
    if env.get("YDOTOOL_SOCKET"):
        return env["YDOTOOL_SOCKET"]
    run = env.get("XDG_RUNTIME_DIR", "")
    if run and Path(run, ".ydotool_socket").exists():
        return str(Path(run, ".ydotool_socket"))
    return "/tmp/.ydotool_socket"


def usable(env: dict[str, str] | None = None, which: Callable[[str], str | None] = shutil.which) -> bool:
    """¿Wayland con ydotool listo? (si no, control.py sigue con pynput/X11 como antes)."""
    env = os.environ if env is None else env
    wayland = env.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(env.get("WAYLAND_DISPLAY"))
    return wayland and bool(which("ydotool")) and Path(socket_path(env)).exists()


def _nombre(x: Any) -> str:
    """Botón o tecla de pynput (Button.left, Key.enter, KeyCode 'a') o texto, a un nombre."""
    if isinstance(x, str):
        return x if len(x) == 1 else x.lower()
    char = getattr(x, "char", None)
    if char:
        return str(char)
    nombre = getattr(x, "name", None)
    return str(nombre or x).lower().split(".")[-1]


class _Base:
    def __init__(self, run: Callable[..., Any] | None = None, env: dict[str, str] | None = None) -> None:
        self.env = dict(os.environ if env is None else env)
        self.env["YDOTOOL_SOCKET"] = socket_path(self.env)
        self.run = run or (lambda cmd, **kw: subprocess.run(cmd, env=self.env, capture_output=True, timeout=5, **kw))

    def ydo(self, *args: str) -> None:
        res = self.run(["ydotool", *args])
        if getattr(res, "returncode", 0) != 0:
            raise OSError("ydotool falló: " + " ".join(args))


class Raton(_Base):
    def move(self, dx: int, dy: int) -> None:
        self.ydo("mousemove", "-x", str(int(dx)), "-y", str(int(dy)))

    def click(self, button: Any, count: int = 1) -> None:
        code = 0xC0 | BOTONES.get(_nombre(button), 0)
        self.ydo("click", "-r", str(max(1, int(count))), "-D", "60", f"0x{code:02X}")

    def press(self, button: Any) -> None:
        self.ydo("click", f"0x{0x40 | BOTONES.get(_nombre(button), 0):02X}")

    def release(self, button: Any) -> None:
        self.ydo("click", f"0x{0x80 | BOTONES.get(_nombre(button), 0):02X}")

    def scroll(self, dx: int, dy: int) -> None:
        self.ydo("mousemove", "-w", "-x", str(int(dx)), "-y", str(int(dy)))


class Teclado(_Base):
    def __init__(self, *a: Any, pegar: Callable[[str], bool] | None = None, **k: Any) -> None:
        super().__init__(*a, **k)
        self.pegar = pegar or self._pegar

    def _code(self, key: Any) -> int:
        nombre = _nombre(key)
        code = TECLAS.get(nombre.lower() if len(nombre) == 1 else nombre)
        if code is None:
            raise OSError(f"tecla sin código: {nombre}")
        return code

    def press(self, key: Any) -> None:
        self.ydo("key", f"{self._code(key)}:1")

    def release(self, key: Any) -> None:
        self.ydo("key", f"{self._code(key)}:0")

    def tap(self, key: Any) -> None:
        c = self._code(key)
        self.ydo("key", f"{c}:1", f"{c}:0")

    def type(self, text: str) -> None:
        if not text:
            return
        if _SEGURO.fullmatch(text):
            self.ydo("type", "-d", "4", "--", text)
            return
        if len(text) == 1 and text in TECLAS:
            self.tap(text)
            return
        if not self.pegar(text):
            raise OSError("no pude escribir ese texto (falta wl-clipboard)")

    def _pegar(self, text: str) -> bool:
        """Deja el texto en el portapapeles, pulsa Ctrl+V y devuelve el portapapeles de antes."""
        if not (shutil.which("wl-copy") and shutil.which("wl-paste")):
            return False
        try:
            import control

            control._mark_injected(text)  # que no entre en las notas como copiado
        except Exception:  # noqa: BLE001
            pass
        antes = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, timeout=3, env=self.env)
        subprocess.run(["wl-copy", "--", text], timeout=3, env=self.env)
        time.sleep(0.05)
        self.ydo("key", "29:1", "47:1", "47:0", "29:0")
        time.sleep(0.2)
        if antes.returncode == 0:
            subprocess.run(["wl-copy"], input=antes.stdout, timeout=3, env=self.env)
        return True
