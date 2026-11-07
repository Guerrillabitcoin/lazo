"""LaZoo 0.63: salta los anuncios de YouTube en cuanto YouTube deja saltarlos.

YouTube no tiene ninguna tecla para «Saltar anuncio»: la flecha de «siguiente» (Mayús+N)
pasa al siguiente vídeo, no salta el anuncio. Pero el botón «Saltar» es un botón de verdad
en el árbol de accesibilidad (UI Automation) del navegador, igual que el «Sí» del aviso
«¿Sigues ahí?» (sigues.py, 0.59).

Qué hace (solo Windows): cada `INTERVALO` s, si hay una ventana de YouTube, un PowerShell
oculto busca en ESA ventana un botón visible que se llame «Saltar», «Omitir», «Skip»,
«Saltar anuncio»… (`SALTAR`, varios idiomas) dentro del reproductor, y lo pulsa con
InvokePattern: sin mover el cursor, sin teclas, sin poner la ventana delante y sin
JavaScript. Si el reproductor no se encuentra (otro idioma, otro navegador), busca en toda la
ventana, pero solo botones con esos nombres exactos («Saltar navegación» no vale).

La flecha «siguiente» del móvil, durante un anuncio, primero intenta saltarlo
(`ANUNCIOS.saltar_ya`); si no hay botón, hace lo de siempre (siguiente vídeo).

Límites: los anuncios que YouTube no deja saltar (o los primeros 5 s) no se pueden saltar.
Se apaga en el Panel o en el móvil, con `--sin-anuncios` o con `LAZO_SIN_ANUNCIOS=1`.
"""

from __future__ import annotations

import base64
import os
import re
import sys
from typing import Any

import sigues

INTERVALO = 2.5      # con YouTube abierto; sin YouTube no se lanza nada
LENTO = 8.0          # si una revisión tarda mucho (página enorme), se espacian
LENTO_MS = 700
DEFAULT_ON = True

# Nombres exactos del botón (minúsculas, sin signos al final).
SALTAR = [
    "skip", "skip ad", "skip ads", "saltar", "saltar anuncio", "saltar anuncios", "omitir",
    "omitir anuncio", "omitir anuncios", "ignorer", "ignorer l'annonce", "ignorer les annonces",
    "passer", "überspringen", "werbung überspringen", "salta", "salta annuncio", "salta annunci",
    "pular", "pular anúncio", "pular anúncios", "ignorar", "ignorar anúncio", "overslaan",
    "advertentie overslaan",
]
# Nombre accesible del reproductor de YouTube (aria-label), para buscar solo dentro.
REPRODUCTOR = ["youtube video player", "reproductor de vídeo de youtube", "reproductor de video de youtube",
               "lecteur vidéo youtube", "youtube-videoplayer", "player video di youtube",
               "player de vídeo do youtube", "player de vídeo de youtube", "youtube-videospeler"]

_LIMPIA = re.compile(r"[\s.!¡▶►⏭→›»]+$")


def es_saltar(nombre: str) -> bool:
    n = _LIMPIA.sub("", (nombre or "").strip()).strip().lower()
    return n in SALTAR


def ps_script() -> str:
    saltar = ",".join("'" + s.replace("'", "''") + "'" for s in SALTAR)
    repro = ",".join("'" + s.replace("'", "''") + "'" for s in REPRODUCTOR)
    return r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
[Console]::InputEncoding = [Text.Encoding]::UTF8
try { Add-Type -AssemblyName UIAutomationClient; Add-Type -AssemblyName UIAutomationTypes }
catch { '{"error":"uia"}'; exit 1 }
$saltar = @(""" + saltar + r""")
$repro = @(""" + repro + r""")
$AE = [Windows.Automation.AutomationElement]
$scope = [Windows.Automation.TreeScope]::Descendants
try { Add-Type -Namespace LaZoo -Name Foco -MemberDefinition '[DllImport("user32.dll")] public static extern System.IntPtr GetForegroundWindow(); [DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr h);' } catch { }
function Conds($names) {
  $c = foreach ($s in $names) { New-Object Windows.Automation.PropertyCondition($AE::NameProperty, $s, [Windows.Automation.PropertyConditionFlags]::IgnoreCase) }
  if ($c.Count -eq 1) { return $c[0] }
  return New-Object Windows.Automation.OrCondition([Windows.Automation.Condition[]]$c)
}
# Botones (y no nombres exactos): el texto puede llevar espacios o una flecha al final.
$condSaltar = New-Object Windows.Automation.PropertyCondition($AE::ControlTypeProperty, [Windows.Automation.ControlType]::Button)
$condRepro = Conds $repro
$cache = @{}
function Limpia($n) { return ($n.Trim() -replace '[\s\.!¡▶►⏭→›»]+$', '').Trim().ToLower() }
function Reproductor($win, $hwnd) {
  $p = $cache[$hwnd]
  if ($p) { try { [void]$p.Current.Name; return $p } catch { $cache.Remove($hwnd) } }
  $p = $win.FindFirst($scope, $condRepro)
  if ($p) { $cache[$hwnd] = $p }
  return $p
}
function Buscar($win, $hwnd) {
  $raiz = Reproductor $win $hwnd
  $donde = 'reproductor'
  if (-not $raiz) { $raiz = $win; $donde = 'ventana' }
  foreach ($b in $raiz.FindAll($scope, $condSaltar)) {
    try {
      if ($b.Current.IsOffscreen -or -not $b.Current.IsEnabled) { continue }
      if ($saltar -notcontains (Limpia $b.Current.Name)) { continue }
      return @($b, $donde)
    } catch { }
  }
  return @($null, $donde)
}
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($line -eq $null -or $line -eq 'fin') { break }
  $out = @{ ok = $true; visto = $false; pulsado = $false; verificado = $false; ms = 0; donde = '' }
  $t = [Diagnostics.Stopwatch]::StartNew()
  try {
    $hwnd = $line.Trim()
    $win = $AE::FromHandle([IntPtr][Int64]$hwnd)
    $r = Buscar $win $hwnd
    $b = $r[0]; $out.donde = $r[1]
    if ($b) {
      $out.visto = $true
      $ip = $null
      if ($b.TryGetCurrentPattern([Windows.Automation.InvokePattern]::Pattern, [ref]$ip)) {
        $antes = [IntPtr]::Zero
        try { $antes = [LaZoo.Foco]::GetForegroundWindow() } catch { }
        $ip.Invoke(); $out.pulsado = $true
        try {
          Start-Sleep -Milliseconds 120
          $ahora = [LaZoo.Foco]::GetForegroundWindow()
          if ($antes -ne [IntPtr]::Zero -and $ahora -ne $antes) { $out.foco = [bool][LaZoo.Foco]::SetForegroundWindow($antes) }
        } catch { }
        for ($i = 0; $i -lt 3; $i++) {
          Start-Sleep -Milliseconds 300
          try { if (-not (Buscar $win $hwnd)[0]) { $out.verificado = $true; break } } catch { $out.verificado = $true; break }
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


class Anuncios(sigues.Sigues):
    KEY = "anuncios"
    COUNT = "anuncios_contador"
    NAME = "lazo-anuncios"
    DEFAULT = DEFAULT_ON
    MESSAGE = "  YouTube: anuncio saltado sin tocar el ratón."

    def interval(self) -> float:
        return LENTO if self.ultima_ms >= LENTO_MS else INTERVALO

    def script(self) -> str:
        return encoded()

    def saltar_ya(self) -> bool:
        """Desde la flecha «siguiente»: si hay un «Saltar» a la vista, lo pulsa ahora.
        Funciona aunque el salto automático esté apagado (lo ha pedido la persona)."""
        if not self.available() or self.disabled:
            return False
        if self.ultima_ms >= LENTO_MS:
            return False  # en este PC cada revisión es lenta: la flecha no espera, salta el bucle
        hwnd = self.find() if self.find else None
        if not hwnd:
            return False
        try:
            res = (self.probe or self._probe_ps)(str(hwnd))
        except Exception as exc:  # noqa: BLE001 (nunca romper la flecha por esto)
            self.error = type(exc).__name__
            return False
        if res.get("pulsado") and res.get("verificado"):
            self.contar()
            return True
        return False


ANUNCIOS = Anuncios(find=sigues._find_youtube_hwnd)


def status() -> dict[str, Any]:
    return ANUNCIOS.status()


def watch() -> bool:
    if "unittest" in sys.modules or "pytest" in sys.modules:
        return False
    if os.environ.get("LAZO_SIN_ANUNCIOS") == "1":
        ANUNCIOS.disabled = True
        return False
    return ANUNCIOS.start()

