"""Icono de LaZoo en la bandeja de Windows (Fase 2). Solo biblioteca estándar + ctypes.

El servidor corre en un hilo de este mismo proceso (lazo.start), así que la bandeja lee
y cambia dispositivos y aprobaciones directamente en APPROVALS, que ya va con lock.
Nada nuevo queda expuesto a la red: el menú abre páginas por 127.0.0.1.

En Linux y macOS se puede importar, pero `main()` solo avisa: su bandeja es una fase
posterior. Ahí sigue valiendo iniciar.sh.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLASS_NAME = "LaZooBandeja"
MUTEX_NAME = "Local\\LaZooBandeja"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "LaZoo"

WM_APP = 0x8000
WM_TRAY = WM_APP + 1      # clics en el icono
WM_NEWDEV = WM_APP + 2    # llegó un dispositivo nuevo (desde otro hilo)
WM_SHOWME = WM_APP + 3    # otra copia pidió abrir la ventana
WM_COMMAND = 0x0111
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
NIN_SELECT = 0x0400
WM_TIMER = 0x0113
TIMER_ID = 7  # 0.55: revisa si hay móviles conectados para el icono rojo/verde

# Órdenes del menú (también se pueden mandar por WM_COMMAND, p. ej. en pruebas).
ID_OPEN, ID_QR, ID_FOLDER, ID_BRIDGE, ID_PROPS, ID_KICKALL, ID_AUTORUN, ID_DEVICES, ID_QUIT = 1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008, 1099
ID_REMEMBER, ID_FORGET = 1009, 1010
PANEL = "Panel de LaZoo"
ID_CUBE, ID_KICK, ID_ACCEPT, ID_REJECT = 1100, 2000, 3000, 4000

CUBES = [("mouse", "Ratón"), ("bridge", "Puente Wi-Fi"), ("windows", "Ventanas"), ("youtube", "YouTube"),
         ("spotify", "Spotify"), ("notes", "Notas"), ("system", "Sistema"), ("lab", "Pruebas"), ("about", "Sobre LaZoo")]

AVAILABLE = sys.platform == "win32"


def autorun_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return f'"{pyw if pyw.exists() else exe}" "{ROOT / "LaZoo.pyw"}"'


def autorun_enabled() -> bool:
    if not AVAILABLE:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_NAME)
            return True
    except OSError:
        return False


def set_autorun(on: bool) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if on:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, autorun_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass


def menu_model(listing: list[dict]) -> dict:
    """Qué sale en el menú, sin Windows de por medio (se prueba en Linux)."""
    pending = [d for d in listing if d["state"] == "pendiente"]
    approved = [d for d in listing if d["state"] == "aprobado"]
    return {
        "pending": [(ID_ACCEPT + i, ID_REJECT + i, d) for i, d in enumerate(pending[:50])],
        "approved": [(ID_KICK + i, d) for i, d in enumerate(approved[:50])],
        "cubes": [(ID_CUBE + i, cid, name) for i, (cid, name) in enumerate(CUBES)],
    }


def resolve(command: int, listing: list[dict]) -> tuple[str, object]:
    """Traduce un id de menú a (acción, dato)."""
    model = menu_model(listing)
    for cid, cube_id, _name in model["cubes"]:
        if command == cid:
            return "cube", cube_id
    for acc, rej, d in model["pending"]:
        if command == acc:
            return "accept", d["id"]
        if command == rej:
            return "reject", d["id"]
    for kid, d in model["approved"]:
        if command == kid:
            return "kick", d["id"]
    names = {ID_OPEN: "open", ID_QR: "qr", ID_FOLDER: "folder", ID_BRIDGE: "bridge", ID_PROPS: "props",
             ID_KICKALL: "kickall", ID_AUTORUN: "autorun", ID_DEVICES: "devices", ID_QUIT: "quit",
             ID_REMEMBER: "remember", ID_FORGET: "forget"}
    return names.get(command, ""), None


def tray_state(count: int) -> tuple[str, str]:
    """0.55: icono y texto de la bandeja según los móviles conectados (función pura).

    Rojo = ninguno; verde = al menos uno. Devuelve (archivo .ico en static/, tooltip)."""
    if count <= 0:
        return "lazoo-rojo.ico", "LaZoo · sin dispositivos"
    if count == 1:
        return "lazoo-verde.ico", "LaZoo · 1 dispositivo conectado"
    return "lazoo-verde.ico", f"LaZoo · {count} dispositivos conectados"


def local_ips() -> str:
    import lazo
    try:
        return ", ".join(ip for _label, ip in lazo.lan_targets()) or "sin red"
    except Exception:
        return "sin red"


class Tray:
    def __init__(self, port: int = 8787, extra: list[str] | None = None) -> None:
        import ctypes
        from ctypes import wintypes as wt

        self.ct, self.wt = ctypes, wt
        self.user32, self.shell32, self.kernel32 = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.kernel32
        self.port_wanted = port
        self.extra = extra or []
        self.hwnd = None
        self.server = None
        self.quitting = False
        self.taskbar_created = -1  # se pone en create(); llegan mensajes antes
        self.ask_seconds = int(os.environ.get("LAZO_TRAY_TIMEOUT", "0") or 0)
        self._types()

    # ---- ctypes ---------------------------------------------------------------
    def _types(self) -> None:
        ct, wt, u, s, k = self.ct, self.wt, self.user32, self.shell32, self.kernel32
        self.LRESULT = ct.c_ssize_t
        self.WNDPROC = ct.WINFUNCTYPE(self.LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

        class WNDCLASSW(ct.Structure):
            _fields_ = [("style", wt.UINT), ("lpfnWndProc", self.WNDPROC), ("cbClsExtra", ct.c_int), ("cbWndExtra", ct.c_int),
                        ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                        ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]

        class GUID(ct.Structure):
            _fields_ = [("a", ct.c_ulong), ("b", ct.c_ushort), ("c", ct.c_ushort), ("d", ct.c_ubyte * 8)]

        class NOTIFYICONDATAW(ct.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("uFlags", wt.UINT), ("uCallbackMessage", wt.UINT),
                        ("hIcon", wt.HICON), ("szTip", wt.WCHAR * 128), ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD),
                        ("szInfo", wt.WCHAR * 256), ("uVersion", wt.UINT), ("szInfoTitle", wt.WCHAR * 64), ("dwInfoFlags", wt.DWORD),
                        ("guidItem", GUID), ("hBalloonIcon", wt.HICON)]

        self.WNDCLASSW, self.NOTIFYICONDATAW = WNDCLASSW, NOTIFYICONDATAW
        u.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        u.DefWindowProcW.restype = self.LRESULT
        u.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ct.c_int, ct.c_int, ct.c_int, ct.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
        u.CreateWindowExW.restype = wt.HWND
        u.RegisterClassW.argtypes = [ct.POINTER(WNDCLASSW)]
        u.RegisterClassW.restype = wt.ATOM
        u.CreatePopupMenu.restype = wt.HMENU
        u.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ct.c_size_t, wt.LPCWSTR]
        u.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ct.c_int, ct.c_int, ct.c_int, wt.HWND, ct.c_void_p]
        u.DestroyMenu.argtypes = [wt.HMENU]
        u.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
        u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
        u.FindWindowW.restype = wt.HWND
        u.CreateIconFromResourceEx.argtypes = [ct.c_char_p, wt.DWORD, wt.BOOL, wt.DWORD, ct.c_int, ct.c_int, wt.UINT]
        u.CreateIconFromResourceEx.restype = wt.HICON
        u.MessageBoxW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT]
        u.GetCursorPos.argtypes = [ct.POINTER(wt.POINT)]
        u.SetForegroundWindow.argtypes = [wt.HWND]
        u.GetMessageW.argtypes = [ct.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
        u.TranslateMessage.argtypes = [ct.POINTER(wt.MSG)]
        u.DispatchMessageW.argtypes = [ct.POINTER(wt.MSG)]
        u.DispatchMessageW.restype = self.LRESULT
        u.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
        u.RegisterWindowMessageW.restype = wt.UINT
        u.DestroyWindow.argtypes = [wt.HWND]
        u.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ct.c_int, ct.c_int, wt.UINT]
        u.LoadImageW.restype = wt.HANDLE
        u.SetTimer.argtypes = [wt.HWND, ct.c_size_t, wt.UINT, ct.c_void_p]
        u.SetTimer.restype = ct.c_size_t
        u.KillTimer.argtypes = [wt.HWND, ct.c_size_t]
        u.GetSystemMetrics.argtypes = [ct.c_int]
        s.Shell_NotifyIconW.argtypes = [wt.DWORD, ct.POINTER(NOTIFYICONDATAW)]
        s.Shell_NotifyIconW.restype = wt.BOOL
        k.GetModuleHandleW.restype = wt.HMODULE
        k.CreateMutexW.argtypes = [ct.c_void_p, wt.BOOL, wt.LPCWSTR]
        k.CreateMutexW.restype = wt.HANDLE

    # ---- arranque ---------------------------------------------------------------
    def single(self) -> bool:
        """True si somos la única bandeja. Si no, pide a la otra que abra su ventana."""
        self.mutex = self.kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if self.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            other = self.user32.FindWindowW(CLASS_NAME, None)
            if other:
                self.user32.PostMessageW(other, WM_SHOWME, 0, 0)
            return False
        return True

    def start_server(self) -> bool:
        import lazo
        import aprobacion

        self.lazo = lazo
        argv = ["--no-browser", "--port", str(self.port_wanted)] + self.extra
        self.server, self.home = lazo.start(argv, console=False)
        if self.server is None:
            return False
        if getattr(sys, "frozen", False):  # .exe: lo recibido, junto al LaZoo.exe y no dentro de _internal
            lazo.control.set_photos_dir(Path(sys.executable).resolve().parent / "Fotos")
        lazo.APPROVALS.on_new.append(self._on_new)
        # La bandeja ya avisa y abre el Panel de LaZoo; el cuadro Sí/No de Windows se queda.
        lazo.maybe_open_mesa = lambda: None
        self.aprobacion = aprobacion
        return True

    def _on_new(self, who: str, row: dict) -> None:
        self.last_new = row
        if self.hwnd:
            self.user32.PostMessageW(self.hwnd, WM_NEWDEV, 0, 0)

    def create(self) -> None:
        ct, u = self.ct, self.user32
        hinst = self.kernel32.GetModuleHandleW(None)
        self._proc = self.WNDPROC(self._wndproc)  # se guarda: si lo recoge el GC, Windows salta a la nada
        wc = self.WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = CLASS_NAME
        u.RegisterClassW(ct.byref(wc))
        self.hwnd = u.CreateWindowExW(0, CLASS_NAME, "LaZoo", 0, 0, 0, 0, 0, None, None, hinst, None)
        self.taskbar_created = u.RegisterWindowMessageW("TaskbarCreated")
        self.icons: dict[str, int] = {}
        self.state = tray_state(self._count())
        self.hicon = self._icon(self.state[0])
        self._add_icon()
        u.SetTimer(self.hwnd, TIMER_ID, 1500, None)  # 0.55: rojo/verde según el estado real

    def _icon(self, name: str):
        """HICON del .ico de static/ al tamaño de la bandeja (se carga una vez y se reutiliza)."""
        if name not in self.icons:
            u = self.user32
            size = u.GetSystemMetrics(49) or 16  # SM_CXSMICON
            path = str(Path(self.lazo.STATIC) / name)
            handle = u.LoadImageW(None, path, 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
            if not handle:
                import icono

                data = icono.dib_icon(32)
                handle = u.CreateIconFromResourceEx(data, len(data), True, 0x00030000, 32, 32, 0)
            self.icons[name] = handle
        return self.icons[name]

    def _count(self) -> int:
        try:
            return int(self.lazo.PAIRING.phone_count())
        except Exception:
            return 0

    def refresh_icon(self) -> None:
        """Cambia icono y tooltip solo si el estado cambió (NIM_MODIFY: sin parpadeo)."""
        state = tray_state(self._count())
        if state == self.state:
            return
        self.state = state
        self.hicon = self._icon(state[0])
        nid = self._nid()
        nid.uFlags = 0x2 | 0x4  # ICON | TIP
        nid.hIcon = self.hicon
        nid.szTip = state[1]
        self.shell32.Shell_NotifyIconW(1, self.ct.byref(nid))  # NIM_MODIFY

    def _nid(self):
        nid = self.NOTIFYICONDATAW()
        nid.cbSize = self.ct.sizeof(self.NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        return nid

    def _add_icon(self) -> None:
        nid = self._nid()
        nid.uFlags = 0x1 | 0x2 | 0x4  # MESSAGE | ICON | TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self.hicon
        nid.szTip = self.state[1]
        self.shell32.Shell_NotifyIconW(0, self.ct.byref(nid))  # NIM_ADD

    def balloon(self, title: str, text: str) -> None:
        nid = self._nid()
        nid.uFlags = 0x10  # NIF_INFO
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        nid.dwInfoFlags = 0x1  # NIIF_INFO
        self.shell32.Shell_NotifyIconW(1, self.ct.byref(nid))  # NIM_MODIFY

    # ---- menú -------------------------------------------------------------------
    def listing(self) -> list[dict]:
        return self.lazo.APPROVALS.listing()

    def show_menu(self) -> None:
        u = self.user32
        model = menu_model(self.listing())
        menu = u.CreatePopupMenu()
        MF_STRING, MF_POPUP, MF_SEP, MF_GRAY, MF_CHECKED = 0x0, 0x10, 0x800, 0x1, 0x8
        u.AppendMenuW(menu, MF_STRING, ID_OPEN, f"Abrir el {PANEL}")
        u.AppendMenuW(menu, MF_STRING, ID_QR, "Mostrar QR para conectar")
        cubes = u.CreatePopupMenu()
        for cid, _cube, name in model["cubes"]:
            u.AppendMenuW(cubes, MF_STRING, cid, name)
        u.AppendMenuW(menu, MF_POPUP, cubes, "Pastillas")
        u.AppendMenuW(menu, MF_SEP, 0, None)
        pend = u.CreatePopupMenu()
        if not model["pending"]:
            u.AppendMenuW(pend, MF_GRAY, 0, "No hay solicitudes")
        for acc, rej, d in model["pending"]:
            sub = u.CreatePopupMenu()
            u.AppendMenuW(sub, MF_STRING, acc, "Aceptar")
            u.AppendMenuW(sub, MF_STRING, rej, "Rechazar")
            u.AppendMenuW(pend, MF_POPUP, sub, f"{d['label']} · {d['ip']} ({d['left']} s)")
        # 0.54: aquí (y en el aviso de Windows) es el ÚNICO sitio donde se acepta un móvil nuevo.
        if len(model["pending"]) == 1:
            acc, rej, d = model["pending"][0]
            u.AppendMenuW(menu, MF_STRING, acc, f"Aceptar dispositivo pendiente: {d['label']}")
            u.AppendMenuW(menu, MF_STRING, rej, "Rechazar dispositivo pendiente")
        u.AppendMenuW(menu, MF_POPUP, pend, f"Solicitudes pendientes ({len(model['pending'])})")
        devs = u.CreatePopupMenu()
        if not model["approved"]:
            u.AppendMenuW(devs, MF_GRAY, 0, "Ningún dispositivo conectado")
        for kid, d in model["approved"]:
            sub = u.CreatePopupMenu()
            u.AppendMenuW(sub, MF_STRING, kid, "Expulsar")
            u.AppendMenuW(devs, MF_POPUP, sub, f"{d['label']} · {d['ip']}")
        u.AppendMenuW(devs, MF_SEP, 0, None)
        u.AppendMenuW(devs, MF_STRING if model["approved"] else MF_GRAY, ID_KICKALL, "Expulsar a todos…")
        u.AppendMenuW(devs, MF_STRING | (MF_CHECKED if self.lazo.STORE.enabled() else 0), ID_REMEMBER, "Recordar dispositivos")
        u.AppendMenuW(devs, MF_STRING, ID_FORGET, "Olvidar todos…")
        u.AppendMenuW(menu, MF_POPUP, devs, f"Dispositivos conectados ({len(model['approved'])})")
        bridge = u.CreatePopupMenu()
        u.AppendMenuW(bridge, MF_STRING, ID_FOLDER, "Abrir carpeta «Recibido del móvil»")
        u.AppendMenuW(bridge, MF_STRING, ID_BRIDGE, f"Abrir el puente en el {PANEL}")
        u.AppendMenuW(menu, MF_POPUP, bridge, "Puente Wi-Fi")
        u.AppendMenuW(menu, MF_SEP, 0, None)
        u.AppendMenuW(menu, MF_STRING, ID_PROPS, "Propiedades…")
        u.AppendMenuW(menu, MF_STRING | (MF_CHECKED if autorun_enabled() else 0), ID_AUTORUN, "Iniciar con Windows")
        u.AppendMenuW(menu, MF_SEP, 0, None)
        u.AppendMenuW(menu, MF_STRING, ID_QUIT, "Salir")
        pt = self.wt.POINT()
        u.GetCursorPos(self.ct.byref(pt))
        u.SetForegroundWindow(self.hwnd)
        u.TrackPopupMenu(menu, 0x0020, pt.x, pt.y, 0, self.hwnd, None)  # TPM_RIGHTALIGN no: TPM_RIGHTBUTTON
        u.PostMessageW(self.hwnd, 0, 0, 0)
        u.DestroyMenu(menu)

    def ask(self, text: str, title: str = "LaZoo") -> bool:
        if self.ask_seconds:
            answer = self.aprobacion.message_box(text, title, self.ask_seconds)
        else:
            answer = self.user32.MessageBoxW(self.hwnd, text, title, 0x4 | 0x20 | 0x40000 | 0x10000)  # YESNO|QUESTION|TOPMOST|SETFOREGROUND
        print(f"bandeja: respuesta {answer}", flush=True)
        return answer == 6

    def info(self, text: str, title: str = "LaZoo") -> None:
        if self.ask_seconds:
            fn = self.user32.MessageBoxTimeoutW
            fn.argtypes = [self.wt.HWND, self.wt.LPCWSTR, self.wt.LPCWSTR, self.wt.UINT, self.wt.WORD, self.wt.DWORD]
            fn(self.hwnd, text, title, 0x40 | 0x40000, 0, self.ask_seconds * 1000)
            return
        self.user32.MessageBoxW(self.hwnd, text, title, 0x40 | 0x40000 | 0x10000)

    def open(self, url: str) -> None:
        if os.environ.get("LAZO_TRAY_DRYRUN") == "1":  # pruebas: no abre el navegador
            print(f"bandeja: abriría {url}", flush=True)
            return
        self.lazo.open_local(url)

    def url(self, page: str) -> str:
        return f"http://127.0.0.1:{self.lazo.PORT}{page}"

    def run_command(self, command: int) -> str:
        action, data = resolve(command, self.listing())
        L, A = self.lazo, self.lazo.APPROVALS
        if action == "open":
            self.open(self.url("/mesa"))
        elif action == "qr":
            self.open(self.url("/conectar"))
        elif action == "cube":
            self.open(self.url(f"/#pastilla={data}"))
        elif action == "bridge":
            self.open(self.url("/mesa#pastilla=puente"))
        elif action == "folder" and os.environ.get("LAZO_TRAY_DRYRUN") == "1":
            print(f"bandeja: abriría la carpeta de recibidos", flush=True)
        elif action == "folder":
            try:
                L.control.open_photos_folder()
            except Exception:
                self.info("No pude abrir la carpeta de recibidos.")
        elif action == "devices":
            self.open(self.url("/mesa#pastilla=dispositivos"))
        elif action == "accept":
            A.decide(str(data), True)
        elif action == "reject":
            A.decide(str(data), False)
        elif action == "kick":
            A.kick(str(data))
        elif action == "kickall":
            if self.ask("¿Expulsar a todos los dispositivos?\nTendrán que volver a entrar y que los aceptes en este PC.", "LaZoo: expulsar a todos"):
                n = A.kick_all()
                self.balloon("LaZoo", f"Expulsados: {n}")
            else:
                action = "kickall-no"
        elif action == "remember":
            L.set_remember(not L.STORE.enabled())
            self.balloon("LaZoo", "Recordar dispositivos: " + ("sí, se reconectan solos al reiniciar" if L.STORE.enabled() else "no, la clave cambia al reiniciar"))
        elif action == "forget":
            if self.ask("¿Olvidar todos los dispositivos?\nSe borra la clave guardada y la lista. Todos los móviles tendrán que volver a emparejarse (QR o PIN) y que los aceptes.", "LaZoo: olvidar todos"):
                n = L.forget_all()["count"]
                self.balloon("LaZoo", f"Olvidados: {n}. Clave nueva.")
            else:
                action = "forget-no"
        elif action == "props":
            self.info(self.props_text(), "Propiedades de LaZoo")
        elif action == "autorun":
            try:
                set_autorun(not autorun_enabled())
            except OSError:
                self.info("No pude cambiar el inicio con Windows.")
        elif action == "quit":
            self.quit()
        if action:
            print(f"bandeja: orden {action}", flush=True)
        return action

    def props_text(self) -> str:
        L = self.lazo
        folder = getattr(L.control, "_photos_dir", None)
        return (f"Versión: {L.VERSION}\nPuerto: {L.PORT}\nIP local: {local_ips()}\n"
                f"Carpeta de recibidos: {folder}\n"
                "Solo red local: sí (se rechaza cualquier IP de internet)\n"
                f"Dispositivos nuevos: {'entran sin aprobación (modo pruebas)' if L.APPROVALS.auto else 'hay que aceptarlos en este PC'}\n"
                f"Recordar dispositivos: {'sí' if L.STORE.enabled() else 'no'}\n"
                f"Iniciar con Windows: {'sí' if autorun_enabled() else 'no'} (cámbialo en el menú del icono)")

    # ---- bucle ------------------------------------------------------------------
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                event = lparam & 0xFFFF
                if event == WM_LBUTTONDBLCLK:
                    self.run_command(ID_OPEN)
                elif event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self.show_menu()
                return 0
            if msg == WM_COMMAND:
                self.run_command(wparam & 0xFFFF)
                return 0
            if msg == WM_NEWDEV:
                row = getattr(self, "last_new", {}) or {}
                self.balloon("LaZoo: dispositivo nuevo", f"{row.get('label', 'Un móvil')} ({row.get('ip', '')}) quiere entrar. Acéptalo o recházalo en el cuadro de Windows o con clic derecho en este icono.")
                return 0
            if msg == WM_TIMER and wparam == TIMER_ID:
                self.refresh_icon()
                return 0
            if msg == WM_SHOWME:
                self.run_command(ID_OPEN)
                return 0
            if msg == self.taskbar_created:  # el Explorador se reinició: vuelve a poner el icono
                self._add_icon()
                return 0
            if msg == WM_DESTROY:
                self.user32.PostQuitMessage(0)
                return 0
        except Exception:
            import traceback
            traceback.print_exc()
        return self.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def quit(self) -> None:
        if self.quitting:
            return
        self.quitting = True
        self.user32.KillTimer(self.hwnd, TIMER_ID)
        self.shell32.Shell_NotifyIconW(2, self.ct.byref(self._nid()))  # NIM_DELETE
        if self.server is not None:
            threading.Thread(target=self._stop_server, daemon=True).start()
        self.user32.DestroyWindow(self.hwnd)

    def _stop_server(self) -> None:
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception:
            pass

    def loop(self) -> None:
        msg = self.wt.MSG()
        while self.user32.GetMessageW(self.ct.byref(msg), None, 0, 0) > 0:
            self.user32.TranslateMessage(self.ct.byref(msg))
            self.user32.DispatchMessageW(self.ct.byref(msg))


def main(argv: list[str] | None = None) -> int:
    if not AVAILABLE:
        print("La bandeja de LaZoo solo existe en Windows por ahora. En Linux y macOS usa iniciar.sh.")
        return 1
    import argparse

    parser = argparse.ArgumentParser(description="LaZoo en la bandeja de Windows")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--sin-ventana", action="store_true", help="no abrir el Panel de LaZoo al arrancar")
    args, extra = parser.parse_known_args(argv)
    tray = Tray(args.port, extra)
    if not tray.single():
        return 0
    if not tray.start_server():
        tray.info("No pude arrancar LaZoo: el puerto está ocupado o falta un permiso.")
        return 1
    tray.create()
    tray.balloon("LaZoo está en marcha", f"Puerto {tray.lazo.PORT}. Clic derecho en el icono para el menú; doble clic abre el Panel de LaZoo.")
    if not args.sin_ventana:
        # 0.44: al arrancar (también con Windows) se abre el Panel de LaZoo con el QR y el PIN.
        # 0.54: con «Recordar dispositivos», los móviles aprobados se reconectan solos.
        tray.open(tray.url("/mesa"))
    tray.loop()
    tray._stop_server()
    return 0


if __name__ == "__main__":
    sys.exit(main())
