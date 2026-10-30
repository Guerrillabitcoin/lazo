"""Qué suena en el PC: título, play/pausa y posición, sin tocar las teclas.

Windows: las sesiones multimedia del sistema (las mismas del panel de volumen),
leídas por un PowerShell que solo lee y se apaga si nadie pregunta en 60 s.
Linux: playerctl (MPRIS). macOS: sin datos, la interfaz usa su estado propio.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

SYSTEM = platform.system()
SCRIPT = Path(__file__).resolve().parent / "medios.ps1"
BROWSERS = ("chrome", "msedge", "firefox", "brave", "opera", "vivaldi", "chromium", "edge")
IDLE = 60


class _Watch:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.rows: list[dict[str, Any]] = []
        self.at = 0.0
        self.asked = 0.0
        self.broken = False

    def get(self) -> list[dict[str, Any]] | None:
        """Sesiones recientes o None si en este PC no se puede saber."""
        self.asked = time.time()
        if SYSTEM == "Windows":
            return self._windows()
        if SYSTEM == "Linux":
            return self._linux()
        return None

    # --- Windows ---
    def _windows(self) -> list[dict[str, Any]] | None:
        if self.broken or not SCRIPT.is_file():
            return None
        with self.lock:
            if not self.proc or self.proc.poll() is not None:
                try:
                    self.proc = subprocess.Popen(
                        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                         "-File", str(SCRIPT), "-Parent", str(os.getpid())],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                        text=True, encoding="utf-8", errors="replace",
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except OSError:
                    self.broken = True
                    return None
                threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
                threading.Thread(target=self._reaper, args=(self.proc,), daemon=True).start()
        # La primera lectura tarda ~1-2 s; no bloquees más que eso.
        end = time.time() + 2.5
        while not self.at and time.time() < end and not self.broken:
            time.sleep(0.1)
        if time.time() - self.at > 6:
            return None
        return list(self.rows)

    def _read(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if "error" in data:
                self.broken = True
                return
            rows = data.get("sessions") or []
            if isinstance(rows, dict):
                rows = [rows]
            self.rows = [r for r in rows if isinstance(r, dict)]
            self.at = time.time()

    def _reaper(self, proc: subprocess.Popen) -> None:
        while proc.poll() is None:
            time.sleep(5)
            if time.time() - self.asked > IDLE:
                try:
                    proc.kill()
                except OSError:
                    pass
                self.at = 0.0
                return

    # --- Linux ---
    def _linux(self) -> list[dict[str, Any]] | None:
        if not shutil.which("playerctl"):
            return None
        if time.time() - self.at < 1.0:
            return list(self.rows)
        rows = []
        try:
            out = subprocess.run(["playerctl", "-a", "metadata", "--format",
                                  "{{playerName}}\t{{status}}\t{{position}}\t{{mpris:length}}\t{{artist}}\t{{title}}"],
                                 capture_output=True, text=True, timeout=3)
            for line in out.stdout.splitlines():
                parts = (line.split("\t") + [""] * 6)[:6]
                if not parts[0]:
                    continue
                rows.append({
                    "app": parts[0], "status": parts[1], "artist": parts[4], "title": parts[5],
                    "pos": _num(parts[2]) / 1e6, "len": _num(parts[3]) / 1e6,
                })
        except (OSError, subprocess.SubprocessError):
            return None
        self.rows, self.at = rows, time.time()
        return rows


def _num(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return 0.0


WATCH = _Watch()


def browser_session(window_title: str = "") -> dict[str, Any] | None:
    rows = WATCH.get()
    if not rows:
        return None
    mine = [r for r in rows if any(b in str(r.get("app", "")).lower() for b in BROWSERS)]
    low = window_title.lower()
    for row in mine:
        title = str(row.get("title") or "").lower()
        if title and title in low:
            return row
    return mine[0] if len(mine) == 1 else None


def spotify_session() -> dict[str, Any] | None:
    rows = WATCH.get()
    if not rows:
        return None
    return next((r for r in rows if "spotify" in str(r.get("app", "")).lower()), None)


def summary(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    status = str(row.get("status") or "").lower()
    return {
        "playing": True if status == "playing" else False if status in ("paused", "stopped") else None,
        "pos": round(float(row.get("pos") or 0), 1),
        "len": round(float(row.get("len") or 0), 1),
        "media_title": str(row.get("title") or "")[:180],
        "artist": str(row.get("artist") or "")[:80],
    }
