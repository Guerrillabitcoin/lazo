"""«Sobre LaZoo»: datos de la app, enlaces y huecos de donación en Bitcoin.

Todo sale de `about.json` (opcional, junto a lazo.py). Nada se consulta en internet
salvo cuando el usuario pulsa «Buscar actualización»: entonces el PC pide una sola vez
el VERSION.txt de la rama main en GitHub, sin cookies.
"""

from __future__ import annotations

import json
import re
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

REPO = "https://github.com/Guerrillabitcoin/lazo"
MAIN_VERSION_URL = "https://raw.githubusercontent.com/Guerrillabitcoin/lazo/main/VERSION.txt"
# La 0.31 de main aún no tiene VERSION.txt: entonces se lee la línea VERSION de lazo.py.
MAIN_LAZO_URL = "https://raw.githubusercontent.com/Guerrillabitcoin/lazo/main/lazo.py"
_PY_VER_RE = re.compile(r'^VERSION = "(\d{1,4}\.\d{1,4})"', re.M)
AUTHOR = "GUERRILLA"
LICENSE = "MIT"
LINK_FIELDS = ("repo", "web", "x", "nostr", "contacto")
LINK_LABELS = {"repo": "Código (GitHub)", "web": "Web", "x": "X", "nostr": "Nostr", "contacto": "Contacto"}

_URL_RE = re.compile(r"^https?://[^\s<>\"'`\\]{3,300}$", re.I)
_VER_RE = re.compile(r"^\d{1,4}\.\d{1,4}$")
_DONATE = {
    "lightning": re.compile(r"^(?:[a-z0-9._+-]{1,64}@[a-z0-9-]+(?:\.[a-z0-9-]+)+|lnurl1[02-9ac-hj-np-z]{20,1000})$", re.I),
    "bolt12": re.compile(r"^lno1[02-9ac-hj-np-z]{20,2000}$", re.I),
    "silent_payment": re.compile(r"^sp1q[02-9ac-hj-np-z]{100,120}$", re.I),
    "onchain": re.compile(
        r"^(?:bc1[02-9ac-hj-np-z]{11,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34}"
        r"|(?:wpkh|tr|sh|wsh)\([0-9A-Za-z\[\]/'h*(),]{20,400}\)(?:#[0-9a-z]{8})?)$"
    ),
}
DONATE_LABELS = {
    "lightning": "Lightning",
    "bolt12": "Lightning (BOLT12)",
    "silent_payment": "On-chain · pagos silenciosos",
    "onchain": "On-chain",
}


def clean_url(value: Any) -> str:
    text = str(value or "").strip() if isinstance(value, str) else ""
    return text if _URL_RE.match(text) else ""


def clean_donation(kind: str, value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return text if kind in _DONATE and _DONATE[kind].match(text) else ""


def load_config(root: Path) -> dict[str, Any]:
    try:
        raw = json.loads((root / "about.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    links: list[dict[str, str]] = []
    for field in LINK_FIELDS:
        url = clean_url(raw.get(field)) or (REPO if field == "repo" else "")
        if url:
            links.append({"label": LINK_LABELS[field], "url": url})
    others = raw.get("otros")
    for item in others if isinstance(others, list) else []:
        if not isinstance(item, dict):
            continue
        url = clean_url(item.get("url"))
        label = str(item.get("etiqueta") or "").strip()[:40] if isinstance(item.get("etiqueta"), str) else ""
        if url:
            links.append({"label": label or url, "url": url})
    del links[12:]
    donations = []
    for kind in _DONATE:
        value = clean_donation(kind, raw.get(kind))
        if value:
            donations.append({"kind": kind, "label": DONATE_LABELS[kind], "value": value})
    return {"links": links, "donations": donations}


def about(root: Path, version: str, qr: Callable[[str], str] | None = None) -> dict[str, Any]:
    data = load_config(root)
    for item in data["donations"]:
        try:
            item["qr"] = qr(item["value"]) if qr else ""
        except Exception:
            item["qr"] = ""
    return {"name": "LaZoo", "version": version, "author": AUTHOR, "license": LICENSE, "repo": REPO, **data}


def parse_version(text: Any) -> tuple[int, int] | None:
    if not isinstance(text, str):
        return None
    clean = text.strip()
    if len(clean) > 10 or not _VER_RE.match(clean):
        return None
    major, minor = clean.split(".")
    return int(major), int(minor)


def compare(local: str, remote: str) -> str:
    """'nueva' si main va por delante, 'igual', 'delante' si la local es más nueva, o 'error'."""
    a, b = parse_version(local), parse_version(remote)
    if a is None or b is None:
        return "error"
    return "nueva" if b > a else "igual" if b == a else "delante"


def _get_python(url: str, cap: int = 64) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "LaZoo", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=6) as res:  # noqa: S310 (solo https fijo)
        if not res.geturl().startswith("https://"):
            raise OSError("salió de HTTPS")
        return res.read(cap)


def _get_curl(url: str, cap: int = 64) -> bytes:
    # Igual que Descargatodo: en Windows, curl.exe usa el almacén de certificados del sistema.
    from descargas import _run_kwargs

    out = subprocess.run(
        [shutil.which("curl") or "curl", "-fsSL", "--proto", "=https", "--proto-redir", "=https",
         "--max-time", "8", "--max-filesize", str(max(cap, 1024) * 16), "-A", "LaZoo", url],
        capture_output=True, timeout=12, **_run_kwargs(),
    )
    if out.returncode != 0:
        raise OSError("curl falló")
    return out.stdout[:cap]


def _get(url: str, cap: int) -> bytes:
    try:
        return _get_python(url, cap)
    except urllib.error.HTTPError:
        raise
    except urllib.error.URLError as exc:
        if not isinstance(exc.reason, ssl.SSLError) or not shutil.which("curl"):
            raise
        return _get_curl(url, cap)


def fetch_main_version(fetch: Callable[[str, int], bytes] | None = None) -> str:
    get = fetch or _get
    try:
        text = get(MAIN_VERSION_URL, 64).decode("utf-8", "replace").strip()
        if parse_version(text):
            return text
    except Exception:
        pass
    head = get(MAIN_LAZO_URL, 4096).decode("utf-8", "replace")
    match = _PY_VER_RE.search(head)
    return match.group(1) if match else ""


def check_update(local: str, fetch: Callable[[str, int], bytes] | None = None) -> dict[str, Any]:
    try:
        remote = fetch_main_version(fetch)
    except Exception:
        remote = ""
    state = compare(local, remote)
    messages = {
        "nueva": f"Hay una versión nueva ({remote}) en main",
        "igual": "Estás al día",
        "delante": f"Estás al día: tu versión es más nueva que la de main ({remote})",
        "error": "No se pudo comprobar",
    }
    return {"state": state, "local": local, "main": remote if state != "error" else "", "message": messages[state], "url": REPO}
