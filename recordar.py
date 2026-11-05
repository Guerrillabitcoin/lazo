"""0.54: «Recordar dispositivos». Guarda en este PC la clave larga (cifrada) y la lista
de móviles aprobados, para que se reconecten solos tras reiniciar sin QR ni PIN.

- Windows: la clave va protegida con DPAPI (solo tu usuario de Windows la abre).
- Linux y macOS: sellada (LZ2) con una clave local aleatoria; los dos archivos con
  permisos 600 en `~/.config/lazoo` (o `$XDG_CONFIG_HOME/lazoo`).
- `LAZO_DATOS` cambia la carpeta (pruebas).

Nada de esto sale del PC. «Olvidar todos» borra la clave y la lista.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import threading
import time
from pathlib import Path

import protocol

KEY_FILE = "clave.bin"
LOCAL_FILE = "clave-local.bin"
LIST_FILE = "dispositivos.json"
DEFAULT_ON = True
# 0.62: marca de la clave maestra guardada desde que cada móvil tiene su propia clave. Una clave
# guardada sin marca es de 0.54-0.61, cuando los móviles tenían la maestra: no se reutiliza.
KEY_TAG = b"LZK3"


def data_dir() -> Path:
    env = os.environ.get("LAZO_DATOS")
    if env:
        return Path(env)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home()) / "LaZoo"
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "lazoo"


# --- DPAPI (Windows) ---------------------------------------------------------

_DPAPI_FNS = None


def _dpapi_fns():
    """0.57: crypt32 y kernel32 PROPIOS (ctypes.WinDLL nuevo), no ctypes.windll compartido.

    Causa del fallo de 0.54-0.56 en el .exe: control._dpapi (portapapeles) pone
    `ctypes.windll.crypt32.CryptProtectData.argtypes` con SU estructura DATA_BLOB, y como
    ctypes.windll es global, aquí saltaba `ctypes.ArgumentError` (que no es OSError) al guardar
    la clave tras aceptar el móvil: /api/pair/wait se cortaba sin respuesta y el móvil nunca
    recibía la clave. Con una instancia propia nadie más toca estas firmas."""
    global _DPAPI_FNS
    if _DPAPI_FNS is None:
        import ctypes

        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        sig = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
        for fn in (crypt32.CryptProtectData, crypt32.CryptUnprotectData):
            fn.argtypes = sig
            fn.restype = ctypes.c_int
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        _DPAPI_FNS = (crypt32.CryptProtectData, crypt32.CryptUnprotectData, kernel32.LocalFree)
    return _DPAPI_FNS


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.c_void_p)]

    protect_fn, unprotect_fn, local_free = _dpapi_fns()
    buf = ctypes.create_string_buffer(data, len(data))
    src = BLOB(len(data), ctypes.cast(buf, ctypes.c_void_p))
    out = BLOB()
    fn = protect_fn if protect else unprotect_fn
    ok = fn(ctypes.addressof(src), "LaZoo" if protect else None, None, None, None, 0x1, ctypes.addressof(out))  # UI_FORBIDDEN
    if not ok or not out.pbData:
        raise OSError("DPAPI no pudo con la clave")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        local_free(out.pbData)


_WRITE_LOCK = threading.Lock()  # 0.57: dos guardados a la vez daban PermissionError en Windows


def _write_private(path: Path, data: bytes) -> None:
    with _WRITE_LOCK:
        _write_private_now(path, data)


def _write_private_now(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(data)
    if sys.platform != "win32":
        os.chmod(tmp, 0o600)
    for intento in range(5):  # Windows: un antivirus o un lector puede tener el archivo abierto un instante
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if intento == 4:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            time.sleep(0.05 * (intento + 1))


class Store:
    def __init__(self, folder: Path | None = None) -> None:
        self.folder = Path(folder) if folder else data_dir()

    # Ajuste
    def _list(self) -> dict:
        try:
            raw = json.loads((self.folder / LIST_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        return raw if isinstance(raw, dict) else {}

    def enabled(self) -> bool:
        return bool(self._list().get("recordar", DEFAULT_ON))

    def devices(self) -> list[dict]:
        rows = self._list().get("dispositivos") or []
        return [r for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str)][:100]

    def _save_list(self, on: bool, devices: list[dict]) -> None:
        clean = [{k: str(r.get(k, ""))[:80] for k in ("id", "label", "fp", "fecha")} for r in devices][:100]
        _write_private(self.folder / LIST_FILE, json.dumps({"recordar": on, "dispositivos": clean}, ensure_ascii=False, indent=1).encode())

    # Clave
    def _local_key(self) -> bytes:
        path = self.folder / LOCAL_FILE
        try:
            key = path.read_bytes()
            if len(key) == 32:
                return key
        except OSError:
            pass
        key = secrets.token_bytes(32)
        _write_private(path, key)
        return key

    def _protect(self, key: bytes) -> bytes:
        if sys.platform == "win32":
            return b"DPAPI" + _dpapi(key, True)
        return protocol.seal(key, self._local_key())

    def _unprotect(self, blob: bytes) -> bytes:
        if blob.startswith(b"DPAPI"):
            return _dpapi(blob[5:], False)
        return protocol.open_sealed(blob, self._local_key())

    def save(self, key: bytes, devices: list[dict]) -> None:
        """Guarda clave y lista (solo si «Recordar» está activo)."""
        if not self.enabled():
            return
        _write_private(self.folder / KEY_FILE, self._protect(KEY_TAG + key))
        self._save_list(True, devices)

    def load(self) -> tuple[bytes | None, list[dict]] | None:
        """(clave, aprobados), o None si no hay nada recordado.

        0.62: una clave de 0.54-0.61 (sin `KEY_TAG`) la tenían los móviles: se devuelve
        `(None, aprobados)` para que el PC haga una clave nueva y conserve la lista."""
        if not self.enabled():
            return None
        try:
            key = self._unprotect((self.folder / KEY_FILE).read_bytes())
        except Exception:  # 0.57: DPAPI/ctypes, archivo dañado... sin clave recordada, nunca un cierre
            return None
        if len(key) == 32:
            return None, self.devices()
        if len(key) != 36 or not key.startswith(KEY_TAG):
            return None
        return key[4:], self.devices()

    def set_enabled(self, on: bool, key: bytes | None = None, devices: list[dict] | None = None) -> None:
        if on:
            self._save_list(True, devices or [])
            if key is not None:
                self.save(key, devices or [])
        else:
            self.forget(keep_setting=True)

    def forget(self, keep_setting: bool = False) -> None:
        """Borra la clave guardada y la lista. Con `keep_setting`, «Recordar» queda apagado."""
        on = self.enabled() if not keep_setting else False
        for name in (KEY_FILE, LOCAL_FILE):
            try:
                (self.folder / name).unlink()
            except OSError:
                pass
        self._save_list(on, [])


def today() -> str:
    return time.strftime("%Y-%m-%d %H:%M")
