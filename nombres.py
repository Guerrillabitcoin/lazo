"""LaZoo 0.76: un solo nombre por dispositivo, el mismo en todos los PCs y móviles.

Antes cada PC tenía sus propios «Renombrar» (apodos.json para los móviles, el apodo de cada fila
de otros-pcs.json y el nombre de este PC en ajustes.json) y cada móvil veía nombres distintos según
a qué PC estuviera conectado. Ahora hay un registro, `nombres.json` en la carpeta de datos:

    claves   pc:<id de 16-32 hex>   un PC (su id fijo, `pc_id` en ajustes.json)
             dev:<id del móvil>     un móvil (la App da el mismo id en todos los PCs)
             local:<id de conexión> un nombre aún sin dueño conocido (un PC 0.75, o migrado):
                                    no se comparte; al saber de quién es, pasa a su clave
    valor    {"n": nombre (≤40, "" = el de siempre), "t": milisegundos de cuando se puso}

Se cambia desde cualquier PC o móvil y viaja con la sincronización entre PCs (sincro.py): gana el
más reciente (y, si coinciden, el texto mayor, para que todos decidan lo mismo).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

ARCHIVO = "nombres.json"
MAX_NOMBRES = 300
MAX_ENLACES = 400
FUTURO_MS = 24 * 3600 * 1000  # una marca más de un día en el futuro (reloj mal) no se acepta
_CLAVE = re.compile(r"(pc:[0-9a-f]{16,32}|dev:[0-9a-f]{8,40}|local:[0-9a-f]{8,40})")
_ID = re.compile(r"[0-9a-f]{8,40}")
_HOST = re.compile(r"[0-9A-Za-z.:%\[\]-]{3,120}")


def ahora_ms() -> int:
    return int(time.time() * 1000)


def limpiar(texto: object) -> str:
    import aprobacion

    return aprobacion.limpiar_apodo(texto)


def clave_valida(clave: object) -> bool:
    return isinstance(clave, str) and bool(_CLAVE.fullmatch(clave))


def compartible(clave: str) -> bool:
    return clave.startswith(("pc:", "dev:"))


def gana(a: dict | None, b: dict | None) -> bool:
    """¿`b` sustituye a `a`? El más reciente; a igualdad, el texto mayor."""
    if b is None:
        return False
    if a is None:
        return True
    return (int(b["t"]), str(b["n"])) > (int(a["t"]), str(a["n"]))


class Nombres:
    def __init__(self, carpeta: Path | str | None = None) -> None:
        self._carpeta = carpeta
        self.lock = threading.RLock()
        self._datos: dict | None = None
        self.al_cambiar: list[Callable[[], None]] = []

    # -- archivo --------------------------------------------------------------------------------
    def carpeta(self) -> Path:
        if self._carpeta is not None:
            return Path(self._carpeta)
        import recordar

        return recordar.data_dir()

    def archivo(self) -> Path:
        return self.carpeta() / ARCHIVO

    def _cargar(self) -> dict:
        if self._datos is not None:
            return self._datos
        try:
            data = json.loads(self.archivo().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        nombres: dict[str, dict] = {}
        for k, v in (data.get("nombres") or {}).items() if isinstance(data.get("nombres"), dict) else []:
            fila = self._fila(k, v)
            if fila is not None:
                nombres[k] = fila
        enlaces = {str(k): str(v) for k, v in (data.get("enlaces") or {}).items()
                   if _ID.fullmatch(str(k)) and clave_valida(v) and compartible(str(v))} if isinstance(data.get("enlaces"), dict) else {}
        hosts = {str(k): str(v) for k, v in (data.get("hosts") or {}).items()
                 if _HOST.fullmatch(str(k)) and clave_valida(v)} if isinstance(data.get("hosts"), dict) else {}
        self._datos = {"nombres": nombres, "enlaces": enlaces, "hosts": hosts, "migrado": data.get("migrado") is True}
        if not self._datos["migrado"]:
            self._migrar()
        return self._datos

    @staticmethod
    def _fila(clave: Any, valor: Any) -> dict | None:
        if not clave_valida(clave) or not isinstance(valor, dict):
            return None
        try:
            n = limpiar(valor.get("n", ""))
            t = int(valor.get("t") or 0)
        except (ValueError, TypeError):
            return None
        if t <= 0:
            return None
        return {"n": n, "t": t}

    def _guardar(self) -> None:
        d = self._datos or {}
        datos = {"nombres": d.get("nombres", {}), "enlaces": d.get("enlaces", {}), "hosts": d.get("hosts", {}), "migrado": True}
        try:
            import recordar

            recordar._write_private(self.archivo(), json.dumps(datos, ensure_ascii=False).encode("utf-8"))
        except OSError:
            pass

    def _avisar(self) -> None:
        for fn in list(self.al_cambiar):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass

    def _recortar(self) -> None:
        d = self._datos or {}
        n = d.get("nombres", {})
        if len(n) > MAX_NOMBRES:
            for k in sorted(n, key=lambda k: n[k]["t"])[: len(n) - MAX_NOMBRES]:
                n.pop(k, None)
        for campo in ("enlaces", "hosts"):
            m = d.get(campo, {})
            while len(m) > MAX_ENLACES:
                m.pop(next(iter(m)))

    # -- migración de la 0.75 ---------------------------------------------------------------------
    def _mtime_ms(self, nombre: str) -> int:
        try:
            return int(os.path.getmtime(self.carpeta() / nombre) * 1000)
        except OSError:
            return 0

    def _migrar(self) -> None:
        """Los «Renombrar» de antes (apodos.json y el apodo de cada PC en otros-pcs.json) pasan a
        nombres sin dueño (`local:`) con la hora del archivo; el más reciente gana. Se comparten en
        cuanto se sabe de quién son (un móvil, al listarlo; un PC, al sincronizar con él)."""
        d = self._datos
        assert d is not None
        d["migrado"] = True
        legado: list[tuple[str, str, int]] = []
        try:
            data = json.loads((self.carpeta() / "apodos.json").read_text(encoding="utf-8"))
            t = self._mtime_ms("apodos.json") or ahora_ms()
            for who, n in (data.items() if isinstance(data, dict) else []):
                legado.append((str(who), n, t))
        except (OSError, ValueError):
            pass
        try:
            data = json.loads((self.carpeta() / "otros-pcs.json").read_text(encoding="utf-8"))
            t = self._mtime_ms("otros-pcs.json") or ahora_ms()
            for fila in (data.get("pcs") or []) if isinstance(data, dict) else []:
                if isinstance(fila, dict) and fila.get("apodo"):
                    legado.append((str(fila.get("id", "")), fila["apodo"], t))
        except (OSError, ValueError):
            pass
        for who, n, t in legado:
            if not _ID.fullmatch(who):
                continue
            fila = self._fila("local:" + who, {"n": n, "t": t})
            if fila and fila["n"] and gana(d["nombres"].get("local:" + who), fila):
                d["nombres"]["local:" + who] = fila
        self._guardar()

    # -- leer -----------------------------------------------------------------------------------
    def get(self, clave: str) -> str:
        with self.lock:
            fila = self._cargar()["nombres"].get(clave)
            return fila["n"] if fila else ""

    def fila(self, clave: str) -> dict | None:
        with self.lock:
            fila = self._cargar()["nombres"].get(clave)
            return dict(fila) if fila else None

    def clave_de(self, who: str) -> str:
        with self.lock:
            return self._cargar()["enlaces"].get(who, "")

    def clave_dispositivo(self, who: str, es_pc: bool = False) -> str:
        """La clave con la que se nombra a un dispositivo de ESTE PC (id de su conexión)."""
        enlazada = self.clave_de(who)
        if enlazada:
            return enlazada
        return ("local:" if es_pc else "dev:") + who

    def nombre_dispositivo(self, who: str, es_pc: bool = False) -> str:
        """Nombre propio ("" = el de siempre). Un nombre `local:` más reciente que el compartido
        (migrado de la 0.75) pasa a la clave compartida en cuanto se sabe cuál es."""
        if not _ID.fullmatch(str(who or "")):
            return ""
        with self.lock:
            d = self._cargar()
            clave = self.clave_dispositivo(who, es_pc)
            local = d["nombres"].get("local:" + who)
            if local is not None and clave != "local:" + who:
                if gana(d["nombres"].get(clave), local):
                    d["nombres"][clave] = dict(local)
                del d["nombres"]["local:" + who]
                self._guardar()
                avisar = True
            else:
                avisar = False
            fila = d["nombres"].get(clave)
        if avisar:
            self._avisar()
        return fila["n"] if fila else ""

    def hosts(self) -> dict[str, str]:
        with self.lock:
            d = self._cargar()
            return {h: d["nombres"][k]["n"] for h, k in d["hosts"].items() if d["nombres"].get(k, {}).get("n")}

    def clave_de_host(self, host: str) -> str:
        with self.lock:
            return self._cargar()["hosts"].get(host, "")

    def exportar(self) -> dict[str, dict]:
        with self.lock:
            return {k: dict(v) for k, v in self._cargar()["nombres"].items() if compartible(k)}

    # -- cambiar --------------------------------------------------------------------------------
    def poner(self, clave: str, texto: object, t: int | None = None) -> str:
        if not clave_valida(clave):
            raise ValueError("Ese dispositivo no está")
        n = limpiar(texto)
        with self.lock:
            d = self._cargar()
            viejo = d["nombres"].get(clave)
            if t is None:
                t = ahora_ms()
                if viejo is not None and t <= viejo["t"]:
                    t = viejo["t"] + 1  # un cambio hecho aquí siempre es el más reciente
            t = int(t)
            d["nombres"][clave] = {"n": n, "t": t}
            self._recortar()
            self._guardar()
        self._avisar()
        return n

    def renombrar_dispositivo(self, who: str, texto: object, es_pc: bool = False) -> str:
        if not _ID.fullmatch(str(who or "")):
            raise ValueError("Ese dispositivo no está")
        clave = self.clave_dispositivo(who, es_pc)
        n = self.poner(clave, texto)
        with self.lock:
            d = self._cargar()
            if clave != "local:" + who and d["nombres"].pop("local:" + who, None) is not None:
                self._guardar()
        return n

    def fusionar(self, entradas: Any) -> bool:
        """Lo que llega de otro PC. Devuelve True si algo cambió aquí."""
        if not isinstance(entradas, dict):
            return False
        limite = ahora_ms() + FUTURO_MS
        cambio = False
        with self.lock:
            d = self._cargar()
            for k, v in list(entradas.items())[:MAX_NOMBRES]:
                if not isinstance(k, str) or not compartible(k):
                    continue
                fila = self._fila(k, v)
                if fila is None or fila["t"] > limite:
                    continue
                if gana(d["nombres"].get(k), fila):
                    d["nombres"][k] = fila
                    cambio = True
            if cambio:
                self._recortar()
                self._guardar()
        if cambio:
            self._avisar()
        return cambio

    def enlazar(self, who: str, clave: str, host: str = "") -> bool:
        """Ese id de conexión es el dispositivo `clave` (lo dijo él al sincronizar)."""
        if not _ID.fullmatch(str(who or "")) or not clave_valida(clave) or not compartible(clave):
            return False
        with self.lock:
            d = self._cargar()
            cambio = d["enlaces"].get(who) != clave
            d["enlaces"][who] = clave
            if host and _HOST.fullmatch(host) and d["hosts"].get(host) != clave:
                d["hosts"][host] = clave
                cambio = True
            if cambio:
                self._recortar()
                self._guardar()
        self.nombre_dispositivo(who)  # pasa un `local:` migrado a la clave compartida
        return cambio

    def copiar(self, viejo: str, nuevo: str) -> None:
        """Al volver a añadir un PC (id de conexión nuevo) conserva su nombre."""
        with self.lock:
            d = self._cargar()
            if viejo in d["enlaces"]:
                d["enlaces"][nuevo] = d["enlaces"][viejo]
            elif "local:" + viejo in d["nombres"]:
                d["nombres"]["local:" + nuevo] = dict(d["nombres"]["local:" + viejo])
            else:
                return
            self._guardar()

    def recargar(self) -> None:
        with self.lock:
            self._datos = None


NOMBRES = Nombres()


def de_carpeta(carpeta: Path | str | None) -> Nombres:
    """El registro global, o uno propio para otra carpeta (pruebas)."""
    if carpeta is None:
        return NOMBRES
    return Nombres(carpeta)
