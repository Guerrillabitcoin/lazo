"""Descargatodo: baja vídeo o audio de YouTube, Instagram, TikTok, X y casi cualquier web.

Todo ocurre en este PC con yt-dlp (y ffmpeg para juntar vídeo y audio o sacar MP3).
LaZoo no los incluye: los busca en la carpeta `herramientas/` o en el PATH y, si faltan,
los baja del sitio oficial por HTTPS comprobando su huella SHA-256. Nunca usa un shell:
la orden es una lista y el enlace va detrás de `--`. Sin cookies del navegador.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import control

SYSTEM = platform.system()
ROOT = Path(__file__).resolve().parent
TOOLS_DIR = ROOT / "herramientas"
OUT_DIR = Path.home() / "Downloads" / "LaZoo"
MAX_URL = 2048
MAX_QUEUE = 10
SEND_CAP = 400 * 1024 * 1024
NOTICE = "Solo para uso personal. Respeta los derechos de autor y las normas de cada web."
TEMPLATE = "%(title).150B [%(id)s].%(ext)s"
PROGRESS = "download:LZP %(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s"

YTDLP_BASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
FFMPEG_BASE = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
FFMPEG_ZIP = "ffmpeg-master-latest-win64-gpl.zip"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if SYSTEM == "Windows" else 0
EXE = ".exe" if SYSTEM == "Windows" else ""


class DlError(control.ControlError):
    pass


# --- herramientas -------------------------------------------------------------

def ytdlp_asset() -> str:
    if SYSTEM == "Windows":
        return "yt-dlp.exe"
    if SYSTEM == "Darwin":
        return "yt-dlp_macos"
    if platform.machine().lower() in ("x86_64", "amd64"):
        return "yt-dlp_linux"
    if platform.machine().lower() in ("aarch64", "arm64"):
        return "yt-dlp_linux_aarch64"
    return "yt-dlp"


def _local(name: str) -> Path:
    return TOOLS_DIR / (name + EXE)


def find_ytdlp() -> list[str] | None:
    """Orden para lanzar yt-dlp como lista, o None si no está."""
    local = _local("yt-dlp")
    if local.is_file():
        return [str(local)]
    found = shutil.which("yt-dlp")
    return [found] if found else None


def find_ffmpeg() -> str | None:
    local = _local("ffmpeg")
    if local.is_file():
        return str(local)
    return shutil.which("ffmpeg")


def ytdlp_cmd() -> list[str]:
    cmd = find_ytdlp()
    if not cmd:
        raise DlError("Falta yt-dlp: pulsa «Instalar herramientas»")
    return cmd


def _run_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL}
    if NO_WINDOW:
        kwargs["creationflags"] = NO_WINDOW
    return kwargs


def ffmpeg_hint() -> str:
    if SYSTEM == "Windows":
        return ""
    if SYSTEM == "Darwin":
        return "Instala ffmpeg con: brew install ffmpeg"
    return "Instala ffmpeg con el gestor del sistema, por ejemplo: sudo apt install ffmpeg"


INSTALL = {"state": "", "what": "", "done": 0, "total": 0, "error": ""}
_INSTALL_LOCK = threading.Lock()


def tools_status() -> dict[str, Any]:
    yt = find_ytdlp()
    ff = find_ffmpeg()
    version = ""
    if yt:
        try:
            out = subprocess.run([*yt, "--version"], capture_output=True, text=True, timeout=20, **_run_kwargs())
            version = (out.stdout or "").strip().splitlines()[0][:40] if out.stdout else ""
        except (OSError, subprocess.SubprocessError, IndexError):
            version = ""
    return {
        "ytdlp": bool(yt),
        "ytdlp_local": bool(yt) and yt[0] == str(_local("yt-dlp")),
        "version": version,
        "ffmpeg": bool(ff),
        "ffmpeg_can_install": SYSTEM == "Windows",
        "ffmpeg_hint": "" if ff else ffmpeg_hint(),
        "install": dict(INSTALL),
        "folder": str(QUEUE.out_dir),
        "notice": NOTICE,
    }


def _fetch(url: str, cap: int, what: str) -> bytes:
    if not url.startswith("https://"):
        raise DlError("solo se descarga por HTTPS")
    try:
        return _fetch_python(url, cap, what)
    except urllib.error.URLError as exc:
        # Python en Windows solo ve las raíces que el sistema ya cargó; curl.exe usa el
        # almacén de Windows completo. Sigue siendo HTTPS y la huella se comprueba igual.
        if not isinstance(exc.reason, ssl.SSLError) or not shutil.which("curl"):
            raise
        return _fetch_curl(url, cap, what)


def _fetch_curl(url: str, cap: int, what: str) -> bytes:
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    temp = TOOLS_DIR / ".bajando"
    temp.unlink(missing_ok=True)
    cmd = [shutil.which("curl") or "curl", "-fsSL", "--proto", "=https", "--proto-redir", "=https",
           "--max-filesize", str(cap), "--max-time", "900", "-A", "LaZoo", "-o", str(temp), url]
    INSTALL.update(what=what, done=0, total=0)
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **_run_kwargs())
    while proc.poll() is None:
        time.sleep(0.5)
        try:
            INSTALL["done"] = temp.stat().st_size
        except OSError:
            pass
    try:
        if proc.returncode != 0 or not temp.is_file():
            raise DlError(f"{what}: no se pudo descargar")
        data = temp.read_bytes()
    finally:
        temp.unlink(missing_ok=True)
    if len(data) > cap:
        raise DlError(f"{what}: demasiado grande")
    INSTALL["done"] = len(data)
    return data


def _fetch_python(url: str, cap: int, what: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "LaZoo"})
    with urllib.request.urlopen(req, timeout=60) as res:  # noqa: S310 (solo https)
        if not res.geturl().startswith("https://"):
            raise DlError("la descarga salió de HTTPS")
        total = int(res.headers.get("Content-Length") or 0)
        if total > cap:
            raise DlError(f"{what}: tamaño raro ({total} bytes)")
        INSTALL.update(what=what, done=0, total=total)
        buf = io.BytesIO()
        while True:
            chunk = res.read(256 * 1024)
            if not chunk:
                break
            buf.write(chunk)
            INSTALL["done"] = buf.tell()
            if buf.tell() > cap:
                raise DlError(f"{what}: demasiado grande")
    return buf.getvalue()


def _sha_from_sums(text: str, name: str) -> str:
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == name and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    raise DlError("no encontré la huella oficial de " + name)


def _install_ytdlp() -> None:
    asset = ytdlp_asset()
    sums = _fetch(YTDLP_BASE + "SHA2-256SUMS", 1024 * 1024, "huellas de yt-dlp").decode("utf-8", "replace")
    want = _sha_from_sums(sums, asset)
    data = _fetch(YTDLP_BASE + asset, 80 * 1024 * 1024, "yt-dlp")
    if len(data) < 1024 * 1024:
        raise DlError("yt-dlp: archivo demasiado pequeño")
    if hashlib.sha256(data).hexdigest() != want:
        raise DlError("yt-dlp: la huella no coincide, no lo instalo")
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    target = _local("yt-dlp")
    temp = target.with_suffix(target.suffix + ".part")
    temp.write_bytes(data)
    if SYSTEM != "Windows":
        temp.chmod(0o755)
    os.replace(temp, target)


def _install_ffmpeg() -> None:
    if SYSTEM != "Windows":
        raise DlError(ffmpeg_hint())
    sums = _fetch(FFMPEG_BASE + "checksums.sha256", 1024 * 1024, "huellas de ffmpeg").decode("utf-8", "replace")
    want = _sha_from_sums(sums, FFMPEG_ZIP)
    data = _fetch(FFMPEG_BASE + FFMPEG_ZIP, 400 * 1024 * 1024, "ffmpeg")
    if hashlib.sha256(data).hexdigest() != want:
        raise DlError("ffmpeg: la huella no coincide, no lo instalo")
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.namelist():
            base = member.rsplit("/", 1)[-1]
            if base in ("ffmpeg.exe", "ffprobe.exe") and "/bin/" in member:
                (TOOLS_DIR / base).write_bytes(zf.read(member))
    if not _local("ffmpeg").is_file():
        raise DlError("ffmpeg: el zip no traía ffmpeg.exe")


def install(what: str = "all") -> dict[str, Any]:
    if what not in ("all", "ytdlp", "ffmpeg"):
        raise DlError("¿instalar qué?")
    if not _INSTALL_LOCK.acquire(blocking=False):
        raise DlError("Ya se está instalando")

    def work() -> None:
        try:
            INSTALL.update(state="instalando", error="", done=0, total=0)
            if what in ("all", "ytdlp"):
                _install_ytdlp()
            if what == "ffmpeg" or (what == "all" and SYSTEM == "Windows" and not find_ffmpeg()):
                _install_ffmpeg()
            INSTALL.update(state="hecho", what="")
        except Exception as exc:  # noqa: BLE001 (se muestra al usuario)
            INSTALL.update(state="error", error=str(exc)[:200] or "No se pudo instalar")
        finally:
            _INSTALL_LOCK.release()

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "detail": "Instalando herramientas…"}


def update() -> dict[str, Any]:
    yt = find_ytdlp()
    if not yt or yt[0] == str(_local("yt-dlp")):
        return install("ytdlp")
    try:
        out = subprocess.run([*yt, "-U"], capture_output=True, text=True, timeout=180, **_run_kwargs())
    except (OSError, subprocess.SubprocessError) as exc:
        raise DlError("No se pudo actualizar") from exc
    last = ((out.stdout or "") + (out.stderr or "")).strip().splitlines()
    return {"ok": out.returncode == 0, "detail": (last[-1] if last else "Hecho")[:120]}


# --- enlaces y órdenes ----------------------------------------------------------

def check_url(url: Any) -> str:
    if not isinstance(url, str):
        raise DlError("Pega un enlace")
    url = url.strip()
    if not url:
        raise DlError("Pega un enlace")
    if len(url) > MAX_URL:
        raise DlError("Enlace demasiado largo")
    if not re.match(r"(?i)https?://", url):
        raise DlError("El enlace tiene que empezar por http:// o https://")
    if any(ord(ch) < 33 or ord(ch) == 127 for ch in url):
        raise DlError("El enlace tiene espacios o caracteres raros")
    parts = urlsplit(url)
    if not parts.hostname:
        raise DlError("Enlace no válido")
    return url


def info_cmd(url: str, playlist: bool = False) -> list[str]:
    url = check_url(url)
    mode = ["--yes-playlist", "--flat-playlist"] if playlist else ["--no-playlist"]
    return [*ytdlp_cmd(), "--ignore-config", "-J", *mode, "--no-warnings", "--", url]


SIMPLE = ("best", "1080", "720", "480", "mp3", "audio")
_FMT_ID = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]{0,47}")


def selector(choice: str, ffmpeg: bool) -> tuple[list[str], str]:
    """Opciones de yt-dlp para una elección. Devuelve (argumentos, etiqueta)."""
    if choice == "best":
        return (["-f", "bv*+ba/b"] if ffmpeg else ["-f", "b"]), "Mejor calidad"
    if choice in ("1080", "720", "480"):
        h = choice
        sel = f"bv*[height<={h}]+ba/b[height<={h}]/b" if ffmpeg else f"b[height<={h}]/b"
        return ["-f", sel], f"{h}p"
    if choice == "mp3":
        if not ffmpeg:
            raise DlError("Para MP3 hace falta ffmpeg")
        return ["-f", "ba/b", "-x", "--audio-format", "mp3", "--audio-quality", "0"], "Audio MP3"
    if choice == "audio":
        return ["-f", "ba[ext=m4a]/ba/b"], "Audio original"
    if choice.startswith("f:"):
        fid = choice[2:]
        ids = fid.split("+")
        if not 1 <= len(ids) <= 2 or not all(_FMT_ID.fullmatch(part) for part in ids):
            raise DlError("Formato no válido")
        if len(ids) == 2 and not ffmpeg:
            raise DlError("Juntar vídeo y audio necesita ffmpeg")
        return ["-f", fid], "Formato " + fid
    raise DlError("Formato no válido")


def download_cmd(url: str, choice: str, out_dir: Path, ffmpeg: str | None = None, playlist: bool = False) -> list[str]:
    url = check_url(url)
    sel, _label = selector(choice, bool(ffmpeg))
    cmd = [
        *ytdlp_cmd(), "--ignore-config", "--newline", "--no-mtime",
        "--windows-filenames",
        "--yes-playlist" if playlist else "--no-playlist",
        "--progress-template", PROGRESS,
        "--print", "after_move:LZF %(filepath)s",
        "-P", str(out_dir), "-o", template_for(choice),
        *sel,
    ]
    if ffmpeg and Path(ffmpeg).parent == TOOLS_DIR:
        cmd += ["--ffmpeg-location", str(TOOLS_DIR)]
    return [*cmd, "--", url]


def template_for(choice: str) -> str:
    """Cada elección con su nombre: así sacar el MP3 no borra el vídeo del mismo enlace."""
    tag = {"best": "", "mp3": " audio", "audio": " audio"}.get(choice)
    if tag is None:
        tag = f" {choice}p" if choice.isdigit() else " f" + re.sub(r"[^A-Za-z0-9]", "-", choice[2:])[:20]
    return TEMPLATE.replace(" [%(id)s]", " [%(id)s]" + tag)


def _size(fmt: dict) -> int:
    return int(fmt.get("filesize") or fmt.get("filesize_approx") or 0)


def parse_info(data: dict) -> dict[str, Any]:
    """Resume la salida de `yt-dlp -J` en opciones sencillas y una lista avanzada."""
    if data.get("_type") == "playlist":
        entries = [e for e in (data.get("entries") or []) if isinstance(e, dict)]
        return {
            "title": str(data.get("title") or "Lista")[:200],
            "playlist": True,
            "count": len(entries),
            "duration": 0,
            "uploader": str(data.get("uploader") or "")[:80],
            "thumbnail": "",
            "choices": [{"id": c, "label": label} for c, label in (
                ("best", "Mejor calidad (vídeo+audio)"), ("720", "720p"), ("mp3", "Solo audio MP3"), ("audio", "Solo audio original"))],
            "formats": [],
        }
    formats = [f for f in (data.get("formats") or []) if isinstance(f, dict) and f.get("format_id")]
    heights = sorted({int(f.get("height") or 0) for f in formats if f.get("vcodec") != "none" and f.get("height")})
    top = heights[-1] if heights else 0
    has_audio = any((f.get("acodec") or "none") != "none" for f in formats) or not formats
    choices = [{"id": "best", "label": "Mejor calidad (vídeo+audio)", "detail": f"{top}p" if top else ""}]
    for h in (1080, 720, 480):
        if top >= h:
            choices.append({"id": str(h), "label": f"{h}p", "detail": ""})
    if has_audio:
        choices.append({"id": "mp3", "label": "Solo audio MP3", "detail": "", "ffmpeg": True})
        choices.append({"id": "audio", "label": "Solo audio original (m4a/opus)", "detail": ""})
    advanced = []
    for f in formats:
        vcodec = f.get("vcodec") or ("?" if f.get("height") else "none")
        acodec = f.get("acodec") or ("?" if f.get("height") else "none")
        if vcodec == "none" and acodec == "none" and f.get("ext") in ("mhtml",):
            continue
        kind = "vídeo+audio" if vcodec != "none" and acodec != "none" else "solo vídeo" if vcodec != "none" else "solo audio" if acodec != "none" else "?"
        res = f"{f.get('height')}p" if f.get("height") else (f.get("resolution") or "")
        advanced.append({
            "id": str(f["format_id"])[:48],
            "res": str(res)[:20],
            "ext": str(f.get("ext") or "")[:8],
            "kind": kind,
            "size": _size(f),
            "note": str(f.get("format_note") or "")[:30],
        })
    return {
        "title": str(data.get("title") or "Sin título")[:200],
        "playlist": False,
        "duration": int(data.get("duration") or 0),
        "uploader": str(data.get("uploader") or data.get("channel") or "")[:80],
        "thumbnail": str(data.get("thumbnail") or "")[:600] if str(data.get("thumbnail") or "").startswith("https://") else "",
        "choices": choices,
        "formats": advanced[-60:],
    }


_INFO_LOCK = threading.Lock()


def get_info(url: str, playlist: bool = False) -> dict[str, Any]:
    cmd = info_cmd(url, playlist)
    if not _INFO_LOCK.acquire(blocking=False):
        raise DlError("Ya estoy buscando otro enlace")
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, **_run_kwargs())
    except subprocess.TimeoutExpired as exc:
        raise DlError("La web tardó demasiado") from exc
    except OSError as exc:
        raise DlError("No pude abrir yt-dlp") from exc
    finally:
        _INFO_LOCK.release()
    if out.returncode != 0:
        raise DlError(_clean_error(out.stderr))
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError as exc:
        raise DlError("yt-dlp no devolvió datos") from exc
    result = parse_info(data)
    result["ffmpeg"] = bool(find_ffmpeg())
    return result


def _clean_error(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    errors = [ln for ln in lines if ln.startswith("ERROR")]
    msg = (errors or lines or ["No se pudo leer ese enlace"])[-1]
    msg = re.sub(r"^ERROR:\s*", "", msg)
    return msg[:180]


def safe_output(path: str, out_dir: Path) -> Path | None:
    """Acepta solo archivos que quedaron dentro de la carpeta de descargas."""
    try:
        target = Path(path.strip()).resolve()
        base = out_dir.resolve()
    except (OSError, ValueError):
        return None
    if base not in target.parents or not target.is_file():
        return None
    return target


# --- cola ---------------------------------------------------------------------------

def _num(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return 0.0


class Queue:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []
        self.procs: dict[str, subprocess.Popen] = {}
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.counter = 0
        self.worker: threading.Thread | None = None
        self.out_dir = OUT_DIR

    def start(self, url: str, choice: str, title: str = "", playlist: bool = False) -> dict[str, Any]:
        url = check_url(url)
        ffmpeg = find_ffmpeg()
        _sel, label = selector(str(choice), bool(ffmpeg))
        ytdlp_cmd()
        with self.lock:
            waiting = [j for j in self.jobs if j["state"] in ("en cola", "descargando", "procesando")]
            if len(waiting) >= MAX_QUEUE:
                raise DlError("La cola está llena")
            self.counter += 1
            job = {
                "id": f"{int(time.time())}{self.counter:03d}",
                "url": url, "choice": str(choice), "label": label, "playlist": bool(playlist),
                "title": str(title or url)[:200], "state": "en cola", "pct": 0.0, "speed": 0.0,
                "eta": 0, "name": "", "size": 0, "error": "", "at": time.time(),
            }
            self.jobs.insert(0, job)
            del self.jobs[30:]
        self._ensure_worker()
        self.wake.set()
        return {"ok": True, "detail": "En cola: " + job["title"][:40], "job": self.public(job)}

    def public(self, job: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in job.items() if k not in ("url", "path")}

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {"jobs": [self.public(j) for j in self.jobs], "folder": str(self.out_dir), "notice": NOTICE, "install": dict(INSTALL)}

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = next((j for j in self.jobs if j["id"] == job_id), None)
            if not job:
                raise DlError("Esa descarga ya no está")
            if job["state"] in ("en cola", "descargando", "procesando"):
                job["state"] = "cancelada"
            proc = self.procs.get(job_id)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
        return {"ok": True, "detail": "Cancelada"}

    def file(self, job_id: str) -> Path:
        with self.lock:
            job = next((j for j in self.jobs if j["id"] == job_id), None)
        if not job or job["state"] != "hecha" or not job.get("path"):
            raise DlError("Ese archivo no está listo")
        path = safe_output(job["path"], self.out_dir)
        if not path:
            raise DlError("Ese archivo ya no está")
        return path

    def _ensure_worker(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.worker = threading.Thread(target=self._loop, daemon=True)
        self.worker.start()

    def _next(self) -> dict[str, Any] | None:
        with self.lock:
            for job in reversed(self.jobs):
                if job["state"] == "en cola":
                    job["state"] = "descargando"
                    return job
        return None

    def _loop(self) -> None:
        while True:
            job = self._next()
            if not job:
                self.wake.clear()
                if not self.wake.wait(30):
                    return
                continue
            try:
                self._run(job)
            except Exception as exc:  # noqa: BLE001
                job["state"] = "error"
                job["error"] = str(exc)[:180] or "No se pudo"

    def _run(self, job: dict[str, Any]) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        cmd = download_cmd(job["url"], job["choice"], self.out_dir, find_ffmpeg(), job["playlist"])
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", bufsize=1, **_run_kwargs(),
        )
        with self.lock:
            self.procs[job["id"]] = proc
            if job["state"] == "cancelada":
                proc.terminate()
        tail: list[str] = []
        files: list[Path] = []
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\r\n")
            if line.startswith("LZP "):
                got, total, guess, speed, eta = (line[4:].split("|") + ["", "", "", "", ""])[:5]
                full = _num(total) or _num(guess)
                if full:
                    job["pct"] = round(min(100.0, _num(got) * 100 / full), 1)
                job["speed"] = _num(speed)
                job["eta"] = int(_num(eta))
            elif line.startswith("LZF "):
                found = safe_output(line[4:], self.out_dir)
                if found:
                    files.append(found)
            elif "[Merger]" in line or "[ExtractAudio]" in line or "[VideoConvertor]" in line:
                job["state"] = "procesando" if job["state"] != "cancelada" else job["state"]
            elif line.strip():
                tail.append(line)
                del tail[:-8]
        code = proc.wait()
        with self.lock:
            self.procs.pop(job["id"], None)
        if job["state"] == "cancelada":
            return
        if code != 0 or not files:
            job["state"] = "error"
            job["error"] = _clean_error("\n".join(tail)) if code != 0 else "No salió ningún archivo"
            return
        last = files[-1]
        job.update(state="hecha", pct=100.0, path=str(last), name=last.name, size=last.stat().st_size, count=len(files))


QUEUE = Queue()


def open_folder() -> dict[str, Any]:
    QUEUE.out_dir.mkdir(parents=True, exist_ok=True)
    if SYSTEM == "Windows":
        os.startfile(QUEUE.out_dir)  # type: ignore[attr-defined]
    elif SYSTEM == "Darwin":
        subprocess.Popen(["open", str(QUEUE.out_dir)])
    else:
        subprocess.Popen(["xdg-open", str(QUEUE.out_dir)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "detail": "Carpeta abierta"}
