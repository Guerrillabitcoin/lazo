"""LaZoo 0.76: historial del portapapeles, notas y nombres comunes entre tus PCs.

Quién habla con quién
    Solo los PCs emparejados con «Controlar otro PC» (Añadir otro PC con su PIN y aceptado allí,
    como un móvil): el PC que lo añadió tiene la clave de ese dispositivo y cada pocos segundos
    hace `POST /api/pc/sync` al otro, firmado (X-Lazo-*) y sellado (LZ2) con esa clave, solo por
    la red local. El otro PC solo lo atiende si ese dispositivo está aprobado y es un PC
    («PC · …»), y contesta sellado. Con una sola petición los dos quedan iguales (el que llama
    manda lo suyo y se lleva lo del otro), así que basta con que UNO haya añadido al otro.

Qué viaja
    - «yo»: id fijo del PC (pc_id), su nombre, su puerto y su sistema.
    - nombres: el registro común (nombres.py), siempre.
    - notas: el historial del portapapeles (las notas) con sus lápidas, solo si los DOS tienen
      «Compartir historial y notas entre mis dispositivos» (encendido de serie). Si el que llama
      ya coincidía con el otro la última vez y no ha cambiado nada, solo manda la huella y el otro
      contesta «igual»: casi nada por la red.
    Nada de imágenes ni archivos: eso va al cambiar de PC con la tecla rápida (pcapc.py).

Un PC con la 0.75 contesta 404: se le deja en paz 10 minutos y el Panel dice que lo actualices.
Nada de esto lanza programas ni abre ventanas (0.75): solo HTTP entre los dos LaZoo.
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
from typing import Any, Callable

RUTA = "/api/pc/sync"
VERSION_SYNC = 1
PERIODO = 5.0           # s entre rondas (antes si algo cambia aquí)
ESPERA_ANTIGUO = 600.0  # s: un PC 0.75 no sabe sincronizar
ESPERA_ERROR = 30.0     # s tras un error de red o de permiso
MAX_CUERPO = 4_000_000  # bytes (sellado) de una petición o respuesta
PUERTO = 8787           # el de este LaZoo (lazo.py lo pone al arrancar)

_PC_ID = re.compile(r"[0-9a-f]{16,32}")


def _sistema() -> str:
    return "Windows" if sys.platform == "win32" else "Linux" if sys.platform.startswith("linux") else "Mac" if sys.platform == "darwin" else "PC"


def yo() -> dict:
    import control
    import pcapc

    return {"pc_id": pcapc.AJUSTES.pc_id or pcapc.AJUSTES.clave()[3:], "nombre": pcapc.AJUSTES.nombre_propio() or control.pc_name(),
            "puerto": int(PUERTO), "sistema": _sistema()}


def paquete(completo: bool = True) -> dict:
    """Lo que este PC manda (o contesta)."""
    import control
    import nombres
    import pcapc

    d: dict[str, Any] = {"v": VERSION_SYNC, "yo": yo(), "comparte": bool(pcapc.AJUSTES.compartir_notas),
                         "nombres": nombres.NOMBRES.exportar()}
    if d["comparte"]:
        notas = control.estado_notas()
        d["firma"] = control.firma_notas(notas)
        if completo:
            d["notas"] = notas
    return d


def _yo_de(data: Any) -> dict | None:
    y = data.get("yo") if isinstance(data, dict) else None
    if not isinstance(y, dict) or not _PC_ID.fullmatch(str(y.get("pc_id", ""))):
        return None
    try:
        puerto = int(y.get("puerto") or 8787)
    except (TypeError, ValueError):
        puerto = 8787
    return {"pc_id": str(y["pc_id"]), "nombre": str(y.get("nombre", ""))[:40], "puerto": puerto if 0 < puerto < 65536 else 8787,
            "sistema": str(y.get("sistema", ""))[:12]}


ENTRANTES: dict[str, dict] = {}  # id del dispositivo (un PC que sincroniza con este) → cuándo y quién


def atender(who: str, ip: str, data: Any) -> tuple[int, dict]:
    """El lado que recibe `POST /api/pc/sync` (ya firmado, aprobado y de un PC)."""
    import control
    import nombres
    import pcapc

    if not isinstance(data, dict) or not isinstance(data.get("v"), int):
        return 400, {"error": "petición rara"}
    suyo = _yo_de(data)
    if suyo is None:
        return 400, {"error": "falta quién eres"}
    if suyo["pc_id"] == pcapc.AJUSTES.pc_id:
        return 400, {"error": "es este mismo PC"}
    nombres.NOMBRES.enlazar(who, "pc:" + suyo["pc_id"], host=f"{ip}:{suyo['puerto']}" if ":" not in ip else f"[{ip}]:{suyo['puerto']}")
    nombres.NOMBRES.fusionar(data.get("nombres"))
    comparte = bool(pcapc.AJUSTES.compartir_notas)
    ENTRANTES[who] = {"visto": time.time(), "pc_id": suyo["pc_id"], "comparte": bool(data.get("comparte")) and comparte}
    resp = paquete(completo=False)
    if comparte and data.get("comparte") is True:
        sus_notas = data.get("notas")
        if isinstance(sus_notas, dict):
            control.fusionar_notas(sus_notas)
            suya = control.firma_notas(sus_notas)
        else:
            suya = str(data.get("firma", ""))
        mias = control.estado_notas()
        resp["firma"] = control.firma_notas(mias)
        if resp["firma"] == suya:
            resp["igual"] = True
        else:
            resp["notas"] = mias
    return 200, resp


class Sincro:
    """El lado que llama: cada PERIODO s (o en cuanto cambian las notas o un nombre) con cada PC
    de «Controlar otro PC»."""

    def __init__(self, pcs: Any = None, pedir: Callable[..., tuple[int, dict]] | None = None,
                 reloj: Callable[[], float] = time.monotonic) -> None:
        self._pcs = pcs
        self._pedir = pedir
        self.reloj = reloj
        self.pares: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.ev = threading.Event()
        self._stop = threading.Event()
        self._hilo: threading.Thread | None = None

    @property
    def pcs(self) -> Any:
        if self._pcs is None:
            import pcapc

            return pcapc.PCS
        return self._pcs

    def avisar(self) -> None:
        self.ev.set()

    def ver(self) -> dict[str, dict]:
        with self.lock:
            return {k: {kk: vv for kk, vv in v.items() if kk not in ("firma_ok", "siguiente")} for k, v in self.pares.items()}

    def start(self) -> bool:
        if self._hilo and self._hilo.is_alive():
            return False
        self._stop.clear()
        self._hilo = threading.Thread(target=self._bucle, name="lazo-sincro", daemon=True)
        self._hilo.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        self.ev.set()

    def _bucle(self) -> None:
        while not self._stop.is_set():
            cambio = self.ev.wait(PERIODO)
            if self._stop.is_set():
                return
            self._stop.wait(0.3)  # junta varios cambios seguidos
            self.ev.clear()
            try:
                self.ronda(cambio=cambio)
            except Exception:  # noqa: BLE001 (nunca tumbar LaZoo por esto)
                pass

    def ronda(self, forzar: bool = False, cambio: bool = False) -> int:
        """Una vuelta. Con `cambio` (algo cambió aquí) no se espera al plazo de los que van bien;
        a los que fallaron o son 0.75 sí."""
        hechos = 0
        try:
            filas = self.pcs.listar()
        except Exception:  # noqa: BLE001
            return 0
        vivos = {f["id"] for f in filas}
        with self.lock:
            for k in [k for k in self.pares if k not in vivos]:
                del self.pares[k]
        for fila in filas:
            with self.lock:
                par = self.pares.setdefault(fila["id"], {"estado": "nada", "mensaje": "", "visto": 0.0, "firma_ok": "", "siguiente": 0.0})
                espera = self.reloj() < par["siguiente"]
                if not forzar and espera and (not cambio or par["estado"] in ("error", "antiguo")):
                    continue
            self.uno(fila)
            hechos += 1
        return hechos

    def _poner(self, pid: str, **kw: Any) -> None:
        with self.lock:
            par = self.pares.setdefault(pid, {"estado": "nada", "mensaje": "", "visto": 0.0, "firma_ok": "", "siguiente": 0.0})
            par.update(kw)

    def uno(self, fila: dict) -> str:
        import control
        import nombres
        import pcapc

        pid = fila["id"]
        with self.lock:
            par = dict(self.pares.get(pid) or {})
        comparte = bool(pcapc.AJUSTES.compartir_notas)
        firma = control.firma_notas() if comparte else ""
        cuerpo = paquete(completo=not comparte or par.get("firma_ok") != firma)
        try:
            kd = self.pcs.clave(pid)
            code, r = (self._pedir or pcapc.peticion)(fila, RUTA, cuerpo, kd)
        except (pcapc.ErrorPC, OSError, ValueError) as exc:
            self._poner(pid, estado="error", mensaje=str(exc), siguiente=self.reloj() + ESPERA_ERROR)
            return "error"
        if code == 404:
            self._poner(pid, estado="antiguo", siguiente=self.reloj() + ESPERA_ANTIGUO,
                        mensaje="Tiene una versión anterior de LaZoo: actualízalo para compartir notas y nombres.")
            return "antiguo"
        if code != 200:
            self._poner(pid, estado="error", siguiente=self.reloj() + ESPERA_ERROR, mensaje=pcapc.mensaje_error(code, r))
            return "error"
        suyo = _yo_de(r)
        if suyo is None:
            self._poner(pid, estado="error", siguiente=self.reloj() + ESPERA_ERROR, mensaje="Respuesta rara del otro PC")
            return "error"
        host = f"[{fila['host']}]" if ":" in str(fila["host"]) else str(fila["host"])
        nombres.NOMBRES.enlazar(pid, "pc:" + suyo["pc_id"], host=f"{host}:{fila['puerto']}")
        nombres.NOMBRES.fusionar(r.get("nombres"))
        firma_ok = ""
        if comparte and r.get("comparte") is True:
            if isinstance(r.get("notas"), dict):
                control.fusionar_notas(r["notas"])
            mia = control.firma_notas()
            if r.get("igual") or (isinstance(r.get("notas"), dict) and control.firma_notas(r["notas"]) == mia):
                firma_ok = mia
            else:
                self.ev.set()  # aún distintos: otra vuelta enseguida, ya con todo
        estado = "ok" if (comparte and r.get("comparte") is True) else "sin_notas"
        mensaje = "" if estado == "ok" else ("Compartir notas está apagado en este PC." if not comparte
                                             else "El otro PC no comparte notas (está apagado allí).")
        self._poner(pid, estado=estado, mensaje=mensaje, visto=time.time(), firma_ok=firma_ok,
                    siguiente=self.reloj() + PERIODO - 0.5, sistema=suyo["sistema"])
        return estado


SINCRO = Sincro()


def instalar() -> bool:
    """Al arrancar LaZoo (no en pruebas): engancha los avisos y arranca el hilo."""
    import control
    import nombres

    if "unittest" in sys.modules or "pytest" in sys.modules:
        return False
    if SINCRO.avisar not in control.CLIP_CAMBIO:
        control.CLIP_CAMBIO.append(SINCRO.avisar)
    if SINCRO.avisar not in nombres.NOMBRES.al_cambiar:
        nombres.NOMBRES.al_cambiar.append(SINCRO.avisar)
    return SINCRO.start()


def leer_cuerpo(raw: bytes) -> Any:
    return json.loads(raw.decode("utf-8") or "{}")
