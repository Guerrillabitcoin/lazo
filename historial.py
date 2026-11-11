"""LaZoo 0.66: historial de anuncios y patrocinios saltados, y el tiempo ahorrado de siempre.

- `entradas`: los últimos `MAX` saltos de verdad (los mismos que suben los contadores), la
  última arriba: hora, anuncio o patrocinio, título del vídeo, id (si se sabe), tramo m:ss →
  m:ss y segundos ahorrados. Se borra entera o de una en una desde el Panel.
- `acumulado`: lo ahorrado desde siempre, por tipo. Borrar el historial NO lo toca, ni «Poner a
  cero» los contadores. Solo se pone a cero con su propio botón.

Anuncios: YouTube no dice cuánto duraba el anuncio que se saltó. Se estima con los controles
multimedia de Windows (`medios.py`, sin internet): justo al saltar se mira la posición y la
duración que publica el navegador y, `ESPERA_ANUNCIO` s después, si la duración ha cambiado (ya
suena el vídeo), lo ahorrado es duración − posición del anuncio. Si no cuadra, se apunta el
anuncio sin minutos («¿?») y no se inventa nada.

Todo en la carpeta de datos (`recordar.data_dir()/historial.json`), nada en la del programa.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

MAX = 200                 # entradas guardadas
ESPERA_ANUNCIO = 4.0      # s tras saltar un anuncio para ver si ya suena el vídeo
ANUNCIO_MAX = 600.0       # s: más que esto no es un anuncio, no se cuenta
TIPOS = ("anuncio", "patrocinio")
_COLA = re.compile(r"\s+[-–—]\s+YouTube(\s+[-–—].*)?$", re.IGNORECASE)
_NOTIF = re.compile(r"^\(\d+\)\s+")


def titulo_limpio(window_title: str) -> str:
    """«(3) Receta de lentejas - YouTube - Brave» → «Receta de lentejas»."""
    t = _NOTIF.sub("", " ".join(str(window_title or "").split()))
    return _COLA.sub("", t)[:160]


def _vacio() -> dict[str, Any]:
    return {"anuncio": {"n": 0, "seg": 0.0, "con_tiempo": 0}, "patrocinio": {"n": 0, "seg": 0.0, "con_tiempo": 0}}


class Historial:
    def __init__(self, file: Path | None = None, clock: Callable[[], float] = time.time) -> None:
        self.file = file
        self.clock = clock
        self.lock = threading.Lock()
        self.entradas: list[dict[str, Any]] = []
        self.acumulado = _vacio()
        self.desde = 0.0
        self.n = 0
        self._load()

    def _path(self) -> Path | None:
        if self.file is not None:
            return self.file
        try:
            import recordar

            return recordar.data_dir() / "historial.json"
        except Exception:  # noqa: BLE001
            return None

    def _load(self) -> None:
        p = self._path()
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p and p.is_file() else {}
        except Exception:  # noqa: BLE001 (archivo roto: se empieza de cero)
            data = {}
        ent = [e for e in data.get("entradas") or [] if isinstance(e, dict) and e.get("tipo") in TIPOS]
        self.entradas = ent[:MAX]
        acc = _vacio()
        for tipo in TIPOS:
            src = (data.get("acumulado") or {}).get(tipo) or {}
            try:
                acc[tipo] = {"n": max(0, int(src.get("n", 0))), "seg": max(0.0, float(src.get("seg", 0) or 0)),
                             "con_tiempo": max(0, int(src.get("con_tiempo", 0)))}
            except (TypeError, ValueError):
                pass
        self.acumulado = acc
        self.desde = float(data.get("desde") or 0)
        self.n = max([int(e.get("id", 0) or 0) for e in self.entradas] + [int(data.get("n") or 0)])

    def _save(self) -> None:
        p = self._path()
        if not p:
            return
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            data = {"entradas": self.entradas, "acumulado": self.acumulado, "desde": self.desde, "n": self.n}
            tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            pass

    # --- apuntar ----------------------------------------------------------------
    def apuntar(self, tipo: str, titulo: str = "", video: str = "", desde: float | None = None,
                hasta: float | None = None, seg: float | None = None, metodo: str = "") -> int:
        if tipo not in TIPOS:
            raise ValueError("tipo")
        import patrocinios

        vid = video if patrocinios._ID.fullmatch(video or "") else ""
        with self.lock:
            self.n += 1
            e = {"id": self.n, "t": round(self.clock(), 1), "tipo": tipo, "titulo": titulo_limpio(titulo),
                 "video": vid, "desde": None if desde is None else round(max(0.0, float(desde)), 1),
                 "hasta": None if hasta is None else round(max(0.0, float(hasta)), 1),
                 "seg": None if seg is None else round(max(0.0, float(seg)), 1), "metodo": str(metodo)[:12]}
            self.entradas.insert(0, e)
            del self.entradas[MAX:]
            a = self.acumulado[tipo]
            a["n"] += 1
            if e["seg"] is not None:
                a["seg"] = round(a["seg"] + e["seg"], 1)
                a["con_tiempo"] += 1
            if not self.desde:
                self.desde = e["t"]
            self._save()
            return e["id"]

    def completar(self, ident: int, seg: float) -> bool:
        """Pone los segundos a un anuncio apuntado sin ellos (cuenta en el acumulado una vez)."""
        seg = round(max(0.0, float(seg)), 1)
        with self.lock:
            e = next((x for x in self.entradas if x.get("id") == ident), None)
            if e is None or e.get("seg") is not None:
                return False
            e["seg"] = seg
            a = self.acumulado[e["tipo"]]
            a["seg"] = round(a["seg"] + seg, 1)
            a["con_tiempo"] += 1
            self._save()
            return True

    # --- borrar -------------------------------------------------------------------
    def borrar(self, ident: object = None) -> dict[str, Any]:
        """Una entrada (por id) o todas (None). El acumulado se queda."""
        with self.lock:
            if ident is None:
                self.entradas = []
            else:
                try:
                    k = int(ident)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    raise ValueError("id") from None
                self.entradas = [e for e in self.entradas if e.get("id") != k]
            self._save()
        return self.status()

    def borrar_acumulado(self) -> dict[str, Any]:
        with self.lock:
            self.acumulado = _vacio()
            self.desde = self.entradas[-1]["t"] if self.entradas else 0.0
            self._save()
        return self.status()

    def status(self, limite: int = MAX) -> dict[str, Any]:
        with self.lock:
            return {"entradas": [dict(e) for e in self.entradas[:max(0, limite)]],
                    "acumulado": json.loads(json.dumps(self.acumulado)), "desde": self.desde, "max": MAX}


HISTORIAL = Historial()


# --- enganches con anuncios.py y patrocinios.py ----------------------------------------
def _yt_row() -> dict[str, str] | None:
    try:
        import control

        if control.SYSTEM != "Windows":
            return None
        with control._lock:
            row = control._find_youtube_unlocked()
        return dict(row) if row else None
    except Exception:  # noqa: BLE001
        return None


def _foto(title: str) -> dict[str, Any]:
    try:
        import medios

        return medios.summary(medios.browser_session(title))
    except Exception:  # noqa: BLE001
        return {}


def estimar_anuncio(antes: dict[str, Any], despues: dict[str, Any]) -> float | None:
    """Segundos que quedaban del anuncio, o None si no se puede saber.
    `antes` = lo que publicaba Windows al saltar; `despues` = unos segundos más tarde."""
    try:
        l0, p0, l1 = float(antes.get("len") or 0), float(antes.get("pos") or 0), float(despues.get("len") or 0)
    except (TypeError, ValueError):
        return None
    if not (0 < l0 <= ANUNCIO_MAX) or l1 <= 0 or abs(l1 - l0) <= 2 or not (0 <= p0 < l0):
        return None
    return round(l0 - p0, 1)


def anuncio_saltado(historial: Historial | None = None, row: dict[str, str] | None = None,
                    foto: Callable[[str], dict[str, Any]] = _foto, espera: float = ESPERA_ANUNCIO,
                    timer: Callable[..., Any] = threading.Timer) -> int:
    """Lo llama anuncios.py tras un salto verificado."""
    h = historial or HISTORIAL
    row = row if row is not None else _yt_row()
    title = (row or {}).get("title", "")
    antes = foto(title) if title else {}
    ident = h.apuntar("anuncio", titulo=title)
    if antes.get("len"):
        def luego() -> None:
            seg = estimar_anuncio(antes, foto(title))
            if seg is not None:
                h.completar(ident, seg)

        t = timer(espera, luego)
        t.daemon = True
        t.start()
    return ident


def patrocinio_saltado(titulo: str, video: str, desde: float | None, hasta: float | None, seg: float,
                       metodo: str, historial: Historial | None = None) -> int:
    """Lo llama patrocinios.py tras un salto verificado."""
    return (historial or HISTORIAL).apuntar("patrocinio", titulo=titulo, video=video, desde=desde,
                                            hasta=hasta, seg=seg, metodo=metodo)
