"""LaZoo 0.67: el icono de la bandeja en Linux (fase 3), con el mismo menú que en Windows.

Usa el indicador estándar de los escritorios de Linux (AppIndicator / StatusNotifierItem) por
PyGObject, que viene con el sistema (paquetes `python3-gi`, `gir1.2-gtk-3.0` y
`gir1.2-ayatanaappindicator3-0.1`). No se instala nada con pip. Si no hay indicador, se usa el
icono antiguo de GTK (X11) y, si tampoco, `main()` devuelve 2 e iniciar.sh sigue en la consola.

- KDE, Cinnamon, Xfce, MATE, Budgie y Ubuntu lo enseñan tal cual. En GNOME sin retocar
  (Fedora) hace falta la extensión «AppIndicator and KStatusNotifierItem Support».
- Aceptar o rechazar un móvil nuevo: un cuadro de GTK con 60 s, como el aviso de Windows, y la
  opción del menú. Nada nuevo queda expuesto a la red: el menú abre páginas por 127.0.0.1.
- «Iniciar con el sistema»: `~/.config/autostart/lazoo.desktop` (estándar de freedesktop).

Las órdenes del menú son las de bandeja.py (`menu_model`, `resolve`, `Tray.run_command`), así
los dos sistemas hacen lo mismo.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import bandeja

ROOT = Path(__file__).resolve().parent
ESPERA = 60  # s para aceptar un móvil, como en Windows
REFRESCO_MS = 1500


# --- piezas sin GTK (se prueban en cualquier Linux) ----------------------------------------
def autostart_file(home: Path | None = None) -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str((home or Path.home()) / ".config")
    return Path(base) / "autostart" / "lazoo.desktop"


def autostart_command() -> str:
    """Lo que arranca LaZoo con la sesión: la AppImage, el ejecutable o Python + este archivo."""
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return shlex.quote(appimage)
    if getattr(sys, "frozen", False):
        return shlex.quote(sys.executable)
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(ROOT / 'bandeja_linux.py'))} --sin-ventana"


def desktop_entry(command: str, icon: str) -> str:
    return ("[Desktop Entry]\nType=Application\nName=LaZoo\nComment=Ratón y teclado del PC desde el móvil\n"
            f"Exec={command}\nIcon={icon}\nTerminal=false\nCategories=Utility;\nX-GNOME-Autostart-enabled=true\n")


def autostart_enabled(home: Path | None = None) -> bool:
    return autostart_file(home).is_file()


def set_autostart(on: bool, home: Path | None = None) -> None:
    f = autostart_file(home)
    if on:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(desktop_entry(autostart_command(), str(icon_path("naranja"))), encoding="utf-8")
    else:
        try:
            f.unlink()
        except FileNotFoundError:
            pass


def icon_path(color: str) -> Path:
    return ROOT / "static" / "img" / f"infinito-{color}.svg"


def state(count: int) -> tuple[Path, str]:
    """(icono, texto) según los móviles conectados: rojo ninguno, verde alguno (como Windows)."""
    ico, text = bandeja.tray_state(count)
    return icon_path("verde" if "verde" in ico else "rojo"), text


def menu_items(listing: list[dict], remember: bool, autostart: bool) -> list[tuple]:
    """El menú como datos: ("item", id, texto) · ("check", id, texto, marcado) · ("sep",) ·
    ("sub", texto, [elementos]) · ("gray", texto). Mismos ids que bandeja.py."""
    b = bandeja
    model = b.menu_model(listing)
    out: list[tuple] = [("item", b.ID_OPEN, f"Abrir el {b.PANEL}"), ("item", b.ID_QR, "Mostrar QR para conectar"),
                        ("sub", "Pastillas", [("item", cid, name) for cid, _c, name in model["cubes"]]), ("sep",)]
    if len(model["pending"]) == 1:
        acc, rej, d = model["pending"][0]
        out += [("item", acc, f"Aceptar dispositivo pendiente: {d['label']}"),
                ("item", rej, "Rechazar dispositivo pendiente")]
    pend = [("sub", f"{d['label']} · {d['ip']}", [("item", acc, "Aceptar"), ("item", rej, "Rechazar")])
            for acc, rej, d in model["pending"]] or [("gray", "No hay solicitudes")]
    out.append(("sub", f"Solicitudes pendientes ({len(model['pending'])})", pend))
    devs = [("sub", f"{d['label']} · {d['ip']}", [("item", kid, "Expulsar")]) for kid, d in model["approved"]]
    devs = devs or [("gray", "Ningún dispositivo conectado")]
    devs += [("sep",), ("item", b.ID_KICKALL, "Expulsar a todos…"), ("check", b.ID_REMEMBER, "Recordar dispositivos", remember),
             ("item", b.ID_FORGET, "Olvidar todos…")]
    out.append(("sub", f"Dispositivos conectados ({len(model['approved'])})", devs))
    out.append(("sub", "Pasar por wifi", [("item", b.ID_FOLDER, "Abrir carpeta «Recibido del móvil»"),
                                          ("item", b.ID_BRIDGE, f"Abrir «Pasar por wifi» en el {b.PANEL}")]))
    out += [("sep",), ("item", b.ID_PROPS, "Propiedades…"), ("check", b.ID_AUTORUN, "Iniciar con el sistema", autostart),
            ("sep",), ("item", b.ID_QUIT, "Salir")]
    return out


def diagnose() -> dict[str, Any]:
    """Qué hay en este Linux para la bandeja (para el mensaje de iniciar.sh y el Panel)."""
    info: dict[str, Any] = {"gtk": False, "indicador": "", "sesion": os.environ.get("XDG_SESSION_TYPE", ""),
                            "escritorio": os.environ.get("XDG_CURRENT_DESKTOP", ""),
                            "pantalla": bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))}
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # noqa: F401

        info["gtk"] = True
        for name in ("AyatanaAppIndicator3", "AppIndicator3"):
            try:
                gi.require_version(name, "0.1")
                __import__("gi.repository." + name)
                info["indicador"] = name
                break
            except (ValueError, ImportError):
                continue
    except Exception:  # noqa: BLE001 (sin PyGObject: consola)
        pass
    return info


def consejo(info: dict[str, Any]) -> str:
    if not info.get("pantalla"):
        return "No hay escritorio gráfico: LaZoo sigue en la consola."
    if not info.get("gtk"):
        return "Para el icono en la bandeja: sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1"
    if not info.get("indicador"):
        return "Falta el indicador: sudo apt install gir1.2-ayatanaappindicator3-0.1 (se usará el icono antiguo de GTK)."
    if "gnome" in str(info.get("escritorio", "")).lower():
        return "En GNOME, si no ves el icono, activa la extensión «AppIndicator and KStatusNotifierItem Support»."
    return ""


# --- la bandeja con GTK -----------------------------------------------------------------------
class LinuxTray:
    """Mismo papel que bandeja.Tray, con GTK. `run_command` es el de Windows."""

    def __init__(self, port: int = 8787, extra: list[str] | None = None) -> None:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import GLib, Gtk

        self.Gtk, self.GLib = Gtk, GLib
        self.ind_mod = None
        for name in ("AyatanaAppIndicator3", "AppIndicator3"):
            try:
                gi.require_version(name, "0.1")
                self.ind_mod = __import__("gi.repository." + name, fromlist=[name])
                break
            except (ValueError, ImportError):
                continue
        self.port_wanted = port
        self.extra = extra or []
        self.ask_seconds = 0
        self.indicator: Any = None
        self.status_icon: Any = None
        self.last_sig: tuple = ()
        self.last_icon = ""

    # bandeja.Tray.run_command usa estos nombres
    run_command = bandeja.Tray.run_command
    start_server = bandeja.Tray.start_server

    def listing(self) -> list[dict]:
        return self.lazo.APPROVALS.listing()

    def url(self, page: str) -> str:
        return f"http://127.0.0.1:{self.lazo.PORT}{page}"

    def open(self, url: str) -> None:
        if os.environ.get("LAZO_TRAY_DRYRUN") == "1":
            print(f"bandeja: abriría {url}", flush=True)
            return
        opener = shutil.which("xdg-open")
        if opener:
            subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            self.lazo.open_local(url)

    def balloon(self, title: str, text: str) -> None:
        if shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-a", "LaZoo", "-i", str(icon_path("naranja")), title, text],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            print(f"{title}: {text}", flush=True)

    def _dialog(self, text: str, title: str, question: bool, seconds: int = 0) -> bool:
        Gtk = self.Gtk
        d = Gtk.MessageDialog(message_type=Gtk.MessageType.QUESTION if question else Gtk.MessageType.INFO,
                              buttons=Gtk.ButtonsType.YES_NO if question else Gtk.ButtonsType.OK, text=title)
        d.format_secondary_text(text)
        d.set_title(title)
        d.set_keep_above(True)
        abierto = [True]

        def caduca() -> bool:
            if abierto[0]:
                d.response(Gtk.ResponseType.NO)
            return False

        if seconds:
            self.GLib.timeout_add_seconds(seconds, caduca)
        answer = d.run()
        abierto[0] = False
        d.destroy()
        return answer == Gtk.ResponseType.YES

    def ask(self, text: str, title: str = "LaZoo") -> bool:
        return self._dialog(text, title, True)

    def info(self, text: str, title: str = "LaZoo") -> None:
        self._dialog(text, title, False)

    def props_text(self) -> str:
        L = self.lazo
        folder = getattr(L.control, "_photos_dir", None)
        return (f"Versión: {L.VERSION}\nPuerto: {L.PORT}\nIP local: {bandeja.local_ips()}\n"
                f"Carpeta de recibidos: {folder}\nSolo red local: sí\n"
                f"Dispositivos nuevos: {'entran sin aprobación (modo pruebas)' if L.APPROVALS.auto else 'hay que aceptarlos en este PC'}\n"
                f"Recordar dispositivos: {'sí' if L.STORE.enabled() else 'no'}\n"
                f"Iniciar con el sistema: {'sí' if autostart_enabled() else 'no'}\n"
                f"Escritorio: {os.environ.get('XDG_CURRENT_DESKTOP', '?')} · sesión {os.environ.get('XDG_SESSION_TYPE', '?')}")

    def command(self, ident: int) -> str:
        if ident == bandeja.ID_AUTORUN:  # en Linux, el autoarranque de freedesktop
            try:
                set_autostart(not autostart_enabled())
            except OSError:
                self.info("No pude cambiar el inicio con el sistema.")
            self.refresh(force=True)
            return "autorun"
        action = self.run_command(ident)
        self.refresh(force=True)
        return action

    # --- menú ---------------------------------------------------------------------
    def _build(self, items: list[tuple]) -> Any:
        Gtk = self.Gtk
        menu = Gtk.Menu()
        for it in items:
            if it[0] == "sep":
                w = Gtk.SeparatorMenuItem()
            elif it[0] == "gray":
                w = Gtk.MenuItem(label=it[1])
                w.set_sensitive(False)
            elif it[0] == "sub":
                w = Gtk.MenuItem(label=it[1])
                w.set_submenu(self._build(it[2]))
            elif it[0] == "check":
                w = Gtk.CheckMenuItem(label=it[2])
                w.set_active(bool(it[3]))
                w.connect("activate", lambda _w, i=it[1]: self.command(i))
            else:
                w = Gtk.MenuItem(label=it[2])
                w.connect("activate", lambda _w, i=it[1]: self.command(i))
            menu.append(w)
        menu.show_all()
        return menu

    def refresh(self, force: bool = False) -> bool:
        listing = self.listing()
        sig = (tuple((d["id"], d["state"]) for d in listing), self.lazo.STORE.enabled(), autostart_enabled())
        if force or sig != self.last_sig:
            self.last_sig = sig
            menu = self._build(menu_items(listing, self.lazo.STORE.enabled(), autostart_enabled()))
            if self.indicator is not None:
                self.indicator.set_menu(menu)
            self.menu = menu
        ico, text = state(self.lazo.PAIRING.phone_count())
        if str(ico) != self.last_icon:
            self.last_icon = str(ico)
            if self.indicator is not None:
                self.indicator.set_icon_full(str(ico), text)
                self.indicator.set_title(text)
            elif self.status_icon is not None:
                self.status_icon.set_from_file(str(ico))
                self.status_icon.set_tooltip_text(text)
        return True

    def create(self) -> None:
        Gtk = self.Gtk
        ico, text = state(0)
        if self.ind_mod is not None:
            I = self.ind_mod.Indicator
            self.indicator = I.new("lazoo", str(ico), self.ind_mod.IndicatorCategory.APPLICATION_STATUS)
            self.indicator.set_status(self.ind_mod.IndicatorStatus.ACTIVE)
            self.indicator.set_title(text)
        else:  # icono antiguo de GTK (X11)
            self.status_icon = Gtk.StatusIcon.new_from_file(str(ico))
            self.status_icon.set_tooltip_text(text)
            self.status_icon.connect("activate", lambda *_a: self.command(bandeja.ID_OPEN))
            self.status_icon.connect("popup-menu", lambda _i, b, t: self.menu.popup(None, None, None, None, b, t))
        self.refresh(force=True)
        self.GLib.timeout_add(REFRESCO_MS, self.refresh)

    # --- móviles nuevos -------------------------------------------------------------
    def _on_new(self, who: str, row: dict) -> None:
        self.GLib.idle_add(self._ask_device, who, row)

    def _ask_device(self, who: str, row: dict) -> bool:
        A = self.lazo.APPROVALS
        self.balloon("LaZoo: un móvil quiere entrar", f"{row.get('label', '')} · {row.get('ip', '')}")
        text = self.aprobacion.ask_text(who, row) + f"\n\n¿Lo dejas entrar? Podrá usar el ratón y el teclado de este PC.\nSi no respondes en {ESPERA} s, se rechaza."
        yes = self._dialog(text, f"LaZoo: nuevo dispositivo {who[:4]}", True, ESPERA)
        if A.state(who) == "pendiente":
            A.decide(who, yes)
        self.refresh(force=True)
        return False

    def quit(self) -> None:
        self.Gtk.main_quit()

    def run(self, open_panel: bool = True) -> int:
        if not self.start_server():
            print("No pude arrancar LaZoo: el puerto está ocupado o falta un permiso.", flush=True)
            return 1
        self.create()  # start_server (el de Windows) ya engancha _on_new
        self.balloon("LaZoo está en marcha", f"Puerto {self.lazo.PORT}. El menú está en el icono de la bandeja.")
        if open_panel:
            self.open(self.url("/mesa"))
        try:
            self.Gtk.main()
        except KeyboardInterrupt:
            pass
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception:  # noqa: BLE001
            pass
        return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="LaZoo en la bandeja de Linux")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--sin-ventana", action="store_true", help="no abrir el Panel de LaZoo al arrancar")
    parser.add_argument("--diagnostico", action="store_true", help="decir qué hay para la bandeja y salir")
    args, extra = parser.parse_known_args(argv)
    info = diagnose()
    if args.diagnostico:
        print(info, consejo(info) or "Todo listo para la bandeja.")
        return 0 if info["gtk"] and info["pantalla"] else 2
    if not (info["gtk"] and info["pantalla"]):
        print(consejo(info), flush=True)
        return 2  # iniciar.sh sigue con la consola
    if consejo(info):
        print(consejo(info), flush=True)
    return LinuxTray(args.port, extra).run(open_panel=not args.sin_ventana)


if __name__ == "__main__":
    sys.exit(main())
