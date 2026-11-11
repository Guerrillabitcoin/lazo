"""LaZoo 0.63: el PC no se bloquea ni se duerme mientras se usa desde el móvil.

Con el PC en la tele y el móvil en el sofá, Windows no ve teclado ni ratón «de verdad» y
acaba apagando la pantalla, bloqueando la sesión (pantalla de contraseña, donde LaZoo ya no
puede escribir) o suspendiendo el PC. Mientras un móvil aceptado haya usado LaZoo en la
última `VENTANA` (1 h 21 min):

- se le dice a Windows «estoy en uso» (`SetThreadExecutionState`, lo mismo que hace un
  reproductor de vídeo): ni suspensión, ni pantalla apagada, ni salvapantallas;
- si Windows lleva `TOQUE_TRAS` s sin ninguna entrada, se le da un toque de ratón de CERO
  píxeles (`SendInput`): cuenta como actividad pero el cursor no se mueve, así YouTube no
  saca su barra de controles encima del vídeo.

Pasada 1 h 21 min sin usar el móvil, Windows vuelve a lo suyo. Si la sesión ya está bloqueada
(por ejemplo con «Bloquear PC»), LaZoo no la mantiene encendida. El «¿Sigues ahí?» de
YouTube es otra cosa: lo contesta sigues.py.

Windows y, desde 0.67, Linux (clase `Linux`: inhibidor de GNOME o de systemd). Se apaga en el Panel o en el móvil, con `--sin-despierto` o con
`LAZO_SIN_DESPIERTO=1`. El ajuste se guarda en `ajustes.json` (`despierto`).
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

VENTANA = 4860.0     # 1 h 21 min tras el último uso del móvil
TOQUE_TRAS = 50.0    # segundos sin entrada antes del toque de cero píxeles
PASO = 20.0          # cada cuánto se revisa
DEFAULT_ON = True

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


class Windows:
    """Las tres llamadas al sistema. Aparte para poder probar sin Windows."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes, self.wt = ctypes, wintypes
        self.k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.u32 = ctypes.WinDLL("user32", use_last_error=True)
        self.k32.SetThreadExecutionState.argtypes = [wintypes.DWORD]
        self.k32.SetThreadExecutionState.restype = wintypes.DWORD

    def keep(self, on: bool) -> None:
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED if on else 0)
        self.k32.SetThreadExecutionState(flags)

    def idle_seconds(self) -> float:
        ctypes, wt = self.ctypes, self.wt

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]

        info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
        if not self.u32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        return max(0, (self.k32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0

    def locked(self) -> bool:
        """La sesión está en la pantalla de bloqueo (el escritorio de entrada no es el nuestro)."""
        desk = self.u32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
        if not desk:
            return True
        try:
            return not self.u32.SwitchDesktop(desk)
        finally:
            self.u32.CloseDesktop(desk)

    def nudge(self) -> None:
        """Entrada de ratón de cero píxeles: Windows la cuenta, el cursor no se mueve."""
        ctypes, wt = self.ctypes, self.wt

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                        ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wt.DWORD), ("mi", MOUSEINPUT), ("_pad", ctypes.c_byte * 8)]

        event = INPUT(0, MOUSEINPUT(0, 0, 0, 0x0001, 0, 0))  # INPUT_MOUSE, MOUSEEVENTF_MOVE
        self.u32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))


class Linux:
    """0.67: lo mismo en Linux. Mientras el móvil se usa, un proceso pequeño «inhibe» el
    reposo, como hace un reproductor de vídeo:

    - GNOME (Ubuntu, Fedora…): `gnome-session-inhibit --inhibit idle:suspend` (ni pantalla
      apagada, ni bloqueo por inactividad, ni suspensión);
    - el resto (KDE, Cinnamon, Xfce…): `systemd-inhibit --what=idle:sleep`;
    - con X11 además `xdg-screensaver reset` en cada revisión (salvapantallas antiguos).

    No hace falta el toque de ratón de Windows: el inhibidor basta y el cursor no se toca.
    Al soltar se cierra el proceso y el escritorio vuelve a lo suyo."""

    def __init__(self, which: Callable[[str], str | None] | None = None, popen: Callable[..., Any] | None = None,
                 run: Callable[..., Any] | None = None, env: dict[str, str] | None = None) -> None:
        import shutil
        import subprocess

        self.which = which or shutil.which
        self.popen = popen or subprocess.Popen
        self.run = run or subprocess.run
        self.env = os.environ if env is None else env
        self.proc: Any = None

    def command(self) -> list[str] | None:
        desk = (self.env.get("XDG_CURRENT_DESKTOP", "") + ":" + self.env.get("DESKTOP_SESSION", "")).lower()
        espera = ["sleep", "infinity"]
        if "gnome" in desk and self.which("gnome-session-inhibit"):
            return ["gnome-session-inhibit", "--inhibit", "idle:suspend", "--reason", "LaZoo: se usa desde el móvil", *espera]
        if self.which("systemd-inhibit"):
            return ["systemd-inhibit", "--what=idle:sleep", "--who=LaZoo", "--why=Se usa desde el móvil",
                    "--mode=block", *espera]
        if self.which("gnome-session-inhibit"):
            return ["gnome-session-inhibit", "--inhibit", "idle:suspend", "--reason", "LaZoo: se usa desde el móvil", *espera]
        return None

    def keep(self, on: bool) -> None:
        import subprocess

        vivo = self.proc is not None and self.proc.poll() is None
        if on and not vivo:
            cmd = self.command()
            if cmd is None:
                raise OSError("sin inhibidor")
            self.proc = self.popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif not on and vivo:
            self.proc.terminate()
            try:
                self.proc.wait(2)
            except Exception:  # noqa: BLE001
                self.proc.kill()
            self.proc = None
        if on and self.env.get("XDG_SESSION_TYPE", "").lower() == "x11" and self.which("xdg-screensaver"):
            try:
                self.run(["xdg-screensaver", "reset"], timeout=3, capture_output=True)
            except Exception:  # noqa: BLE001
                pass

    def idle_seconds(self) -> float:
        return 0.0  # nunca hace falta el toque

    def locked(self) -> bool:
        """Con la sesión ya bloqueada no se mantiene encendida (como en Windows)."""
        sid = self.env.get("XDG_SESSION_ID", "")
        if not sid or not self.which("loginctl"):
            return False
        try:
            out = self.run(["loginctl", "show-session", sid, "-p", "LockedHint", "--value"],
                           timeout=3, capture_output=True, text=True)
            return str(out.stdout).strip() == "yes"
        except Exception:  # noqa: BLE001
            return False

    def nudge(self) -> None:
        pass


def _ajustes_file() -> Path:
    import recordar

    return recordar.data_dir() / "ajustes.json"


class Despierto:
    def __init__(self, system: Any = None, file: Path | None = None, clock: Callable[[], float] = time.time) -> None:
        self.system = system
        self.file = file
        self.clock = clock
        self.on = self._load()
        self.disabled = False
        self.last_phone = 0.0
        self.active = False
        self.toques = 0
        self.error = ""
        self.thread: threading.Thread | None = None
        self.stop_ev = threading.Event()

    # --- ajuste ---------------------------------------------------------------
    def _path(self) -> Path | None:
        if self.file is not None:
            return self.file
        try:
            return _ajustes_file()
        except Exception:  # noqa: BLE001
            return None

    def _load(self) -> bool:
        p = self._path()
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p and p.is_file() else {}
            return bool(data.get("despierto", DEFAULT_ON))
        except Exception:  # noqa: BLE001
            return DEFAULT_ON

    def _save(self) -> None:
        p = self._path()
        if not p:
            return
        import sigues  # mismo candado: sigues, anuncios y esto comparten ajustes.json

        with sigues._SAVE_LOCK:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                try:
                    data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
                except ValueError:
                    data = {}
                data["despierto"] = self.on
                tmp = p.with_name(f"{p.name}.{os.getpid()}.d.tmp")
                tmp.write_text(json.dumps(data), encoding="utf-8")
                os.replace(tmp, p)
            except OSError:
                pass

    def available(self) -> bool:
        return sys.platform == "win32" or sys.platform.startswith("linux") or self.system is not None

    def status(self) -> dict[str, Any]:
        left = max(0, int(self.last_phone + VENTANA - self.clock())) if self.last_phone else 0
        return {"on": self.on and not self.disabled, "available": self.available(), "disabled": self.disabled,
                "activo": self.active, "quedan_s": left if self.active else 0, "ventana_s": int(VENTANA),
                "toques": self.toques, "error": self.error}

    def set_on(self, on: object) -> dict[str, Any]:
        if on is not None:
            self.on = bool(on)
            self._save()
            if self.on:
                self.start()
            else:
                self.tick()  # suelta ya el «estoy en uso»
        return self.status()

    # --- uso --------------------------------------------------------------------
    def touch(self) -> None:
        """Un móvil aceptado acaba de hablar con el PC."""
        self.last_phone = self.clock()

    def tick(self) -> dict[str, Any]:
        """Una revisión. Devuelve qué hizo (para pruebas y el bucle)."""
        sysapi = self._sys()
        if sysapi is None:
            return {"skip": "sin windows"}
        want = (self.on and not self.disabled and self.last_phone > 0
                and self.clock() - self.last_phone < VENTANA)
        did: dict[str, Any] = {"want": want, "toque": False}
        try:
            if want and sysapi.locked():
                want = False
                did["bloqueado"] = True
            if want != self.active or want:
                sysapi.keep(want)  # repetir con ES_CONTINUOUS no cuesta nada
            self.active = want
            if want and sysapi.idle_seconds() >= TOQUE_TRAS:
                sysapi.nudge()
                self.toques += 1
                did["toque"] = True
            self.error = ""
        except Exception as exc:  # noqa: BLE001 (nunca tumbar LaZoo por esto)
            self.error = type(exc).__name__
        did["activo"] = self.active
        return did

    def _sys(self) -> Any:
        if self.system is None and (sys.platform == "win32" or sys.platform.startswith("linux")):
            try:
                self.system = Windows() if sys.platform == "win32" else Linux()
            except Exception as exc:  # noqa: BLE001
                self.error = type(exc).__name__
                self.disabled = True
        return self.system

    def _loop(self) -> None:
        # Todo en ESTE hilo: SetThreadExecutionState vale para el hilo que lo llama.
        while not self.stop_ev.wait(PASO):
            self.tick()
        if self.active and self.system is not None:
            try:
                self.system.keep(False)
            except Exception:  # noqa: BLE001
                pass
            self.active = False

    def start(self) -> bool:
        if not self.available() or self.disabled:
            return False
        if self.thread and self.thread.is_alive():
            return True
        self.stop_ev.clear()
        self.thread = threading.Thread(target=self._loop, name="lazo-despierto", daemon=True)
        self.thread.start()
        return True

    def stop(self) -> None:
        self.stop_ev.set()


DESPIERTO = Despierto()


def watch() -> bool:
    if "unittest" in sys.modules or "pytest" in sys.modules:
        return False
    if os.environ.get("LAZO_SIN_DESPIERTO") == "1":
        DESPIERTO.disabled = True
        return False
    return DESPIERTO.start()
