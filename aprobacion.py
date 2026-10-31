"""Red local y aprobación de dispositivos nuevos.

- `allowed(ip)`: LaZoo solo atiende a direcciones de la red local (loopback, privadas,
  link-local, ULA y sus IPv4 mapeadas en IPv6). Lo demás se corta antes de leer nada.
  Las cabeceras X-Forwarded-For se ignoran: publicar LaZoo detrás de un proxy no se soporta.
- `Approvals`: el primer contacto de un móvil (QR o PIN válidos) queda pendiente hasta que
  el PC lo acepta (consola, cuadro de Windows o ventana del PC). Se recuerda mientras el
  servidor siga encendido: al reiniciar cambia la clave y todo empieza de cero.
"""

from __future__ import annotations

import ipaddress
import re
import sys
import threading
import time
from typing import Callable

LOCAL_NETS = [ipaddress.ip_network(n) for n in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
    "::1/128", "fe80::/10", "fc00::/7",
)]
EXTRA_NETS: list = []

WAIT_SECONDS = 60
BLOCK_SECONDS = 300
PROMPT_SECONDS = 30


def add_allowed(cidr: str) -> str:
    """Añade un rango extra (p. ej. una VPN). Devuelve el rango normalizado."""
    net = ipaddress.ip_network(cidr.strip(), strict=False)
    EXTRA_NETS.append(net)
    return str(net)


def allowed(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(str(ip).split("%", 1)[0])
    except ValueError:
        return False
    if addr.version == 6 and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return any(addr.version == net.version and addr in net for net in LOCAL_NETS + EXTRA_NETS)


class RejectLog:
    """Una línea por IP como mucho cada 60 s, para que un escaneo no llene la consola."""

    def __init__(self, every: float = 60.0) -> None:
        self.every = every
        self.last: dict[str, float] = {}
        self.lock = threading.Lock()

    def note(self, ip: str, out=None) -> bool:
        now = time.time()
        with self.lock:
            if now - self.last.get(ip, 0) < self.every:
                return False
            if len(self.last) > 500:
                self.last.clear()
            self.last[ip] = now
        print(f"  Rechazada conexión desde fuera de la red local: {ip}", file=out or sys.stdout, flush=True)
        return True


def device_label(ua: str) -> str:
    ua = ua or ""
    if "iPhone" in ua:
        kind = "iPhone"
    elif "iPad" in ua:
        kind = "iPad"
    elif "Android" in ua:
        kind = "Android"
    elif "Mac OS X" in ua:
        kind = "Mac"
    elif "Windows" in ua:
        kind = "Windows"
    elif "Linux" in ua:
        kind = "Linux"
    else:
        kind = "Dispositivo"
    for name, rx in (("Edge", r"Edg/"), ("Firefox", r"Firefox/|FxiOS/"), ("Samsung Internet", r"SamsungBrowser/"),
                     ("Chrome", r"Chrome/|CriOS/"), ("Safari", r"Safari/")):
        if re.search(rx, ua):
            return f"{kind} · {name}"
    return kind


class Approvals:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.devices: dict[str, dict] = {}
        self.auto = False
        self.on_new: list[Callable[[str, dict], None]] = []

    def _expire(self, now: float) -> None:
        for who, row in list(self.devices.items()):
            if row["state"] == "pendiente" and now - row["since"] >= WAIT_SECONDS:
                row["state"], row["until"] = "rechazado", now + BLOCK_SECONDS
            elif row["state"] == "rechazado" and now >= row.get("until", 0):
                del self.devices[who]

    def check(self, who: str, ua: str = "", ip: str = "") -> str:
        """`ok`, `pendiente` o `rechazado`. Un desconocido pasa a pendiente y avisa al PC."""
        now = time.time()
        fresh = None
        with self.lock:
            self._expire(now)
            row = self.devices.get(who)
            if row is None:
                row = {"state": "aprobado" if self.auto else "pendiente", "since": now, "label": device_label(ua), "ip": ip, "seen": now}
                self.devices[who] = row
                if not self.auto:
                    fresh = dict(row)
            row["seen"] = now
            if ip:
                row["ip"] = ip
            state = row["state"]
        if fresh:
            for hook in self.on_new:
                try:
                    hook(who, fresh)
                except Exception:
                    pass
        return {"aprobado": "ok"}.get(state, state)

    def state(self, who: str) -> str:
        with self.lock:
            self._expire(time.time())
            row = self.devices.get(who)
            return row["state"] if row else "nuevo"

    def is_ok(self, who: str) -> bool:
        return self.state(who) == "aprobado"

    def decide(self, who: str, ok: bool) -> bool:
        """Solo cambia un pendiente. Devuelve si había algo que decidir."""
        now = time.time()
        with self.lock:
            self._expire(now)
            row = self.devices.get(who)
            if not row or row["state"] != "pendiente":
                return False
            row["state"] = "aprobado" if ok else "rechazado"
            row["until"] = now + BLOCK_SECONDS
        print(f"  {'Aceptado' if ok else 'Rechazado'}: {row['label']} ({row['ip']})", flush=True)
        return True

    def kick(self, who: str) -> bool:
        with self.lock:
            return self.devices.pop(who, None) is not None

    def kick_all(self) -> int:
        with self.lock:
            count = sum(1 for row in self.devices.values() if row["state"] == "aprobado")
            self.devices = {w: r for w, r in self.devices.items() if r["state"] == "rechazado"}
            return count

    def listing(self) -> list[dict]:
        now = time.time()
        with self.lock:
            self._expire(now)
            return [
                {"id": who, "short": who[:4], "state": row["state"], "label": row["label"], "ip": row["ip"],
                 "left": max(0, int(WAIT_SECONDS - (now - row["since"]))) if row["state"] == "pendiente" else 0,
                 "ago": int(now - row["seen"])}
                for who, row in sorted(self.devices.items(), key=lambda kv: kv[1]["since"])
            ]


def ask_text(who: str, row: dict) -> str:
    return f"Nuevo dispositivo {row['label']} ({row['ip']}, id {who[:4]}) quiere entrar en LaZoo."


# ---- Preguntar en el PC -------------------------------------------------------

def _read_key(seconds: float) -> str:
    """Lee S o N del teclado de la consola con tiempo límite. '' si no llega."""
    end = time.time() + seconds
    if sys.platform == "win32":
        import msvcrt

        while time.time() < end:
            if msvcrt.kbhit():
                return msvcrt.getwch().lower()
            time.sleep(0.05)
        return ""
    import select

    while time.time() < end:
        ready, _, _ = select.select([sys.stdin], [], [], max(0.0, min(0.5, end - time.time())))
        if ready:
            line = sys.stdin.readline()
            return (line.strip()[:1] or "").lower()
    return ""


class ConsolePrompt:
    """Pregunta de una en una en la consola, si es interactiva."""

    def __init__(self, approvals: Approvals, reader: Callable[[float], str] = _read_key) -> None:
        self.approvals = approvals
        self.reader = reader
        self.queue: list[tuple[str, dict]] = []
        self.cond = threading.Condition()
        threading.Thread(target=self._run, daemon=True).start()

    def __call__(self, who: str, row: dict) -> None:
        with self.cond:
            self.queue.append((who, row))
            self.cond.notify()

    def _run(self) -> None:
        while True:
            with self.cond:
                while not self.queue:
                    self.cond.wait()
                who, row = self.queue.pop(0)
            if self.approvals.state(who) != "pendiente":
                continue
            print(f"\n  {ask_text(who, row)}\n  Pulsa S para aceptar o N para rechazar ({PROMPT_SECONDS} s)", flush=True)
            key = ""
            end = time.time() + PROMPT_SECONDS
            while time.time() < end and self.approvals.state(who) == "pendiente":
                key = self.reader(min(1.0, end - time.time()))
                if key in ("s", "y", "n"):
                    break
            if key in ("s", "y"):
                self.approvals.decide(who, True)
            elif key == "n":
                self.approvals.decide(who, False)
            elif self.approvals.state(who) == "pendiente":
                print("  Sin respuesta en la consola. Puedes aceptarlo en la ventana del PC.", flush=True)


MB_YESNO, MB_ICONQUESTION, MB_SETFOREGROUND, MB_TOPMOST, IDYES, MB_TIMEDOUT = 0x4, 0x20, 0x10000, 0x40000, 6, 32000


def message_box(text: str, title: str, seconds: int) -> int:
    """Cuadro Sí/No de Windows, siempre encima, que se cierra solo. 32000 = sin respuesta."""
    import ctypes

    user32 = ctypes.windll.user32
    fn = user32.MessageBoxTimeoutW
    fn.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_ushort, ctypes.c_uint]
    fn.restype = ctypes.c_int
    return fn(None, text, title, MB_YESNO | MB_ICONQUESTION | MB_SETFOREGROUND | MB_TOPMOST, 0, int(seconds * 1000))


def close_box(title: str) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = ctypes.c_void_p
    hwnd = user32.FindWindowW(None, title)
    if hwnd:
        # Un cuadro Sí/No ignora WM_CLOSE: se pulsa «No» por programa (ya se decidió en otro sitio).
        user32.PostMessageW(ctypes.c_void_p(hwnd), 0x0111, 7, 0)


def windows_dialog(approvals: Approvals, seconds: int = WAIT_SECONDS) -> Callable[[str, dict], None]:
    def ask(who: str, row: dict) -> None:
        def run() -> None:
            title = f"LaZoo: nuevo dispositivo {who[:4]}"
            text = ask_text(who, row) + "\n\n¿Lo dejas entrar? Podrá usar el ratón y el teclado de este PC.\nSi no respondes en 60 s, se rechaza."

            def watch() -> None:  # si se decide en otro sitio, cierra el cuadro
                while approvals.state(who) == "pendiente":
                    time.sleep(0.5)
                close_box(title)

            threading.Thread(target=watch, daemon=True).start()
            try:
                answer = message_box(text, title, seconds)
            except (OSError, AttributeError):
                return
            if approvals.state(who) == "pendiente":
                approvals.decide(who, answer == IDYES)

        threading.Thread(target=run, daemon=True).start()

    return ask
