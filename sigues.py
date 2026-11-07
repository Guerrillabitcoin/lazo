"""LaZoo 0.59: evita que YouTube se quede en «Vídeo en pausa. ¿Quieres seguir viendo?».

YouTube pregunta si sigues ahí cuando lleva rato sin ver el teclado ni el ratón del PC.
Si manejas el PC desde el móvil y solo miras, lo pregunta aunque estés delante.

Qué hace (solo Windows): cada `INTERVALO` s, si hay una ventana de YouTube, un PowerShell
oculto mira el árbol de accesibilidad (UI Automation) de ESA ventana. Si encuentra el aviso
(«Continue watching?», «¿Quieres seguir viendo?», …) con su botón «Yes»/«Sí», lo pulsa con
InvokePattern: es una acción de accesibilidad, no un clic. No mueve el cursor, no pulsa
teclas, no trae la ventana delante, no inyecta JavaScript y no sale a internet.

Se apaga en el Panel o en el móvil («Evitar el aviso ‘¿Sigues ahí?’ de YouTube»), con
`--sin-sigues` o con `LAZO_SIN_SIGUES=1`. El ajuste se guarda en `ajustes.json`.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

INTERVALO = 15.0
TIEMPO_MAX = 12.0
DEFAULT_ON = True

# Textos del aviso (minúsculas, sin depender de signos). Varios idiomas de YouTube.
AVISO = [
    "continue watching", "still watching", "seguir viendo", "continuar viendo", "sigues ahí",
    "sigues ahi", "continuer à regarder", "continuer la lecture", "weiterschauen", "weiter ansehen",
    "continuare a guardare", "continuar a assistir", "continuar assistindo", "doorgaan met kijken",
]
SI = ["yes", "sí", "si", "oui", "ja", "sì", "sim"]

_AVISO_RE = re.compile("|".join(re.escape(t) for t in AVISO), re.IGNORECASE)


def es_aviso(texto: str) -> bool:
    return bool(_AVISO_RE.search(texto or ""))


def es_si(nombre: str) -> bool:
    return (nombre or "").strip().strip(".!¡").lower() in SI


def ps_script() -> str:
    aviso = "|".join(re.escape(t).replace("\\ ", " ") for t in AVISO).replace("'", "''")
    si = ",".join("'" + s + "'" for s in SI)
    return r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
try { Add-Type -AssemblyName UIAutomationClient; Add-Type -AssemblyName UIAutomationTypes }
catch { '{"error":"uia"}'; exit 1 }
$aviso = '(?i)(""" + aviso + r""")'
$si = @(""" + si + r""")
$walker = [Windows.Automation.TreeWalker]::ControlViewWalker
# Guarda del foco: si al pulsar la ventana se pusiera delante, se devuelve la que estaba.
try { Add-Type -Namespace LaZoo -Name Foco -MemberDefinition '[DllImport("user32.dll")] public static extern System.IntPtr GetForegroundWindow(); [DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr h);' } catch { }
$conds = foreach ($s in $si) { New-Object Windows.Automation.PropertyCondition([Windows.Automation.AutomationElement]::NameProperty, $s, [Windows.Automation.PropertyConditionFlags]::IgnoreCase) }
$btn = New-Object Windows.Automation.OrCondition([Windows.Automation.Condition[]]$conds)
function Nivel($el) {
  # A qué altura está el texto del aviso (1 = hermano). 99 = no está cerca.
  $p = $el
  for ($i = 1; $i -le 4; $i++) {
    $p = $walker.GetParent($p)
    if (-not $p) { break }
    if ($p.Current.Name -match $aviso) { return $i }
    $kids = $p.FindAll([Windows.Automation.TreeScope]::Children, [Windows.Automation.Condition]::TrueCondition)
    if ($kids.Count -gt 60) { continue }
    foreach ($k in $kids) { if ($k.Current.Name -match $aviso) { return $i } }
  }
  return 99
}
function Buscar($win) {
  $mejor = $null; $nivel = 99
  foreach ($b in $win.FindAll([Windows.Automation.TreeScope]::Descendants, $btn)) {
    $n = ($b.Current.Name).Trim().TrimEnd('.', '!').ToLower()
    if ($si -notcontains $n) { continue }
    $lv = Nivel $b
    if ($lv -lt $nivel) { $mejor = $b; $nivel = $lv }
  }
  if ($nivel -ge 99) { return $null }
  return $mejor
}
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($line -eq $null -or $line -eq 'fin') { break }
  $out = @{ ok = $true; visto = $false; pulsado = $false; verificado = $false; ms = 0 }
  $t = [Diagnostics.Stopwatch]::StartNew()
  try {
    $win = [Windows.Automation.AutomationElement]::FromHandle([IntPtr][Int64]$line)
    $mejor = Buscar $win
    if ($mejor) {
      $out.visto = $true
      $ip = $null
      if ($mejor.TryGetCurrentPattern([Windows.Automation.InvokePattern]::Pattern, [ref]$ip)) {
        $antes = [IntPtr]::Zero
        try { $antes = [LaZoo.Foco]::GetForegroundWindow() } catch { }
        $ip.Invoke(); $out.pulsado = $true
        try {
          Start-Sleep -Milliseconds 150
          $ahora = [LaZoo.Foco]::GetForegroundWindow()
          if ($antes -ne [IntPtr]::Zero -and $ahora -ne $antes) { $out.foco = [bool][LaZoo.Foco]::SetForegroundWindow($antes) }
        } catch { }
        # 0.60: solo cuenta si el aviso ha desaparecido de verdad.
        for ($r = 0; $r -lt 4; $r++) {
          Start-Sleep -Milliseconds 400
          try { if (-not (Buscar $win)) { $out.verificado = $true; break } } catch { $out.verificado = $true; break }
        }
      }
    }
  } catch { $out.ok = $false; $out.error = $_.Exception.GetType().Name }
  $out.ms = [int]$t.ElapsedMilliseconds
  ($out | ConvertTo-Json -Compress)
}
"""


def encoded() -> str:
    return base64.b64encode(ps_script().encode("utf-16-le")).decode("ascii")


_SAVE_LOCK = threading.Lock()


def _ajustes_file() -> Path:
    import recordar

    return recordar.data_dir() / "ajustes.json"


class Sigues:
    # 0.63: lo mismo sirve para saltar anuncios (anuncios.py cambia estos valores).
    KEY = "sigues"            # interruptor en ajustes.json
    COUNT = "contador"        # contador en ajustes.json
    NAME = "lazo-sigues"      # nombre del hilo
    DEFAULT = DEFAULT_ON
    MESSAGE = "  YouTube preguntó «¿Sigues ahí?»: contestado «Sí» sin tocar el ratón."

    def interval(self) -> float:
        return INTERVALO

    def script(self) -> str:
        return encoded()

    def __init__(self, find: Callable[[], str | None] | None = None,
                 probe: Callable[[str], dict] | None = None, file: Path | None = None) -> None:
        self.lock = threading.Lock()
        self.talk = threading.Lock()  # 0.63: una pregunta al PowerShell cada vez (bucle y flecha)
        self.find = find
        self.probe = probe
        self.file = file
        self.on = self._load()
        self.disabled = False  # --sin-sigues
        self.proc: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None
        self.stop_ev = threading.Event()
        self.pulsados = 0  # esta sesión
        self.ultimo = 0.0
        self.total, self.hoy, self.dia = 0, 0, ""
        self._load_count()
        self.ultima_ms = 0
        self.error = ""
        self.revisiones = 0

    # --- ajuste -------------------------------------------------------------
    def _path(self) -> Path | None:
        if self.file is not None:
            return self.file
        try:
            return _ajustes_file()
        except Exception:  # noqa: BLE001
            return None

    def _load(self) -> bool:
        p = self._path()
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p and p.is_file() else {}
            return bool(data.get(self.KEY, self.DEFAULT))
        except Exception:  # noqa: BLE001 (archivo roto: valor por defecto)
            return self.DEFAULT

    def _load_count(self) -> None:
        p = self._path()
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p and p.is_file() else {}
            c = data.get(self.COUNT) or {}
            self.total = max(0, int(c.get("total", 0)))
            self.ultimo = float(c.get("ultimo", 0) or 0)
            self.dia = str(c.get("dia", ""))
            self.hoy = max(0, int(c.get("hoy", 0)))
        except Exception:  # noqa: BLE001
            self.total, self.hoy, self.dia = 0, 0, ""

    def _hoy(self) -> int:
        return self.hoy if self.dia == time.strftime("%Y-%m-%d") else 0

    def contar(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        dia = time.strftime("%Y-%m-%d", time.localtime(now))
        if dia != self.dia:
            self.dia, self.hoy = dia, 0
        self.total += 1
        self.hoy += 1
        self.pulsados += 1
        self.ultimo = now
        self._save()

    def reset(self) -> dict[str, Any]:
        self.total = self.hoy = self.pulsados = 0
        self.ultimo, self.dia = 0.0, ""
        self._save()
        return self.status()

    def _save(self) -> None:
        p = self._path()
        if not p:
            return
        with _SAVE_LOCK:  # 0.63: sigues y anuncios comparten ajustes.json
            self._save_now(p)

    def _save_now(self, p: Path) -> None:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if p.is_file():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except ValueError:
                    data = {}
            data[self.KEY] = self.on
            data[self.COUNT] = {"total": self.total, "hoy": self.hoy, "dia": self.dia, "ultimo": self.ultimo}
            tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            pass

    def available(self) -> bool:
        return sys.platform == "win32" or self.probe is not None

    def status(self) -> dict[str, Any]:
        return {"on": self.on and not self.disabled, "available": self.available(), "disabled": self.disabled,
                "pulsados": self.pulsados, "ultimo": self.ultimo,
                "total": self.total, "hoy": self._hoy(), "sesion": self.pulsados, "ultima_ms": self.ultima_ms,
                "revisiones": self.revisiones, "error": self.error, "intervalo_s": self.interval()}

    def set_on(self, on: object, reset: bool = False) -> dict[str, Any]:
        if reset:
            self.reset()
        if on is not None:
            self.on = bool(on)
            self._save()
            if self.on:
                self.start()
            else:
                self._close()
        return self.status()

    # --- vigilancia ---------------------------------------------------------
    def check_once(self) -> dict[str, Any]:
        """Una revisión. Devuelve lo que vio (para pruebas y el bucle)."""
        if not (self.on and not self.disabled):
            return {"skip": "apagado"}
        hwnd = self.find() if self.find else None
        if not hwnd:
            return {"skip": "sin youtube"}
        res = (self.probe or self._probe_ps)(str(hwnd))
        self.revisiones += 1
        self.ultima_ms = int(res.get("ms", 0) or 0)
        self.error = str(res.get("error", "")) if not res.get("ok", True) else ""
        if res.get("pulsado") and res.get("verificado"):
            self.contar()
            try:
                print(self.MESSAGE, flush=True)
            except Exception:  # noqa: BLE001 (sin consola o consola cp1252)
                pass
        return res

    def _probe_ps(self, hwnd: str) -> dict:
        with self.talk:
            return self._probe_ps_now(hwnd)

    def _probe_ps_now(self, hwnd: str) -> dict:
        with self.lock:
            if not self.proc or self.proc.poll() is not None:
                self.proc = subprocess.Popen(
                    ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                     "-EncodedCommand", self.script()],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            proc = self.proc
        assert proc.stdin and proc.stdout
        box: dict = {}

        def read() -> None:
            box["line"] = proc.stdout.readline()

        proc.stdin.write(hwnd + "\n")
        proc.stdin.flush()
        t = threading.Thread(target=read, daemon=True)
        t.start()
        t.join(TIEMPO_MAX)
        if t.is_alive() or not box.get("line"):
            self._close()
            return {"ok": False, "error": "sin respuesta"}
        try:
            data = json.loads(box["line"])
        except ValueError:
            return {"ok": False, "error": "respuesta rara"}
        if "error" in data and data.get("ok") is None:
            self.disabled = True  # sin UI Automation en este Windows
        return data

    def _close(self) -> None:
        with self.lock:
            proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            try:
                proc.stdin.write("fin\n")  # type: ignore[union-attr]
                proc.stdin.flush()  # type: ignore[union-attr]
                proc.wait(2)
            except Exception:  # noqa: BLE001
                proc.kill()

    def _loop(self) -> None:
        while not self.stop_ev.wait(self.interval()):
            if not self.on:
                continue
            try:
                self.check_once()
            except Exception as exc:  # noqa: BLE001 (nunca tumbar LaZoo por esto)
                self.error = type(exc).__name__
                self._close()

    def start(self) -> bool:
        if not self.available() or self.disabled:
            return False
        if self.thread and self.thread.is_alive():
            return True
        self.stop_ev.clear()
        self.thread = threading.Thread(target=self._loop, name=self.NAME, daemon=True)
        self.thread.start()
        return True

    def stop(self) -> None:
        self.stop_ev.set()
        self._close()


def _find_youtube_hwnd() -> str | None:
    import control

    if control.SYSTEM != "Windows":
        return None
    with control._lock:
        row = control._find_youtube_unlocked()
    return str(row["id"]) if row else None


SIGUES = Sigues(find=_find_youtube_hwnd)


def watch() -> bool:
    if "unittest" in sys.modules or "pytest" in sys.modules:
        return False
    if os.environ.get("LAZO_SIN_SIGUES") == "1":
        SIGUES.disabled = True
        return False
    return SIGUES.start()
