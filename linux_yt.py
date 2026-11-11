"""LaZoo 0.67: lo de YouTube por accesibilidad, también en Linux.

En Windows, sigues.py, anuncios.py, patrocinios.py y mando.py hablan con un PowerShell oculto que
usa UI Automation. En Linux este módulo contesta EXACTAMENTE lo mismo (los mismos diccionarios),
pero con las herramientas de Linux, así la lógica de cada función no cambia:

- AT-SPI (la accesibilidad de Linux, por PyGObject: `gi.repository.Atspi`, paquete
  `gir1.2-atspi-2.0`, que viene con el escritorio): encontrar y pulsar «Sí» en «¿Sigues ahí?»,
  «Saltar» en los anuncios, leer el volumen y el botón de silencio del reproductor y leer la
  barra de direcciones. Solo se leen nombres y se pulsa la acción del botón: sin cursor, sin
  teclas, sin foco y sin JavaScript. Vale con X11 y con Wayland.
- MPRIS (`playerctl`, vía medios.py y control._mpris_seek): posición, duración, velocidad y el
  salto a un segundo exacto.

Chrome y Brave solo enseñan su página por AT-SPI si la accesibilidad está activada:
`gsettings set org.gnome.desktop.interface toolkit-accessibility true` (GNOME) o arrancarlos con
`--force-renderer-accessibility`. Firefox la da siempre. `python3 linux_yt.py --diagnostico` dice
qué ve LaZoo. Nada de esto sale a internet (salvo SponsorBlock, que ya decide patrocinios.py).
"""

from __future__ import annotations

import json
import shutil
import threading
import subprocess
import sys
import time
from typing import Any, Callable, Iterator

MAX_NODOS = 8000      # nodos como mucho por búsqueda (una página de YouTube tiene miles)
PROFUNDIDAD = 70
NAVEGADORES = ("chrome", "chromium", "brave", "firefox", "edge", "opera", "vivaldi")


def _low(text: Any) -> str:
    return " ".join(str(text or "").lower().split())


class Arbol:
    """Envoltura mínima de AT-SPI. Aparte para poder probar con un árbol de mentira."""

    def __init__(self) -> None:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi

        self.A = Atspi
        self.R = Atspi.Role

    # -- lectura
    def hijos(self, n: Any) -> list[Any]:
        try:
            return [n.get_child_at_index(i) for i in range(min(n.get_child_count(), 400))]
        except Exception:  # noqa: BLE001
            return []

    def padre(self, n: Any) -> Any:
        try:
            return n.get_parent()
        except Exception:  # noqa: BLE001
            return None

    def nombre(self, n: Any) -> str:
        try:
            return str(n.get_name() or "")
        except Exception:  # noqa: BLE001
            return ""

    def rol(self, n: Any) -> str:
        try:
            return str(n.get_role_name() or "")
        except Exception:  # noqa: BLE001
            return ""

    def visible(self, n: Any) -> bool:
        try:
            return bool(n.get_state_set().contains(self.A.StateType.SHOWING))
        except Exception:  # noqa: BLE001
            return False

    def activo(self, n: Any) -> bool:
        try:
            return bool(n.get_state_set().contains(self.A.StateType.ACTIVE))
        except Exception:  # noqa: BLE001
            return False

    def texto(self, n: Any) -> str:
        try:
            return str(self.A.Text.get_text(n, 0, -1) or "")
        except Exception:  # noqa: BLE001
            return ""

    def valor(self, n: Any) -> tuple[float, float] | None:
        try:
            return float(self.A.Value.get_current_value(n)), float(self.A.Value.get_maximum_value(n))
        except Exception:  # noqa: BLE001
            return None

    def fijar(self, n: Any, valor: float) -> bool:
        try:
            return bool(self.A.Value.set_current_value(n, float(valor)))
        except Exception:  # noqa: BLE001
            return False

    def pulsar(self, n: Any) -> bool:
        try:
            return bool(self.A.Action.do_action(n, 0))
        except Exception:  # noqa: BLE001
            return False

    def escritorio(self) -> Any:
        return self.A.get_desktop(0)


# --- búsqueda en el árbol -----------------------------------------------------------------
def recorrer(t: Any, raiz: Any, saltar: Callable[[Any], bool] | None = None) -> Iterator[Any]:
    pila = [(raiz, 0)]
    vistos = 0
    while pila and vistos < MAX_NODOS:
        n, d = pila.pop()
        vistos += 1
        yield n
        if d >= PROFUNDIDAD or (saltar and saltar(n)):
            continue
        pila.extend((h, d + 1) for h in reversed(t.hijos(n)))


def ventanas_youtube(t: Any) -> list[tuple[Any, str, bool]]:
    """(marco, título, activa) de cada ventana de navegador con YouTube."""
    out = []
    for app in t.hijos(t.escritorio()):
        if not any(b in _low(t.nombre(app)) for b in NAVEGADORES):
            continue
        for marco in t.hijos(app):
            titulo = t.nombre(marco)
            low = _low(titulo)
            if "youtube" in low and "youtube music" not in low:
                out.append((marco, titulo, t.activo(marco)))
    out.sort(key=lambda x: not x[2])  # la activa primero
    return out


def documento(t: Any, marco: Any) -> Any:
    for n in recorrer(t, marco):
        if t.rol(n) in ("document web", "document frame"):
            return n
    return None


def reproductor(t: Any, raiz: Any) -> Any:
    import anuncios

    nombres = {x.lower() for x in anuncios.REPRODUCTOR}
    for n in recorrer(t, raiz):
        if _low(t.nombre(n)) in nombres:
            return n
    return None


def barra_direcciones(t: Any, marco: Any) -> str:
    """El texto de la barra de direcciones, sin entrar en la página (como en Windows)."""
    fuera = lambda n: t.rol(n) in ("document web", "document frame", "page tab")  # noqa: E731
    for n in recorrer(t, marco, saltar=fuera):
        if t.rol(n) == "entry":
            v = t.texto(n) or t.nombre(n)
            if "youtu" in v:
                return v
    return ""


def buscar_si(t: Any, raiz: Any) -> Any:
    """El botón «Sí» del aviso «¿Sigues ahí?»: un botón con nombre de `SI` cuyo entorno (hasta
    4 padres) tiene un texto del aviso. Igual que el PowerShell de sigues.py."""
    import sigues

    si = set(sigues.SI)
    for n in recorrer(t, raiz):
        if t.rol(n) not in ("push button", "button") or _low(t.nombre(n)) not in si or not t.visible(n):
            continue
        p = n
        for _ in range(4):
            p = t.padre(p)
            if p is None:
                break
            textos = " ".join(t.nombre(x) + " " + t.texto(x) for x in recorrer(t, p) if t.rol(x) not in ("push button", "button"))
            if sigues.es_aviso(textos):
                return n
    return None


def buscar_saltar(t: Any, raiz: Any) -> Any:
    import anuncios

    nombres = set(anuncios.SALTAR)
    for n in recorrer(t, raiz):
        if t.rol(n) in ("push button", "button") and t.visible(n):
            if anuncios._LIMPIA.sub("", _low(t.nombre(n))) in nombres:
                return n
    return None


def boton_atajo(t: Any, raiz: Any, atajo: str) -> Any:
    """El botón del reproductor cuyo nombre lleva su atajo: «Subtítulos (c)», «Modo cine (t)»,
    «Pantalla completa (f)», «Silenciar (m)»… Así no hace falta pulsar la tecla (0.68)."""
    marca = f"({atajo.lower()})"
    for n in recorrer(t, raiz):
        if t.rol(n) in ("push button", "button", "toggle button") and marca in _low(t.nombre(n)):
            return n
    return None


def deslizador_volumen(t: Any, raiz: Any) -> Any:
    import mando

    for n in recorrer(t, raiz):
        if t.rol(n) == "slider" and any(v in _low(t.nombre(n)) for v in mando.VOLUMEN):
            return n
    return None


def volumen(t: Any, raiz: Any) -> dict[str, Any]:
    import mando

    deslizador, boton = None, ""
    for n in recorrer(t, raiz):
        r, nom = t.rol(n), _low(t.nombre(n))
        if deslizador is None and r == "slider" and any(v in nom for v in mando.VOLUMEN):
            deslizador = n
        elif not boton and r in ("push button", "button") and "(m)" in nom:
            boton = t.nombre(n)
        if deslizador is not None and boton:
            break
    if deslizador is None:
        return {"hay": False}
    v = t.valor(deslizador)
    if v is None:
        return {"hay": False}
    nivel = v[0] * 100 / v[1] if v[1] and v[1] != 100 else v[0]
    return {"hay": True, "nivel": round(nivel), "boton": boton}


# --- las respuestas de los «PowerShell» --------------------------------------------------
class Linux:
    def __init__(self, arbol: Any = None, sesiones: Callable[[], list[dict]] | None = None,
                 saltar: Callable[[str, float], bool] | None = None, clock: Callable[[], float] = time.monotonic,
                 espera: Callable[[float], None] = time.sleep) -> None:
        self._t = arbol
        self.sesiones = sesiones or _sesiones_mpris
        self.saltar = saltar or _saltar_mpris
        self.clock = clock
        self.espera = espera
        # libatspi no es para varios hilos a la vez: sigues, anuncios, patrocinios y mando se turnan.
        self.lock = threading.RLock()
        self._cache: dict[str, Any] = {}

    @property
    def t(self) -> Any:
        if self._t is None:
            self._t = Arbol()
        return self._t

    def _yt(self) -> tuple[Any, str, bool] | None:
        v = ventanas_youtube(self.t)
        return v[0] if v else None

    def _raiz(self) -> Any:
        yt = self._yt()
        if not yt:
            return None
        c = self._cache
        if c.get("marco_t") == yt[1] and c.get("doc") is not None and self.t.rol(c["doc"]):
            return c["doc"]
        doc = documento(self.t, yt[0]) or yt[0]
        self._cache = {"marco_t": yt[1], "doc": doc}
        return doc

    def _repro(self, raiz: Any) -> Any:
        """El reproductor, guardado mientras siga siendo él (buscarlo cuesta: miles de nodos)."""
        import anuncios

        r = self._cache.get("repro")
        if r is not None and _low(self.t.nombre(r)) in {x.lower() for x in anuncios.REPRODUCTOR}:
            return r
        r = reproductor(self.t, raiz)
        self._cache["repro"] = r
        return r

    def find_row(self) -> dict[str, Any] | None:
        """Como control._find_youtube_unlocked, pero sin wmctrl (vale en Wayland)."""
        with self.lock:
            yt = self._yt()
        return {"id": "atspi", "title": yt[1], "active": yt[2]} if yt else None

    # sigues.py: probe(hwnd) -> {ok, pulsado, verificado, ms}
    def _sigues(self, _hwnd: str = "") -> dict[str, Any]:
        t0 = self.clock()
        out: dict[str, Any] = {"ok": True, "pulsado": False, "verificado": False}
        raiz = self._raiz()
        boton = buscar_si(self.t, raiz) if raiz is not None else None
        if boton is not None and self.t.pulsar(boton):
            out["pulsado"] = True
            for _ in range(4):
                self.espera(0.4)
                if buscar_si(self.t, self._raiz()) is None:
                    out["verificado"] = True
                    break
        out["ms"] = int((self.clock() - t0) * 1000)
        return out

    # anuncios.py: probe(hwnd) -> {ok, pulsado, verificado, ms}
    def _anuncios(self, _hwnd: str = "") -> dict[str, Any]:
        t0 = self.clock()
        out: dict[str, Any] = {"ok": True, "pulsado": False, "verificado": False}
        raiz = self._raiz()
        zona = (self._repro(raiz) or raiz) if raiz is not None else None
        boton = buscar_saltar(self.t, zona) if zona is not None else None
        if boton is not None and self.t.pulsar(boton):
            out["pulsado"] = True
            for _ in range(3):
                self.espera(0.3)
                if buscar_saltar(self.t, zona) is None:
                    out["verificado"] = True
                    break
        out["ms"] = int((self.clock() - t0) * 1000)
        return out

    # patrocinios.py y mando.py: probe(línea JSON) -> dict
    def _orden(self, line: str) -> dict[str, Any]:
        t0 = self.clock()
        try:
            cmd = json.loads(line)
        except ValueError:
            return {"ok": False, "error": "orden"}
        c = cmd.get("c")
        out: dict[str, Any] = {"ok": True}
        try:
            if c == "mira":  # patrocinios
                if cmd.get("url"):
                    yt = self._yt()
                    out["url"] = barra_direcciones(self.t, yt[0]) if yt else ""
                out["sesiones"] = self.sesiones()
                out["texto"] = None  # no se sabe: patrocinios no pulsa teclas
            elif c == "salta":  # patrocinios
                out.update(self._salta(cmd))
            elif c == "vol":  # mando
                raiz = self._raiz()
                out["vol"] = volumen(self.t, self._repro(raiz) or raiz) if raiz is not None else {"hay": False}
            elif c == "url":  # mando
                yt = self._yt()
                out["url"] = barra_direcciones(self.t, yt[0]) if yt else ""
            elif c == "ir":  # mando
                ok = self.saltar(str(cmd.get("titulo", "")), float(cmd.get("a", 0)))
                out.update(aceptado=ok, verificado=ok, deja=True)
            else:
                out = {"ok": False, "error": "orden"}
        except Exception as exc:  # noqa: BLE001
            out = {"ok": False, "error": type(exc).__name__}
        out["ms"] = int((self.clock() - t0) * 1000)
        return out

    def sigues(self, hwnd: str = "") -> dict[str, Any]:
        with self.lock:
            return self._sigues(hwnd)

    def anuncios(self, hwnd: str = "") -> dict[str, Any]:
        with self.lock:
            return self._anuncios(hwnd)

    def orden(self, line: str) -> dict[str, Any]:
        with self.lock:
            return self._orden(line)

    def boton(self, atajo: str) -> bool:
        """0.68: pulsa un botón del reproductor por su atajo (c, t, f, m, i)."""
        with self.lock:
            raiz = self._raiz()
            if raiz is None:
                return False
            n = boton_atajo(self.t, self._repro(raiz) or raiz, atajo)
            return bool(n is not None and self.t.pulsar(n))

    def fijar_volumen(self, nivel: int) -> dict[str, Any] | None:
        """0.68: pone el volumen del reproductor exacto (0-100) y devuelve el que queda."""
        with self.lock:
            raiz = self._raiz()
            if raiz is None:
                return None
            zona = self._repro(raiz) or raiz
            d = deslizador_volumen(self.t, zona)
            if d is None:
                return None
            v = self.t.valor(d)
            maximo = v[1] if v and v[1] else 100.0
            if not self.t.fijar(d, max(0, min(100, int(nivel))) * maximo / 100):
                return None
            return volumen(self.t, zona)

    def _salta(self, cmd: dict) -> dict[str, Any]:
        titulo = _low(cmd.get("titulo"))
        desde, hasta = float(cmd.get("desde", 0)), float(cmd.get("hasta", 0))
        s = next((x for x in self.sesiones() if _low(x.get("titulo")) == titulo), None)
        if s is None:
            return {"aceptado": False, "verificado": False, "error": "sin sesion"}
        antes = float(s.get("pos") or 0)
        if s.get("estado") != "playing" or not (desde - 1.5 <= antes < hasta):
            return {"aceptado": False, "verificado": False, "fuera": True, "antes": antes}
        ok = self.saltar(str(cmd.get("titulo", "")), hasta)
        return {"aceptado": ok, "verificado": ok, "antes": antes}


def _sesiones_mpris() -> list[dict[str, Any]]:
    """Las sesiones multimedia con los nombres que espera patrocinios.py."""
    import medios

    rows = medios.WATCH.get() or []
    out = []
    for r in rows:
        if not any(b in str(r.get("app", "")).lower() for b in medios.BROWSERS):
            continue
        out.append({"app": r.get("app", ""), "titulo": r.get("title", ""), "estado": str(r.get("status", "")).lower(),
                    "pos": round(float(r.get("pos") or 0), 2), "len": round(float(r.get("len") or 0), 2),
                    "vel": medios._rate(r.get("rate")) or 1.0, "saltar": bool(shutil.which("playerctl"))})
    return out


def _saltar_mpris(titulo: str, segundos: float) -> bool:
    import control

    return control._mpris_seek(titulo, segundos)


# --- puesta en marcha ---------------------------------------------------------------------
def diagnose(t: Any = None) -> dict[str, Any]:
    info: dict[str, Any] = {"atspi": False, "navegadores": [], "youtube": "", "pagina": False, "barra": False,
                            "playerctl": bool(shutil.which("playerctl")), "accesibilidad": _gsettings_a11y()}
    try:
        t = t or Arbol()
        info["atspi"] = True
        info["navegadores"] = sorted({t.nombre(a) for a in t.hijos(t.escritorio())
                                      if any(b in _low(t.nombre(a)) for b in NAVEGADORES)})
        yt = ventanas_youtube(t)
        if yt:
            info["youtube"] = yt[0][1]
            info["pagina"] = documento(t, yt[0][0]) is not None
            info["barra"] = bool(barra_direcciones(t, yt[0][0]))
    except Exception:  # noqa: BLE001
        pass
    return info


def consejo(info: dict[str, Any]) -> str:
    if not info.get("atspi"):
        return "Falta la accesibilidad de Linux para Python: sudo apt install gir1.2-atspi-2.0 python3-gi"
    if not info.get("playerctl"):
        return "Falta playerctl (posición del vídeo y saltos): sudo apt install playerctl"
    if info.get("youtube") and not info.get("pagina"):
        return ("El navegador no enseña la página. Activa la accesibilidad y reabre el navegador: "
                "gsettings set org.gnome.desktop.interface toolkit-accessibility true "
                "(o arráncalo con --force-renderer-accessibility).")
    if not info.get("youtube"):
        return "Abre YouTube en el navegador para comprobarlo."
    return ""


def _gsettings_a11y() -> bool | None:
    if not shutil.which("gsettings"):
        return None
    try:
        out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "toolkit-accessibility"],
                             capture_output=True, text=True, timeout=3)
        return out.stdout.strip() == "true"
    except Exception:  # noqa: BLE001
        return None


LINUX: Linux | None = None


def instalar() -> bool:
    """Engancha las respuestas de Linux en sigues, anuncios, patrocinios y mando. Solo si
    AT-SPI está (si no, todo sigue como antes: esas funciones no aparecen en Linux)."""
    global LINUX
    if not sys.platform.startswith("linux"):
        return False
    try:
        Arbol()
    except Exception:  # noqa: BLE001 (sin PyGObject o sin AT-SPI)
        return False
    import anuncios
    import mando
    import patrocinios
    import sigues

    LINUX = Linux()
    find_hwnd = lambda: "atspi" if LINUX and LINUX.find_row() else None  # noqa: E731
    sigues.SIGUES.probe, sigues.SIGUES.find = LINUX.sigues, find_hwnd
    anuncios.ANUNCIOS.probe, anuncios.ANUNCIOS.find = LINUX.anuncios, find_hwnd
    patrocinios.PATROCINIOS.probe, patrocinios.PATROCINIOS.find = LINUX.orden, LINUX.find_row
    mando.MANDO.probe = LINUX.orden
    return True


if __name__ == "__main__":
    if "--diagnostico" in sys.argv:
        i = diagnose()
        print(json.dumps(i, ensure_ascii=False, indent=2))
        print(consejo(i) or "Todo listo: LaZoo ve YouTube por accesibilidad.")
