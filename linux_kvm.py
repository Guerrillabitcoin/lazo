"""LaZoo 0.71: Linux en «Controlar otro PC» (pcapc.py). Solo biblioteca estándar.

Receptor (otro PC controla este Linux)
    Se elige solo, en cadena. Xorg: XTest por ctypes (sin permisos) → uinput → xdotool.
    Wayland: uinput → ydotool (sintaxis de su versión). Con uinput: un ratón y un teclado VIRTUALES propios en /dev/uinput (ioctl, sin programas de
    fuera): movimientos RELATIVOS de verdad, botones, rueda (también de alta resolución) y teclas
    por su código del kernel. Vale en X11 y en Wayland, y GNOME enseña el cursor porque hay un
    dispositivo de puntero. Necesita permiso de escritura en /dev/uinput (instalar-linux.sh pone
    una regla udev y el grupo «uinput»; luego hay que cerrar sesión).
    Sin ese permiso: en X11, XTest (o xdotool); en Wayland, ydotool SEGÚN SU VERSIÓN:
        - ydotool 1.x: `mousemove -x DX -y DY` es relativo (`-a`/`--absolute` es absoluto),
          `click 0x40|b` / `0x80|b` baja y sube, `key CÓDIGO:1` / `CÓDIGO:0`.
        - ydotool 0.1.x (Ubuntu 22.04 y 24.04, Debian 12): `mousemove X Y` es ABSOLUTO (primero
          lleva el puntero a la esquina de arriba a la izquierda y luego a X,Y) y espera 100 ms;
          el relativo es `mousemove_relative`. No entiende `-x/-y`, ni `0x40`, ni `CÓDIGO:1`.
          Esa mezcla era el fallo de la 0.70: «parece conectar, pero el ratón no aparece o se va a
          una esquina». En Wayland sin ydotool usable, XTest de XWayland mueve un puntero que no
          se ve. Por eso ahora: uinput primero, ydotool con la sintaxis de SU versión, y nunca
          XTest en Wayland.

Emisor (este Linux controla otro PC)
    Xorg: XGrabKey + XGrabKeyboard/XGrabPointer por ctypes (sin permisos). Si no (Wayland):
    evdev: lee /dev/input/event* (teclados, ratones y touchpads) y, mientras controla, los coge
    en exclusiva con EVIOCGRAB: el escritorio no ve nada (X11 y Wayland). Necesita leer
    /dev/input (grupo «input»; instalar-linux.sh --pcapc lo prepara en un paso). En Wayland sin
    ese permiso no se puede capturar.
    Antes de coger los dispositivos espera a que sueltes las teclas de la tecla rápida (si no, el
    escritorio las daría por pulsadas). Ctrl+Alt+Esc suelta el «grab» en el mismo hilo que lee,
    sin esperar a nada. También se suelta si se cae la conexión o falta el latido, y siempre al
    cerrar (el kernel lo suelta si LaZoo muere).

    python3 linux_kvm.py --diagnostico   dice qué método se usa para cada cosa y por qué.
"""

from __future__ import annotations

import glob
import os
import re
import select
import shutil
import struct
import subprocess
import sys
import threading
import time
from typing import Any, Callable

# --- ioctl de Linux ---------------------------------------------------------------------------


def _ioc(d: int, t: str, nr: int, size: int) -> int:
    return (d << 30) | (size << 16) | (ord(t) << 8) | nr


UI_SET_EVBIT = _ioc(1, "U", 100, 4)
UI_SET_KEYBIT = _ioc(1, "U", 101, 4)
UI_SET_RELBIT = _ioc(1, "U", 102, 4)
UI_DEV_CREATE = _ioc(0, "U", 1, 0)
UI_DEV_DESTROY = _ioc(0, "U", 2, 0)
UI_DEV_SETUP = _ioc(1, "U", 3, 92)
EVIOCGRAB = _ioc(1, "E", 0x90, 4)


def EVIOCGNAME(n: int) -> int:  # noqa: N802
    return _ioc(2, "E", 0x06, n)


def EVIOCGPROP(n: int) -> int:  # noqa: N802
    return _ioc(2, "E", 0x09, n)


def EVIOCGKEY(n: int) -> int:  # noqa: N802
    return _ioc(2, "E", 0x18, n)


def EVIOCGBIT(ev: int, n: int) -> int:  # noqa: N802
    return _ioc(2, "E", 0x20 + ev, n)


def EVIOCGABS(eje: int) -> int:  # noqa: N802
    return _ioc(2, "E", 0x40 + eje, 24)


EV_SYN, EV_KEY, EV_REL, EV_ABS, EV_MSC = 0, 1, 2, 3, 4
SYN_REPORT = 0
REL_X, REL_Y, REL_HWHEEL, REL_WHEEL, REL_WHEEL_HI_RES, REL_HWHEEL_HI_RES = 0, 1, 6, 8, 11, 12
ABS_X, ABS_Y = 0, 1
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA, BTN_FORWARD, BTN_BACK = 0x110, 0x111, 0x112, 0x113, 0x114, 0x115, 0x116
BTN_TOOL_FINGER, BTN_TOUCH, BTN_TOOL_DOUBLETAP, BTN_TOOL_TRIPLETAP, BTN_TOOL_QUADTAP = 0x145, 0x14A, 0x14D, 0x14E, 0x14F
KEY_ESC, KEY_A, KEY_SPACE = 1, 30, 57
KEY_MAX_LAZO = 248
INPUT_PROP_DIRECT = 1
BUS_VIRTUAL = 0x06
EVENTO = struct.Struct("llHHi")  # struct input_event: timeval (2 long), tipo, código, valor
NOMBRE_DISPOSITIVO = "LaZoo PC a PC"

# Botones de pcapc (1 izq, 2 der, 3 central, 4 atrás, 5 adelante) <-> códigos del kernel
BOTON_A_EVDEV = {1: BTN_LEFT, 2: BTN_RIGHT, 3: BTN_MIDDLE, 4: BTN_SIDE, 5: BTN_EXTRA}
EVDEV_A_BOTON = {BTN_LEFT: 1, BTN_RIGHT: 2, BTN_MIDDLE: 3, BTN_SIDE: 4, BTN_EXTRA: 5, BTN_BACK: 4, BTN_FORWARD: 5}


def _bit(buf: bytes, n: int) -> bool:
    return len(buf) > n // 8 and bool(buf[n // 8] & (1 << (n % 8)))


# --- Teclas: código del kernel (evdev) -> tecla de Windows (vk, scan, extendida) ----------------


def _tabla_evdev_a_windows() -> dict[int, tuple[int, int, bool]]:
    import pcapc

    t: dict[int, tuple[int, int, bool]] = {}
    for scan in range(1, 89):  # juego 1: del Esc (1) al F12 (88) el código coincide
        t[scan] = (0, scan, False)
    for scan, code in pcapc._OTRAS_EVDEV.items():
        t[code] = (0, scan, False)
    for scan, code in pcapc._EXT_EVDEV.items():
        t[code] = (0, scan, True)
    vks = {1: 0x1B, 14: 0x08, 15: 0x09, 28: 0x0D, 29: 0xA2, 42: 0xA0, 54: 0xA1, 56: 0xA4, 57: 0x20, 58: 0x14,
           97: 0xA3, 100: 0xA5, 125: 0x5B, 126: 0x5C, 127: 0x5D, 103: 0x26, 108: 0x28, 105: 0x25, 106: 0x27,
           102: 0x24, 107: 0x23, 104: 0x21, 109: 0x22, 110: 0x2D, 111: 0x2E, 99: 0x2C, 70: 0x91}
    for fila, inicio in (("QWERTYUIOP", 16), ("ASDFGHJKL", 30), ("ZXCVBNM", 44)):
        for i, c in enumerate(fila):
            vks[inicio + i] = ord(c)
    for i, c in enumerate("1234567890"):
        vks[2 + i] = ord(c)
    for i in range(10):
        vks[59 + i] = 0x70 + i  # F1-F10
    vks[87], vks[88] = 0x7A, 0x7B  # F11, F12
    for code, vk in vks.items():
        if code in t:
            t[code] = (vk, t[code][1], t[code][2])
    # Bloq Num y Pausa comparten el 0x45: Bloq Num va extendida, Pausa por su vk.
    t[69] = (0x90, 0x45, True)
    t[119] = (0x13, 0x45, False)
    media = {113: 0xAD, 114: 0xAE, 115: 0xAF, 163: 0xB0, 165: 0xB1, 166: 0xB2, 164: 0xB3, 158: 0xA6, 159: 0xA7}
    for code, vk in media.items():
        if code in t:
            t[code] = (vk, t[code][1], True)
    return t


_EVDEV_WIN: dict[int, tuple[int, int, bool]] = {}


def windows_de_evdev(code: int) -> tuple[int, int, bool] | None:
    """(vk, scan, extendida) de Windows para un código de tecla del kernel. None = no se manda."""
    if not _EVDEV_WIN:
        _EVDEV_WIN.update(_tabla_evdev_a_windows())
    return _EVDEV_WIN.get(int(code))


def evdev_de_vk(vk: int) -> int | None:
    """La tecla rápida (vk de Windows: letra, número o F1-F12) a su código del kernel."""
    if 0x41 <= vk <= 0x5A:
        c = chr(vk)
        for fila, inicio in (("QWERTYUIOP", 16), ("ASDFGHJKL", 30), ("ZXCVBNM", 44)):
            if c in fila:
                return inicio + fila.index(c)
    if 0x30 <= vk <= 0x39:
        return 11 if vk == 0x30 else 2 + vk - 0x31
    if 0x70 <= vk <= 0x79:
        return 59 + vk - 0x70
    if vk in (0x7A, 0x7B):
        return 87 + vk - 0x7A
    return None


CTRL_EV, ALT_EV, SHIFT_EV, WIN_EV = (29, 97), (56, 100), (42, 54), (125, 126)


def mods_de_evdev(abajo: set[int]) -> int:
    import pcapc

    m = 0
    for codigos, bit in ((CTRL_EV, pcapc.MOD_CONTROL), (ALT_EV, pcapc.MOD_ALT), (SHIFT_EV, pcapc.MOD_SHIFT), (WIN_EV, pcapc.MOD_WIN)):
        if abajo & set(codigos):
            m |= bit
    return m


# --- Receptor: inyectores -----------------------------------------------------------------------


class InyectorUinput:
    """Ratón y teclado virtuales propios en /dev/uinput. Movimiento relativo de verdad, sin
    procesos por evento (latencia ~0). Lo ve el escritorio como un ratón USB más."""

    lento = False
    metodo = "uinput"

    def __init__(self, ruta: str = "/dev/uinput", ioctl: Callable[..., Any] | None = None,
                 abrir: Callable[..., int] = os.open, escribir: Callable[[int, bytes], int] = os.write,
                 esperar: float = 0.3) -> None:
        if ioctl is None:
            import fcntl

            ioctl = fcntl.ioctl
        self.escribir = escribir
        self.resto = [0, 0]
        fd = abrir(ruta, os.O_WRONLY)
        try:
            ioctl(fd, UI_SET_EVBIT, EV_KEY)
            ioctl(fd, UI_SET_EVBIT, EV_REL)
            for k in range(1, KEY_MAX_LAZO + 1):
                ioctl(fd, UI_SET_KEYBIT, k)
            for b in BOTON_A_EVDEV.values():
                ioctl(fd, UI_SET_KEYBIT, b)
            for r in (REL_X, REL_Y, REL_HWHEEL, REL_WHEEL, REL_WHEEL_HI_RES, REL_HWHEEL_HI_RES):
                ioctl(fd, UI_SET_RELBIT, r)
            nombre = NOMBRE_DISPOSITIVO.encode()
            try:
                ioctl(fd, UI_DEV_SETUP, struct.pack("<HHHH80sI", BUS_VIRTUAL, 0x4C5A, 0x0071, 1, nombre, 0))
            except OSError:  # núcleo anterior a 4.5: struct uinput_user_dev
                escribir(fd, struct.pack("<80sHHHHI", nombre, BUS_VIRTUAL, 0x4C5A, 0x0071, 1, 0) + bytes(4 * 64 * 4))
            ioctl(fd, UI_DEV_CREATE)
        except BaseException:
            os.close(fd) if abrir is os.open else None
            raise
        self.fd = fd
        if esperar:
            time.sleep(esperar)  # el escritorio tarda un momento en ver el dispositivo nuevo

    def _mandar(self, *eventos: tuple[int, int, int]) -> None:
        datos = b"".join(EVENTO.pack(0, 0, t, c, v) for t, c, v in eventos) + EVENTO.pack(0, 0, EV_SYN, SYN_REPORT, 0)
        self.escribir(self.fd, datos)

    def mover(self, dx: int, dy: int) -> None:
        ev = []
        if dx:
            ev.append((EV_REL, REL_X, int(dx)))
        if dy:
            ev.append((EV_REL, REL_Y, int(dy)))
        if ev:
            self._mandar(*ev)

    def boton(self, b: int, abajo: bool) -> None:
        self._mandar((EV_KEY, BOTON_A_EVDEV[b], 1 if abajo else 0))

    def rueda(self, eje: int, delta: int) -> None:
        """Alta resolución (120 = una muesca, como Windows) y la muesca clásica cuando se completa."""
        import pcapc

        hi = REL_HWHEEL_HI_RES if eje else REL_WHEEL_HI_RES
        ev = [(EV_REL, hi, int(delta))]
        pasos = pcapc.pasos_rueda(self.resto, eje, delta)
        if pasos:
            ev.append((EV_REL, REL_HWHEEL if eje else REL_WHEEL, sum(pasos)))
        self._mandar(*ev)

    def tecla(self, vk: int, scan: int, ext: bool, abajo: bool) -> None:
        import pcapc

        code = pcapc.evdev(vk, scan, ext)
        if code is not None:
            self._mandar((EV_KEY, code, 1 if abajo else 0))

    def cerrar(self) -> None:
        try:
            import fcntl

            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        except Exception:  # noqa: BLE001
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass


def version_ydotool(texto: str) -> str:
    """De la ayuda de `ydotool mousemove --help`: "1" (1.x), "0.1" (0.1.x) o "" (no se sabe)."""
    t = str(texto or "").lower()
    if "--xpos" in t or "--absolute" in t or "-x <xpos>" in t:
        return "1"
    if "mousemove_relative" in t or "<x> <y>" in t or ("--delay" in t and "mousemove" in t):
        return "0.1"
    return ""


def detectar_ydotool(run: Callable[..., Any] | None = None) -> str:
    if not shutil.which("ydotool"):
        return ""
    run = run or (lambda cmd: subprocess.run(cmd, capture_output=True, text=True, timeout=3))
    try:
        r = run(["ydotool", "mousemove", "--help"])
        texto = (getattr(r, "stdout", "") or "") + (getattr(r, "stderr", "") or "")
    except (OSError, subprocess.SubprocessError):
        return ""
    v = version_ydotool(texto)
    if not v:
        try:
            r = run(["ydotool"])
            v = version_ydotool((getattr(r, "stdout", "") or "") + (getattr(r, "stderr", "") or ""))
        except (OSError, subprocess.SubprocessError):
            v = ""
    return v


def orden_ydotool(version: str, accion: str, *a: int) -> list[str] | None:
    """Los argumentos de ydotool para una acción, con la sintaxis de ESA versión. None = no se puede.
    acciones: mover(dx, dy) · boton(b, abajo) · rueda(eje, muescas) · tecla(código, abajo)."""
    if version == "1":
        if accion == "mover":
            return ["mousemove", "-x", str(int(a[0])), "-y", str(int(a[1]))]  # relativo en 1.x
        if accion == "boton":
            codigo = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4}[a[0]]
            return ["click", f"0x{(0x40 if a[1] else 0x80) | codigo:02X}"]
        if accion == "rueda":
            return ["mousemove", "-w", "-x", str(int(a[1]) if a[0] else 0), "-y", str(0 if a[0] else int(a[1]))]
        if accion == "tecla":
            return ["key", f"{int(a[0])}:{1 if a[1] else 0}"]
        return None
    if version == "0.1":
        if accion == "mover":  # `mousemove` es ABSOLUTO en 0.1.x: el relativo es este
            return ["mousemove_relative", "--delay", "0", "--", str(int(a[0])), str(int(a[1]))]
        if accion == "boton" and a[1] and a[0] in (1, 2, 3):
            return ["click", "--delay", "0", str(a[0])]  # 0.1.x: 1 izq, 2 der, 3 central; solo clic entero
        return None  # 0.1.x no baja/sube botones ni teclas por separado, ni tiene rueda
    return None


class InyectorYdotool:
    """Respaldo en Wayland sin permiso en /dev/uinput. Un proceso por orden: el receptor junta
    los movimientos mientras tanto (`lento`)."""

    lento = True
    metodo = "ydotool"

    def __init__(self, version: str, base: Any = None) -> None:
        if base is None:
            import ydo

            base = ydo._Base()
        self.version = version
        self.b = base
        self.resto = [0, 0]

    def _orden(self, accion: str, *a: int) -> None:
        args = orden_ydotool(self.version, accion, *a)
        if args:
            self.b.ydo(*args)

    def mover(self, dx: int, dy: int) -> None:
        self._orden("mover", dx, dy)

    def boton(self, b: int, abajo: bool) -> None:
        self._orden("boton", b, abajo)

    def rueda(self, eje: int, delta: int) -> None:
        import pcapc

        pasos = pcapc.pasos_rueda(self.resto, eje, delta)
        if pasos:
            self._orden("rueda", eje, sum(pasos))

    def tecla(self, vk: int, scan: int, ext: bool, abajo: bool) -> None:
        import pcapc

        code = pcapc.evdev(vk, scan, ext)
        if code is not None:
            self._orden("tecla", code, abajo)


def orden_xdotool(accion: str, *a: int) -> list[str] | None:
    """xdotool (X11). Con números negativos hace falta `--` o los toma por opciones."""
    if accion == "mover":
        return ["xdotool", "mousemove_relative", "--", str(int(a[0])), str(int(a[1]))]
    if accion == "boton":
        return ["xdotool", "mousedown" if a[1] else "mouseup", str({1: 1, 2: 3, 3: 2, 4: 8, 5: 9}[a[0]])]
    if accion == "rueda":  # a = (botón de X 4/5/6/7, veces)
        return ["xdotool", "click", "--repeat", str(max(1, int(a[1]))), str(int(a[0]))]
    return None


class InyectorXdotool:
    """X11 sin libXtst por ctypes: xdotool (ratón; las teclas necesitan XTest)."""

    lento = True
    metodo = "xdotool"

    def __init__(self, run: Callable[..., Any] | None = None) -> None:
        self.run = run or (lambda cmd: subprocess.run(cmd, capture_output=True, timeout=3))
        self.resto = [0, 0]

    def mover(self, dx: int, dy: int) -> None:
        self.run(orden_xdotool("mover", dx, dy))

    def boton(self, b: int, abajo: bool) -> None:
        self.run(orden_xdotool("boton", b, abajo))

    def rueda(self, eje: int, delta: int) -> None:
        import pcapc

        pasos = pcapc.pasos_rueda(self.resto, eje, delta, x11=True)
        if pasos:
            self.run(orden_xdotool("rueda", pasos[0], len(pasos)))

    def tecla(self, vk: int, scan: int, ext: bool, abajo: bool) -> None:
        return None


# --- Diagnóstico ---------------------------------------------------------------------------------


def sesion(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    tipo = str(env.get("XDG_SESSION_TYPE", "")).lower()
    if tipo == "wayland" or env.get("WAYLAND_DISPLAY"):
        return "wayland"
    if tipo == "x11" or env.get("DISPLAY"):
        return "x11"
    return "ninguna"


def uinput_escribible(ruta: str = "/dev/uinput") -> bool:
    return os.path.exists(ruta) and os.access(ruta, os.W_OK)


def _grupos() -> list[str]:
    try:
        import grp

        return sorted({grp.getgrgid(g).gr_name for g in os.getgroups()})
    except (ImportError, KeyError, OSError):
        return []


def _libxtst() -> bool:
    try:
        import ctypes

        ctypes.CDLL("libXtst.so.6")
        return True
    except OSError:
        return False


def eventos_legibles() -> tuple[int, int]:
    """(cuántos /dev/input/event* hay, cuántos se pueden leer)."""
    rutas = glob.glob("/dev/input/event*")
    return len(rutas), sum(1 for r in rutas if os.access(r, os.R_OK))


def elegir_receptor(ses: str, uinput: bool, xtst: bool, ydotool: str, ydotool_listo: bool, xdotool: bool) -> tuple[str, str]:
    """(método, por qué). Método "" = no se puede (el por qué dice qué hacer). En Xorg, XTest
    primero (no pide ningún permiso); en Wayland, uinput (XTest ahí movería un puntero invisible)."""
    if ses == "x11":
        if xtst:
            return "xtest", "Xorg con XTest (sin permisos extra)."
        if uinput:
            return "uinput", "Xorg sin libXtst: ratón y teclado virtuales de LaZoo en /dev/uinput."
        if xdotool:
            return "xdotool", "Xorg con xdotool (solo ratón; para el teclado falta libXtst)."
        return "", "Xorg sin XTest ni xdotool: ejecuta «sh instalar-linux.sh» (instala libxtst y xdotool)."
    if uinput:
        return "uinput", "Ratón y teclado virtuales de LaZoo en /dev/uinput: relativo, sin retraso."
    if ses == "wayland":
        if ydotool == "1" and ydotool_listo:
            return "ydotool", "Wayland con ydotool 1.x (más lento que uinput). Mejor: sh instalar-linux.sh --pcapc y cerrar sesión."
        if ydotool == "0.1" and ydotool_listo:
            return "ydotool", ("Wayland con ydotool 0.1.x: SOLO mover y clic (sin teclas, rueda ni arrastrar). "
                               "Para todo: sh instalar-linux.sh --pcapc y cerrar sesión (usa /dev/uinput).")
        return "", ("Wayland sin permiso en /dev/uinput (y sin ydotool listo): el ratón no se movería de verdad. "
                    "Pulsa «Arreglar» en el Panel (o: sh instalar-linux.sh --pcapc) y cierra sesión.")
    return "", "No hay sesión gráfica."


def elegir_emisor(ses: str, legibles: int, xlib: bool) -> tuple[str, str]:
    """En Xorg, X11 primero (XGrabKeyboard/XGrabPointer, sin permisos). En Wayland, evdev."""
    if ses == "x11" and xlib:
        return "x11", "Xorg: XGrabKey y XGrabKeyboard/XGrabPointer (sin permisos extra)."
    if legibles:
        return "evdev", "Teclado y ratón por /dev/input con EVIOCGRAB (vale también en Wayland)."
    if ses == "wayland":
        return "", ("En Wayland hace falta leer /dev/input para capturar el ratón y el teclado: "
                    "pulsa «Arreglar» en el Panel (o: sh instalar-linux.sh --pcapc) y cierra sesión.")
    return "", "Sin permiso en /dev/input ni sesión X11: este PC no puede controlar otro."


def diagnostico(env: dict | None = None) -> dict:
    ses = sesion(env)
    ui = uinput_escribible()
    xt = _libxtst() if ses == "x11" else False
    yv = detectar_ydotool() if ses == "wayland" else ""
    try:
        import ydo

        ylisto = ydo.usable(env)
    except Exception:  # noqa: BLE001
        ylisto = False
    total, legibles = eventos_legibles()
    rec, rec_por = elegir_receptor(ses, ui, xt, yv, ylisto, bool(shutil.which("xdotool")))
    emi, emi_por = elegir_emisor(ses, legibles, _libx11() if ses == "x11" else False)
    return {"sesion": ses, "uinput": {"existe": os.path.exists("/dev/uinput"), "escribible": ui},
            "ydotool": {"version": yv or ("no está" if not shutil.which("ydotool") else "desconocida"), "listo": ylisto},
            "xtest": xt, "eventos": {"total": total, "legibles": legibles}, "grupos": _grupos(),
            "receptor": rec or "ninguno", "receptor_por": rec_por, "emisor": emi or "ninguno", "emisor_por": emi_por,
            "arreglable": ses != "ninguna" and (not rec or not emi)}


def falta(d: dict) -> str:
    """Lo que falta para que todo vaya, en una frase ("" = nada)."""
    if d["receptor"] == "ninguno" and d["emisor"] == "ninguno":
        return "Faltan permisos para que otro PC controle este y para controlar otro desde este."
    if d["receptor"] == "ninguno":
        return "Falta permiso para que otro PC controle este."
    if d["emisor"] == "ninguno":
        return "Falta permiso para controlar otro PC desde este."
    return ""


def arreglar(popen: Callable[..., Any] = subprocess.Popen, which: Callable[[str], Any] = shutil.which) -> dict:
    """El botón «Arreglar» del Panel: los permisos de instalar-linux.sh en un paso, con pkexec
    (pide la contraseña en una ventana). Devuelve {"ok", "mensaje"}."""
    import getpass

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instalar-linux.sh")
    usuario = getpass.getuser()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,32}", usuario or ""):
        return {"ok": False, "mensaje": "No sé tu nombre de usuario: ejecuta «sh instalar-linux.sh --pcapc» en una terminal."}
    if not which("pkexec"):
        return {"ok": False, "mensaje": f"Ejecuta en una terminal: sh {script} --pcapc (y luego cierra sesión)."}
    try:
        popen(["pkexec", "sh", script, "--permisos-root", usuario], stdin=subprocess.DEVNULL,
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return {"ok": False, "mensaje": f"Ejecuta en una terminal: sh {script} --pcapc (y luego cierra sesión)."}
    return {"ok": True, "mensaje": "Escribe tu contraseña en la ventana que sale. Después, cierra sesión y vuelve a entrar."}


def _libx11() -> bool:
    try:
        import ctypes

        ctypes.CDLL("libX11.so.6")
        return True
    except OSError:
        return False


def texto_diagnostico(d: dict) -> str:
    return "\n".join([
        f"Sesión: {d['sesion']}",
        f"/dev/uinput: {'se puede escribir' if d['uinput']['escribible'] else 'existe, sin permiso' if d['uinput']['existe'] else 'no existe'}",
        f"ydotool: {d['ydotool']['version']}{' (servicio listo)' if d['ydotool']['listo'] else ''}",
        f"/dev/input: {d['eventos']['legibles']} de {d['eventos']['total']} se pueden leer",
        f"Grupos: {', '.join(d['grupos']) or '—'}",
        f"Que otro PC controle este: {d['receptor']} — {d['receptor_por']}",
        f"Controlar otro PC desde este: {d['emisor']} — {d['emisor_por']}",
    ])


def inyector_linux() -> Any:
    """El inyector de este Linux, o pcapc.ErrorPC con el motivo y qué hacer."""
    import pcapc

    ses = sesion()
    if ses == "x11":  # 1) XTest  2) uinput  3) xdotool
        try:
            iny = pcapc.InyectorX11()
            iny.metodo = "xtest"
            return iny
        except OSError:
            pass
    if uinput_escribible():
        try:
            return InyectorUinput()
        except OSError:
            pass
    if ses == "x11" and shutil.which("xdotool"):
        return InyectorXdotool()
    if ses == "wayland":
        yv = detectar_ydotool()
        try:
            import ydo

            listo = ydo.usable()
        except Exception:  # noqa: BLE001
            listo = False
        if yv and listo:
            return InyectorYdotool(yv)
    raise pcapc.ErrorPC("El otro PC (Linux) no puede mover su ratón: allí, ejecuta «sh instalar-linux.sh --pcapc» "
                        "y cierra sesión. «python3 linux_kvm.py --diagnostico» dice qué falta.")


# --- Emisor: lo que se hace con cada evento (sin dispositivos de por medio: se prueba solo) --------

TOQUE_PX_MM = 8.0       # touchpad: píxeles por milímetro de dedo
TOQUE_RUEDA_MM = 12.0   # touchpad con dos dedos: delta de rueda por milímetro (120 = una muesca)


class Traductor:
    """Recibe eventos del kernel (tipo, código, valor) de un dispositivo y llama al `sink` (Control)
    mientras se controla. Siempre lleva la cuenta de las teclas pulsadas para ver la tecla rápida.
    `evento` devuelve "alternar", "emergencia" o None."""

    def __init__(self, mods: int = 0, tecla: int | None = None) -> None:
        self.sink: Any = None
        self.mods, self.tecla = mods, tecla
        self.abajo: set[int] = set()
        self.enviadas: set[int] = set()
        self.botones: dict[int, int] = {}
        self._dx = self._dy = 0
        self._toque: dict[Any, dict] = {}

    def configurar(self, mods: int, tecla: int | None) -> None:
        self.mods, self.tecla = mods, tecla

    def empezar(self, sink: Any) -> None:
        self.enviadas.clear()
        self.botones.clear()
        self._dx = self._dy = 0
        self._toque.clear()
        self.sink = sink

    def evento(self, dev: Any, tipo: int, code: int, valor: int) -> str | None:
        import pcapc

        if tipo == EV_KEY and code < BTN_LEFT - 0x10:  # teclas (los botones van de 0x100 en adelante)
            if valor:
                self.abajo.add(code)
            else:
                self.abajo.discard(code)
            m = mods_de_evdev(self.abajo)
            ambos = pcapc.MOD_CONTROL | pcapc.MOD_ALT
            if valor == 1 and code == KEY_ESC and m & ambos == ambos:
                self.sink = None
                return "emergencia"
            if valor == 1 and self.tecla and code == self.tecla and self.mods and m & self.mods == self.mods:
                self.sink = None
                return "alternar"
            sink = self.sink
            if sink is None:
                return None
            win = windows_de_evdev(code)
            if win is None:
                return None
            vk, scan, ext = win
            if valor:  # 1 = baja, 2 = repetición (Windows la hace igual: otra bajada)
                self.enviadas.add(code)
                sink.tecla(vk, scan, ext, True)
            elif code in self.enviadas:
                self.enviadas.discard(code)
                sink.tecla(vk, scan, ext, False)
            return None
        sink = self.sink
        toque = self._toque.setdefault(id(dev), {"x": None, "y": None, "px": None, "py": None, "dedos": 0,
                                                 "tocando": False, "fx": 0.0, "fy": 0.0, "rx": 0.0, "ry": 0.0})
        if tipo == EV_KEY:
            if code in (BTN_TOOL_FINGER, BTN_TOOL_DOUBLETAP, BTN_TOOL_TRIPLETAP, BTN_TOOL_QUADTAP):
                n = {BTN_TOOL_FINGER: 1, BTN_TOOL_DOUBLETAP: 2, BTN_TOOL_TRIPLETAP: 3, BTN_TOOL_QUADTAP: 4}[code]
                toque["dedos"] = n if valor else (0 if toque["dedos"] == n else toque["dedos"])
                toque["px"] = toque["py"] = None  # al cambiar de dedos, sin saltos
                return None
            if code == BTN_TOUCH:
                toque["tocando"] = bool(valor)
                toque["px"] = toque["py"] = None
                return None
            if sink is None:
                return None
            if valor == 1:
                b = EVDEV_A_BOTON.get(code)
                if b is None:
                    return None
                if b == 1 and toque["dedos"] >= 2:  # touchpad: clic con dos dedos = derecho
                    b = 2
                self.botones[code] = b
                sink.boton(b, True)
            elif valor == 0 and code in self.botones:
                sink.boton(self.botones.pop(code), False)
            return None
        if tipo == EV_REL:
            if sink is None:
                return None
            hires = getattr(dev, "hires", False)
            if code == REL_X:
                self._dx += valor
            elif code == REL_Y:
                self._dy += valor
            elif code == REL_WHEEL_HI_RES:
                sink.rueda(0, valor)
            elif code == REL_HWHEEL_HI_RES:
                sink.rueda(1, valor)
            elif code == REL_WHEEL and not hires:
                sink.rueda(0, valor * 120)
            elif code == REL_HWHEEL and not hires:
                sink.rueda(1, valor * 120)
            return None
        if tipo == EV_ABS:
            if code == ABS_X:
                toque["x"] = valor
            elif code == ABS_Y:
                toque["y"] = valor
            return None
        if tipo == EV_SYN and code == SYN_REPORT:
            if sink is not None and (self._dx or self._dy):
                sink.mover(self._dx, self._dy)
            self._dx = self._dy = 0
            self._toque_syn(dev, toque, sink)
        return None

    def _toque_syn(self, dev: Any, t: dict, sink: Any) -> None:
        if t["x"] is None or t["y"] is None:
            return
        if not t["tocando"] or not t["dedos"]:
            t["px"], t["py"] = t["x"], t["y"]
            return
        if t["px"] is None:
            t["px"], t["py"] = t["x"], t["y"]
            return
        res_x, res_y = getattr(dev, "res", (10.0, 10.0))
        mm_x = (t["x"] - t["px"]) / res_x
        mm_y = (t["y"] - t["py"]) / res_y
        t["px"], t["py"] = t["x"], t["y"]
        if sink is None:
            return
        if t["dedos"] >= 2:  # desplazamiento «natural»: el contenido sigue a los dedos
            t["ry"] += mm_y * TOQUE_RUEDA_MM
            t["rx"] += -mm_x * TOQUE_RUEDA_MM
            v, h = int(t["ry"]), int(t["rx"])
            if v:
                t["ry"] -= v
                sink.rueda(0, v)
            if h:
                t["rx"] -= h
                sink.rueda(1, h)
            return
        t["fx"] += mm_x * TOQUE_PX_MM
        t["fy"] += mm_y * TOQUE_PX_MM
        dx, dy = int(t["fx"]), int(t["fy"])
        if dx or dy:
            t["fx"] -= dx
            t["fy"] -= dy
            sink.mover(dx, dy)


class Dispositivo:
    def __init__(self, fd: int, ruta: str, nombre: str, teclado: bool, raton: bool, tactil: bool,
                 hires: bool = False, res: tuple[float, float] = (10.0, 10.0)) -> None:
        self.fd, self.ruta, self.nombre = fd, ruta, nombre
        self.teclado, self.raton, self.tactil, self.hires, self.res = teclado, raton, tactil, hires, res


def clasificar(fd: int, ruta: str, ioctl: Callable[..., Any] | None = None) -> Dispositivo | None:
    """Teclado, ratón o touchpad (nada de pantallas táctiles, mandos ni nuestro propio uinput)."""
    if ioctl is None:
        import fcntl

        ioctl = fcntl.ioctl
    try:
        nombre = bytes(ioctl(fd, EVIOCGNAME(256), bytes(256))).split(b"\0", 1)[0].decode("utf-8", "replace")
        tipos = bytes(ioctl(fd, EVIOCGBIT(0, 4), bytes(4)))
        teclas = bytes(ioctl(fd, EVIOCGBIT(EV_KEY, 96), bytes(96))) if _bit(tipos, EV_KEY) else b""
        rels = bytes(ioctl(fd, EVIOCGBIT(EV_REL, 4), bytes(4))) if _bit(tipos, EV_REL) else b""
        abss = bytes(ioctl(fd, EVIOCGBIT(EV_ABS, 8), bytes(8))) if _bit(tipos, EV_ABS) else b""
        try:
            props = bytes(ioctl(fd, EVIOCGPROP(4), bytes(4)))
        except OSError:
            props = b""
    except OSError:
        return None
    if NOMBRE_DISPOSITIVO in nombre or "ydotool" in nombre.lower():
        return None
    teclado = _bit(teclas, KEY_A) and _bit(teclas, KEY_SPACE)
    raton = _bit(rels, REL_X) and _bit(rels, REL_Y) and _bit(teclas, BTN_LEFT)
    tactil = (_bit(abss, ABS_X) and _bit(abss, ABS_Y) and _bit(teclas, BTN_TOOL_FINGER)
              and not _bit(props, INPUT_PROP_DIRECT))
    if not (teclado or raton or tactil):
        return None
    res = (10.0, 10.0)
    if tactil:
        try:
            ejes = []
            for eje in (ABS_X, ABS_Y):
                _v, mn, mx, _f, _fl, r = struct.unpack("6i", bytes(ioctl(fd, EVIOCGABS(eje), bytes(24))))
                ejes.append(float(r) if r > 0 else max(1.0, (mx - mn) / 100.0))
            res = (ejes[0], ejes[1])
        except OSError:
            pass
    return Dispositivo(fd, ruta, nombre, teclado, raton, tactil, _bit(rels, REL_WHEEL_HI_RES), res)


class CapturaEvdev:
    """Emisor en Linux por /dev/input. Un hilo lee todos los teclados, ratones y touchpads. Libre:
    solo mira si llega la tecla rápida (el escritorio lo recibe todo como siempre). Controlando:
    EVIOCGRAB en todos (el escritorio no recibe nada) y todo va al otro PC."""

    def __init__(self, control: Any, rutas: Callable[[], list[str]] | None = None,
                 abrir: Callable[[str], int] | None = None, ioctl: Callable[..., Any] | None = None,
                 clasificar_fn: Callable[..., Any] = clasificar, reloj: Callable[[], float] = time.monotonic) -> None:
        if ioctl is None:
            import fcntl

            ioctl = fcntl.ioctl
        self.control = control
        self.rutas = rutas or (lambda: sorted(glob.glob("/dev/input/event*")))
        self.abrir = abrir or (lambda r: os.open(r, os.O_RDONLY | os.O_NONBLOCK))
        self.ioctl = ioctl
        self.clasificar = clasificar_fn
        self.reloj = reloj
        self.trad = Traductor()
        self.devs: dict[int, Dispositivo] = {}
        self.tecla_ok = False
        self.instalada = False
        self.cogido = False
        self._quiere = 0.0  # hasta cuándo esperar a que se suelten las teclas antes de coger
        self._lock = threading.RLock()
        self._hilo: threading.Thread | None = None
        self._fin = False
        self._escaneo = 0.0

    # Dispositivos ---------------------------------------------------------------------------
    def escanear(self) -> None:
        with self._lock:
            vistas = set(self.rutas())
            for fd, d in list(self.devs.items()):
                if d.ruta not in vistas:
                    self._cerrar(fd)
            abiertas = {d.ruta for d in self.devs.values()}
            for ruta in vistas - abiertas:
                try:
                    fd = self.abrir(ruta)
                except OSError:
                    continue
                d = self.clasificar(fd, ruta, self.ioctl)
                if d is None:
                    os.close(fd)
                    continue
                self.devs[fd] = d
                if self.cogido:
                    self._grab(d, True)
            self._escaneo = self.reloj()

    def _cerrar(self, fd: int) -> None:
        d = self.devs.pop(fd, None)
        if d is None:
            return
        try:
            os.close(fd)
        except OSError:
            pass

    def _grab(self, d: Dispositivo, on: bool) -> bool:
        try:
            self.ioctl(d.fd, EVIOCGRAB, 1 if on else 0)
            return True
        except OSError:
            return False

    def soltar_grab(self) -> None:
        """Devuelve el teclado y el ratón al escritorio. Se puede llamar desde cualquier hilo."""
        with self._lock:
            self._quiere = 0.0
            if self.cogido:
                for d in list(self.devs.values()):
                    self._grab(d, False)
            self.cogido = False

    def algo_pulsado(self) -> bool:
        for d in list(self.devs.values()):
            try:
                if any(bytes(self.ioctl(d.fd, EVIOCGKEY(96), bytes(96)))):
                    return True
            except OSError:
                continue
        return False

    def _coger(self) -> bool:
        with self._lock:
            if self.trad.sink is None:
                self._quiere = 0.0
                return False
            ok = [self._grab(d, True) for d in self.devs.values() if d.teclado or d.raton or d.tactil]
            self.cogido = any(ok)
            self._quiere = 0.0
            return self.cogido

    # Lo que llama Control ------------------------------------------------------------------------
    def _arrancar(self) -> None:
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._fin = False
        self.escanear()
        self._hilo = threading.Thread(target=self._bucle, name="lazo-kvm-evdev", daemon=True)
        self._hilo.start()

    def registrar(self, mods: int, vk: int) -> bool:
        """La tecla rápida. Sin vk (no hay PCs): deja de leer los teclados."""
        if not vk:
            self.trad.configurar(0, None)
            if self.trad.sink is None:
                self.cerrar()
            self.tecla_ok = False
            return True
        self.trad.configurar(mods, evdev_de_vk(vk))
        self._arrancar()
        self.tecla_ok = any(d.teclado for d in self.devs.values())
        return self.tecla_ok

    def empezar(self, sink: Any) -> bool:
        import pcapc

        mods, vk, _ = pcapc.leer_tecla(pcapc.AJUSTES.tecla)
        self.trad.configurar(mods, evdev_de_vk(vk))
        self._arrancar()
        if not any(d.teclado or d.raton or d.tactil for d in self.devs.values()):
            return False
        with self._lock:
            self.trad.empezar(sink)
            self._quiere = self.reloj() + 2.0  # se coge en cuanto sueltes la tecla rápida
        self.instalada = True
        return True

    def parar(self) -> None:
        self.trad.sink = None
        self.soltar_grab()
        self.instalada = False

    def cerrar(self) -> None:
        self._fin = True
        self.parar()
        with self._lock:
            for fd in list(self.devs):
                self._cerrar(fd)

    # El hilo -------------------------------------------------------------------------------------
    def paso(self, espera: float = 0.1) -> None:
        """Una vuelta del bucle (se usa en las pruebas)."""
        if self.reloj() - self._escaneo > 3.0:
            self.escanear()
        fds = list(self.devs)
        listos = select.select(fds, [], [], espera)[0] if fds else []
        if not fds:
            time.sleep(espera)
        for fd in listos:
            d = self.devs.get(fd)
            if d is None:
                continue
            try:
                datos = os.read(fd, EVENTO.size * 64)
            except BlockingIOError:
                continue
            except OSError:
                with self._lock:
                    self._cerrar(fd)  # se desenchufó
                continue
            for i in range(0, len(datos) - EVENTO.size + 1, EVENTO.size):
                _s, _us, tipo, code, valor = EVENTO.unpack_from(datos, i)
                accion = self.trad.evento(d, tipo, code, valor)
                if accion == "emergencia":
                    self.soltar_grab()  # aquí mismo, sin esperar a nadie
                    self.control.pedir("emergencia")
                elif accion == "alternar":
                    self.soltar_grab()
                    self.control.pedir("alternar")
        if self._quiere and not self.cogido:
            if self.reloj() >= self._quiere or not self.algo_pulsado():
                self._coger()
        if self.cogido and (self.trad.sink is None or not self.control.vivo()):
            self.soltar_grab()
            if self.trad.sink is not None:
                self.trad.sink = None
                self.control.pedir("parar")

    def _bucle(self) -> None:
        try:
            while not self._fin:
                try:
                    self.paso()
                except (OSError, ValueError):
                    time.sleep(0.2)
        finally:
            self.soltar_grab()  # pase lo que pase, el teclado vuelve al escritorio


class CapturaX11:
    """Emisor en Xorg sin permiso en /dev/input. La tecla rápida con XGrabKey; mientras controla,
    XGrabKeyboard y XGrabPointer (nadie más recibe nada) y el puntero se devuelve al centro tras
    cada movimiento para medir cuánto se movió. Todo X se hace en un único hilo."""

    _X_MODS = ((1, 8), (2, 4), (4, 1), (8, 64))  # (mod de pcapc, máscara de X): Alt, Ctrl, Shift, Win

    def __init__(self, control: Any, libx11: Any = None) -> None:
        self.control = control
        self.trad = Traductor()
        self.tecla_ok = False
        self.instalada = False
        self.cogido = False
        self._x = libx11
        self._cola: list[tuple] = []
        self._lock = threading.Lock()
        self._hecho = threading.Event()
        self._hilo: threading.Thread | None = None
        self._listo = threading.Event()
        self._fin = False
        self._kc = 0
        self._xmods = 0
        self._error = 0

    def _arrancar(self) -> None:
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._listo.clear()
        self._fin = False
        self._hilo = threading.Thread(target=self._bucle, name="lazo-kvm-x11", daemon=True)
        self._hilo.start()
        self._listo.wait(3)

    def _pedir(self, orden: str, *a: Any, esperar: bool = True) -> None:
        self._arrancar()
        with self._lock:
            self._cola.append((orden, a))
            self._hecho.clear()
        if esperar and threading.current_thread() is not self._hilo:
            self._hecho.wait(2.5)

    def registrar(self, mods: int, vk: int) -> bool:
        self._pedir("tecla", mods, vk)
        return self.tecla_ok

    def empezar(self, sink: Any) -> bool:
        import pcapc

        mods, vk, _ = pcapc.leer_tecla(pcapc.AJUSTES.tecla)
        self.trad.configurar(mods, evdev_de_vk(vk))
        self.trad.empezar(sink)
        self._pedir("coger")
        if not self.cogido:
            self.trad.sink = None
        self.instalada = self.cogido
        return self.cogido

    def parar(self) -> None:
        self.trad.sink = None
        self._pedir("soltar")
        self.instalada = False

    def _bucle(self) -> None:  # pragma: no cover - se prueba con Xvfb si está
        import ctypes

        x = self._x or ctypes.CDLL("libX11.so.6")
        V, UL, I, UI = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_uint
        x.XOpenDisplay.restype, x.XOpenDisplay.argtypes = V, [ctypes.c_char_p]
        x.XDefaultRootWindow.restype, x.XDefaultRootWindow.argtypes = UL, [V]
        x.XDefaultScreen.argtypes = [V]
        x.XDisplayWidth.argtypes = x.XDisplayHeight.argtypes = [V, I]
        x.XConnectionNumber.argtypes = [V]
        x.XPending.argtypes = [V]
        x.XNextEvent.argtypes = [V, V]
        x.XFlush.argtypes = [V]
        x.XSync.argtypes = [V, I]
        x.XGrabKey.argtypes = [V, I, UI, UL, I, I, I]
        x.XUngrabKey.argtypes = [V, I, UI, UL]
        x.XGrabKeyboard.argtypes = [V, UL, I, I, I, UL]
        x.XUngrabKeyboard.argtypes = [V, UL]
        x.XGrabPointer.argtypes = [V, UL, I, UI, I, I, UL, UL, UL]
        x.XUngrabPointer.argtypes = [V, UL]
        x.XWarpPointer.argtypes = [V, UL, UL, I, I, UI, UI, I, I]
        x.XQueryPointer.argtypes = [V, UL, ctypes.POINTER(UL), ctypes.POINTER(UL), ctypes.POINTER(I), ctypes.POINTER(I),
                                    ctypes.POINTER(I), ctypes.POINTER(I), ctypes.POINTER(UI)]
        MANEJADOR = ctypes.CFUNCTYPE(I, V, V)

        def al_error(_d: Any, _e: Any) -> int:
            self._error += 1  # sin esto, un error de X (p. ej. tecla ya cogida) cerraría LaZoo
            return 0

        manejador = MANEJADOR(al_error)
        x.XSetErrorHandler.argtypes = [MANEJADOR]
        x.XSetErrorHandler(manejador)
        d = x.XOpenDisplay(None)
        if not d:
            self._listo.set()
            return
        root = x.XDefaultRootWindow(d)
        scr = x.XDefaultScreen(d)
        centro = (x.XDisplayWidth(d, scr) // 2, x.XDisplayHeight(d, scr) // 2)
        guardado = [0, 0]
        ev = ctypes.create_string_buffer(192)
        cogidas: list[tuple[int, int]] = []
        fdx = x.XConnectionNumber(d)

        def soltar_tecla() -> None:
            for kc, m in cogidas:
                x.XUngrabKey(d, kc, m, root)
            cogidas.clear()
            self.tecla_ok = False

        def coger_tecla(mods: int, vk: int) -> None:
            soltar_tecla()
            code = evdev_de_vk(vk) if vk else None
            if not code:
                x.XSync(d, 0)
                return
            xm = 0
            for bit, mask in self._X_MODS:
                if mods & bit:
                    xm |= mask
            self._kc, self._xmods = code + 8, xm
            antes = self._error
            for extra in (0, 2, 16, 18):  # también con Bloq Mayús y Bloq Num
                x.XGrabKey(d, code + 8, xm | extra, root, 0, 1, 1)
                cogidas.append((code + 8, xm | extra))
            x.XSync(d, 0)
            self.tecla_ok = self._error == antes

        def soltar() -> None:
            if self.cogido:
                x.XUngrabPointer(d, 0)
                x.XUngrabKeyboard(d, 0)
                x.XWarpPointer(d, 0, root, 0, 0, 0, 0, guardado[0], guardado[1])
                x.XSync(d, 0)
            self.cogido = False

        def coger() -> None:
            if self.trad.sink is None:
                return
            r, c = UL(), UL()
            rx, ry, wx, wy, m = I(), I(), I(), I(), UI()
            x.XQueryPointer(d, root, ctypes.byref(r), ctypes.byref(c), ctypes.byref(rx), ctypes.byref(ry),
                            ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(m))
            guardado[:] = [rx.value, ry.value]
            fin = time.monotonic() + 1.0
            while time.monotonic() < fin:
                k = x.XGrabKeyboard(d, root, 0, 1, 1, 0)
                p = x.XGrabPointer(d, root, 0, (1 << 2) | (1 << 3) | (1 << 6), 1, 1, root, 0, 0) if k == 0 else 1
                if k == 0 and p == 0:
                    self.cogido = True
                    x.XWarpPointer(d, 0, root, 0, 0, 0, 0, centro[0], centro[1])
                    x.XSync(d, 0)
                    return
                if k == 0:
                    x.XUngrabKeyboard(d, 0)
                x.XSync(d, 0)
                time.sleep(0.05)

        self._listo.set()
        u32 = struct.Struct("<I")
        i32 = struct.Struct("<i")
        try:
            while not self._fin:
                with self._lock:
                    cola, self._cola = self._cola, []
                for orden, a in cola:
                    if orden == "tecla":
                        coger_tecla(*a)
                    elif orden == "coger":
                        coger()
                    elif orden == "soltar":
                        soltar()
                if cola:
                    self._hecho.set()
                if not x.XPending(d):
                    select.select([fdx], [], [], 0.05)
                    if self.cogido and (self.trad.sink is None or not self.control.vivo()):
                        sink = self.trad.sink
                        soltar()
                        if sink is not None:
                            self.trad.sink = None
                            self.control.pedir("parar")
                    continue
                x.XNextEvent(d, ev)
                tipo = i32.unpack_from(ev.raw, 0)[0]
                if tipo in (2, 3):  # KeyPress / KeyRelease
                    kc = u32.unpack_from(ev.raw, 84)[0]
                    if not self.cogido:
                        if tipo == 2 and kc == self._kc:
                            self.control.pedir("alternar")  # la tecla rápida (XGrabKey)
                        continue
                    accion = self.trad.evento(None, EV_KEY, kc - 8, 1 if tipo == 2 else 0)
                    if accion:
                        soltar()
                        self.control.pedir(accion)
                elif tipo in (4, 5) and self.cogido and self.trad.sink is not None:
                    b = u32.unpack_from(ev.raw, 84)[0]
                    sink = self.trad.sink
                    if tipo == 4 and b in (4, 5, 6, 7):
                        sink.rueda(0 if b in (4, 5) else 1, 120 if b in (4, 7) else -120)
                    elif b in (1, 2, 3, 8, 9):
                        code = {1: BTN_LEFT, 2: BTN_MIDDLE, 3: BTN_RIGHT, 8: BTN_SIDE, 9: BTN_EXTRA}[b]
                        self.trad.evento(None, EV_KEY, code, 1 if tipo == 4 else 0)
                elif tipo == 6 and self.cogido:
                    xr, yr = i32.unpack_from(ev.raw, 72)[0], i32.unpack_from(ev.raw, 76)[0]
                    if (xr, yr) != centro and self.trad.sink is not None:
                        self.trad.sink.mover(xr - centro[0], yr - centro[1])
                        x.XWarpPointer(d, 0, root, 0, 0, 0, 0, centro[0], centro[1])
                        x.XFlush(d)
        finally:
            soltar()
            soltar_tecla()
            x.XSync(d, 0)
            self._hecho.set()


def puede_capturar(env: dict | None = None) -> tuple[bool, str]:
    ses = sesion(env)
    _total, legibles = eventos_legibles()
    metodo, por = elegir_emisor(ses, legibles, _libx11() if ses == "x11" else False)
    return bool(metodo), ("" if metodo else por)


def captura_linux(control: Any) -> Any:
    ses = sesion()
    _total, legibles = eventos_legibles()
    metodo, _por = elegir_emisor(ses, legibles, _libx11() if ses == "x11" else False)
    if metodo == "evdev":
        return CapturaEvdev(control)
    if metodo == "x11":
        return CapturaX11(control)
    return None


def main(argv: list[str]) -> int:
    if "--diagnostico" in argv or "-d" in argv:
        print(texto_diagnostico(diagnostico()))
        return 0
    print("Uso: python3 linux_kvm.py --diagnostico")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
