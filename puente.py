"""Puente por trozos: archivos de cualquier tipo y tamaño entre el móvil y el PC.

Subida (móvil -> PC):
  POST /api/up/start      {name, size, key}  -> {id, chunk, total, have, skip}
  POST /api/up/<id>/<i>   cuerpo = trozo i sellado (LZ2) y firmado como el resto
  POST /api/up/<id>/done  {sha256}           -> {name, size, folder}
  POST /api/up/<id>/cancel
El trozo se escribe en disco en su sitio (`.part`), así que ni el móvil ni el PC tienen el
archivo entero en memoria. `key` es una huella del archivo en el móvil (nombre, tamaño y
fecha): si se corta la red o el PC se reinicia, la misma huella retoma los trozos que ya
llegaron. Al terminar se comprueba el SHA-256 del archivo entero.

Bajada (PC -> móvil): el móvil pide trozos de `CHUNK` con GET y los junta él.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable

CHUNK = 4 * 1024 * 1024
MAX_FILE = int(float(os.environ.get("LAZO_MAX_GB", "8")) * 1024**3)
MARGIN = 256 * 1024 * 1024
STALE_SECONDS = 24 * 3600
PART_DIR = ".lazo-partes"

_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {f"{p}{n}" for p in ("COM", "LPT") for n in "123456789¹²³"}
_ID = re.compile(r"[0-9a-f]{20}")


class BridgeError(ValueError):
    """Error con mensaje en español para el móvil."""


def set_max_gb(gb: float) -> None:
    global MAX_FILE
    MAX_FILE = int(gb * 1024**3)


def human(size: int) -> str:
    if size >= 1024**3:
        return f"{size / 1024**3:.1f} GB".replace(".", ",")
    if size >= 1024**2:
        return f"{size / 1024**2:.0f} MB"
    return f"{max(1, size // 1024)} KB" if size else "0 B"


def clean_name(name: str, fallback: str = "archivo") -> str:
    """Nombre seguro en Windows, Linux y Mac: sin carpetas, sin `..`, sin caracteres
    prohibidos ni nombres reservados (CON, NUL, COM1...), y no muy largo."""
    base = str(name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join("_" if ch in '<>:"|?*' else ch for ch in base if ord(ch) >= 32 and ord(ch) != 127)
    base = base.strip().strip(".").strip()
    if not base:
        base = fallback
    stem, dot, ext = base.rpartition(".")
    if not dot or not stem:
        stem, ext = base, ""
    else:
        ext = "." + ext
    if len(ext) > 16:
        stem, ext = base, ""
    if stem.split(".")[0].strip().upper() in _RESERVED:
        stem = "_" + stem
    while len((stem + ext).encode("utf-8")) > 180:
        stem = stem[:-1]
    return (stem.rstrip(" .") or fallback) + ext


def unique_path(folder: Path, name: str) -> Path:
    candidate = folder / name
    if not candidate.exists():
        return candidate
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        stem, ext = name, ""
    else:
        ext = "." + ext
    number = 2
    while True:
        candidate = folder / f"{stem} ({number}){ext}"
        if not candidate.exists():
            return candidate
        number += 1


class Uploads:
    def __init__(self, folder: Callable[[], Path]) -> None:
        self._folder = folder
        self._lock = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._last_clean = 0.0

    # --- rutas -------------------------------------------------------------
    def folder(self) -> Path:
        path = Path(self._folder())
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _parts(self) -> Path:
        path = self.folder() / PART_DIR
        path.mkdir(exist_ok=True)
        return path

    def _meta_path(self, up_id: str) -> Path:
        if not _ID.fullmatch(up_id or ""):
            raise BridgeError("Envío no válido")
        return self._parts() / f"{up_id}.json"

    def _read(self, up_id: str) -> dict[str, Any]:
        try:
            meta = json.loads(self._meta_path(up_id).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise BridgeError("Ese envío ya no está; vuelve a elegir el archivo") from None
        if not isinstance(meta, dict):
            raise BridgeError("Envío no válido")
        return meta

    def _write(self, up_id: str, meta: dict[str, Any]) -> None:
        path = self._meta_path(up_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta), encoding="utf-8")
        os.replace(tmp, path)

    def _id_lock(self, up_id: str) -> threading.Lock:
        with self._lock:
            return self._locks.setdefault(up_id, threading.Lock())

    # --- limpieza ----------------------------------------------------------
    def cleanup(self, max_age: float = STALE_SECONDS, force: bool = False) -> int:
        """Borra envíos a medias que nadie ha tocado en `max_age` segundos."""
        now = time.time()
        if not force and now - self._last_clean < 600:
            return 0
        self._last_clean = now
        removed = 0
        try:
            entries = list(self._parts().iterdir())
        except OSError:
            return 0
        for path in entries:
            try:
                if now - path.stat().st_mtime > max_age:
                    path.unlink()
                    removed += 1
            except OSError:
                pass
        return removed

    def _reserved(self, skip: str = "") -> int:
        total = 0
        for meta_path in self._parts().glob("*.json"):
            if meta_path.stem == skip:
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                total += max(0, int(meta["size"]) - len(meta["have"]) * int(meta["chunk"]))
            except (OSError, ValueError, KeyError, TypeError):
                pass
        return total

    # --- subida ------------------------------------------------------------
    def start(self, name: str, size: Any, key: str = "", who: str = "") -> dict[str, Any]:
        try:
            size = int(size)
        except (TypeError, ValueError):
            raise BridgeError("Tamaño no válido") from None
        if size < 0:
            raise BridgeError("Tamaño no válido")
        if size > MAX_FILE:
            raise BridgeError(f"Pasa del límite de {human(MAX_FILE)} por archivo")
        clean = clean_name(name)
        self.cleanup()
        folder = self.folder()
        existing = folder / clean
        if size and existing.is_file() and existing.stat().st_size == size:
            return {"skip": True, "name": clean}
        up_id = hashlib.sha256(f"{who}\n{key}\n{clean}\n{size}".encode()).hexdigest()[:20] if key else secrets.token_hex(10)
        total = (size + CHUNK - 1) // CHUNK
        with self._id_lock(up_id):
            try:
                meta = self._read(up_id)
                if meta.get("size") != size or meta.get("chunk") != CHUNK:
                    raise BridgeError("cambió")
            except BridgeError:
                meta = {"name": clean, "size": size, "chunk": CHUNK, "have": [], "at": int(time.time())}
            need = size - len(meta["have"]) * CHUNK
            free = shutil.disk_usage(folder).free
            reserved = self._reserved(skip=up_id)
            if need > 0 and free - reserved - need < MARGIN:
                left = max(0, free - reserved - MARGIN)
                raise BridgeError(f"No cabe en el PC: «{clean}» necesita {human(need)} y quedan {human(left)} libres")
            part = self._parts() / f"{up_id}.part"
            if not part.exists():
                part.write_bytes(b"")
                meta["have"] = []
            self._write(up_id, meta)
        return {"id": up_id, "chunk": CHUNK, "total": total, "have": sorted(meta["have"]), "name": clean}

    def write(self, up_id: str, index: int, data: bytes) -> dict[str, Any]:
        with self._id_lock(up_id):
            meta = self._read(up_id)
            size, chunk = int(meta["size"]), int(meta["chunk"])
            total = (size + chunk - 1) // chunk
            if not 0 <= index < total:
                raise BridgeError("Trozo fuera de rango")
            expect = min(chunk, size - index * chunk)
            if len(data) != expect:
                raise BridgeError("Trozo incompleto")
            part = self._parts() / f"{up_id}.part"
            try:
                with open(part, "r+b") as out:
                    out.seek(index * chunk)
                    out.write(data)
            except FileNotFoundError:
                raise BridgeError("Ese envío ya no está; vuelve a elegir el archivo") from None
            except OSError as exc:
                raise BridgeError("No se pudo escribir en el disco del PC (¿lleno?)") from exc
            if index not in meta["have"]:
                meta["have"].append(index)
            meta["at"] = int(time.time())
            self._write(up_id, meta)
            return {"ok": True, "have": len(meta["have"]), "total": total}

    def finish(self, up_id: str, sha256: str) -> dict[str, Any]:
        with self._id_lock(up_id):
            meta = self._read(up_id)
            size, chunk = int(meta["size"]), int(meta["chunk"])
            total = (size + chunk - 1) // chunk
            missing = total - len(set(meta["have"]))
            if missing:
                raise BridgeError(f"Faltan {missing} trozos")
            part = self._parts() / f"{up_id}.part"
            digest = hashlib.sha256()
            with open(part, "rb") as src:
                while True:
                    block = src.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
            if part.stat().st_size != size:
                raise BridgeError("El tamaño no cuadra")
            if sha256 and digest.hexdigest() != str(sha256).lower():
                part.unlink(missing_ok=True)
                self._meta_path(up_id).unlink(missing_ok=True)
                raise BridgeError("El archivo llegó dañado (el SHA-256 no coincide). Vuelve a enviarlo.")
            folder = self.folder()
            with self._lock:
                final = unique_path(folder, meta["name"])
                os.replace(part, final)
            self._meta_path(up_id).unlink(missing_ok=True)
        with self._lock:
            self._locks.pop(up_id, None)
        return {"name": final.name, "size": size, "sha256": digest.hexdigest(), "folder": str(folder)}

    def cancel(self, up_id: str) -> dict[str, Any]:
        with self._id_lock(up_id):
            path = self._meta_path(up_id)
            path.unlink(missing_ok=True)
            (self._parts() / f"{up_id}.part").unlink(missing_ok=True)
        with self._lock:
            self._locks.pop(up_id, None)
        return {"ok": True}


def read_chunk(path: Path, index: int, chunk: int = CHUNK) -> bytes:
    size = path.stat().st_size
    total = max(1, (size + chunk - 1) // chunk)
    if not 0 <= index < total:
        raise BridgeError("Trozo fuera de rango")
    with open(path, "rb") as src:
        src.seek(index * chunk)
        return src.read(chunk)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as src:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
