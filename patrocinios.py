"""LaZoo 0.64: salta los patrocinios que van dentro del propio vídeo de YouTube (SponsorBlock).

Cuando el youtuber dedica un rato a su patrocinador («este vídeo está patrocinado por…»), eso
no es un anuncio de YouTube: no hay botón «Saltar» (eso ya lo hace anuncios.py). La comunidad
de SponsorBlock marca dónde empieza y acaba ese tramo en cada vídeo. LaZoo pregunta y salta
el tramo solo, sin que se note.

Qué hace (solo Windows), en el hilo `lazo-patrocinios`:
1. Mira la ventana de YouTube que ya usa el resto de LaZoo, sin enfocarla. Cuando cambia su
   título, un PowerShell oculto lee por accesibilidad (UI Automation) la dirección de la barra
   del navegador, sin entrar en la página, y saca el id del vídeo.
2. Pregunta a SponsorBlock solo con 4 letras del SHA-256 del id (`prefijo`). El servidor
   devuelve los tramos de unos cien vídeos con ese prefijo y LaZoo se queda con el suyo: nadie
   fuera de este PC sabe qué vídeo ves. Sin cookies ni cuenta, con caché en memoria. Es la
   única conexión a internet nueva, y se apaga con la casilla.
3. Lee posición, duración, velocidad y play/pausa de los controles multimedia de Windows (los
   del panel de volumen) y se despierta justo cuando empieza el patrocinio.
4. Salta al final del tramo pidiéndoselo a Windows (`TryChangePlaybackPositionAsync`, lo mismo
   que arrastrar la barra del panel multimedia): sin teclas, sin cursor, sin traer la ventana
   delante y sin JavaScript. Después comprueba que la posición cambió de verdad. Si el navegador
   no lo acepta, y solo si YouTube ya está delante y no estás escribiendo en un campo, usa las
   teclas de YouTube (l = +10 s, → = +5 s) sin pasarse del final. Si no, no hace nada visible.

Cada tramo se salta una vez por vídeo: si vuelves atrás para verlo, se queda. Al volver al
principio del vídeo se pueden saltar otra vez. Si el tramo no cuadra con la duración que da
Windows (otra versión del vídeo, o está sonando un anuncio de YouTube), no se salta.
0.73: no solo «sponsor». SponsorBlock marca también el autobombo del canal (selfpromo), los
«suscríbete, dale like y a la campana» (interaction), intros, créditos finales, avances,
relleno y partes sin música en vídeos musicales. Se piden todas en la misma consulta (así la
consulta no dice cuáles te interesan) y se saltan las elegidas; de serie: patrocinios,
autobombo y recordatorios. Los «momentos destacados» (poi_highlight) no se piden ni se saltan, y si
el vídeo entero está marcado como patrocinado o autopromoción (actionType «full») no se salta
nada: solo se avisa.

Desde 0.65 viene APAGADO de serie: se enciende en el Panel o en el móvil (se recuerda) o, solo para
esa sesión, con `--con-patrocinios` / `LAZO_CON_PATROCINIOS=1`. `--sin-patrocinios` /
`LAZO_SIN_PATROCINIOS=1` lo apagan del todo y mandan sobre todo lo demás.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
from typing import Any, Callable

import sigues

API = "https://sponsor.ajay.app/api/skipSegments/"
PREFIJO = 4              # letras del SHA-256 del id que salen del PC (las que recomienda SponsorBlock)
# 0.73: todas las que se pueden saltar, en el orden en que salen en el Panel y el móvil.
CATEGORIAS = ("sponsor", "selfpromo", "interaction", "intro", "outro", "preview", "filler", "music_offtopic")
NOMBRES = {
    "sponsor": "Patrocinios",
    "selfpromo": "Autobombo / promo del canal",
    "interaction": "Recordatorios de suscribirse y like",
    "intro": "Intros",
    "outro": "Outros / créditos",
    "preview": "Avances / resúmenes",
    "filler": "Relleno / desvíos",
    "music_offtopic": "Partes sin música en vídeos musicales",
}
DEFECTO = ("sponsor", "selfpromo", "interaction")  # 0.73: lo que hace perder el tiempo, de serie
CLAVE_CATEGORIAS = "patrocinios_categorias"        # en ajustes.json; sin ella, DEFECTO (migración)
TIPOS_ENTERO = ("sponsor", "selfpromo", "exclusive_access")  # «todo el vídeo es…»: solo se avisa
NOMBRES_ENTERO = {"sponsor": "patrocinado", "selfpromo": "autopromoción del canal", "exclusive_access": "acceso exclusivo pagado"}
AGENTE = "LaZoo"         # User-Agent: sin versión del sistema ni nada personal
TIEMPO_RED = 5.0
DEFAULT_ON = False  # 0.65: apagado de serie (decisión del dueño); al encenderlo se recuerda en ajustes.json

TOLERANCIA = 2.0         # s de diferencia admitida entre la duración del tramo marcado y la real
MIN_TRAMO = 1.0          # tramos más cortos no se saltan
MARGEN_FIN = 2.0         # si quedan menos de 2 s del tramo, no merece la pena
ANTES = 0.4              # se puede saltar hasta 0,4 s antes del inicio marcado (se marcan a mano)
ADELANTO = 0.15          # se despierta un poco antes del inicio
CERCA = 4.0              # con el inicio a menos de esto, espera justo hasta él

PASO = 1.5               # con YouTube abierto: cada cuánto mira (título y posición)
SIN_YOUTUBE = 3.0        # sin ventana de YouTube solo se listan ventanas, sin PowerShell
CERRAR = 60.0            # sin YouTube tanto rato, se cierra el PowerShell
VERIFICAR = 1.2          # Windows aceptó el salto: lo que se espera a que se note
INTENTOS = 3

CACHE_OK = 1800.0
CACHE_NADA = 600.0       # sin tramos: se vuelve a preguntar en 10 min (los vídeos nuevos se marcan después)
CACHE_ERROR = 90.0

_ID = re.compile(r"[A-Za-z0-9_-]{11}")


# --- piezas puras (se prueban en Linux) -------------------------------------
def video_id(url: str) -> str | None:
    """Id de 11 caracteres de una dirección de YouTube, tal como la enseña la barra del navegador
    (a menudo sin «https://»). None si no es la página de un vídeo de YouTube."""
    text = (url or "").strip()
    if not text:
        return None
    if "://" not in text:
        text = "https://" + text
    try:
        parts = urllib.parse.urlsplit(text)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    path = parts.path or ""
    found = ""
    if host == "youtu.be":
        found = path.strip("/").split("/")[0]
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        if path.rstrip("/") == "/watch":
            found = (urllib.parse.parse_qs(parts.query).get("v") or [""])[0]
        else:
            bits = path.strip("/").split("/")
            if len(bits) >= 2 and bits[0] in ("shorts", "live", "embed", "v"):
                found = bits[1]
    return found if _ID.fullmatch(found or "") else None


def prefijo(vid: str) -> str:
    return hashlib.sha256(vid.encode("ascii")).hexdigest()[:PREFIJO]


def url_consulta(vid: str) -> str:
    """Siempre las mismas categorías (todas) y sin el id: solo el prefijo del hash sale del PC."""
    cats = list(CATEGORIAS) + [c for c in TIPOS_ENTERO if c not in CATEGORIAS]
    query = "&".join([f"category={c}" for c in cats] + ["actionType=skip", "actionType=full"])
    return f"{API}{prefijo(vid)}?{query}"


def limpiar_categorias(valor: Any) -> list[str]:
    """Lista válida de categorías (en el orden de CATEGORIAS). Acepta lista o {cat: bool}.
    Lanza ValueError con algo que no sea una categoría conocida."""
    if isinstance(valor, dict):
        valor = [k for k, v in valor.items() if v is True]
    if not isinstance(valor, (list, tuple)) or len(valor) > 20:
        raise ValueError("categorías no válidas")
    for c in valor:
        if c not in CATEGORIAS:
            raise ValueError(f"categoría desconocida: {str(c)[:30]}")
    return [c for c in CATEGORIAS if c in valor]


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if out == out and abs(out) != float("inf") else default


def tramos(data: Any, vid: str) -> list[dict[str, Any]]:
    """De la respuesta de SponsorBlock (vídeos con el mismo prefijo), los tramos de `vid` que se
    pueden saltar, con su «categoria» (0.73: de todas; validos() se queda con las elegidas).
    Los de «todo el vídeo» salen aparte con «entero»: True (nunca se saltan)."""
    out: list[dict[str, Any]] = []
    if not isinstance(data, list):
        return out
    for video in data:
        if not isinstance(video, dict) or video.get("videoID") != vid:
            continue
        for seg in video.get("segments") or []:
            if not isinstance(seg, dict):
                continue
            cat, accion = seg.get("category"), seg.get("actionType", "skip")
            if accion == "full" and cat in TIPOS_ENTERO:
                out.append({"inicio": 0.0, "fin": 0.0, "duracion": max(0.0, _num(seg.get("videoDuration"))),
                            "categoria": cat, "entero": True})
                continue
            if cat not in CATEGORIAS or accion != "skip":  # poi_highlight, mute, chapter: nunca
                continue
            pair = seg.get("segment")
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            ini, fin = _num(pair[0], -1), _num(pair[1], -1)
            if ini < 0 or fin - ini < MIN_TRAMO:
                continue
            out.append({"inicio": ini, "fin": fin, "duracion": max(0.0, _num(seg.get("videoDuration"))), "categoria": cat})
    out.sort(key=lambda t: t["inicio"])
    return out


def entero(lista: list[dict[str, Any]]) -> str:
    """0.73: «patrocinado», «autopromoción del canal»… si todo el vídeo está marcado así; si no, ""."""
    for t in lista:
        if t.get("entero"):
            return NOMBRES_ENTERO.get(t.get("categoria"), "patrocinado")
    return ""


def unir(lista: list[tuple]) -> list[tuple]:
    """Tramos que se pisan o casi se tocan (menos de 1 s) se saltan de una vez. Con tríos
    (inicio, fin, categorías) el tramo unido lleva las categorías de todos (0.73)."""
    out: list[list] = []
    trios = bool(lista) and len(lista[0]) > 2
    for t in sorted(lista, key=lambda x: (x[0], x[1])):
        ini, fin = t[0], t[1]
        cats = tuple(t[2]) if trios else ()
        if out and ini <= out[-1][1] + 1.0:
            out[-1][1] = max(out[-1][1], fin)
            out[-1][2] = out[-1][2] + tuple(c for c in cats if c not in out[-1][2])
        else:
            out.append([ini, fin, cats])
    return [(a, b, c) if trios else (a, b) for a, b, c in out]


def validos(lista: list[dict[str, Any]], duracion: float, categorias: Any = None,
            con_categoria: bool = False) -> list[tuple]:
    """Solo con la duración real conocida. Un tramo marcado en un vídeo de otra duración (otra
    versión, o lo que suena es un anuncio de YouTube) no vale. 0.73: solo las `categorias`
    elegidas (None = solo «sponsor», como hasta la 0.72); con `con_categoria`, tríos
    (inicio, fin, categorías)."""
    if duracion <= 1:
        return []
    elegidas = ("sponsor",) if categorias is None else tuple(categorias)
    out = []
    for t in lista:
        if t.get("entero") or t.get("categoria", "sponsor") not in elegidas:
            continue
        if t["duracion"] and abs(t["duracion"] - duracion) > TOLERANCIA:
            continue
        ini, fin = t["inicio"], min(t["fin"], duracion)
        if ini >= duracion - 0.5 or fin - ini < MIN_TRAMO:
            continue
        out.append((ini, fin, (t.get("categoria", "sponsor"),)) if con_categoria else (ini, fin))
    return unir(out)


def nombre_de(categorias: Any) -> str:
    """«Autobombo / promo del canal» o «Patrocinios + Intros» para el aviso del salto."""
    cats = [c for c in (categorias or ()) if c in NOMBRES] or ["sponsor"]
    return " + ".join(NOMBRES[c] for c in cats)


def clave(ini: float) -> str:
    return f"{ini:.1f}"


def decidir(lista: list[tuple[float, float]], pos: float, duracion: float, tocando: bool,
            velocidad: float = 1.0, hechos: set[str] | frozenset[str] = frozenset()) -> dict[str, Any]:
    """Qué hacer ahora: {"accion": "saltar", desde, hasta, clave} o {"accion": "esperar", s}."""
    vel = velocidad if 0.25 <= velocidad <= 4 else 1.0
    if not lista or duracion <= 1:
        return {"accion": "esperar", "s": PASO}
    if not tocando:
        return {"accion": "esperar", "s": PASO}
    proximo = None
    for t in lista:
        ini, fin = t[0], t[1]
        k = clave(ini)
        if k in hechos:
            continue
        if ini - ANTES <= pos < fin - MARGEN_FIN:
            out = {"accion": "saltar", "desde": ini, "hasta": fin, "clave": k}
            if len(t) > 2:
                out["categorias"] = list(t[2])
            return out
        if ini - ANTES > pos and (proximo is None or ini < proximo):
            proximo = ini
    if proximo is None:
        return {"accion": "esperar", "s": PASO}
    falta = (proximo - ADELANTO - pos) / vel
    if falta <= CERCA:
        return {"accion": "esperar", "s": max(0.05, falta)}
    return {"accion": "esperar", "s": min(PASO, falta - CERCA / 2)}


def pasos(segundos: float) -> tuple[int, int]:
    """Teclas de YouTube para avanzar sin pasarse del final del tramo: l = +10 s, → = +5 s."""
    s = max(0.0, segundos - 0.5)
    n10 = int(s // 10)
    n5 = 1 if s - n10 * 10 >= 5 else 0
    return min(n10, 60), n5


def _limpio(text: Any) -> str:
    return " ".join(str(text or "").lower().split())


def consultar(vid: str, abrir: Callable | None = None, timeout: float = TIEMPO_RED) -> list[dict[str, Any]]:
    """Tramos de SponsorBlock para `vid`, preguntando solo por su prefijo. [] si no hay.
    Lanza si la red falla (la caché lo reintenta más tarde)."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url_consulta(vid), headers={"User-Agent": AGENTE, "Accept": "application/json"})
    try:
        with (abrir or urllib.request.urlopen)(req, timeout=timeout) as res:
            data = json.loads(res.read(4_000_000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # SponsorBlock: ningún vídeo con ese prefijo tiene tramos
            return []
        raise
    return tramos(data, vid)


# --- PowerShell oculto ------------------------------------------------------
def ps_script() -> str:
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
} catch { '{"error":"sin sesiones multimedia"}'; exit 1 }
$AE = [Windows.Automation.AutomationElement]
$CT = [Windows.Automation.ControlType]
$walker = [Windows.Automation.TreeWalker]::ControlViewWalker
$barras = @{}
$edits = New-Object System.Collections.ArrayList
function Valor($e) {
  try { return [string]$e.GetCurrentPattern([Windows.Automation.ValuePattern]::Pattern).Current.Value } catch { return '' }
}
# Solo la barra del navegador: no entra en la página web (Document ni su panel) ni en las pestañas.
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
function Fila($s, $titulo) {
  $tl = $s.GetTimelineProperties()
  $pi = $s.GetPlaybackInfo()
  $st = [string]$pi.PlaybackStatus
  $vel = 1.0
  try { if ($pi.PlaybackRate -ne $null -and [double]$pi.PlaybackRate -gt 0) { $vel = [double]$pi.PlaybackRate } } catch { }
  $pos = $tl.Position.TotalSeconds
  $len = $tl.EndTime.TotalSeconds
  if ($st -eq 'Playing') {
    $hace = ((Get-Date).ToUniversalTime() - $tl.LastUpdatedTime.UtcDateTime).TotalSeconds
    if ($hace -lt -5 -or $hace -gt 21600) { $len = 0 } elseif ($hace -gt 0) { $pos += $hace * $vel }
  }
  $deja = $false
  try { $deja = [bool]$pi.Controls.IsPlaybackPositionEnabled } catch { }
  return [pscustomobject]@{ app = [string]$s.SourceAppUserModelId; titulo = $titulo; estado = $st; pos = [math]::Round($pos, 2); len = [math]::Round($len, 2); vel = [math]::Round($vel, 2); saltar = $deja }
}
function Sesiones() {
  $rows = @()
  foreach ($s in $mgr.GetSessions()) {
    try { $p = Espera ($s.TryGetMediaPropertiesAsync()) $propType; $rows += (Fila $s ([string]$p.Title)) } catch { }
  }
  return ,$rows
}
function Busca($app, $titulo) {
  foreach ($s in $mgr.GetSessions()) {
    try {
      if ([string]$s.SourceAppUserModelId -ne $app) { continue }
      $p = Espera ($s.TryGetMediaPropertiesAsync()) $propType
      if ([string]$p.Title -eq $titulo) { return $s }
    } catch { }
  }
  return $null
}
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($line -eq $null -or $line -eq 'fin') { break }
  $out = @{ ok = $true; ms = 0 }
  $ses = $null
  $sw = [Diagnostics.Stopwatch]::StartNew()
  try {
    $cmd = ConvertFrom-Json $line
    if ($cmd.c -eq 'mira') {
      $hwnd = [string]$cmd.hwnd
      if ($cmd.url) { try { $out.url = Direccion $hwnd } catch { $out.url = '' } }
      if ($cmd.foco) {
        $out.texto = $false
        try { $f = $AE::FocusedElement.Current.ControlType; $out.texto = ($f -eq $CT::Edit -or $f -eq $CT::ComboBox) } catch { }
      }
      $ses = Sesiones
    } elseif ($cmd.c -eq 'salta') {
      $desde = [double]$cmd.desde; $hasta = [double]$cmd.hasta
      $out.aceptado = $false; $out.verificado = $false; $out.fuera = $false; $out.no_deja = $false
      $s = Busca ([string]$cmd.app) ([string]$cmd.titulo)
      if (-not $s) { $out.ok = $false; $out.error = 'sin sesion' }
      else {
        $f = Fila $s ''
        $out.antes = $f.pos
        if ($f.estado -ne 'Playing' -or $f.pos -lt ($desde - 0.6) -or $f.pos -ge ($hasta - 1.5)) { $out.fuera = $true }
        elseif (-not $f.saltar) { $out.no_deja = $true }
        else {
          $out.aceptado = [bool](Espera ($s.TryChangePlaybackPositionAsync([int64][math]::Round($hasta * 10000000))) ([bool]))
          if ($out.aceptado) {
            for ($i = 0; $i -lt 8; $i++) {
              Start-Sleep -Milliseconds 200
              $g = Fila $s ''
              if ($g.pos -ge ($hasta - 0.5)) { $out.verificado = $true; $out.pos = $g.pos; break }
            }
          }
        }
      }
    } else { $out.ok = $false; $out.error = 'orden' }
  } catch { $out.ok = $false; $out.error = $_.Exception.GetType().Name }
  $out.ms = [int]$sw.ElapsedMilliseconds
  $j = $out | ConvertTo-Json -Compress
  if ($null -ne $ses) { $j = $j.Substring(0, $j.Length - 1) + ',"sesiones":' + (ConvertTo-Json -Compress -InputObject $ses) + '}' }
  [Console]::Out.WriteLine($j)
  [Console]::Out.Flush()
}
"""


def encoded() -> str:
    return base64.b64encode(ps_script().encode("utf-16-le")).decode("ascii")


# --- vigilante --------------------------------------------------------------
class Patrocinios(sigues.Sigues):
    KEY = "patrocinios"
    COUNT = "patrocinios_contador"
    NAME = "lazo-patrocinios"
    DEFAULT = DEFAULT_ON
    MESSAGE = "  YouTube: {que} saltado sin tocar el ratón."  # 0.73: dice qué categoría

    def __init__(self, find: Callable[[], dict | None] | None = None, probe: Callable[[str], dict] | None = None,
                 file=None, fetch: Callable[[str], list] | None = None,
                 keys: Callable[[str, int, int], bool] | None = None, clock: Callable[[], float] = time.time) -> None:
        self.fetch = fetch or consultar
        self.keys = keys or _teclas
        self.clock = clock
        self.cache: dict[str, tuple[float, list, str]] = {}
        self.titulos: dict[str, str] = {}   # título del vídeo (Windows) → id, visto en su página
        self.v: dict[str, Any] = {}         # vídeo que suena ahora
        self.pendiente: dict[str, Any] | None = None
        self.espera = SIN_YOUTUBE
        self.metodo = ""                    # «windows» o «teclas»: cómo saltó la última vez
        self.consulta = ""                  # ok / nada / sin red
        self.n_video = 0
        self.sin_yt = 0.0
        self.entero = ""                    # 0.73: «patrocinado»… si el vídeo entero lo es (no se salta)
        self.ultimo_salto: dict[str, Any] = {}
        super().__init__(find=find, probe=probe, file=file)
        self.categorias = self._load_categorias()

    # --- 0.73: qué categorías se saltan ----------------------------------------
    def _load_categorias(self) -> list[str]:
        """Las guardadas en ajustes.json o, si nunca se eligieron (hasta 0.72 solo había
        «sponsor»), las de serie: patrocinios, autobombo y recordatorios."""
        p = self._path()
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p and p.is_file() else {}
            if CLAVE_CATEGORIAS in data:
                return limpiar_categorias(data[CLAVE_CATEGORIAS])
        except Exception:  # noqa: BLE001 (archivo roto o lista rara: las de serie)
            pass
        return list(DEFECTO)

    def set_categorias(self, valor: Any) -> dict[str, Any]:
        cats = limpiar_categorias(valor)
        if isinstance(valor, dict):  # {cat: bool}: solo cambian las que vienen
            cats = [c for c in CATEGORIAS if (valor.get(c) is True) or (c in self.categorias and c not in valor)]
        self.categorias = cats
        self._save()
        return self.status()

    def _save_now(self, p) -> None:
        super()._save_now(p)
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
            data[CLAVE_CATEGORIAS] = list(getattr(self, "categorias", DEFECTO))
            tmp = p.with_name(f"{p.name}.{os.getpid()}.c.tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, p)
        except (OSError, ValueError):
            pass

    # --- contador con el tiempo ahorrado (y, 0.73, por categoría) ---------------
    def _load_count(self) -> None:
        super()._load_count()
        self.ahorrado = self.ahorrado_hoy = 0.0
        self.por_categoria: dict[str, int] = {}
        p = self._path()
        try:
            data = json.loads(p.read_text(encoding="utf-8")) if p and p.is_file() else {}
            c = data.get(self.COUNT) or {}
            self.ahorrado = max(0.0, float(c.get("ahorrado", 0) or 0))
            self.ahorrado_hoy = max(0.0, float(c.get("ahorrado_hoy", 0) or 0))
            pc = c.get("por_categoria") or {}
            if isinstance(pc, dict):
                self.por_categoria = {k: max(0, int(v)) for k, v in pc.items() if k in CATEGORIAS}
        except Exception:  # noqa: BLE001 (archivo roto: a cero)
            pass

    def _contador(self) -> dict[str, Any]:
        c = super()._contador()
        c.update(ahorrado=round(self.ahorrado, 1), ahorrado_hoy=round(self.ahorrado_hoy, 1),
                 por_categoria=dict(getattr(self, "por_categoria", {})))
        return c

    def contar(self, now: float | None = None, segundos: float = 0.0, categorias: Any = None) -> None:
        now = time.time() if now is None else now
        if time.strftime("%Y-%m-%d", time.localtime(now)) != self.dia:
            self.ahorrado_hoy = 0.0
        self.ahorrado += max(0.0, segundos)
        self.ahorrado_hoy += max(0.0, segundos)
        for c in categorias or ():
            if c in CATEGORIAS:
                self.por_categoria[c] = self.por_categoria.get(c, 0) + 1
        super().contar(now)

    def reset(self) -> dict[str, Any]:
        self.ahorrado = self.ahorrado_hoy = 0.0
        self.por_categoria = {}
        return super().reset()

    def status(self) -> dict[str, Any]:
        st = super().status()
        hoy = self.dia == time.strftime("%Y-%m-%d")
        st.update(ahorrado=round(self.ahorrado), ahorrado_hoy=round(self.ahorrado_hoy if hoy else 0),
                  metodo=self.metodo, video=self.n_video, consulta=self.consulta, intervalo_s=PASO,
                  categorias=list(getattr(self, "categorias", DEFECTO)),
                  todas=[{"id": c, "nombre": NOMBRES[c], "defecto": c in DEFECTO} for c in CATEGORIAS],
                  por_categoria=dict(getattr(self, "por_categoria", {})),
                  ultimo_salto=dict(getattr(self, "ultimo_salto", {})), entero=getattr(self, "entero", ""))
        return st

    # --- bucle ------------------------------------------------------------------
    def interval(self) -> float:
        if not self.on or self.disabled:
            return SIN_YOUTUBE
        return max(0.05, min(SIN_YOUTUBE, self.espera))

    def script(self) -> str:
        return encoded()

    def _pedir(self, **cmd: Any) -> dict:
        res = (self.probe or self._probe_ps)(json.dumps(cmd, ensure_ascii=True))
        self.revisiones += 1
        self.ultima_ms = int(_num(res.get("ms")))
        if not res.get("ok", True):
            self.error = str(res.get("error", ""))
        return res

    def check_once(self) -> dict[str, Any]:
        """Una vuelta: qué suena, si hay patrocinio y, si toca, saltarlo."""
        if not (self.on and not self.disabled):
            self.espera = SIN_YOUTUBE
            return {"skip": "apagado"}
        now = self.clock()
        row = self.find() if self.find else None
        if not row:
            self.espera, self.v, self.n_video = SIN_YOUTUBE, {}, 0
            self.sin_yt = self.sin_yt or now
            if now - self.sin_yt > CERRAR and self.proc:
                self._close()
            return {"skip": "sin youtube"}
        self.sin_yt = 0.0
        self.espera = PASO
        hwnd, titulo = str(row.get("id", "")), str(row.get("title", ""))
        nuevo = (hwnd, titulo) != (self.v.get("hwnd"), self.v.get("titulo"))
        # La dirección solo se lee al cambiar el título (o, sin id, cada 5 s: alguien escribía en la barra).
        leer = nuevo or (not self.v.get("vid_url") and now - self.v.get("url_t", 0.0) > 5)
        delante = bool(row.get("active"))
        res = self._pedir(c="mira", hwnd=hwnd, url=leer, foco=delante)
        if not res.get("ok", True):
            return res
        if leer:
            self.v.update(hwnd=hwnd, titulo=titulo, url_t=now, vid_url=video_id(str(res.get("url") or "")))
        sesion, por_ventana = self._sesion(res.get("sesiones"), titulo)
        vid = None
        if sesion is not None:
            nombre = _limpio(sesion.get("titulo"))
            if por_ventana and self.v.get("vid_url"):
                vid = self.v["vid_url"]
                self._recuerda(nombre, vid)
            else:
                vid = self.titulos.get(nombre)
        if vid and vid != self.v.get("vid"):  # otro vídeo: tramos y saltos de cero
            self.v.update(vid=vid, hechos=set(), intentos={}, aceptados=set(), max_pos=0.0)
            self.pendiente = None
        if not vid or sesion is None:
            self.n_video = 0
            self.entero = ""
            return {"skip": "sin vídeo"}
        crudos = self._tramos(vid, now)
        self.entero = entero(crudos)  # 0.73: vídeo entero patrocinado: no se salta, solo se avisa
        lista = validos(crudos, _num(sesion.get("len")), categorias=self.categorias, con_categoria=True)
        self.n_video = len(lista)
        pos = _num(sesion.get("pos"))
        hechos = self.v["hechos"]
        if pos < 3 and self.v.get("max_pos", 0.0) > 15:  # vuelta al principio: se pueden saltar otra vez
            hechos.clear()
            self.v.update(intentos={}, aceptados=set(), max_pos=0.0)
        self.v["max_pos"] = max(self.v.get("max_pos", 0.0), pos)
        if self.pendiente:
            self._comprueba(pos)
        tocando = str(sesion.get("estado", "")).lower() == "playing"
        d = decidir(lista, pos, _num(sesion.get("len")), tocando, _num(sesion.get("vel"), 1.0), hechos)
        if d["accion"] == "saltar":
            self._saltar(d, sesion, delante and res.get("texto") is False, pos)
            self.espera = min(PASO, VERIFICAR)
        else:
            self.espera = min(PASO, d["s"])
        return {"vid": vid, "pos": pos, "decision": d}

    def _sesion(self, rows: Any, titulo: str) -> tuple[dict | None, bool]:
        """La sesión multimedia de Windows que es este YouTube: la de título igual al de la
        ventana; si no (minirreproductor, título a medio cambiar), una que ya vimos en su página."""
        if isinstance(rows, dict):
            rows = [rows]
        rows = [r for r in rows or [] if isinstance(r, dict) and "spotify" not in str(r.get("app", "")).lower()]
        playing = lambda r: str(r.get("estado", "")).lower() == "playing"  # noqa: E731
        low = _limpio(titulo)
        mias = [r for r in rows if len(_limpio(r.get("titulo"))) >= 3 and _limpio(r.get("titulo")) in low]
        if mias:
            mias.sort(key=lambda r: not playing(r))
            return mias[0], True
        conocidas = [r for r in rows if _limpio(r.get("titulo")) in self.titulos]
        sonando = [r for r in conocidas if playing(r)]
        elegidas = sonando if len(sonando) == 1 else conocidas if len(conocidas) == 1 else []
        return (elegidas[0], False) if elegidas else (None, False)

    def _recuerda(self, nombre: str, vid: str) -> None:
        self.titulos.pop(nombre, None)
        self.titulos[nombre] = vid
        while len(self.titulos) > 200:
            self.titulos.pop(next(iter(self.titulos)))

    def _tramos(self, vid: str, now: float) -> list[dict[str, Any]]:
        hit = self.cache.get(vid)
        if hit and hit[0] > now:
            self.consulta = hit[2]
            return hit[1]
        try:
            lista = list(self.fetch(vid))
            estado, ttl = ("ok", CACHE_OK) if lista else ("nada", CACHE_NADA)
        except Exception:  # noqa: BLE001 (sin red o SponsorBlock caído: el vídeo sigue igual)
            lista, estado, ttl = (hit[1] if hit else []), "sin red", CACHE_ERROR
        self.cache.pop(vid, None)
        self.cache[vid] = (now + ttl, lista, estado)
        while len(self.cache) > 300:
            self.cache.pop(next(iter(self.cache)))
        self.consulta = estado
        return lista

    def _saltar(self, d: dict[str, Any], sesion: dict, teclas_ok: bool, pos: float) -> None:
        k = d["clave"]
        self.v.setdefault("tramo", {})[k] = (pos, d["hasta"])  # 0.66: para el historial
        self.v.setdefault("cats", {})[k] = tuple(d.get("categorias") or ("sponsor",))  # 0.73
        p = self.pendiente
        if p and p["clave"] == k and self.clock() - p["t"] < VERIFICAR * 2:
            return  # Windows ya lo aceptó: se espera a que se note, nunca dos saltos
        intentos = self.v.setdefault("intentos", {})
        aceptados = self.v.setdefault("aceptados", set())
        n = intentos.get(k, 0)
        if n >= INTENTOS:
            self.v["hechos"].add(k)
            self.error = "No se pudo saltar este patrocinio"
            return
        por_windows = bool(sesion.get("saltar")) and n < 2
        n10, n5 = pasos(d["hasta"] - pos)
        # Si Windows ya aceptó un salto de este tramo, nunca teclas encima: se avanzaría de más.
        por_teclas = teclas_ok and bool(n10 or n5) and k not in aceptados
        if not (por_windows or por_teclas):
            self.error = ("Este navegador no deja saltar sin traer YouTube delante" if not sesion.get("saltar")
                          else "Windows no confirmó el salto")
            return
        intentos[k] = n + 1
        if por_windows:
            r = self._pedir(c="salta", app=str(sesion.get("app", "")), titulo=str(sesion.get("titulo", "")),
                            desde=round(d["desde"], 2), hasta=round(d["hasta"], 2))
            antes = _num(r.get("antes"), pos)
            if r.get("verificado"):
                self._hecho(k, d["hasta"] - antes, "windows")
                return
            if r.get("aceptado"):
                aceptados.add(k)
                self.pendiente = {"clave": k, "hasta": d["hasta"], "t": self.clock(),
                                  "seg": d["hasta"] - antes, "metodo": "windows"}
                return
            if r.get("fuera"):
                intentos[k] = n  # ya no estaba dentro (pausa, vuelta atrás): no cuenta
                return
            if not por_teclas:
                return
        if self.keys(self.v.get("hwnd", ""), n10, n5):
            self.v["hechos"].add(k)  # con teclas, una sola vez: nunca avanzar de más
            salto = n10 * 10 + n5 * 5
            self.pendiente = {"clave": k, "hasta": pos + salto, "t": self.clock(), "seg": salto, "metodo": "teclas"}

    def _comprueba(self, pos: float) -> None:
        p = self.pendiente
        assert p is not None
        margen = 2.0 if p["metodo"] == "teclas" else 0.5
        if pos >= p["hasta"] - margen:
            self.pendiente = None
            self._hecho(p["clave"], p["seg"], p["metodo"])
        elif self.clock() - p["t"] > VERIFICAR * 3:
            self.pendiente = None  # no llegó: Windows lo reintenta; con teclas no se repite

    def _hecho(self, k: str, segundos: float, metodo: str) -> None:
        self.v.setdefault("hechos", set()).add(k)
        self.metodo, self.error = metodo, ""
        cats = tuple(self.v.get("cats", {}).get(k) or ("sponsor",))
        que = nombre_de(cats)
        self.contar(segundos=max(0.0, segundos), categorias=cats)
        self.ultimo_salto = {"categorias": list(cats), "nombre": que, "t": round(time.time(), 1),
                             "seg": round(max(0.0, segundos), 1)}
        try:  # 0.66: al historial del Panel (0.73: con la categoría)
            import historial

            desde, hasta = self.v.get("tramo", {}).get(k, (None, None))
            historial.patrocinio_saltado(str(self.v.get("titulo") or ""), str(self.v.get("vid") or ""),
                                         desde, hasta, max(0.0, segundos), metodo, categoria=cats[0])
        except Exception:  # noqa: BLE001 (el historial nunca rompe el salto)
            pass
        try:
            print(self.MESSAGE.format(que=que), flush=True)
        except Exception:  # noqa: BLE001 (sin consola o consola cp1252)
            pass


def _find_youtube_row() -> dict | None:
    import control

    if control.SYSTEM != "Windows":
        return None
    with control._lock:
        row = control._find_youtube_unlocked()
    return dict(row) if row else None


def _teclas(hwnd: str, n10: int, n5: int) -> bool:
    """Solo si YouTube ya está delante: nunca trae la ventana ni toca el ratón."""
    import control

    if control.SYSTEM != "Windows" or not hwnd:
        return False
    with control._lock:
        if not control._is_foreground(int(hwnd)):
            return False
        for _ in range(n10):
            control._yt_keys(["l"])
            time.sleep(0.03)
        for _ in range(n5):
            control._yt_keys(["right"])
            time.sleep(0.03)
    return True


PATROCINIOS = Patrocinios(find=_find_youtube_row)


def status() -> dict[str, Any]:
    return PATROCINIOS.status()


def watch() -> bool:
    if "unittest" in sys.modules or "pytest" in sys.modules:
        return False
    if os.environ.get("LAZO_SIN_PATROCINIOS") == "1":
        PATROCINIOS.disabled = True
        return False
    if os.environ.get("LAZO_CON_PATROCINIOS") == "1":
        PATROCINIOS.on = True  # 0.65: solo esta sesión; no se guarda en ajustes.json
    return PATROCINIOS.start()
