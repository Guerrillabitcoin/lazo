"""Control del PC para Lazo. Best-effort en Windows, macOS y Linux."""

from __future__ import annotations

import ctypes
import json
import platform
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

SYSTEM = platform.system()  # Windows, Darwin, Linux

_lock = threading.Lock()
_mouse_lock = threading.Lock()
_clip_lock = threading.Lock()
_mouse = None
_keyboard = None
_cursor_mode = "normal"
_saved_cursor: Any = None
_history_path = Path(__file__).with_name("clipboard-history.json")
_history: list[dict[str, Any]] = []
_history_loaded = False
_clip_seq = 0
_CLIP_LIMIT = 40
_CLIP_CHARS = 8000


class ControlError(Exception):
    pass


def _run(cmd: list[str], timeout: float = 4) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _which(name: str) -> bool:
    return shutil.which(name) is not None


def _input():
    global _mouse, _keyboard
    if _mouse is not None and _keyboard is not None:
        return _mouse, _keyboard
    try:
        from pynput.keyboard import Controller as KeyController
        from pynput.mouse import Controller as MouseController
    except ImportError as exc:
        raise ControlError(
            "Falta pynput. En el PC: pip install -r requirements.txt"
        ) from exc
    _mouse = MouseController()
    _keyboard = KeyController()
    return _mouse, _keyboard


def _button(name: str):
    from pynput.mouse import Button

    if name == "right":
        return Button.right
    if name == "middle":
        return Button.middle
    return Button.left


def _special(name: str):
    from pynput.keyboard import Key

    table = {
        "Enter": Key.enter,
        "Backspace": Key.backspace,
        "Tab": Key.tab,
        "Escape": Key.esc,
        "ArrowLeft": Key.left,
        "ArrowRight": Key.right,
        "ArrowUp": Key.up,
        "ArrowDown": Key.down,
        " ": Key.space,
        "Delete": Key.delete,
        "Home": Key.home,
        "End": Key.end,
        "Shift": Key.shift,
        "Control": Key.ctrl,
        "Alt": Key.alt,
    }
    return table.get(name)


_move_hook = None


def set_move_hook(fn) -> None:
    global _move_hook
    _move_hook = fn


def backend_for(system: str, display: str | None, wayland: str | None) -> str:
    if system == "Windows":
        return "sendinput"
    if system == "Darwin":
        return "cgevent"
    if system == "Linux":
        if display:
            return "xtest"
        if wayland:
            return "ydotool"
        return "none"
    return "pynput"


def move_mouse(dx: int, dy: int) -> None:
    dx = max(-4000, min(4000, int(dx)))
    dy = max(-4000, min(4000, int(dy)))
    if dx == 0 and dy == 0:
        return
    _mark_injected()
    if _move_hook is not None:
        _move_hook(dx, dy)
        return
    with _mouse_lock:
        _dispatch_move(dx, dy)


def _dispatch_move(dx: int, dy: int) -> None:
    import os

    kind = backend_for(SYSTEM, os.environ.get("DISPLAY"), os.environ.get("WAYLAND_DISPLAY"))
    if kind == "sendinput" and _win_move(dx, dy):
        return
    if kind == "cgevent" and _mac_move(dx, dy):
        return
    if kind == "xtest" and _linux_xtest(dx, dy):
        return
    if kind == "ydotool":
        _ydotool(["mousemove", "-x", str(dx), "-y", str(dy)])
        return
    if kind == "none":
        raise ControlError("No hay sesión gráfica para mover el ratón")
    mouse, _keyboard = _input()
    mouse.move(dx, dy)


def _win_move(dx: int, dy: int) -> bool:
    extra = ctypes.c_size_t
    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", extra),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("mi", MOUSEINPUT)]

    event = INPUT()
    event.type = 0
    event.mi.dx = dx
    event.mi.dy = dy
    event.mi.dwFlags = 0x0001
    sent = ctypes.windll.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))
    return sent == 1


def _mac_move(dx: int, dy: int) -> bool:
    try:
        quartz = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        core = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    except OSError:
        return False
    quartz.CGEventCreate.restype = ctypes.c_void_p
    quartz.CGEventCreate.argtypes = [ctypes.c_void_p]
    event = quartz.CGEventCreate(None)
    if not event:
        return False
    quartz.CGEventSetType(event, 5)
    quartz.CGEventSetIntegerValueField(event, 4, int(dx))
    quartz.CGEventSetIntegerValueField(event, 5, int(dy))
    quartz.CGEventPost(0, event)
    core.CFRelease(event)
    return True


_x_bundle = None
_x_failed = False


def _linux_xtest(dx: int, dy: int) -> bool:
    global _x_bundle, _x_failed
    if _x_failed:
        return False
    try:
        if _x_bundle is None:
            x11 = ctypes.CDLL("libX11.so.6")
            xtst = ctypes.CDLL("libXtst.so.6")
            x11.XOpenDisplay.restype = ctypes.c_void_p
            disp = x11.XOpenDisplay(None)
            if not disp:
                _x_failed = True
                return False
            _x_bundle = (x11, xtst, disp)
        x11, xtst, disp = _x_bundle
        xtst.XTestFakeRelativeMotionEvent(ctypes.c_void_p(disp), int(dx), int(dy), 0)
        x11.XFlush(ctypes.c_void_p(disp))
        return True
    except OSError:
        _x_failed = True
        return False


def mouse_click(button: str, count: int = 1) -> None:
    count = max(1, min(3, int(count)))
    with _mouse_lock:
        mouse, _keyboard = _input()
        mouse.click(_button(button), count)


def mouse_down(button: str) -> None:
    with _mouse_lock:
        mouse, _keyboard = _input()
        mouse.press(_button(button))


def mouse_up(button: str) -> None:
    with _mouse_lock:
        mouse, _keyboard = _input()
        mouse.release(_button(button))


def scroll_steps(dy: int) -> int:
    dy = int(dy)
    if dy == 0:
        return 0
    steps = int(round(-dy / 90))
    if steps == 0:
        steps = -1 if dy > 0 else 1
    return max(-2, min(2, steps))


def scroll_mouse(dy: int) -> None:
    steps = scroll_steps(dy)
    if steps == 0:
        return
    with _mouse_lock:
        mouse, _keyboard = _input()
        mouse.scroll(0, steps)


def press_key(name: str) -> None:
    if not isinstance(name, str) or not name or len(name) > 32:
        raise ControlError("tecla no válida")
    with _lock:
        _keyboard_send(name)


def type_text(text: str) -> None:
    if not isinstance(text, str):
        raise ControlError("texto no válido")
    text = text[:400]
    with _lock:
        _mouse, keyboard = _input()
        keyboard.type(text)


def _keyboard_send(name: str) -> None:
    _mouse, keyboard = _input()
    special = _special(name)
    if special is not None:
        keyboard.press(special)
        keyboard.release(special)
        return
    if len(name) == 1:
        keyboard.type(name)
        return
    raise ControlError("tecla no válida")


def _chord(parts: list[str]) -> None:
    from pynput.keyboard import Key

    _mouse, keyboard = _input()
    held = []
    try:
        for part in parts:
            if part == "shift":
                keyboard.press(Key.shift)
                held.append(Key.shift)
            elif part == "ctrl":
                keyboard.press(Key.ctrl)
                held.append(Key.ctrl)
            elif part == "up":
                keyboard.press(Key.up)
                keyboard.release(Key.up)
            elif part == "down":
                keyboard.press(Key.down)
                keyboard.release(Key.down)
            elif len(part) == 1:
                keyboard.press(part)
                keyboard.release(part)
            else:
                raise ControlError("atajo no válido")
    finally:
        for key in reversed(held):
            keyboard.release(key)


def system_volume(delta: int) -> str:
    delta = int(delta)
    with _lock:
        if SYSTEM == "Darwin":
            return _mac_volume(delta)
        if SYSTEM == "Windows":
            return _win_media_key(0xAD if delta == 0 else 0xAF if delta > 0 else 0xAE)
        return _linux_volume(delta)


def _mac_volume(delta: int) -> str:
    if delta == 0:
        script = "set volume output muted not (output muted of (get volume settings))"
    else:
        step = 6 if delta > 0 else -6
        script = (
            "set cur to output volume of (get volume settings)\n"
            f"set nxt to cur + {step}\n"
            "if nxt < 0 then set nxt to 0\n"
            "if nxt > 100 then set nxt to 100\n"
            "set volume output volume nxt without muting"
        )
    result = _run(["osascript", "-e", script])
    if result.returncode != 0:
        raise ControlError("macOS no dejó cambiar el volumen")
    return "Volumen del Mac"


def _linux_volume(delta: int) -> str:
    if _which("wpctl"):
        if delta == 0:
            cmd = ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"]
        else:
            cmd = ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%+" if delta > 0 else "5%-"]
        result = _run(cmd)
        if result.returncode == 0:
            return "Volumen"
    if _which("pactl"):
        if delta == 0:
            cmd = ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"]
        else:
            cmd = ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%" if delta > 0 else "-5%"]
        result = _run(cmd)
        if result.returncode == 0:
            return "Volumen"
    if _which("amixer"):
        if delta == 0:
            cmd = ["amixer", "-q", "sset", "Master", "toggle"]
        else:
            cmd = ["amixer", "-q", "sset", "Master", "5%+" if delta > 0 else "5%-"]
        result = _run(cmd)
        if result.returncode == 0:
            return "Volumen"
    _media_key("mute" if delta == 0 else "up" if delta > 0 else "down")
    return "Volumen (tecla multimedia)"


def _media_key(kind: str) -> None:
    from pynput.keyboard import Key

    mapping = {
        "up": getattr(Key, "media_volume_up", None),
        "down": getattr(Key, "media_volume_down", None),
        "mute": getattr(Key, "media_volume_mute", None),
        "play": getattr(Key, "media_play_pause", None),
        "next": getattr(Key, "media_next", None),
        "prev": getattr(Key, "media_previous", None),
    }
    key = mapping.get(kind)
    if key is None:
        raise ControlError("este sistema no tiene esa tecla multimedia")
    _mouse, keyboard = _input()
    keyboard.press(key)
    keyboard.release(key)


def _win_media_key(vk: int) -> str:
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(vk, 0, 2, 0)
    return "Volumen de Windows"


def _display_ok() -> bool:
    if SYSTEM != "Linux":
        return True
    import os

    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _ydotool(args: list[str]) -> None:
    if not _which("ydotool"):
        raise ControlError("No hay sesión gráfica para mover el ratón")
    result = _run(["ydotool", *args])
    if result.returncode != 0:
        raise ControlError("ydotool no pudo mover el ratón")


def set_cursor_mode(mode: str) -> dict[str, Any]:
    global _cursor_mode
    if mode not in ("normal", "large", "huge"):
        raise ControlError("modo de cursor no válido")
    with _lock:
        detail = _apply_cursor_size(_cursor_target(mode))
        _cursor_mode = mode
    labels = {"normal": "Cursor normal", "large": "Cursor grande", "huge": "Cursor enorme"}
    return {"mode": mode, "label": labels[mode], "detail": detail}


def cursor_status() -> dict[str, str]:
    return {"mode": _cursor_mode}


def _cursor_target(mode: str) -> Any:
    if SYSTEM == "Windows":
        size = {"normal": 1, "large": 8, "huge": 15}[mode]
        return (size, _windows_base(size))
    if SYSTEM == "Darwin":
        return {"normal": 1.0, "large": 2.5, "huge": 4.0}[mode]
    return {"normal": 24, "large": 48, "huge": 96}[mode]


def _read_cursor_size() -> Any:
    if SYSTEM == "Windows":
        import winreg

        cursor = 1
        base = 32
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Accessibility") as key:
                cursor = int(winreg.QueryValueEx(key, "CursorSize")[0])
        except OSError:
            cursor = 1
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Cursors") as key:
                base = int(winreg.QueryValueEx(key, "CursorBaseSize")[0])
        except OSError:
            base = _windows_base(cursor)
        return (cursor, base)
    if SYSTEM == "Darwin":
        result = _run(
            ["defaults", "read", "com.apple.universalaccess", "mouseDriverCursorSize"]
        )
        try:
            return float(result.stdout.strip())
        except ValueError:
            return 1.0
    if _which("gsettings"):
        result = _run(["gsettings", "get", "org.gnome.desktop.interface", "cursor-size"])
        raw = result.stdout.strip().split()[-1] if result.stdout.strip() else ""
        try:
            return int(raw)
        except ValueError:
            return 24
    return 24


def _windows_base(size: int) -> int:
    size = max(1, min(15, int(size)))
    return 32 + (size - 1) * 16


def _windows_refresh_cursors(base: int) -> None:
    user32 = ctypes.windll.user32
    user32.SystemParametersInfoW.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
    user32.SystemParametersInfoW.restype = ctypes.c_bool
    # 0x2029 aplica el tamaño al momento. El tercer valor es el tamaño, no un puntero.
    user32.SystemParametersInfoW(0x2029, 0, ctypes.c_void_p(int(base)), 0x0001 | 0x0002)
    user32.SystemParametersInfoW(0x0057, 0, None, 0x0001 | 0x0002)


def _apply_cursor_size(size: Any) -> str:
    if SYSTEM == "Windows":
        import winreg

        if isinstance(size, tuple):
            cursor, base = int(size[0]), int(size[1])
        else:
            cursor = int(size)
            base = _windows_base(cursor)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Accessibility") as key:
            winreg.SetValueEx(key, "CursorSize", 0, winreg.REG_DWORD, cursor)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Cursors") as key:
            winreg.SetValueEx(key, "CursorBaseSize", 0, winreg.REG_DWORD, base)
        _windows_refresh_cursors(base)
        return "Cursor cambiado al momento"
    if SYSTEM == "Darwin":
        result = _run(
            [
                "defaults",
                "write",
                "com.apple.universalaccess",
                "mouseDriverCursorSize",
                "-float",
                str(float(size)),
            ]
        )
        if result.returncode != 0:
            raise ControlError("macOS no dejó cambiar el tamaño del cursor")
        return "Tamaño pedido a macOS. Hace falta permiso de Accesibilidad; a veces pide cerrar sesión."
    if _which("gsettings"):
        result = _run(
            ["gsettings", "set", "org.gnome.desktop.interface", "cursor-size", str(int(size))]
        )
        if result.returncode == 0:
            return "Cursor del escritorio GNOME"
    raise ControlError(
        "No pude agrandar el cursor del sistema. En GNOME instala el escritorio con gsettings."
    )


_SKIP_TITLES = {
    "program manager",
    "windows input experience",
    "windows shell experience host",
    "msctfime ui",
    "default ime",
}


def typing_focus() -> bool:
    if SYSTEM != "Windows":
        return False
    user32 = ctypes.windll.user32

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class GUITHREADINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("flags", ctypes.c_ulong),
            ("hwndActive", ctypes.c_void_p),
            ("hwndFocus", ctypes.c_void_p),
            ("hwndCapture", ctypes.c_void_p),
            ("hwndMenuOwner", ctypes.c_void_p),
            ("hwndMoveSize", ctypes.c_void_p),
            ("hwndCaret", ctypes.c_void_p),
            ("rcCaret", RECT),
        ]

    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    user32.GetGUIThreadInfo.argtypes = [ctypes.c_ulong, ctypes.POINTER(GUITHREADINFO)]
    user32.GetGUIThreadInfo.restype = ctypes.c_bool
    user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    foreground = user32.GetForegroundWindow()
    if not foreground:
        return False
    thread = user32.GetWindowThreadProcessId(foreground, None)
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    if not user32.GetGUIThreadInfo(thread, ctypes.byref(info)):
        return False
    caret = info.rcCaret.right - info.rcCaret.left or info.rcCaret.bottom - info.rcCaret.top
    if info.flags & 0x1 or info.hwndCaret or caret:
        return True
    if not info.hwndFocus:
        return False
    name = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(info.hwndFocus, name, 64)
    kind = name.value.lower()
    return "edit" in kind


def list_windows() -> list[dict[str, str]]:
    with _lock:
        if SYSTEM == "Windows":
            return _windows_list()
        if SYSTEM == "Darwin":
            return _mac_windows()
        return _linux_windows()


def window_action(window_id: str, action: str) -> str:
    allowed = {"focus", "minimize", "maximize", "close", "snap_left", "snap_right"}
    if action not in allowed:
        raise ControlError("acción de ventana no válida")
    if not window_id:
        raise ControlError("falta la ventana")
    with _lock:
        if SYSTEM == "Windows":
            return _windows_action(int(window_id), action)
        if SYSTEM == "Darwin":
            return _mac_window_action(window_id, action)
        return _linux_window_action(window_id, action)


def _windows_list() -> list[dict[str, str]]:
    user32 = ctypes.windll.user32
    rows: list[dict[str, str]] = []

    try:
        dwmapi = ctypes.windll.dwmapi
    except OSError:
        dwmapi = None

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if dwmapi is not None:
            cloaked = ctypes.c_int(0)
            if dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4) == 0 and cloaked.value:
                return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title or title.lower() in _SKIP_TITLES:
            return True
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = _process_name(pid.value)
        rows.append({"id": str(int(hwnd)), "title": title[:180], "process": process})
        return True

    user32.EnumWindows(callback, 0)
    return rows[:40]


def _hwnd(value: int) -> ctypes.c_void_p:
    return ctypes.c_void_p(int(value))


def _user32():
    user32 = ctypes.windll.user32
    void = ctypes.c_void_p
    user32.ShowWindow.argtypes = [void, ctypes.c_int]
    user32.ShowWindow.restype = ctypes.c_bool
    user32.SetForegroundWindow.argtypes = [void]
    user32.SetForegroundWindow.restype = ctypes.c_bool
    user32.BringWindowToTop.argtypes = [void]
    user32.BringWindowToTop.restype = ctypes.c_bool
    user32.GetForegroundWindow.restype = void
    user32.GetWindowThreadProcessId.argtypes = [void, ctypes.c_void_p]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool]
    user32.AttachThreadInput.restype = ctypes.c_bool
    user32.IsIconic.argtypes = [void]
    user32.IsIconic.restype = ctypes.c_bool
    user32.IsWindow.argtypes = [void]
    user32.IsWindow.restype = ctypes.c_bool
    user32.PostMessageW.argtypes = [void, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    user32.PostMessageW.restype = ctypes.c_bool
    return user32


def _force_foreground(hwnd: int) -> None:
    user32 = _user32()
    handle = _hwnd(hwnd)
    # SW_RESTORE (9) saca la ventana de maximizada. Solo si está minimizada.
    if user32.IsIconic(handle):
        user32.ShowWindow(handle, 9)
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    target_thread = user32.GetWindowThreadProcessId(handle, None)
    attached = bool(fg_thread and target_thread and fg_thread != target_thread)
    if attached:
        user32.AttachThreadInput(fg_thread, target_thread, True)
    user32.SetForegroundWindow(handle)
    user32.BringWindowToTop(handle)
    if attached:
        user32.AttachThreadInput(fg_thread, target_thread, False)


def _win_hotkey(*vks: int) -> None:
    user32 = ctypes.windll.user32
    for vk in vks:
        user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks):
        user32.keybd_event(vk, 0, 2, 0)


def _process_name(pid: int) -> str:
    if not pid:
        return ""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = ctypes.c_ulong(260)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value.rsplit("\\", 1)[-1]
    finally:
        kernel32.CloseHandle(handle)


_BROWSERS = ("chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe")


def pick_spotify_window(rows: list[dict[str, str]]) -> dict[str, str] | None:
    for row in rows:
        process = row.get("process", "").lower()
        title = row.get("title", "")
        title_l = title.lower()
        if process in _BROWSERS or any(mark in title_l for mark in ("google chrome", "mozilla firefox", "microsoft edge")):
            continue
        if process == "spotify.exe" or title_l in {"spotify", "spotify premium", "spotify free"}:
            return row
        if not process and "spotify" in title_l:
            return row
    return None


def _launch_spotify_app() -> None:
    import os

    candidates = [
        os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\Spotify.exe"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            subprocess.Popen([path])
            return
    subprocess.Popen(["cmd", "/c", "start", "", "spotify:"], close_fds=True)


def _windows_action(hwnd: int, action: str) -> str:
    user32 = _user32()
    handle = _hwnd(hwnd)
    if not user32.IsWindow(handle):
        raise ControlError("Esa ventana ya se cerró. Pulsa Actualizar.")
    if action == "focus":
        _force_foreground(hwnd)
        return "Ventana al frente"
    if action == "minimize":
        user32.ShowWindow(handle, 6)
        return "Minimizada"
    if action == "maximize":
        user32.ShowWindow(handle, 3)
        return "Maximizada"
    if action == "close":
        user32.SendMessageTimeoutW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        user32.SendMessageTimeoutW.restype = ctypes.c_void_p
        answered = ctypes.c_size_t()
        user32.SendMessageTimeoutW(handle, 0x0010, 0, 0, 0x0002, 400, ctypes.byref(answered))
        if user32.IsWindow(handle):
            _force_foreground(hwnd)
            _win_hotkey(0x12, 0x73)
        return "Cerrada"
    if action == "snap_left":
        _force_foreground(hwnd)
        _win_hotkey(0x5B, 0x25)
        return "A la izquierda"
    _force_foreground(hwnd)
    _win_hotkey(0x5B, 0x27)
    return "A la derecha"


def _linux_windows() -> list[dict[str, str]]:
    if not _which("wmctrl"):
        raise ControlError("Instala wmctrl para ver las ventanas (sudo apt install wmctrl)")
    result = _run(["wmctrl", "-l"])
    if result.returncode != 0:
        raise ControlError("wmctrl no pudo listar las ventanas. En Wayland a veces hace falta una sesión Xorg.")
    rows = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        title = parts[3].strip()
        if not title or title.lower() in _SKIP_TITLES:
            continue
        rows.append({"id": parts[0], "title": title[:180]})
    return rows[:40]


def _linux_window_action(window_id: str, action: str) -> str:
    if not window_id.startswith("0x"):
        raise ControlError("ventana no válida")
    if not _which("wmctrl"):
        raise ControlError("Instala wmctrl")
    if action == "focus":
        cmd = ["wmctrl", "-i", "-a", window_id]
        label = "Ventana al frente"
    elif action == "minimize":
        cmd = ["wmctrl", "-i", "-r", window_id, "-b", "add,hidden"]
        label = "Minimizada"
    elif action == "maximize":
        cmd = ["wmctrl", "-i", "-r", window_id, "-b", "add,maximized_vert,maximized_horz"]
        label = "Maximizada"
    elif action == "close":
        cmd = ["wmctrl", "-i", "-c", window_id]
        label = "Cerrar enviado"
    else:
        _run(["wmctrl", "-i", "-a", window_id])
        _run(["wmctrl", "-i", "-r", window_id, "-b", "remove,maximized_vert,maximized_horz"])
        geo = _desktop_size()
        width = max(400, geo[0] // 2)
        x = 0 if action == "snap_left" else width
        cmd = ["wmctrl", "-i", "-r", window_id, "-e", f"0,{x},0,{width},{geo[1]}"]
        label = "A la izquierda" if action == "snap_left" else "A la derecha"
    result = _run(cmd)
    if result.returncode != 0:
        raise ControlError("No pude mover esa ventana")
    return label


def _desktop_size() -> tuple[int, int]:
    result = _run(["wmctrl", "-d"])
    for line in result.stdout.splitlines():
        if "DG:" in line:
            chunk = line.split("DG:", 1)[1].split()[0]
            if "x" in chunk:
                w, h = chunk.split("x", 1)
                return int(w), int(h)
    return 1920, 1080


def _mac_windows() -> list[dict[str, str]]:
    script = r'''
set rows to {}
tell application "System Events"
  repeat with p in (every process whose background only is false)
    set pn to name of p
    try
      set i to 1
      repeat with w in windows of p
        set wn to name of w
        if wn is not "" then set end of rows to pn & tab & (i as text) & tab & wn
        set i to i + 1
      end repeat
    end try
  end repeat
end tell
set AppleScript's text item delimiters to linefeed
return rows as text
'''
    result = _run(["osascript", "-e", script], timeout=8)
    if result.returncode != 0:
        raise ControlError("macOS no dejó ver las ventanas. Da permiso de Accesibilidad a Terminal.")
    rows = []
    for line in result.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        app, index, title = parts
        rows.append({"id": f"{app}\t{index}", "title": f"{title[:140]}  ·  {app}"[:180]})
    return rows[:40]


def _mac_window_action(window_id: str, action: str) -> str:
    if "\t" not in window_id:
        raise ControlError("ventana no válida")
    app, index = window_id.split("\t", 1)
    if not index.isdigit() or not app:
        raise ControlError("ventana no válida")
    if action == "focus":
        body = "set frontmost to true\nperform action \"AXRaise\" of window IDX"
        label = "Ventana al frente"
    elif action == "minimize":
        body = 'set value of attribute "AXMinimized" of window IDX to true'
        label = "Minimizada"
    elif action == "maximize":
        body = 'click (first button of window IDX whose subrole is "AXFullScreenButton")'
        label = "Pantalla completa"
    elif action == "close":
        body = 'click (first button of window IDX whose subrole is "AXCloseButton")'
        label = "Cerrar enviado"
    elif action == "snap_left":
        body = 'set frontmost to true\nset position of window IDX to {0, 30}\nset size of window IDX to {720, 800}'
        label = "A la izquierda"
    else:
        body = 'set frontmost to true\nset position of window IDX to {740, 30}\nset size of window IDX to {720, 800}'
        label = "A la derecha"
    body = body.replace("IDX", index)
    script = f'''
tell application "System Events"
  tell process "{_as_escape(app)}"
    {body}
  end tell
end tell
'''
    result = _run(["osascript", "-e", script], timeout=8)
    if result.returncode != 0:
        raise ControlError("macOS no dejó tocar esa ventana. Revisa Accesibilidad.")
    return label


def _as_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _find_title(needle: str, exclude: str | None = None) -> dict[str, str] | None:
    needle = needle.lower()
    exclude_l = exclude.lower() if exclude else None
    for row in list_windows():
        title = row["title"].lower()
        if exclude_l and exclude_l in title:
            continue
        if needle in title:
            return row
    return None


_levels = {"youtube": 50, "spotify": 50, "youtube_speed": 1.0}
_YOUTUBE_SPEEDS = (1.0, 1.25, 1.5, 2.0)
_YOUTUBE_LADDER = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
_YOUTUBE_SPEED_TEXT = {1.0: "1.0", 1.25: "1.25", 1.5: "1.50", 2.0: "2"}


def match_youtube_speed(raw: object) -> float:
    rate = round(float(raw), 2)
    for item in _YOUTUBE_SPEEDS:
        if abs(rate - item) < 0.001:
            return item
    raise ControlError("velocidad no válida")


def youtube_speed_ups(raw: object) -> int:
    return _YOUTUBE_LADDER.index(match_youtube_speed(raw))


def youtube(action: str, extra: dict | None = None) -> dict[str, Any]:
    extra = extra or {}
    if action == "search":
        return _youtube_search(str(extra.get("query", "")))
    if action == "open":
        return _youtube_open(str(extra.get("video", "")))
    if action == "home":
        return _youtube_home()
    if action == "volume":
        return _youtube_volume(int(extra.get("level", _levels["youtube"])))
    if action == "speed":
        return _youtube_speed(extra.get("rate", _levels["youtube_speed"]))
    actions = {
        "play": ["k"],
        "mute": ["m"],
        "full": ["f"],
        "back": ["j"],
        "forward": ["l"],
        "volup": ["up"],
        "voldown": ["down"],
        "next": ["shift", "N"],
        "prev": ["shift", "P"],
        "captions": ["c"],
        "theater": ["t"],
    }
    if action not in actions:
        raise ControlError("acción de YouTube no válida")
    with _lock:
        row = _find_youtube_unlocked()
        if row is None:
            raise ControlError("No veo YouTube. Ábrelo en el navegador de este PC.")
        _focus_unlocked(row["id"])
    time.sleep(0.12)
    with _lock:
        _chord(actions[action])
    if action == "volup":
        _levels["youtube"] = min(100, _levels["youtube"] + 5)
    elif action == "voldown":
        _levels["youtube"] = max(0, _levels["youtube"] - 5)
    return {"detail": "YouTube", "title": row["title"], "level": _levels["youtube"]}


def _youtube_speed(raw: object) -> dict[str, Any]:
    rate = match_youtube_speed(raw)
    with _lock:
        row = _find_youtube_unlocked()
        if row is None:
            raise ControlError("No veo YouTube. Ábrelo en el navegador de este PC.")
        _focus_unlocked(row["id"])
    time.sleep(0.12)
    # YouTube solo salta 0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75 y 2.
    # Bajar del todo y luego subir deja la velocidad exacta, sin abrir ventanas.
    for _ in range(8):
        _speed_tap(False)
        time.sleep(0.04)
    for _ in range(youtube_speed_ups(rate)):
        _speed_tap(True)
        time.sleep(0.04)
    _levels["youtube_speed"] = rate
    label = _YOUTUBE_SPEED_TEXT[rate]
    return {
        "detail": f"Velocidad {label}",
        "title": row["title"],
        "level": _levels["youtube"],
        "rate": rate,
    }


def _speed_tap(faster: bool) -> None:
    if SYSTEM == "Windows" and _win_speed_key(faster):
        return
    _chord(["shift", "." if faster else ","])


def _win_speed_key(faster: bool) -> bool:
    extra = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", extra),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", extra),
        ]

    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

        _anonymous_ = ("u",)
        _fields_ = [("type", ctypes.c_ulong), ("u", _U)]

    if ctypes.sizeof(INPUT) != 40:
        return False
    # Shift + punto sube, Shift + coma baja. Son las teclas del vídeo, no un carácter.
    vk = 0xBE if faster else 0xBC
    steps = ((0x10, 0), (vk, 0), (vk, 0x0002), (0x10, 0x0002))
    batch = (INPUT * 4)()
    for index, (key, flags) in enumerate(steps):
        batch[index].type = 1
        batch[index].ki.wVk = key
        batch[index].ki.dwFlags = flags
    return ctypes.windll.user32.SendInput(4, batch, ctypes.sizeof(INPUT)) == 4


def _youtube_volume(level: int) -> dict[str, Any]:
    level = max(0, min(100, int(level)))
    steps = int(round((level - _levels["youtube"]) / 5))
    steps = max(-12, min(12, steps))
    with _lock:
        row = _find_youtube_unlocked()
        if row is None:
            raise ControlError("No veo YouTube. Ábrelo en el navegador de este PC.")
        if steps:
            _focus_unlocked(row["id"])
    if steps:
        time.sleep(0.12)
        with _lock:
            for _ in range(abs(steps)):
                _chord(["up" if steps > 0 else "down"])
        _levels["youtube"] = max(0, min(100, _levels["youtube"] + steps * 5))
    else:
        _levels["youtube"] = level
    return {"detail": "YouTube", "title": row["title"], "level": _levels["youtube"]}


def _youtube_home() -> dict[str, Any]:
    import webbrowser

    webbrowser.open_new("https://www.youtube.com/")
    return {"detail": "Inicio de YouTube", "title": "Inicio de YouTube", "level": _levels["youtube"]}


def _youtube_search(query: str) -> dict[str, Any]:
    import urllib.parse
    import webbrowser

    query = query.strip()[:120]
    if not query:
        raise ControlError("escribe qué buscar")
    webbrowser.open_new("https://www.youtube.com/results?search_query=" + urllib.parse.quote(query))
    return {
        "detail": "Búsqueda abierta en el PC",
        "title": query,
        "results": _youtube_hits(query),
        "level": _levels["youtube"],
    }


def _youtube_hits(query: str) -> list[dict[str, str]]:
    import html
    import re
    import urllib.parse
    import urllib.request

    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        page = urllib.request.urlopen(request, timeout=5).read().decode("utf-8", "replace")
    except Exception:
        return []
    hits: list[dict[str, str]] = []
    seen: set[str] = set()
    pattern = re.compile(r'"videoId":"([\w-]{11})".{0,500}?"text":"((?:\\.|[^"\\]){1,160})"')
    for video_id, title in pattern.findall(page):
        if video_id in seen:
            continue
        seen.add(video_id)
        try:
            title = html.unescape(title.encode("utf-8").decode("unicode_escape"))
        except UnicodeError:
            title = html.unescape(title)
        hits.append({"id": video_id, "title": title[:140]})
        if len(hits) >= 5:
            break
    return hits


def _youtube_open(video: str) -> dict[str, Any]:
    import re
    import webbrowser

    if not re.fullmatch(r"[\w-]{11}", video):
        raise ControlError("vídeo no válido")
    webbrowser.open_new(f"https://www.youtube.com/watch?v={video}")
    return {"detail": "Vídeo abierto en el PC", "title": "YouTube", "level": _levels["youtube"]}


def _find_youtube_unlocked() -> dict[str, str] | None:
    if SYSTEM == "Windows":
        rows = _windows_list()
    elif SYSTEM == "Darwin":
        rows = _mac_windows()
    else:
        rows = _linux_windows()
    for row in rows:
        title = row["title"].lower()
        if "youtube music" in title:
            continue
        if "youtube" in title:
            return row
    return None


def _focus_unlocked(window_id: str) -> None:
    if SYSTEM == "Windows":
        _windows_action(int(window_id), "focus")
    elif SYSTEM == "Darwin":
        _mac_window_action(window_id, "focus")
    else:
        _linux_window_action(window_id, "focus")


def spotify(action: str, extra: dict | None = None) -> dict[str, Any]:
    extra = extra or {}
    allowed = {"play", "next", "prev", "volup", "voldown", "status", "volume", "mute", "search"}
    if action not in allowed:
        raise ControlError("acción de Spotify no válida")
    with _lock:
        if SYSTEM == "Darwin":
            return _mac_spotify(action, extra)
        if SYSTEM == "Linux":
            return _linux_spotify(action, extra)
        return _windows_spotify(action, extra)


def _mac_spotify(action: str, extra: dict | None = None) -> dict[str, Any]:
    extra = extra or {}
    if action == "search":
        return _spotify_search(str(extra.get("query", "")))
    if action == "volume":
        level = max(0, min(100, int(extra.get("level", _levels["spotify"]))))
        command = f"set sound volume to {level}"
        _levels["spotify"] = level
    elif action == "mute":
        command = "set sound volume to 0" if _levels["spotify"] else "set sound volume to 40"
        _levels["spotify"] = 0 if _levels["spotify"] else 40
    else:
        commands = {
            "play": "playpause",
            "next": "next track",
            "prev": "previous track",
            "volup": "set sound volume to (sound volume + 10)",
            "voldown": "set sound volume to (sound volume - 10)",
            "status": "",
        }
        command = commands[action]
    script = f'''
tell application "Spotify"
  if it is not running then error "apagado"
  {command}
  set who to artist of current track
  set what to name of current track
  set loud to sound volume
  return who & " — " & what & tab & (loud as text)
end tell
'''
    result = _run(["osascript", "-e", script], timeout=6)
    if result.returncode != 0:
        raise ControlError("Abre la app de Spotify en el Mac")
    lines = result.stdout.strip().split("\t")
    title = lines[0][:180]
    if len(lines) > 1 and lines[1].isdigit():
        _levels["spotify"] = int(lines[1])
    return {"detail": "Spotify", "title": title, "level": _levels["spotify"]}


def _linux_spotify(action: str, extra: dict | None = None) -> dict[str, Any]:
    extra = extra or {}
    if action == "search":
        return _spotify_search(str(extra.get("query", "")))
    if not _which("playerctl"):
        raise ControlError("Instala playerctl para Spotify (sudo apt install playerctl)")
    players = _run(["playerctl", "-l"])
    names = [line.strip() for line in players.stdout.splitlines() if line.strip()]
    player = next((name for name in names if "spotify" in name.lower()), None)
    if player is None:
        raise ControlError("Abre Spotify en este PC")
    if action == "volume":
        level = max(0, min(100, int(extra.get("level", _levels["spotify"]))))
        verbs = ["volume", str(level / 100)]
        _levels["spotify"] = level
    elif action == "mute":
        verbs = ["volume", "0" if _levels["spotify"] else "0.4"]
        _levels["spotify"] = 0 if _levels["spotify"] else 40
    else:
        verbs = {
            "play": ["play-pause"],
            "next": ["next"],
            "prev": ["previous"],
            "volup": ["volume", "0.08+"],
            "voldown": ["volume", "0.08-"],
            "status": [],
        }[action]
    if verbs:
        result = _run(["playerctl", "-p", player, *verbs])
        if result.returncode != 0:
            raise ControlError("Spotify no respondió")
    meta = _run(["playerctl", "-p", player, "metadata", "--format", "{{artist}} — {{title}}"])
    title = meta.stdout.strip() or "Spotify"
    return {"detail": "Spotify", "title": title[:180], "level": _levels["spotify"]}


def _windows_spotify(action: str, extra: dict | None = None) -> dict[str, Any]:
    extra = extra or {}
    if action == "search":
        return _spotify_search(str(extra.get("query", "")))
    row = pick_spotify_window(_windows_list())
    if row is None:
        if action != "status":
            _launch_spotify_app()
        raise ControlError("Abro la app de Spotify del PC, no la web. Espera un segundo y pulsa otra vez.")
    title = _spotify_title(row)
    if action == "status":
        return {"detail": "Spotify", "title": title, "level": _levels["spotify"]}
    if action == "volume":
        return _windows_spotify_volume(int(row["id"]), int(extra.get("level", _levels["spotify"])), title)
    if action == "mute":
        target = 0 if _levels["spotify"] else 40
        return _windows_spotify_volume(int(row["id"]), target, title)
    # Play, anterior y siguiente son teclas globales. No se toca el tamaño de la ventana.
    keys = {"play": 0xB3, "next": 0xB0, "prev": 0xB1, "volup": None, "voldown": None}
    if action in ("volup", "voldown"):
        return _windows_spotify_volume(
            int(row["id"]),
            _levels["spotify"] + (10 if action == "volup" else -10),
            title,
        )
    _win_media_key(keys[action])
    time.sleep(0.32)
    fresh = pick_spotify_window(_windows_list())
    if fresh is not None:
        title = _spotify_title(fresh)
    return {"detail": "Spotify", "title": title, "level": _levels["spotify"]}


def _spotify_title(row: dict[str, str]) -> str:
    title = row["title"]
    if title.lower() in {"spotify", "spotify premium", "spotify free"}:
        return "Spotify"
    return title[:180]


def _windows_spotify_volume(hwnd: int, level: int, title: str) -> dict[str, Any]:
    level = max(0, min(100, int(level)))
    steps = int(round((level - _levels["spotify"]) / 10))
    steps = max(-10, min(10, steps))
    if steps:
        _force_foreground(hwnd)
        for _ in range(abs(steps)):
            _win_hotkey(0x11, 0x26 if steps > 0 else 0x28)
            time.sleep(0.03)
        _levels["spotify"] = max(0, min(100, _levels["spotify"] + steps * 10))
    else:
        _levels["spotify"] = level
    return {"detail": "Spotify", "title": title, "level": _levels["spotify"]}


def _spotify_search(query: str) -> dict[str, Any]:
    import urllib.parse

    query = query.strip()[:120]
    if not query:
        raise ControlError("escribe qué buscar")
    uri = "spotify:search:" + urllib.parse.quote(query)
    if SYSTEM == "Windows":
        subprocess.Popen(["cmd", "/c", "start", "", uri], close_fds=True)
    elif SYSTEM == "Darwin":
        subprocess.Popen(["open", uri])
    else:
        subprocess.Popen(["xdg-open", uri])
    return {
        "detail": "Búsqueda en la app de Spotify",
        "title": query,
        "results": [],
        "level": _levels["spotify"],
    }


def status() -> dict[str, Any]:
    now = ""
    try:
        info = spotify("status")
        now = info.get("title", "")
    except ControlError:
        now = ""
    return {
        "platform": SYSTEM,
        "cursor": _cursor_mode,
        "spotify": now,
    }


def set_history_path(path: Path) -> None:
    global _history_path, _history, _history_loaded, _clip_seq
    _history_path = Path(path)
    _history = []
    _history_loaded = False
    _clip_seq = 0


def clipboard_history(text: str | None = None, auto: bool = False) -> dict[str, Any]:
    with _clip_lock:
        _load_history()
        if text is not None:
            clean = _clip_norm(text)
            if clean:
                _remember_clip(clean, auto)
        ranked = sorted(
            _history,
            key=lambda item: (float(item.get("at") or 0), int(item.get("seq") or 0)),
            reverse=True,
        )
        _history[:] = ranked
        return {"items": [dict(item) for item in _history]}


def _clip_norm(text: str) -> str:
    clean = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return clean[:_CLIP_CHARS]


def _remember_clip(clean: str, auto: bool) -> None:
    global _clip_seq
    for index, item in enumerate(_history):
        if _clip_norm(str(item.get("text") or "")) == clean:
            if auto:
                return
            _clip_seq += 1
            item["text"] = clean
            item["at"] = time.time()
            item["seq"] = _clip_seq
            _history.insert(0, _history.pop(index))
            _save_history()
            return
    _clip_seq += 1
    _history.insert(
        0,
        {"id": secrets.token_hex(4), "text": clean, "at": time.time(), "seq": _clip_seq},
    )
    del _history[_CLIP_LIMIT:]
    _save_history()


def _load_history() -> None:
    global _history_loaded
    if _history_loaded:
        return
    _history_loaded = True
    try:
        raw = json.loads(_open_seal(_history_path.read_bytes()).decode("utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return
    if not isinstance(raw, list):
        return
    kept: dict[str, tuple[tuple[float, int], dict[str, Any]]] = {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        clean = _clip_norm(item["text"])
        if not clean:
            continue
        stamp = (float(item.get("at") or 0), int(item.get("seq") or 0))
        previous = kept.get(clean)
        if previous is None or stamp >= previous[0]:
            kept[clean] = (stamp, item)
    ranked = sorted(kept.items(), key=lambda pair: pair[1][0], reverse=True)
    global _clip_seq
    for clean, (stamp, item) in ranked[:_CLIP_LIMIT]:
        seq = int(item.get("seq") or 0)
        _clip_seq = max(_clip_seq, seq)
        _history.append(
            {
                "id": str(item.get("id") or secrets.token_hex(4)),
                "text": clean,
                "at": stamp[0],
                "seq": seq,
            }
        )


def _save_history() -> None:
    try:
        raw = json.dumps(_history, ensure_ascii=False).encode("utf-8")
        _history_path.write_bytes(_seal(raw))
    except OSError:
        return


def _read_clipboard_text() -> str:
    try:
        if SYSTEM == "Windows":
            return _windows_clipboard()
        if SYSTEM == "Darwin":
            result = _run(["pbpaste"])
            return result.stdout if result.returncode == 0 else ""
        import os

        if os.environ.get("WAYLAND_DISPLAY") and _which("wl-paste"):
            result = _run(["wl-paste", "-n"])
            if result.returncode == 0:
                return result.stdout
        if _which("xclip"):
            result = _run(["xclip", "-selection", "clipboard", "-o"])
            if result.returncode == 0:
                return result.stdout
        if _which("xsel"):
            result = _run(["xsel", "--clipboard", "--output"])
            if result.returncode == 0:
                return result.stdout
    except Exception:
        return ""
    return ""


def _windows_clipboard() -> str:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_bool
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_bool
    if not user32.OpenClipboard(None):
        time.sleep(0.02)
        if not user32.OpenClipboard(None):
            return ""
    try:
        handle = user32.GetClipboardData(13)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


_injected_until = 0.0
_hook_proc = None


def _mark_injected() -> None:
    global _injected_until
    _injected_until = time.time() + 0.2


def watch_physical_mouse() -> None:
    if SYSTEM != "Windows":
        return
    threading.Thread(target=_physical_mouse_loop, name="lazo-mouse", daemon=True).start()


def _physical_mouse_loop() -> None:
    global _hook_proc
    user32 = ctypes.windll.user32
    user32.CallNextHookEx.restype = ctypes.c_long
    user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p]

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("pt", POINT),
            ("mouseData", ctypes.c_ulong),
            ("flags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    def _proc(code, wparam, lparam):
        if code >= 0 and lparam:
            flags = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents.flags
            real = not (flags & 0x01 or flags & 0x02)
            if real and time.time() > _injected_until and _cursor_mode != "normal":
                try:
                    set_cursor_mode("normal")
                except ControlError:
                    pass
        return user32.CallNextHookEx(None, code, wparam, lparam)

    hook_type = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, ctypes.c_size_t, ctypes.c_void_p)
    _hook_proc = hook_type(_proc)
    user32.SetWindowsHookExW.restype = ctypes.c_void_p
    user32.SetWindowsHookExW(14, _hook_proc, None, 0)
    msg = ctypes.wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


_files_dir = Path(__file__).with_name("nube")
_photos_dir = Path(__file__).with_name("Fotos")
_FILE_CAP = 80 * 1024 * 1024
_FILE_TOTAL = 400 * 1024 * 1024
_PHOTO_CAP = 1536 * 1024 * 1024
_PHOTO_TOTAL = 30 * 1024 * 1024 * 1024
_photo_lock = threading.Lock()


def set_files_dir(path: Path) -> None:
    global _files_dir
    _files_dir = Path(path)


def set_photos_dir(path: Path) -> None:
    global _photos_dir
    _photos_dir = Path(path)


def list_photos() -> dict[str, Any]:
    _photos_dir.mkdir(parents=True, exist_ok=True)
    rows = _photo_rows()
    return {"folder": str(_photos_dir), "count": len(rows), "photos": rows[:40]}


def photo_status(name: str, size: int) -> dict[str, Any]:
    size = int(size)
    if size <= 0 or size > _PHOTO_CAP:
        raise ControlError("Pasa de 1,5 GB o está vacío")
    clean = _photo_name(name)
    path = _photos_dir / clean
    skip = path.is_file() and path.stat().st_size == size
    return {"skip": skip, "name": clean}


def start_photo(name: str, size: int) -> tuple[Path, Path] | None:
    size = int(size)
    if size <= 0 or size > _PHOTO_CAP:
        raise ControlError("Pasa de 1,5 GB o está vacío")
    clean = _photo_name(name)
    with _photo_lock:
        _photos_dir.mkdir(parents=True, exist_ok=True)
        current = _photos_dir / clean
        if current.is_file() and current.stat().st_size == size:
            return None
        used = sum(path.stat().st_size for path in _photos_dir.iterdir() if path.is_file() and not path.name.endswith(".part"))
        if used + size > _PHOTO_TOTAL:
            raise ControlError("La carpeta Fotos está llena")
        final = current if not current.exists() else _unique_photo(clean)
        part = Path(str(final) + ".part")
        part.write_bytes(b"")
        return part, final


def finish_photo(part: Path, final: Path, size: int) -> dict[str, Any]:
    if not part.is_file() or part.stat().st_size != int(size):
        part.unlink(missing_ok=True)
        raise ControlError("Se cortó el envío")
    if final.parent != _photos_dir:
        part.unlink(missing_ok=True)
        raise ControlError("nombre no válido")
    part.replace(final)
    return {"name": final.name, "size": int(size), "folder": str(_photos_dir)}


def open_photos_folder() -> dict[str, Any]:
    import os

    _photos_dir.mkdir(parents=True, exist_ok=True)
    if SYSTEM == "Windows":
        os.startfile(_photos_dir)  # type: ignore[attr-defined]
    elif SYSTEM == "Darwin":
        _run(["open", str(_photos_dir)])
    else:
        _run(["xdg-open", str(_photos_dir)])
    return {"folder": str(_photos_dir)}


def _photo_name(name: str) -> str:
    base = Path(str(name).replace("\\", "/")).name
    base = "".join(ch for ch in base if ch not in '<>:"|?*' and ord(ch) >= 32).strip().strip(".")
    return (base or "foto")[:120]


def _unique_photo(name: str) -> Path:
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        stem, ext = name, ""
    else:
        ext = "." + ext
    number = 2
    while True:
        candidate = _photos_dir / f"{stem} ({number}){ext}"
        if not candidate.exists():
            return candidate
        number += 1


def _photo_rows() -> list[dict[str, Any]]:
    if not _photos_dir.is_dir():
        return []
    rows = []
    for path in _photos_dir.iterdir():
        if not path.is_file() or path.name.endswith(".part") or path.name.startswith("."):
            continue
        stat = path.stat()
        rows.append({"name": path.name, "size": stat.st_size, "at": int(stat.st_mtime)})
    rows.sort(key=lambda row: (row["at"], row["name"]), reverse=True)
    return rows


def list_files() -> dict[str, Any]:
    return {"files": _file_rows()}


def save_file(name: str, data: bytes) -> dict[str, Any]:
    if not isinstance(data, bytes) or not data:
        raise ControlError("archivo vacío")
    if len(data) > _FILE_CAP:
        raise ControlError("El archivo pasa de 80 MB")
    clean = "".join(ch for ch in name if ch.isalnum() or ch in "._- ").strip()[:80] or "archivo"
    _files_dir.mkdir(parents=True, exist_ok=True)
    rows = _file_rows()
    total = sum(int(row["size"]) for row in rows) + len(data)
    if total > _FILE_TOTAL:
        raise ControlError("La mesa está llena. Quita algún archivo.")
    file_id = secrets.token_hex(4)
    (_files_dir / file_id).write_bytes(_seal(data))
    rows.insert(0, {"id": file_id, "name": clean, "size": len(data), "at": int(time.time())})
    _write_file_rows(rows[:30])
    return {"file": rows[0]}


def read_file(file_id: str) -> tuple[str, bytes]:
    row = _file_row(file_id)
    if row is None:
        raise ControlError("ese archivo ya no está")
    return row["name"], _open_seal((_files_dir / row["id"]).read_bytes())


def delete_file(file_id: str) -> dict[str, Any]:
    row = _file_row(file_id)
    rows = [item for item in _file_rows() if item["id"] != file_id]
    if row is not None:
        path = _files_dir / row["id"]
        if path.is_file():
            path.unlink()
    _write_file_rows(rows)
    return {"ok": True}


def _file_row(file_id: str) -> dict[str, Any] | None:
    if not isinstance(file_id, str) or len(file_id) != 8 or any(ch not in "0123456789abcdef" for ch in file_id):
        return None
    for row in _file_rows():
        if row["id"] == file_id:
            return row
    return None


def _file_rows() -> list[dict[str, Any]]:
    try:
        raw = json.loads((_files_dir / "index.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        file_id = str(item.get("id", ""))
        if len(file_id) != 8 or not (_files_dir / file_id).is_file():
            continue
        rows.append(
            {
                "id": file_id,
                "name": str(item.get("name") or "archivo")[:80],
                "size": int(item.get("size") or 0),
                "at": int(item.get("at") or 0),
            }
        )
    return rows


def _write_file_rows(rows: list[dict[str, Any]]) -> None:
    _files_dir.mkdir(parents=True, exist_ok=True)
    (_files_dir / "index.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def _seal(data: bytes) -> bytes:
    if SYSTEM != "Windows" or not data:
        return data
    sealed = _dpapi(data, True)
    if not sealed:
        return data
    return b"LZ1" + sealed


def _open_seal(data: bytes) -> bytes:
    if data.startswith(b"LZ1"):
        opened = _dpapi(data[3:], False)
        return opened or data
    return data


def _dpapi(data: bytes, protect: bool) -> bytes:
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.c_void_p)]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data)
    incoming = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.c_void_p))
    outgoing = DATA_BLOB()
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_wchar_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.argtypes = crypt32.CryptProtectData.argtypes
    crypt32.CryptProtectData.restype = ctypes.c_bool
    crypt32.CryptUnprotectData.restype = ctypes.c_bool
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(incoming), None, None, None, None, 0, ctypes.byref(outgoing)):
        return b""
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        kernel32.LocalFree(outgoing.pbData)



