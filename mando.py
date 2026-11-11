"""LaZoo 0.65: lo que el mando de YouTube del móvil necesita saber o pedir al PC.

Todo sin tocar la página de YouTube: ni JavaScript ni extensiones. Solo Windows; en otros
sistemas cada función devuelve «no sé» y el mando sigue como antes.

- `volumen(hwnd)`: el volumen REAL del reproductor de YouTube (0-100) y si está en silencio.
  Un PowerShell oculto lee por accesibilidad (UI Automation) el deslizador de volumen del
  propio reproductor y el nombre del botón de silencio («Silenciar (m)» / «Activar sonido (m)»).
  Solo lee: no pulsa, no mueve el cursor, no trae la ventana delante.
- `direccion(hwnd)`: la dirección de la barra del navegador (para «Seguir en el móvil»),
  igual que patrocinios.py: sin entrar en la página.
- `ir(titulo, segundos)`: lleva el vídeo a un segundo exacto pidiéndoselo a los controles
  multimedia de Windows (`TryChangePlaybackPositionAsync`, lo mismo que la barra del panel de
  volumen). Si el navegador no lo deja, control.py usa las teclas de YouTube (`plan_teclas`).

Nada de esto sale a internet. Un solo proceso PowerShell, que se abre al primer uso y se
cierra solo si nadie lo usa en `CERRAR` segundos.
"""

from __future__ import annotations

import base64
import json
import platform
import subprocess
import threading
import time
from typing import Any, Callable

TIEMPO_MAX = 6.0      # s que se espera una respuesta del PowerShell
CACHE_VOL = 3.0       # s que vale una lectura del volumen (el móvil pregunta cada 2,5 s)
VIEJO = 30.0          # s que una lectura vieja aún se enseña mientras llega la nueva
CERRAR = 120.0        # s sin uso y el PowerShell se cierra

# Nombres accesibles del reproductor de YouTube, en los idiomas más comunes.
VOLUMEN = ("volum", "lautst", "громк")              # deslizador: «Volumen», «Volume», «Lautstärke»…
SIN_SONIDO = ("activar sonido", "reactivar", "unmute", "réactiver", "attiva audio", "ton ein")


def es_silencio(nombre: str) -> bool | None:
    """Por el nombre del botón (m): «Activar sonido (m)» = está en silencio; «Silenciar (m)» = no."""
    low = (nombre or "").lower()
    if "(m)" not in low:
        return None
    return any(t in low for t in SIN_SONIDO)


def ps_script() -> str:
    import anuncios

    repro = ",".join("'" + n.replace("'", "''") + "'" for n in anuncios.REPRODUCTOR)
    vol = ",".join("'" + n + "'" for n in VOLUMEN)
    return r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
[Console]::InputEncoding = [Text.Encoding]::UTF8
try {
  Add-Type -AssemblyName UIAutomationClient
  Add-Type -AssemblyName UIAutomationTypes
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  function Espera($op, $type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    if (-not $task.Wait(3000)) { throw 'tiempo' }
    $task.Result
  }
  $mgrType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
  $propType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties, Windows.Media.Control, ContentType = WindowsRuntime]
  $mgr = Espera ($mgrType::RequestAsync()) $mgrType
} catch { '{"error":"sin UI Automation"}'; exit 1 }
$AE = [Windows.Automation.AutomationElement]
$CT = [Windows.Automation.ControlType]
$TS = [Windows.Automation.TreeScope]
$walker = [Windows.Automation.TreeWalker]::ControlViewWalker
$VOL = @(""" + vol + r""")
$repro = @(""" + repro + r""")
$condRepro = New-Object Windows.Automation.OrCondition([Windows.Automation.Condition[]]@(foreach ($n in $repro) { New-Object Windows.Automation.PropertyCondition($AE::NameProperty, $n, [Windows.Automation.PropertyConditionFlags]::IgnoreCase) }))
$barras = @{}; $deslizadores = @{}; $silencios = @{}
$edits = New-Object System.Collections.ArrayList
function Valor($e) {
  try { return [string]$e.GetCurrentPattern([Windows.Automation.ValuePattern]::Pattern).Current.Value } catch { return '' }
}
# Barra de direcciones: no entra en la página web (Document) ni en las pestañas.
function Walk($e, $d) {
  if ($d -gt 14 -or $edits.Count -ge 6) { return }
  $ch = $walker.GetFirstChild($e)
  $n = 0
  while ($ch -ne $null -and $n -lt 200) {
    $n++
    $ct = $ch.Current.ControlType
    $cls = $ch.Current.ClassName
    if ($ct -eq $CT::Document -or $ct -eq $CT::TabItem -or $cls -eq 'Chrome_RenderWidgetHostHWND' -or $cls -eq 'MozillaContentWindowClass') { }
    elseif ($ct -eq $CT::Edit) { [void]$edits.Add($ch) }
    else { Walk $ch ($d + 1) }
    $ch = $walker.GetNextSibling($ch)
  }
}
function Direccion($hwnd) {
  $e = $barras[$hwnd]
  if ($e) { $v = Valor $e; if ($v -match 'youtu') { return $v } }
  $edits.Clear()
  Walk ($AE::FromHandle([IntPtr][Int64]$hwnd)) 0
  foreach ($x in $edits) {
    $v = Valor $x
    if ($v -match 'youtu') { $barras[$hwnd] = $x; return $v }
  }
  return ''
}
function Vivo($e) { try { [void]$e.Current.Name; return $true } catch { return $false } }
# Volumen del reproductor: el deslizador «Volumen» y el botón «Silenciar (m)». Solo se leen.
function Volumen($hwnd) {
  $s = $deslizadores[$hwnd]; $b = $silencios[$hwnd]
  if (-not ($s -and (Vivo $s))) {
    $s = $null
    $win = $AE::FromHandle([IntPtr][Int64]$hwnd)
    # Solo dentro del reproductor (como anuncios.py); si no se encuentra, en toda la ventana.
    $p = $win.FindFirst($TS::Descendants, $condRepro)
    if ($p) { $win = $p }
    $todos = $win.FindAll($TS::Descendants, (New-Object Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $CT::Slider)))
    foreach ($x in $todos) {
      $n = ([string]$x.Current.Name).ToLower()
      foreach ($v in $VOL) { if ($n.Contains($v)) { $s = $x; break } }
      if ($s) { break }
    }
    $b = $null
    if ($s) {
      $botones = $win.FindAll($TS::Descendants, (New-Object Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $CT::Button)))
      foreach ($x in $botones) { if (([string]$x.Current.Name).ToLower().Contains('(m)')) { $b = $x; break } }
    }
    $deslizadores[$hwnd] = $s; $silencios[$hwnd] = $b
  }
  if (-not $s) { return @{ hay = $false } }
  $r = $s.GetCurrentPattern([Windows.Automation.RangeValuePattern]::Pattern).Current
  $nivel = [double]$r.Value
  if ([double]$r.Maximum -gt 0 -and [double]$r.Maximum -ne 100) { $nivel = $nivel * 100 / [double]$r.Maximum }
  $boton = ''
  if ($b -and (Vivo $b)) { $boton = [string]$b.Current.Name }
  return @{ hay = $true; nivel = [math]::Round($nivel); boton = $boton }
}
function Busca($titulo) {
  $mejor = $null
  foreach ($s in $mgr.GetSessions()) {
    try {
      if (([string]$s.SourceAppUserModelId).ToLower().Contains('spotify')) { continue }
      $p = Espera ($s.TryGetMediaPropertiesAsync()) $propType
      $t = ([string]$p.Title).ToLower()
      if ($t.Length -ge 3 -and $titulo.ToLower().Contains($t)) { $mejor = $s; break }
    } catch { }
  }
  return $mejor
}
function Pos($s) {
  $tl = $s.GetTimelineProperties(); $pi = $s.GetPlaybackInfo()
  $pos = $tl.Position.TotalSeconds
  if ([string]$pi.PlaybackStatus -eq 'Playing') {
    $hace = ((Get-Date).ToUniversalTime() - $tl.LastUpdatedTime.UtcDateTime).TotalSeconds
    if ($hace -gt 0 -and $hace -lt 21600) { $pos += $hace }
  }
  return $pos
}
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($line -eq $null -or $line -eq 'fin') { break }
  $out = @{ ok = $true }
  $sw = [Diagnostics.Stopwatch]::StartNew()
  try {
    $cmd = ConvertFrom-Json $line
    $hwnd = [string]$cmd.hwnd
    if ($cmd.c -eq 'vol') { $out.vol = Volumen $hwnd }
    elseif ($cmd.c -eq 'url') { $out.url = Direccion $hwnd }
    elseif ($cmd.c -eq 'ir') {
      $a = [double]$cmd.a
      $out.aceptado = $false; $out.verificado = $false
      $s = Busca ([string]$cmd.titulo)
      if (-not $s) { $out.error = 'sin sesion' }
      else {
        $deja = $false
        try { $deja = [bool]$s.GetPlaybackInfo().Controls.IsPlaybackPositionEnabled } catch { }
        $out.deja = $deja
        if ($deja) {
          $out.aceptado = [bool](Espera ($s.TryChangePlaybackPositionAsync([int64][math]::Round($a * 10000000))) ([bool]))
          if ($out.aceptado) {
            for ($i = 0; $i -lt 8; $i++) {
              Start-Sleep -Milliseconds 200
              $p = Pos $s
              if ([math]::Abs($p - $a) -lt 3) { $out.verificado = $true; $out.pos = [math]::Round($p, 1); break }
            }
          }
        }
      }
    } else { $out.ok = $false; $out.error = 'orden' }
  } catch { $out.ok = $false; $out.error = $_.Exception.GetType().Name }
  $out.ms = [int]$sw.ElapsedMilliseconds
  [Console]::Out.WriteLine(($out | ConvertTo-Json -Compress -Depth 4))
  [Console]::Out.Flush()
}
"""


def encoded() -> str:
    return base64.b64encode(ps_script().encode("utf-16-le")).decode("ascii")


def plan_teclas(pos: float | None, duracion: float, destino: float) -> dict[str, Any]:
    """Teclas de YouTube para llegar a `destino` cuando Windows no deja saltar.
    Con la duración: la cifra 0-9 (va al 0 %…90 %) y luego flechas de 5 s. Sin ella, desde
    la posición actual: «l»/«j» de 10 s y flechas de 5 s. Como mucho 24 flechas o saltos."""
    destino = max(0.0, float(destino))
    if duracion and duracion > 0:
        destino = min(destino, max(0.0, duracion - 1))
        cifra = max(0, min(9, int(destino * 10 // duracion)))
        base = cifra * duracion / 10
        n5 = int(round((destino - base) / 5))
        n5 = max(-24, min(24, n5))
        return {"cifra": str(cifra), "diez": 0, "cinco": n5}
    if pos is None:
        return {"cifra": None, "diez": 0, "cinco": 0}
    delta = destino - pos
    n10 = int(delta / 10)
    n5 = int(round((delta - n10 * 10) / 5))
    return {"cifra": None, "diez": max(-24, min(24, n10)), "cinco": max(-2, min(2, n5))}


def teclas(plan: dict[str, Any]) -> list[list[str]]:
    """El plan como pulsaciones para control._yt_keys, en orden."""
    out: list[list[str]] = []
    if plan.get("cifra") is not None:
        out.append([str(plan["cifra"])])
    d = int(plan.get("diez") or 0)
    out += [["l" if d > 0 else "j"]] * abs(d)
    c = int(plan.get("cinco") or 0)
    out += [["right" if c > 0 else "left"]] * abs(c)
    return out


def enlace(video: str, segundos: float | None) -> str:
    """Dirección para abrir el vídeo en otro aparato, 2 s antes de donde iba (para no perder
    la frase). Solo ids válidos de YouTube."""
    import patrocinios

    if not patrocinios._ID.fullmatch(video or ""):
        raise ValueError("id de vídeo no válido")
    t = max(0, int(segundos or 0) - 2)
    return f"https://www.youtube.com/watch?v={video}" + (f"&t={t}s" if t > 0 else "")


class Mando:
    def __init__(self, probe: Callable[[str], dict] | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        self.probe = probe
        self.clock = clock
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.talk = threading.Lock()
        self.disabled = False
        self.usado = 0.0
        self.vol_cache: dict[str, tuple[float, dict]] = {}
        self.cierre: threading.Timer | None = None
        self.leyendo = threading.Event()

    def available(self) -> bool:
        return (self.probe is not None or platform.system() == "Windows") and not self.disabled

    def pedir(self, **cmd: Any) -> dict:
        if not self.available():
            return {"ok": False, "error": "solo Windows"}
        line = json.dumps(cmd, ensure_ascii=True)
        self.usado = self.clock()
        if self.probe is not None:
            return self.probe(line)
        with self.talk:
            res = self._ps(line)
        self._programa_cierre()
        return res

    # --- lecturas -------------------------------------------------------------
    def volumen(self, hwnd: str, fresco: bool = False) -> dict[str, Any] | None:
        """{"level": 0-100, "muted": bool|None} leído del reproductor, o None si no se ve."""
        now = self.clock()
        hit = self.vol_cache.get(hwnd)
        if hit and not fresco and now - hit[0] < CACHE_VOL:
            return hit[1] or None
        res = self.pedir(c="vol", hwnd=str(hwnd))
        vol = res.get("vol") if res.get("ok", True) else None
        out: dict[str, Any] = {}
        if isinstance(vol, dict) and vol.get("hay"):
            try:
                level = max(0, min(100, int(round(float(vol.get("nivel"))))))
                out = {"level": level, "muted": es_silencio(str(vol.get("boton") or ""))}
            except (TypeError, ValueError):
                out = {}
        self.vol_cache = {hwnd: (now, out)}
        return out or None

    def volumen_sin_esperar(self, hwnd: str) -> dict[str, Any] | None:
        """Para el sondeo del móvil: devuelve la última lectura (si tiene menos de `VIEJO` s) y,
        si toca, la renueva en segundo plano. Así el estado nunca espera al PowerShell, que la
        primera vez tarda en arrancar."""
        now = self.clock()
        hit = self.vol_cache.get(hwnd)
        if hit and now - hit[0] < CACHE_VOL:
            return hit[1] or None
        if self.probe is not None:
            return self.volumen(hwnd)
        if not self.leyendo.is_set():
            self.leyendo.set()

            def leer() -> None:
                try:
                    self.volumen(hwnd, fresco=True)
                except Exception:  # noqa: BLE001
                    pass
                finally:
                    self.leyendo.clear()

            threading.Thread(target=leer, name="lazo-mando-vol", daemon=True).start()
        return (hit[1] or None) if hit and now - hit[0] < VIEJO else None

    def direccion(self, hwnd: str) -> str:
        res = self.pedir(c="url", hwnd=str(hwnd))
        return str(res.get("url") or "") if res.get("ok", True) else ""

    def ir(self, titulo: str, segundos: float) -> dict[str, Any]:
        res = self.pedir(c="ir", titulo=str(titulo), a=round(float(segundos), 2))
        return {"ok": bool(res.get("ok", True)) and bool(res.get("verificado")),
                "deja": bool(res.get("deja")), "pos": res.get("pos"), "error": res.get("error", "")}

    # --- PowerShell -------------------------------------------------------------
    def _ps(self, line: str) -> dict:
        with self.lock:
            if not self.proc or self.proc.poll() is not None:
                self.proc = subprocess.Popen(
                    ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                     "-EncodedCommand", encoded()],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            proc = self.proc
        assert proc.stdin and proc.stdout
        box: dict = {}

        def read() -> None:
            box["line"] = proc.stdout.readline()

        try:
            proc.stdin.write(line + "\n")
            proc.stdin.flush()
        except OSError:
            self.cerrar()
            return {"ok": False, "error": "sin proceso"}
        t = threading.Thread(target=read, daemon=True)
        t.start()
        t.join(TIEMPO_MAX)
        if t.is_alive() or not box.get("line"):
            self.cerrar()
            return {"ok": False, "error": "sin respuesta"}
        try:
            data = json.loads(box["line"])
        except ValueError:
            return {"ok": False, "error": "respuesta rara"}
        if "error" in data and data.get("ok") is None:
            self.disabled = True  # este Windows no tiene UI Automation o controles multimedia
        return data

    def _programa_cierre(self) -> None:
        if self.cierre:
            self.cierre.cancel()
        self.cierre = threading.Timer(CERRAR, self._cierra_si_quieto)
        self.cierre.daemon = True
        self.cierre.start()

    def _cierra_si_quieto(self) -> None:
        if self.clock() - self.usado >= CERRAR - 1:
            self.cerrar()

    def cerrar(self) -> None:
        with self.lock:
            proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            try:
                proc.stdin.write("fin\n")  # type: ignore[union-attr]
                proc.stdin.flush()  # type: ignore[union-attr]
                proc.wait(2)
            except Exception:  # noqa: BLE001
                proc.kill()


MANDO = Mando()
