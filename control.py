"""Control del PC para Lazo. Best-effort en Windows, macOS y Linux."""

from __future__ import annotations

import collections
import ctypes
import hashlib
import os
import json
import math
import platform
import secrets
import shutil
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

SYSTEM = platform.system()  # Windows, Darwin, Linux

_lock = threading.Lock()
_mouse_lock = threading.Lock()
_clip_lock = threading.Lock()
_mouse = None
_keyboard = None
_cursor_mode = "normal"
_saved_cursor: Any = None
_history_path = Path(__file__).with_name("clipboard-history.json")
_history: list[dict[str, Any]] = []
_history_loaded = False
_clip_seq = 0
_CLIP_LIMIT = 40
_CLIP_CHARS = 8000


class ControlError(Exception):
    pass


_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # 0.45: sin consolas que parpadean


def _run(cmd: list[str], timeout: float = 4) -> subprocess.CompletedProcess[str]:
    """Ejecuta sin colgar LaZoo: si el programa no contesta a tiempo, cuenta como fallo."""
    try:
        return _run_raw(cmd, timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "tiempo agotado")
    except OSError as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


def _run_raw(cmd: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        stdin=subprocess.DEVNULL,
        creationflags=_NO_WINDOW,
    )


def _which(name: str) -> bool:
    return shutil.which(name) is not None


def _input():
    global _mouse, _keyboard
    if _mouse is not None and _keyboard is not None:
        return _mouse, _keyboard
    try:
        from pynput.keyboard import Controller as KeyController
        from pynput.mouse import Controller as MouseController
    except ImportError as exc:
        raise ControlError(
            "Falta pynput. En el PC: pip install -r requirements.txt"
        ) from exc
    _mouse = MouseController()
    _keyboard = KeyController()
    return _mouse, _keyboard


def _button(name: str):
    _input()
    from pynput.mouse import Button

    if name == "right":
        return Button.right
    if name == "middle":
        return Button.middle
    return Button.left


def _special(name: str):
    _input()
    from pynput.keyboard import Key

    table = {
        "Enter": Key.enter,
        "Backspace": Key.backspace,
        "Tab": Key.tab,
        "Escape": Key.esc,
        "ArrowLeft": Key.left,
        "ArrowRight": Key.right,
        "ArrowUp": Key.up,
        "ArrowDown": Key.down,
        " ": Key.space,
        "Delete": Key.delete,
        "Home": Key.home,
        "End": Key.end,
        "Shift": Key.shift,
        "Control": Key.ctrl,
        "Alt": Key.alt,
    }
    return table.get(name)


_move_hook = None


def set_move_hook(fn) -> None:
    global _move_hook
    _move_hook = fn


def backend_for(system: str, display: str | None, wayland: str | None) -> str:
    if system == "Windows":
        return "sendinput"
    if system == "Darwin":
        return "cgevent"
    if system == "Linux":
        if display:
            return "xtest"
        if wayland:
            return "ydotool"
        return "none"
    return "pynput"


def move_mouse(dx: int, dy: int) -> None:
    dx = max(-4000, min(4000, int(dx)))
    dy = max(-4000, min(4000, int(dy)))
    if dx == 0 and dy == 0:
        return
    _mark_injected()
    if _move_hook is not None:
        _move_hook(dx, dy)
        return
    if CONTINUO.on:
        CONTINUO.push(dx, dy)
        return
    if SMOOTHER.on and SMOOTHER.push(dx, dy):
        return
    with _mouse_lock:
        _dispatch_move(dx, dy)


def split_move(dx: int, dy: int, parts: int) -> list[tuple[int, int]]:
    """0.47: reparte (dx, dy) en `parts` pasos enteros que suman exactamente lo mismo."""
    out, px, py = [], 0, 0
    for i in range(1, parts + 1):
        nx, ny = round(dx * i / parts), round(dy * i / parts)
        if nx != px or ny != py:
            out.append((nx - px, ny - py))
        px, py = nx, ny
    return out


class Smoother:
    """0.47: suavizado opcional en el PC. Cada movimiento se reparte en 2-4 micro-pasos
    cada STEP s. Sin retraso acumulado: si llega otro antes de acabar, lo pendiente se
    aplica de golpe primero. Clic, arrastre y rueda llaman a flush() antes, así el orden se
    mantiene."""

    STEP = 0.005

    def __init__(self) -> None:
        self.on = False
        self._cv = threading.Condition()
        self._steps: list[tuple[int, int]] = []
        self._thread: threading.Thread | None = None

    def set(self, on: bool) -> bool:
        on = bool(on)
        if on != self.on and SYSTEM == "Windows":
            # 0.48: sin esto Windows duerme ~15 ms en vez de 5. Solo mientras está activo.
            try:
                winmm = ctypes.windll.winmm
                (winmm.timeBeginPeriod if on else winmm.timeEndPeriod)(1)
            except Exception:
                pass
        self.on = on
        if not self.on:
            self.flush()
        return self.on

    def push(self, dx: int, dy: int) -> bool:
        parts = max(1, min(4, max(abs(dx), abs(dy))))
        if parts == 1:
            self.flush()
            return False
        with self._cv:
            rest = self._steps
            self._steps = []
            if rest:
                rx, ry = sum(a for a, _ in rest), sum(b for _, b in rest)
                with _mouse_lock:
                    _dispatch_move(rx, ry)
            first, *more = split_move(dx, dy, parts)
            with _mouse_lock:
                _dispatch_move(*first)
            self._steps = more
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="lazoo-suave", daemon=True)
                self._thread.start()
            self._cv.notify()
        return True

    def flush(self) -> None:
        with self._cv:
            rest = self._steps
            self._steps = []
        if rest:
            rx, ry = sum(a for a, _ in rest), sum(b for _, b in rest)
            if rx or ry:
                with _mouse_lock:
                    _dispatch_move(rx, ry)

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._steps:
                    if not self._cv.wait(30):
                        self._thread = None
                        return
                step = self._steps.pop(0)
            try:
                with _mouse_lock:
                    _dispatch_move(*step)
            except Exception:
                pass
            _pause(self.STEP)


def _pause(seconds: float) -> None:
    """Pausa corta y precisa: duerme casi todo y apura el último milisegundo."""
    end = time.perf_counter() + seconds
    if seconds > 0.0015:
        time.sleep(seconds - 0.0015)
    while time.perf_counter() < end:
        time.sleep(0)


SMOOTHER = Smoother()


class Continuo:
    """0.50: movimiento continuo. Lo que llega por la red (a ráfagas) se guarda y se
    reparte en pasos pequeños cada TICK s, vaciando la cola en ~`buffer` s. El colchón
    se adapta: sube si hay huecos/ráfagas, baja despacio si va estable. Nunca se pierde
    desplazamiento: se sueltan enteros y el resto se guarda. Tope: si lo pendiente supera
    MAX_LAG s de colchón, se vacía más deprisa.

    0.51: predicción. Se estima la velocidad del dedo (px/s, ventana corta VEL_WIN + EMA).
    Si la cola se vacía y no llega nada, se sigue moviendo a esa velocidad, frenando con
    exp(-t/PRED_TAU) y como mucho PRED_MAX s. Lo predicho (enteros) es una «deuda»: al
    llegar datos reales se descuenta de ellos, así que la suma enviada es exactamente la
    real (sin deriva). Si el dedo se paró de verdad (fin de toque o SETTLE s sin datos), la
    deuda se devuelve con suavidad. Con `pred` apagado, todo es idéntico a 0.50.
    Inercia (opcional): al soltar el dedo, desliza con fricción como un touchpad.

    0.53: ajuste fino (`aplicar`). Corrección suave (lo predicho de más se devuelve en 2-4
    pasos iguales), mezcla al llegar datos reales tras predecir, interpolación lineal en
    pasos de TICK solo tras un hueco, colchón adaptativo con rango o fijo, frecuencia de
    pasos, curva de la predicción, sub-píxel con redondeo estable, límite de cola y modo
    «reciente primero». Con los valores de clase (preset «Como 0.50» + predicción) todo es
    como en 0.52 (salvo que, tras devolver lo predicho, no vuelve a predecir hasta que
    lleguen datos); con «Como 0.50», idéntico a 0.50. La contabilidad no cambia: deriva 0."""

    TICK = 0.005          # 200 Hz
    MIN_BUF, MAX_BUF, DEFAULT_BUF = 0.010, 0.120, 0.030
    MAX_LAG = 0.150
    VEL_WIN = 0.20        # ventana de la velocidad
    VEL_ALPHA = 0.5       # EMA de la velocidad
    PRED_MAX = 0.150      # extrapolación máxima tras vaciarse la cola
    PRED_TAU = 0.090      # decaimiento de la velocidad predicha
    PRED_MIN_SPEED = 30.0 # px/s; por debajo no se predice
    SETTLE = 0.35         # sin datos tanto tiempo: el dedo se paró, se devuelve la deuda
    RETURN_TIME = 0.06    # la devolución se reparte en ~60 ms
    INERCIA = {"poca": 0.10, "media": 0.20, "mucha": 0.35}  # constante de fricción (s)
    GLIDE_MAX = 1.5
    GLIDE_STOP = 15.0     # px/s
    INTERP_GAP = 0.030    # 0.53: hueco a partir del cual se interpola

    def __init__(self, dispatch=None, clock=None) -> None:
        self.on = True
        self.pred = True
        self.inercia = None  # None o "poca"/"media"/"mucha"
        self.buffer = self.DEFAULT_BUF
        self._dispatch = dispatch
        self._clock = clock or time.perf_counter
        self._cv = threading.Condition()
        self._px = 0.0   # pendiente (float, con sub-píxeles de los pasos)
        self._py = 0.0
        self._last_in = None
        self._last_tick = None
        self._rate = 0.0  # px/s de entrada (últimos 0,5 s), para el tope de retraso
        self._hist = collections.deque()
        self._thread = None
        self._steps = 0
        self._sec_start = self._clock()
        self._stats = {"pasos_s": 0, "cola_max_ms": 0.0}
        self._qmax = 0.0
        # 0.51
        self._vhist = collections.deque()
        self._vx = self._vy = 0.0
        self._empty_at = None
        self._fx = self._fy = 0.0     # sub-píxeles de lo predicho
        self._dbx = self._dby = 0.0   # deuda: predicho y aún no cubierto por datos reales
        self._returning = False
        self._ended = False
        self._real_x = self._real_y = 0.0
        self._out_x = self._out_y = 0.0
        self._glide = None  # (vx, vy, t0, tau)
        self._gfx = self._gfy = 0.0
        self._glide_x = self._glide_y = 0.0
        self._pred_px = 0.0
        self._errs: list[float] = []
        self._stats2 = {"predichos_px_s": 0, "error_medio_px": 0.0, "error_max_px": 0.0}
        # 0.53: ajuste fino (por defecto, el comportamiento de 0.52)
        self.corr_pasos = 0
        self.mezcla = 0.0
        self.interp = False
        self.subpixel = False
        self.reciente = False
        self.hires = True
        self.colchon_fijo = False
        self.preset = "personalizado"
        self.ajustes = dict(PRESETS["como050"], prediccion=True)
        self._corr = 0
        self._lin = 0
        self._settled = False
        self._cx = self._cy = 0.0
        self._n_corr = self._n_interp = 0
        self._stats3 = {"correcciones_s": 0, "pasos_corr_s": 0, "interpolados_s": 0}
        self._n_corr_ev = 0

    def aplicar(self, opts: dict, preset: str | None = None) -> dict:
        """0.53: aplica un ajuste ya validado (ver validar_ajuste)."""
        with self._cv:
            a = dict(self.ajustes)
            a.update(opts)
            self.ajustes = a
            self.corr_pasos = int(a["correccion_pasos"])
            self.mezcla = a["mezcla_ms"] / 1000
            self.interp = bool(a["interpolacion"])
            self.subpixel = bool(a["subpixel"])
            self.reciente = bool(a["reciente_primero"])
            self.hires = bool(a["alta_resolucion"])
            self.TICK = 1.0 / a["frecuencia_hz"]
            self.MIN_BUF = a["colchon_min_ms"] / 1000
            self.MAX_BUF = a["colchon_max_ms"] / 1000
            self.colchon_fijo = a["colchon_modo"] == "fijo"
            if self.colchon_fijo:
                self.buffer = a["colchon_fijo_ms"] / 1000
            else:
                self.buffer = max(self.MIN_BUF, min(self.MAX_BUF, self.buffer))
            self.MAX_LAG = a["cola_max_ms"] / 1000
            self.PRED_MAX = a["pred_max_ms"] / 1000
            self.PRED_TAU = a["pred_frenado_ms"] / 1000
            self.preset = preset if preset in PRESETS else "personalizado"
            self._cx = self._cy = 0.0
            if not self.corr_pasos:
                self._corr = 0
            if not (self.interp or self.mezcla):
                self._lin = 0
        if "prediccion" in opts:
            self.set_pred(opts["prediccion"])
        if "inercia" in opts:
            self.set_inercia(opts["inercia"])
        return self.ajuste()

    def ajuste(self) -> dict:
        a = dict(self.ajustes)
        a["prediccion"] = self.pred
        a["inercia"] = self.inercia
        return {"preset": self.preset, "opciones": a}

    def _send(self, dx: int, dy: int) -> None:
        self._out_x += dx
        self._out_y += dy
        if self._dispatch is not None:
            self._dispatch(dx, dy)
            return
        with _mouse_lock:
            _dispatch_move(dx, dy)

    def set(self, on: bool) -> bool:
        self.on = bool(on)
        if not self.on:
            self.flush()
        return self.on

    def set_pred(self, on: bool) -> bool:
        with self._cv:
            self.pred = bool(on)
            if not self.pred:
                self._settle_debt()
        return self.pred

    def set_inercia(self, level) -> str | None:
        with self._cv:
            self.inercia = level if level in self.INERCIA else None
            if self.inercia is None:
                self._glide = None
        return self.inercia

    def pending(self) -> tuple[float, float]:
        return self._px, self._py

    def velocity(self) -> tuple[float, float]:
        return self._vx, self._vy

    def drift(self) -> float:
        """Lo enviado + lo pendiente - deuda frente a la suma real (sin deslizamiento)."""
        ex = self._out_x - self._glide_x + self._px - self._dbx - self._real_x
        ey = self._out_y - self._glide_y + self._py - self._dby - self._real_y
        return math.hypot(ex, ey)

    def _note_err(self, e: float) -> None:
        self._errs.append(e)
        if len(self._errs) > 200:
            del self._errs[:100]

    def _settle_debt(self) -> None:
        """Devuelve lo predicho de más (el dedo se paró). Dentro de _cv."""
        self._settled = True  # 0.53: no se vuelve a predecir hasta que lleguen datos
        if self._dbx or self._dby:
            self._note_err(math.hypot(self._dbx, self._dby))
            self._px -= self._dbx
            self._py -= self._dby
            self._dbx = self._dby = 0.0
            self._returning = abs(self._px) + abs(self._py) >= 0.5
            if self._returning and self.corr_pasos:
                self._returning = False
                self._corr = self.corr_pasos  # 0.53: corrección suave
                self._lin = 0
                self._n_corr_ev += 1
        self._fx = self._fy = 0.0

    def push(self, dx: int, dy: int, now: float | None = None, start: bool = True) -> None:
        now = self._clock() if now is None else now
        with self._cv:
            # tocar de nuevo cancela la inercia; lo que llega justo tras el fin (la red va
            # detrás del aviso) se suma sin cancelarla
            if self._glide is not None and now - self._glide[2] < 0.10:
                pass
            else:
                self._glide = None
                self._ended = False
            self._real_x += dx
            self._real_y += dy
            gap = None if self._last_in is None else now - self._last_in
            had_debt = bool(self._dbx or self._dby)
            if self._last_in is not None and self.colchon_fijo:
                pass
            elif self._last_in is not None:
                if gap > self.buffer * 1.2 and gap < 0.5:
                    self.buffer = min(self.MAX_BUF, self.buffer * 0.6 + gap * 0.5)
                elif gap < 0.5:
                    self.buffer = max(self.MIN_BUF, self.buffer * 0.995)
            else:
                self._hist.clear()
            # 0.51: velocidad del dedo (px/s) en ventana corta + EMA
            if self._last_in is None or now - self._last_in > 0.3:
                self._vhist.clear()
                self._vx = self._vy = 0.0
            self._vhist.append((now, dx, dy))
            while self._vhist and now - self._vhist[0][0] > self.VEL_WIN:
                self._vhist.popleft()
            span = max(0.05, min(self.VEL_WIN, now - self._vhist[0][0] + 1 / 60))
            ivx = sum(v[1] for v in self._vhist) / span
            ivy = sum(v[2] for v in self._vhist) / span
            a = self.VEL_ALPHA
            self._vx = self._vx * (1 - a) + ivx * a
            self._vy = self._vy * (1 - a) + ivy * a
            self._last_in = now
            self._hist.append((now, abs(dx) + abs(dy)))
            while self._hist and now - self._hist[0][0] > 0.5:
                self._hist.popleft()
            self._rate = sum(m for _, m in self._hist) / 0.5
            if abs(self._px) + abs(self._py) < 0.5:
                self._last_tick = now  # arranca de cero, sin «deuda» de tiempo
            # 0.51: lo real descuenta lo ya predicho (contabilidad exacta)
            if self._dbx or self._dby:
                ex = max(0.0, abs(self._dbx) - abs(dx)) if (self._dbx > 0) == (dx > 0) else abs(self._dbx)
                ey = max(0.0, abs(self._dby) - abs(dy)) if (self._dby > 0) == (dy > 0) else abs(self._dby)
                self._note_err(math.hypot(ex, ey))
            dbx, dby = self._dbx, self._dby
            self._px += dx - self._dbx
            self._py += dy - self._dby
            self._dbx = self._dby = 0.0
            self._fx = self._fy = 0.0
            self._empty_at = None
            self._returning = False
            self._settled = False
            # 0.53: cómo se reparte lo que queda
            self._corr = 0
            if had_debt and self.corr_pasos and (self._px * dbx < 0 or self._py * dby < 0):
                self._corr = self.corr_pasos  # se predijo de más: vuelve en 2-4 pasos
                self._lin = 0
                self._n_corr_ev += 1
            elif had_debt and self.mezcla > 0:
                self._lin = max(1, round(self.mezcla / self.TICK))
            elif self.interp and gap is not None and self.INTERP_GAP < gap < 0.5:
                self._lin = max(self._lin, math.ceil(min(gap, self.MAX_BUF) / self.TICK - 1e-9))
            if start and (self._thread is None or not self._thread.is_alive()):
                self._thread = threading.Thread(target=self._run, name="lazoo-continuo", daemon=True)
                self._thread.start()
            self._cv.notify()

    def touch_end(self, now: float | None = None, start: bool = True) -> None:
        """0.51: el móvil avisa de que se levantó el dedo."""
        now = self._clock() if now is None else now
        with self._cv:
            self._ended = True
            self._settle_debt()
            sp = math.hypot(self._vx, self._vy)
            recent = self._last_in is not None and now - self._last_in < 0.12
            if self.on and self.inercia and recent and sp > 60:
                self._glide = (self._vx, self._vy, now, self.INERCIA[self.inercia])
                self._gfx = self._gfy = 0.0
                self._last_tick = now if self._last_tick is None else self._last_tick
                if start and (self._thread is None or not self._thread.is_alive()):
                    self._thread = threading.Thread(target=self._run, name="lazoo-continuo", daemon=True)
                    self._thread.start()
            self._cv.notify()

    def cancel_glide(self) -> None:
        with self._cv:
            self._glide = None

    def _wants(self, now: float) -> bool:
        if abs(self._px) + abs(self._py) >= 0.5 or self._glide is not None:
            return True
        if self._dbx or self._dby:
            return True  # hay que vigilar SETTLE
        return self.pred and self._last_in is not None and not self._ended and now - self._last_in < self.PRED_MAX + 0.25

    def _roll_stats(self, now: float) -> None:
        if now - self._sec_start >= 1.0:
            el = now - self._sec_start
            errs = self._errs
            self._stats = {"pasos_s": round(self._steps / el), "cola_max_ms": round(self._qmax, 1)}
            self._stats2 = {"predichos_px_s": round(self._pred_px / el),
                            "error_medio_px": round(sum(errs) / len(errs), 1) if errs else 0.0,
                            "error_max_px": round(max(errs), 1) if errs else 0.0}
            self._stats3 = {"correcciones_s": round(self._n_corr_ev / el), "pasos_corr_s": round(self._n_corr / el),
                            "interpolados_s": round(self._n_interp / el)}
            self._n_corr_ev = self._n_corr = self._n_interp = 0
            self._errs = []
            self._steps, self._qmax, self._sec_start, self._pred_px = 0, 0.0, now, 0.0

    def _extra(self, now: float) -> tuple[int, int, bool]:
        """0.51: paso predicho o de inercia con la cola vacía. Dentro de _cv."""
        dt = min(0.03, max(0.0, now - (self._last_tick if self._last_tick is not None else now)) or self.TICK)
        self._last_tick = now
        if self._glide is not None:
            gvx, gvy, t0, tau = self._glide
            f = math.exp(-(now - t0) / tau)
            if now - t0 > self.GLIDE_MAX or math.hypot(gvx, gvy) * f < self.GLIDE_STOP:
                self._glide = None
                return 0, 0, False
            self._gfx += gvx * f * dt
            self._gfy += gvy * f * dt
            ix, iy = int(self._gfx), int(self._gfy)
            self._gfx -= ix
            self._gfy -= iy
            self._glide_x += ix
            self._glide_y += iy
            return ix, iy, True
        if (self._dbx or self._dby) and self._last_in is not None and now - self._last_in > self.SETTLE:
            self._settle_debt()
            return 0, 0, False
        if not self.pred or self._ended or self._last_in is None or self._settled:
            return 0, 0, False
        if self._empty_at is None:
            self._empty_at = now
        t = now - self._empty_at
        if t > self.PRED_MAX or now - self._last_in > self.PRED_MAX + 0.25:
            return 0, 0, False
        sp = math.hypot(self._vx, self._vy)
        if sp < self.PRED_MIN_SPEED:
            return 0, 0, False
        f = math.exp(-t / self.PRED_TAU)
        self._fx += self._vx * f * dt
        self._fy += self._vy * f * dt
        ix, iy = int(self._fx), int(self._fy)
        self._fx -= ix
        self._fy -= iy
        self._dbx += ix
        self._dby += iy
        self._pred_px += abs(ix) + abs(iy)
        return ix, iy, True

    def tick(self, now: float | None = None) -> tuple[int, int]:
        """Suelta un paso. Devuelve lo enviado (enteros)."""
        now = self._clock() if now is None else now
        with self._cv:
            px, py = self._px, self._py
            mag = abs(px) + abs(py)
            if mag < 0.5:
                ix, iy, extra = self._extra(now)
                if extra:
                    self._steps += 1
                self._roll_stats(now)
                if not (ix or iy):
                    return 0, 0
            else:
                self._empty_at = None
                dt = max(0.0, now - (self._last_tick if self._last_tick is not None else now)) or self.TICK
                self._last_tick = now
                buf = self.buffer
                # tope: si a este ritmo la cola equivale a más de MAX_LAG, vaciar más deprisa
                lagged = self._rate > 0 and mag / self._rate > self.MAX_LAG and not self._corr
                if lagged:
                    # 0.53: con corrección suave, el vaciado rápido también va en 2-4 pasos
                    buf = min(buf, self.TICK * max(1, self.corr_pasos))
                    self._lin = self._corr = 0
                if self._returning:
                    buf = self.RETURN_TIME
                frac = min(1.0, dt / buf) if buf > 0 else 1.0
                idle = self._last_in is None or now - self._last_in > 0.25
                if (idle and not self._returning) or mag * frac < 1.0 and mag <= 2:
                    frac = 1.0
                if lagged and self.reciente:
                    frac = 1.0  # 0.53: reciente primero, se salta lo viejo de golpe
                n = 0
                if self._corr > 0 and not (lagged and self.reciente):
                    n, self._corr = self._corr, self._corr - 1
                    self._n_corr += 1
                    frac = min(frac, 0.999)
                elif self._lin > 0 and not idle:
                    n, self._lin = self._lin, self._lin - 1
                    self._n_interp += 1
                sx, sy = px * frac, py * frac
                ix, iy = int(round(sx)), int(round(sy))
                if n:
                    ix, iy = _rnd(px / n), _rnd(py / n)
                elif self.subpixel and frac < 1.0:
                    # 0.53: acumulador de sub-píxeles y redondeo estable (sin «0,5 al par»)
                    self._cx += sx
                    self._cy += sy
                    ix, iy = _rnd(self._cx), _rnd(self._cy)
                    ix = max(-_rnd(abs(px)), min(_rnd(abs(px)), ix))
                    iy = max(-_rnd(abs(py)), min(_rnd(abs(py)), iy))
                    self._cx -= ix
                    self._cy -= iy
                if frac >= 1.0:
                    ix, iy = int(round(px)), int(round(py))
                    self._cx = self._cy = 0.0
                    self._lin = self._corr = 0
                if ix == 0 and iy == 0 and (n or self.subpixel):
                    pass
                elif ix == 0 and iy == 0:
                    # avanza al menos un píxel en el eje más largo, para no estancarse
                    if abs(px) >= abs(py):
                        ix = 1 if px > 0 else -1
                    else:
                        iy = 1 if py > 0 else -1
                self._px -= ix
                self._py -= iy
                if abs(self._px) + abs(self._py) < 0.5:
                    self._returning = False
                    self._lin = self._corr = 0
                    self._cx = self._cy = 0.0
                if self._rate > 0:
                    self._qmax = max(self._qmax, (abs(self._px) + abs(self._py)) / self._rate * 1000)
                self._steps += 1
                self._roll_stats(now)
        if ix or iy:
            self._send(ix, iy)
        return ix, iy

    def flush(self) -> None:
        """Clic, arrastre y rueda: aplica lo pendiente real, sin predicción ni inercia."""
        with self._cv:
            self._glide = None
            self._settle_debt()
            self._returning = False
            self._corr = self._lin = 0
            self._cx = self._cy = 0.0
            ix, iy = int(round(self._px)), int(round(self._py))
            self._px -= ix
            self._py -= iy
        if ix or iy:
            self._send(ix, iy)

    def status(self) -> dict:
        now = self._clock()
        st = dict(self._stats)
        st2 = dict(self._stats2)
        if now - self._sec_start > 2.0:
            st = {"pasos_s": 0, "cola_max_ms": 0.0}
            st2 = {"predichos_px_s": 0, "error_medio_px": 0.0, "error_max_px": 0.0}
        st3 = dict(self._stats3) if now - self._sec_start <= 2.0 else {"correcciones_s": 0, "pasos_corr_s": 0, "interpolados_s": 0}
        return {"on": self.on, "colchon_ms": round(self.buffer * 1000, 1), **st,
                "prediccion": self.pred, "inercia": self.inercia, **st2,
                "deriva_px": round(self.drift(), 2),
                "colchon_min_ms": round(self.MIN_BUF * 1000), "colchon_max_ms": round(self.MAX_BUF * 1000),
                "colchon_modo": "fijo" if self.colchon_fijo else "adaptativo", **st3, **self.ajuste()}

    def _run(self) -> None:
        hi = False
        try:
            while True:
                with self._cv:
                    while not self._wants(self._clock()):
                        if hi:
                            _hires(False)
                            hi = False
                        if not self._cv.wait(30):
                            self._thread = None
                            return
                if not hi and self.hires:
                    _hires(True)
                    hi = True
                try:
                    self.tick()
                except Exception:
                    pass
                _pause(self.TICK)
        finally:
            if hi:
                _hires(False)


def _hires(on: bool) -> None:
    """Temporizador de 1 ms en Windows solo mientras hay movimiento pendiente."""
    if SYSTEM != "Windows":
        return
    try:
        winmm = ctypes.windll.winmm
        (winmm.timeBeginPeriod if on else winmm.timeEndPeriod)(1)
    except Exception:
        pass


def _rnd(v: float) -> int:
    """Redondeo estable: siempre la mitad hacia fuera (round() de Python va «al par»)."""
    return int(math.floor(v + 0.5)) if v >= 0 else -int(math.floor(-v + 0.5))


# 0.53: ajuste fino del ratón. Rangos (mín, máx) o valores permitidos.
AJUSTE_RANGOS: dict[str, Any] = {
    "correccion_pasos": (0, 2, 3, 4),
    "mezcla_ms": (0, 60),
    "interpolacion": bool,
    "colchon_modo": ("adaptativo", "fijo"),
    "colchon_min_ms": (10, 60),
    "colchon_max_ms": (15, 150),
    "colchon_fijo_ms": (10, 80),
    "frecuencia_hz": (125, 200, 250, 500),
    "pred_max_ms": (50, 300),
    "pred_frenado_ms": (30, 200),
    "subpixel": bool,
    "cola_max_ms": (60, 300),
    "reciente_primero": bool,
    "alta_resolucion": bool,
    "tasa_envio": (30, 60, 90, 120),
    "prediccion": bool,
    "inercia": (None, "poca", "media", "mucha"),
}
_BASE = {"correccion_pasos": 0, "mezcla_ms": 0, "interpolacion": False, "colchon_modo": "adaptativo",
         "colchon_min_ms": 10, "colchon_max_ms": 120, "colchon_fijo_ms": 30, "frecuencia_hz": 200,
         "pred_max_ms": 150, "pred_frenado_ms": 90, "subpixel": False, "cola_max_ms": 150,
         "reciente_primero": False, "alta_resolucion": True, "tasa_envio": 60}
PRESETS: dict[str, dict[str, Any]] = {
    "equilibrado": {**_BASE, "correccion_pasos": 3, "mezcla_ms": 30, "interpolacion": True,
                    "colchon_min_ms": 15, "colchon_max_ms": 40, "subpixel": True, "prediccion": True},
    "fluidez": {**_BASE, "correccion_pasos": 4, "mezcla_ms": 50, "interpolacion": True,
                "colchon_min_ms": 25, "colchon_max_ms": 60, "frecuencia_hz": 250, "subpixel": True, "cola_max_ms": 200, "prediccion": True},
    "retraso": {**_BASE, "correccion_pasos": 2, "colchon_min_ms": 10, "colchon_max_ms": 20,
                "frecuencia_hz": 500, "pred_max_ms": 100, "pred_frenado_ms": 60, "subpixel": True,
                "cola_max_ms": 100, "reciente_primero": True, "tasa_envio": 90, "prediccion": True},
    "como050": {**_BASE, "prediccion": False, "inercia": None},
}


def validar_ajuste(opts: Any) -> dict:
    """0.53: comprueba tipos y rangos; cualquier cosa rara es un error, no se corrige sola."""
    if not isinstance(opts, dict) or len(opts) > len(AJUSTE_RANGOS):
        raise ControlError("Ajuste no válido")
    out: dict[str, Any] = {}
    for k, v in opts.items():
        rule = AJUSTE_RANGOS.get(k)
        if rule is None:
            raise ControlError(f"Opción desconocida: {str(k)[:40]}")
        if rule is bool:
            if not isinstance(v, bool):
                raise ControlError(f"{k}: debe ser sí o no")
        elif k in ("mezcla_ms", "colchon_min_ms", "colchon_max_ms", "colchon_fijo_ms", "pred_max_ms",
                   "pred_frenado_ms", "cola_max_ms"):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not rule[0] <= v <= rule[1]:
                raise ControlError(f"{k}: fuera de rango ({rule[0]}-{rule[1]})")
            v = int(round(v))
        elif isinstance(v, bool) or v not in rule:
            raise ControlError(f"{k}: valor no permitido")
        out[k] = v
    return out


def set_ajuste(body: Any) -> dict:
    """POST /api/ajuste: {preset: "equilibrado"} o {opciones: {...}} (se puede mandar ambos)."""
    if not isinstance(body, dict):
        raise ControlError("Ajuste no válido")
    preset = body.get("preset")
    if preset is None and body.get("opciones") is None:
        return CONTINUO.ajuste()  # solo consulta
    opts: dict[str, Any] = {}
    if preset is not None:
        if not isinstance(preset, str) or preset not in PRESETS:
            raise ControlError("Preset desconocido")
        opts.update(PRESETS[preset])
    if body.get("opciones") is not None:
        extra = validar_ajuste(body.get("opciones"))
        if extra:
            preset = None
        opts.update(extra)
    merged = {**CONTINUO.ajustes, **opts}
    if merged["colchon_min_ms"] > merged["colchon_max_ms"]:
        raise ControlError("El colchón mínimo no puede ser mayor que el máximo")
    return CONTINUO.aplicar(opts, preset)


CONTINUO = Continuo()
CONTINUO.aplicar(PRESETS["equilibrado"], "equilibrado")


def set_continuo(on) -> dict:
    return {"continuo": CONTINUO.set(bool(on))}


def set_prediccion(on) -> dict:
    return {"prediccion": CONTINUO.set_pred(bool(on))}


def set_inercia(level) -> dict:
    return {"inercia": CONTINUO.set_inercia(level if isinstance(level, str) else None)}


def touch_end() -> dict:
    CONTINUO.touch_end()
    return {"ok": True}


def set_smoothing(on) -> dict:
    return {"smooth": SMOOTHER.set(bool(on))}


def _dispatch_move(dx: int, dy: int) -> None:
    import os

    kind = backend_for(SYSTEM, os.environ.get("DISPLAY"), os.environ.get("WAYLAND_DISPLAY"))
    if kind == "sendinput" and _win_move(dx, dy):
        return
    if kind == "cgevent" and _mac_move(dx, dy):
        return
    if kind == "xtest" and _linux_xtest(dx, dy):
        return
    if kind == "ydotool":
        _ydotool(["mousemove", "-x", str(dx), "-y", str(dy)])
        return
    if kind == "none":
        raise ControlError("No hay sesión gráfica para mover el ratón")
    mouse, _keyboard = _input()
    mouse.move(dx, dy)


def _win_move(dx: int, dy: int) -> bool:
    extra = ctypes.c_size_t
    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", extra),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("mi", MOUSEINPUT)]

    event = INPUT()
    event.type = 0
    event.mi.dx = dx
    event.mi.dy = dy
    event.mi.dwFlags = 0x0001
    sent = ctypes.windll.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event))
    return sent == 1


def _mac_move(dx: int, dy: int) -> bool:
    try:
        quartz = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        core = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    except OSError:
        return False
    quartz.CGEventCreate.restype = ctypes.c_void_p
    quartz.CGEventCreate.argtypes = [ctypes.c_void_p]
    event = quartz.CGEventCreate(None)
    if not event:
        return False
    quartz.CGEventSetType(event, 5)
    quartz.CGEventSetIntegerValueField(event, 4, int(dx))
    quartz.CGEventSetIntegerValueField(event, 5, int(dy))
    quartz.CGEventPost(0, event)
    core.CFRelease(event)
    return True


_x_bundle = None
_x_failed = False


def _linux_xtest(dx: int, dy: int) -> bool:
    global _x_bundle, _x_failed
    if _x_failed:
        return False
    try:
        if _x_bundle is None:
            x11 = ctypes.CDLL("libX11.so.6")
            xtst = ctypes.CDLL("libXtst.so.6")
            x11.XOpenDisplay.restype = ctypes.c_void_p
            disp = x11.XOpenDisplay(None)
            if not disp:
                _x_failed = True
                return False
            _x_bundle = (x11, xtst, disp)
        x11, xtst, disp = _x_bundle
        xtst.XTestFakeRelativeMotionEvent(ctypes.c_void_p(disp), int(dx), int(dy), 0)
        x11.XFlush(ctypes.c_void_p(disp))
        return True
    except OSError:
        _x_failed = True
        return False


def mouse_click(button: str, count: int = 1) -> None:
    count = max(1, min(3, int(count)))
    CONTINUO.flush()
    SMOOTHER.flush()
    with _mouse_lock:
        mouse, _keyboard = _input()
        mouse.click(_button(button), count)


def mouse_down(button: str) -> None:
    CONTINUO.flush()
    SMOOTHER.flush()
    with _mouse_lock:
        mouse, _keyboard = _input()
        mouse.press(_button(button))


def mouse_up(button: str) -> None:
    CONTINUO.flush()
    SMOOTHER.flush()
    with _mouse_lock:
        mouse, _keyboard = _input()
        mouse.release(_button(button))


def scroll_steps(dy: int) -> int:
    dy = int(dy)
    if dy == 0:
        return 0
    steps = int(round(-dy / 90))
    if steps == 0:
        steps = -1 if dy > 0 else 1
    return max(-2, min(2, steps))


def scroll_mouse(dy: int) -> None:
    steps = scroll_steps(dy)
    if steps == 0:
        return
    CONTINUO.flush()
    SMOOTHER.flush()
    with _mouse_lock:
        mouse, _keyboard = _input()
        mouse.scroll(0, steps)


def press_key(name: str) -> None:
    if not isinstance(name, str) or not name or len(name) > 32:
        raise ControlError("tecla no válida")
    with _lock:
        _keyboard_send(name)


def type_text(text: str) -> None:
    if not isinstance(text, str):
        raise ControlError("texto no válido")
    text = text[:400]
    with _lock:
        _mouse, keyboard = _input()
        keyboard.type(text)


def _keyboard_send(name: str) -> None:
    _mouse, keyboard = _input()
    special = _special(name)
    if special is not None:
        keyboard.press(special)
        keyboard.release(special)
        return
    if len(name) == 1:
        keyboard.type(name)
        return
    raise ControlError("tecla no válida")


def _chord(parts: list[str]) -> None:
    _input()
    from pynput.keyboard import Key

    _mouse, keyboard = _input()
    held = []
    try:
        for part in parts:
            if part == "shift":
                keyboard.press(Key.shift)
                held.append(Key.shift)
            elif part in ("ctrl", "alt", "cmd"):
                key = getattr(Key, part)
                keyboard.press(key)
                held.append(key)
            elif part in ("left", "right"):
                key = getattr(Key, part)
                keyboard.press(key)
                keyboard.release(key)
            elif part == "up":
                keyboard.press(Key.up)
                keyboard.release(Key.up)
            elif part == "down":
                keyboard.press(Key.down)
                keyboard.release(Key.down)
            elif part == "escape":
                keyboard.press(Key.esc)
                keyboard.release(Key.esc)
            elif len(part) == 1:
                keyboard.press(part)
                keyboard.release(part)
            else:
                raise ControlError("atajo no válido")
    finally:
        for key in reversed(held):
            keyboard.release(key)


def system_volume(delta: int) -> str:
    delta = int(delta)
    with _lock:
        if SYSTEM == "Darwin":
            return _mac_volume(delta)
        if SYSTEM == "Windows":
            return _win_media_key(0xAD if delta == 0 else 0xAF if delta > 0 else 0xAE)
        return _linux_volume(delta)


def _mac_volume(delta: int) -> str:
    if delta == 0:
        script = "set volume output muted not (output muted of (get volume settings))"
    else:
        step = 6 if delta > 0 else -6
        script = (
            "set cur to output volume of (get volume settings)\n"
            f"set nxt to cur + {step}\n"
            "if nxt < 0 then set nxt to 0\n"
            "if nxt > 100 then set nxt to 100\n"
            "set volume output volume nxt without muting"
        )
    result = _run(["osascript", "-e", script])
    if result.returncode != 0:
        raise ControlError("macOS no dejó cambiar el volumen")
    return "Volumen del Mac"


def _linux_volume(delta: int) -> str:
    if _which("wpctl"):
        if delta == 0:
            cmd = ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"]
        else:
            cmd = ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%+" if delta > 0 else "5%-"]
        result = _run(cmd)
        if result.returncode == 0:
            return "Volumen"
    if _which("pactl"):
        if delta == 0:
            cmd = ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"]
        else:
            cmd = ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%" if delta > 0 else "-5%"]
        result = _run(cmd)
        if result.returncode == 0:
            return "Volumen"
    if _which("amixer"):
        if delta == 0:
            cmd = ["amixer", "-q", "sset", "Master", "toggle"]
        else:
            cmd = ["amixer", "-q", "sset", "Master", "5%+" if delta > 0 else "5%-"]
        result = _run(cmd)
        if result.returncode == 0:
            return "Volumen"
    _media_key("mute" if delta == 0 else "up" if delta > 0 else "down")
    return "Volumen (tecla multimedia)"


def _media_key(kind: str) -> None:
    _input()
    from pynput.keyboard import Key

    mapping = {
        "up": getattr(Key, "media_volume_up", None),
        "down": getattr(Key, "media_volume_down", None),
        "mute": getattr(Key, "media_volume_mute", None),
        "play": getattr(Key, "media_play_pause", None),
        "next": getattr(Key, "media_next", None),
        "prev": getattr(Key, "media_previous", None),
    }
    key = mapping.get(kind)
    if key is None:
        raise ControlError("este sistema no tiene esa tecla multimedia")
    _mouse, keyboard = _input()
    keyboard.press(key)
    keyboard.release(key)


def _win_media_key(vk: int) -> str:
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(vk, 0, 2, 0)
    return "Volumen de Windows"


def _display_ok() -> bool:
    if SYSTEM != "Linux":
        return True
    import os

    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _ydotool(args: list[str]) -> None:
    if not _which("ydotool"):
        raise ControlError("No hay sesión gráfica para mover el ratón")
    result = _run(["ydotool", *args])
    if result.returncode != 0:
        raise ControlError("ydotool no pudo mover el ratón")


def set_cursor_mode(mode: str) -> dict[str, Any]:
    global _cursor_mode
    if mode not in ("normal", "large", "huge"):
        raise ControlError("modo de cursor no válido")
    with _lock:
        detail = _apply_cursor_size(_cursor_target(mode))
        _cursor_mode = mode
    try:
        VIGILANTE.sync()  # 0.48: el gancho solo vive mientras el cursor no es normal
    except Exception:
        pass
    labels = {"normal": "Cursor normal", "large": "Cursor grande", "huge": "Cursor enorme"}
    return {"mode": mode, "label": labels[mode], "detail": detail}


def cursor_status() -> dict[str, str]:
    return {"mode": _cursor_mode}


def _cursor_target(mode: str) -> Any:
    if SYSTEM == "Windows":
        size = {"normal": 1, "large": 8, "huge": 15}[mode]
        return (size, _windows_base(size))
    if SYSTEM == "Darwin":
        return {"normal": 1.0, "large": 2.5, "huge": 4.0}[mode]
    return {"normal": 24, "large": 48, "huge": 96}[mode]


def _read_cursor_size() -> Any:
    if SYSTEM == "Windows":
        import winreg

        cursor = 1
        base = 32
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Accessibility") as key:
                cursor = int(winreg.QueryValueEx(key, "CursorSize")[0])
        except OSError:
            cursor = 1
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Cursors") as key:
                base = int(winreg.QueryValueEx(key, "CursorBaseSize")[0])
        except OSError:
            base = _windows_base(cursor)
        return (cursor, base)
    if SYSTEM == "Darwin":
        result = _run(
            ["defaults", "read", "com.apple.universalaccess", "mouseDriverCursorSize"]
        )
        try:
            return float(result.stdout.strip())
        except ValueError:
            return 1.0
    if _which("gsettings"):
        result = _run(["gsettings", "get", "org.gnome.desktop.interface", "cursor-size"])
        raw = result.stdout.strip().split()[-1] if result.stdout.strip() else ""
        try:
            return int(raw)
        except ValueError:
            return 24
    return 24


def _windows_base(size: int) -> int:
    size = max(1, min(15, int(size)))
    return 32 + (size - 1) * 16


def _windows_refresh_cursors(base: int) -> None:
    user32 = ctypes.windll.user32
    user32.SystemParametersInfoW.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
    user32.SystemParametersInfoW.restype = ctypes.c_bool
    # 0x2029 aplica el tamaño al momento. El tercer valor es el tamaño, no un puntero.
    user32.SystemParametersInfoW(0x2029, 0, ctypes.c_void_p(int(base)), 0x0001 | 0x0002)
    user32.SystemParametersInfoW(0x0057, 0, None, 0x0001 | 0x0002)


def _apply_cursor_size(size: Any) -> str:
    if SYSTEM == "Windows":
        import winreg

        if isinstance(size, tuple):
            cursor, base = int(size[0]), int(size[1])
        else:
            cursor = int(size)
            base = _windows_base(cursor)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Accessibility") as key:
            winreg.SetValueEx(key, "CursorSize", 0, winreg.REG_DWORD, cursor)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Cursors") as key:
            winreg.SetValueEx(key, "CursorBaseSize", 0, winreg.REG_DWORD, base)
        _windows_refresh_cursors(base)
        return "Cursor cambiado al momento"
    if SYSTEM == "Darwin":
        result = _run(
            [
                "defaults",
                "write",
                "com.apple.universalaccess",
                "mouseDriverCursorSize",
                "-float",
                str(float(size)),
            ]
        )
        if result.returncode != 0:
            raise ControlError("macOS no dejó cambiar el tamaño del cursor")
        return "Tamaño pedido a macOS. Hace falta permiso de Accesibilidad; a veces pide cerrar sesión."
    if _which("gsettings"):
        result = _run(
            ["gsettings", "set", "org.gnome.desktop.interface", "cursor-size", str(int(size))]
        )
        if result.returncode == 0:
            return "Cursor del escritorio GNOME"
    raise ControlError(
        "No pude agrandar el cursor del sistema. En GNOME instala el escritorio con gsettings."
    )


_SKIP_TITLES = {
    "xfce4-panel",
    "desktop",
    "program manager",
    "windows input experience",
    "windows shell experience host",
    "msctfime ui",
    "default ime",
}


def typing_focus() -> bool:
    if SYSTEM != "Windows":
        return False
    user32 = ctypes.windll.user32

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class GUITHREADINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("flags", ctypes.c_ulong),
            ("hwndActive", ctypes.c_void_p),
            ("hwndFocus", ctypes.c_void_p),
            ("hwndCapture", ctypes.c_void_p),
            ("hwndMenuOwner", ctypes.c_void_p),
            ("hwndMoveSize", ctypes.c_void_p),
            ("hwndCaret", ctypes.c_void_p),
            ("rcCaret", RECT),
        ]

    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    user32.GetGUIThreadInfo.argtypes = [ctypes.c_ulong, ctypes.POINTER(GUITHREADINFO)]
    user32.GetGUIThreadInfo.restype = ctypes.c_bool
    user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    foreground = user32.GetForegroundWindow()
    if not foreground:
        return False
    thread = user32.GetWindowThreadProcessId(foreground, None)
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    if not user32.GetGUIThreadInfo(thread, ctypes.byref(info)):
        return False
    caret = info.rcCaret.right - info.rcCaret.left or info.rcCaret.bottom - info.rcCaret.top
    if info.flags & 0x1 or info.hwndCaret or caret:
        return True
    if not info.hwndFocus:
        return False
    name = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(info.hwndFocus, name, 64)
    kind = name.value.lower()
    return "edit" in kind


_APP_NAMES = {
    "chrome": "Chrome", "google-chrome": "Chrome", "chromium": "Chromium", "chromium-browser": "Chromium",
    "msedge": "Edge", "microsoft-edge": "Edge", "firefox": "Firefox", "navigator": "Firefox",
    "brave": "Brave", "brave-browser": "Brave", "opera": "Opera", "vivaldi": "Vivaldi",
    "explorer": "Explorador de archivos", "nautilus": "Archivos", "org.gnome.nautilus": "Archivos",
    "thunar": "Archivos", "dolphin": "Archivos", "nemo": "Archivos", "pcmanfm": "Archivos", "finder": "Finder",
    "7zfm": "7-Zip", "7zg": "7-Zip", "winrar": "WinRAR", "file-roller": "Archivos comprimidos",
    "org.gnome.fileroller": "Archivos comprimidos", "ark": "Archivos comprimidos", "peazip": "PeaZip",
    "code": "VS Code", "notepad": "Bloc de notas", "notepad++": "Notepad++", "spotify": "Spotify",
    "vlc": "VLC", "xterm": "Terminal", "gnome-terminal-server": "Terminal", "windowsterminal": "Terminal",
    "cmd": "Símbolo del sistema", "powershell": "PowerShell", "pwsh": "PowerShell", "conhost": "Consola",
    "discord": "Discord", "telegram": "Telegram", "telegramdesktop": "Telegram", "signal": "Signal",
    "obs64": "OBS", "obs": "OBS", "steam": "Steam", "winword": "Word", "excel": "Excel",
    "powerpnt": "PowerPoint", "outlook": "Outlook", "teams": "Teams", "ms-teams": "Teams",
    "thunderbird": "Thunderbird", "gimp": "GIMP", "libreoffice": "LibreOffice", "soffice": "LibreOffice",
    "mspaint": "Paint", "calc": "Calculadora", "applicationframehost": "App de Windows",
    "systemsettings": "Configuración", "taskmgr": "Administrador de tareas", "python": "Python", "pythonw": "Python",
}
_TAB_APPS = {"Chrome", "Chromium", "Edge", "Brave", "Opera", "Vivaldi", "Firefox"}
_TITLE_HINTS = (
    ("google chrome", "Chrome"), ("microsoft edge", "Edge"), ("mozilla firefox", "Firefox"),
    ("brave", "Brave"), ("visual studio code", "VS Code"), ("winrar", "WinRAR"), ("7-zip", "7-Zip"),
)


def app_name(process: str, title: str = "") -> str:
    """Nombre amigable de la app a partir del proceso (o la clase de ventana en Linux)."""
    raw = (process or "").strip()
    key = raw.lower()
    if key.endswith(".exe"):
        key = key[:-4]
    if key in _APP_NAMES:
        return _APP_NAMES[key]
    low = (title or "").lower()
    for mark, name in _TITLE_HINTS:
        if low.endswith(mark) or f" - {mark}" in low:
            return name
    if not key:
        return "Otras"
    base = raw[:-4] if raw.lower().endswith(".exe") else raw
    base = base.rsplit(".", 1)[-1] if "." in base else base
    return (base[:1].upper() + base[1:])[:40] or "Otras"


def short_title(title: str, app: str) -> str:
    """Quita el « - Google Chrome» final para que se lea lo importante."""
    text = "".join(ch for ch in title if ch not in "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
    for suffix in (" - Google Chrome", " - Microsoft​ Edge", " - Microsoft Edge", " — Mozilla Firefox",
                   " - Mozilla Firefox", " - Brave", " - Visual Studio Code", " - Chromium"):
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break
    return text.strip() or title or app


def _decorate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in rows:
        app = app_name(str(row.get("process", "") or row.get("cls", "")), str(row.get("title", "")))
        row["app"] = app
        row["short"] = short_title(str(row.get("title", "")), app)
        row["tabs"] = app in _TAB_APPS
    return rows


def window_tabs(window_id: str) -> dict[str, Any]:
    """Pestañas de un navegador. En Windows las lee con UI Automation (sin puertos ni extensiones)."""
    if not window_id:
        raise ControlError("falta la ventana")
    if SYSTEM == "Windows":
        try:
            hwnd = int(window_id)
        except ValueError:
            raise ControlError("ventana no válida") from None
        tabs = _uia_tabs(hwnd, None)
        return {"tabs": tabs, "list": tabs is not None}
    return {"tabs": None, "list": False}


def tab_action(window_id: str, action: str, index: Any = None) -> str:
    if action not in {"next", "prev", "go"}:
        raise ControlError("acción de pestaña no válida")
    if not window_id:
        raise ControlError("falta la ventana")
    if SYSTEM == "Windows":
        try:
            hwnd = int(window_id)
        except ValueError:
            raise ControlError("ventana no válida") from None
        if action == "go":
            try:
                n = int(index)
            except (TypeError, ValueError):
                raise ControlError("pestaña no válida") from None
            with _lock:
                if _uia_tabs(hwnd, n) is None:
                    raise ControlError("No pude cambiar a esa pestaña")
                _force_foreground(hwnd)
            return "Pestaña cambiada"
        with _lock:
            if not _activate_window(hwnd):
                raise ControlError("No pude traer el navegador al frente")
            if action == "next":
                _win_hotkey(0x11, 0x09)
            else:
                _win_hotkey(0x11, 0x10, 0x09)
        return "Pestaña siguiente" if action == "next" else "Pestaña anterior"
    if SYSTEM == "Darwin":
        raise ControlError("Cambiar de pestaña aún no está en Mac")
    if not re.fullmatch(r"0x[0-9a-fA-F]{1,10}", window_id):
        raise ControlError("ventana no válida")
    if not _which("xdotool"):
        raise ControlError("Instala xdotool para cambiar de pestaña (sudo apt install xdotool)")
    keys = {"next": "ctrl+Tab", "prev": "ctrl+shift+Tab"}
    if action == "go":
        try:
            n = int(index)
        except (TypeError, ValueError):
            raise ControlError("pestaña no válida") from None
        if not 1 <= n <= 8:
            raise ControlError("pestaña no válida")
        keys["go"] = f"ctrl+{n}"
    with _lock:
        _linux_window_action(window_id, "focus")
        time.sleep(0.15)
        _run(["xdotool", "key", "--clearmodifiers", keys[action]])
    return "Pestaña cambiada"


_UIA_PS = r"""
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes
$A=[System.Windows.Automation.AutomationElement]
$CT=[System.Windows.Automation.ControlType]
$h=[IntPtr]::new([long]$env:LAZO_HWND)
$w=$A::FromHandle($h)
$walker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
$found=New-Object System.Collections.ArrayList
# Solo la barra del navegador: no entra en la página web (Document ni su panel),
# que es de donde salían «pestañas» falsas como las secciones de YouTube.
function Walk($e,$d){
  if($d -gt 16 -or $found.Count -ge 120){return}
  $ch=$walker.GetFirstChild($e)
  while($ch -ne $null){
    $ct=$ch.Current.ControlType
    $cls=$ch.Current.ClassName
    if($ct -eq $CT::Document -or $cls -eq 'Chrome_RenderWidgetHostHWND' -or $cls -eq 'MozillaContentWindowClass'){}
    elseif($ct -eq $CT::TabItem){[void]$found.Add($ch)}
    else{Walk $ch ($d+1)}
    $ch=$walker.GetNextSibling($ch)
  }
}
Walk $w 0
$pick=[int]$env:LAZO_PICK
$i=0
foreach($t in $found){
  $sel=$false
  try{$sel=$t.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Current.IsSelected}catch{}
  if($i -eq $pick){$t.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()}
  $n=$t.Current.Name -replace "[\r\n\t]"," "
  [Console]::Out.WriteLine(($i.ToString()+"`t"+[int]$sel+"`t"+$n))
  $i++
  if($i -ge 80){break}
}
"""


def _uia_tabs(hwnd: int, pick: int | None) -> list[dict[str, Any]] | None:
    import os

    env = dict(os.environ, LAZO_HWND=str(int(hwnd)), LAZO_PICK=str(-1 if pick is None else int(pick)))
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + _UIA_PS],
            capture_output=True, timeout=8, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return parse_uia_tabs(result.stdout.decode("utf-8", "replace"))


def parse_uia_tabs(text: str) -> list[dict[str, Any]]:
    tabs = []
    for line in text.splitlines():
        parts = line.lstrip("\ufeff").split("\t", 2)
        if len(parts) != 3 or not parts[0].isdigit():
            continue
        tabs.append({"i": int(parts[0]), "active": parts[1] == "1", "title": parts[2].strip()[:160] or "Pestaña"})
    return tabs


def list_windows() -> list[dict[str, str]]:
    with _lock:
        if SYSTEM == "Windows":
            rows = _decorate(_windows_list())
        elif SYSTEM == "Darwin":
            rows = _decorate(_mac_windows())
        else:
            rows = _decorate(_linux_windows())
    for row in rows:
        row.pop("_exe", None)  # la ruta del programa no sale del PC
    return rows


def windows_with_icons() -> dict[str, Any]:
    """Lista de ventanas y los iconos de sus apps (los que ya estén listos)."""
    with _lock:
        if SYSTEM == "Windows":
            rows = _decorate(_windows_list())
        elif SYSTEM == "Darwin":
            rows = _decorate(_mac_windows())
        else:
            rows = _decorate(_linux_windows())
    icons: dict[str, str] = {}
    wanted: list[str] = []
    for row in rows:
        source = str(row.pop("_exe", "") or "") if SYSTEM == "Windows" else str(row.get("process") or "")
        if not source:
            continue
        key = hashlib.sha1(source.lower().encode("utf-8", "replace")).hexdigest()[:12]
        row["icon"] = key
        if key in _icon_cache:
            if _icon_cache[key]:
                icons[key] = _icon_cache[key]
        elif source not in wanted:
            wanted.append(source)
            _icon_keys[source] = key
    if wanted:
        _icons_async(wanted)
    return {"windows": rows, "icons": icons, "icons_pending": bool(wanted) or bool(_icon_busy)}


_icon_cache: dict[str, str] = {}
_icon_keys: dict[str, str] = {}
_icon_busy: set[str] = set()
_icon_lock = threading.Lock()
_ICON_MAX = 300

_ICON_PS = r"""
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$i=0
foreach($p in ($env:LAZO_EXES -split "\|")){
  $b64=''
  try{
    $ic=[System.Drawing.Icon]::ExtractAssociatedIcon($p)
    $src=$ic.ToBitmap()
    $bmp=New-Object System.Drawing.Bitmap 32,32
    $g=[System.Drawing.Graphics]::FromImage($bmp)
    $g.InterpolationMode=[System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $g.DrawImage($src,0,0,32,32)
    $g.Dispose()
    $ms=New-Object System.IO.MemoryStream
    $bmp.Save($ms,[System.Drawing.Imaging.ImageFormat]::Png)
    $b64=[Convert]::ToBase64String($ms.ToArray())
  }catch{}
  [Console]::Out.WriteLine($i.ToString()+"`t"+$b64)
  $i++
}
"""


def _icons_async(sources: list[str]) -> None:
    with _icon_lock:
        todo = [src for src in sources if src not in _icon_busy][:40]
        if not todo:
            return
        _icon_busy.update(todo)
    threading.Thread(target=_load_icons, args=(todo,), daemon=True).start()


def _load_icons(todo: list[str]) -> None:
    try:
        found = _windows_icons(todo) if SYSTEM == "Windows" else [_linux_icon(src) for src in todo]
    except Exception:  # noqa: BLE001 (sin icono: la inicial de color vale)
        found = [""] * len(todo)
    with _icon_lock:
        if len(_icon_cache) > _ICON_MAX:
            _icon_cache.clear()
        for src, data in zip(todo, found):
            _icon_cache[_icon_keys.get(src, "")] = data
            _icon_busy.discard(src)


def _windows_icons(paths: list[str]) -> list[str]:
    paths = [p for p in paths if "|" not in p]
    env = dict(os.environ, LAZO_EXES="|".join(paths))
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _ICON_PS],
            capture_output=True, timeout=20, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return [""] * len(paths)
    out = [""] * len(paths)
    for line in result.stdout.decode("utf-8", "replace").splitlines():
        idx, _, b64 = line.lstrip("\ufeff").partition("\t")
        if idx.isdigit() and int(idx) < len(out) and re.fullmatch(r"[A-Za-z0-9+/=]{20,20000}", b64.strip()):
            out[int(idx)] = "data:image/png;base64," + b64.strip()
    return out


def _linux_icon(cls: str) -> str:
    """Icono del tema por la clase de la ventana (p. ej. «firefox», «code»)."""
    import base64

    names = {cls, cls.lower(), cls.lower().replace(" ", "-")}
    bases = [Path.home() / ".local/share/icons/hicolor", Path("/usr/share/icons/hicolor")]
    for name in names:
        if not re.fullmatch(r"[A-Za-z0-9_.+-]{1,60}", name):
            continue
        cands = [b / size / "apps" / f"{name}.png" for b in bases for size in ("32x32", "48x48", "64x64", "24x24", "128x128")]
        cands += [Path("/usr/share/pixmaps") / f"{name}.png"]
        cands += [b / "scalable" / "apps" / f"{name}.svg" for b in bases] + [Path("/usr/share/pixmaps") / f"{name}.svg"]
        for path in cands:
            try:
                if path.is_file() and path.stat().st_size <= 64 * 1024:
                    mime = "image/svg+xml" if path.suffix == ".svg" else "image/png"
                    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
            except OSError:
                continue
    return ""


def window_action(window_id: str, action: str) -> str:
    allowed = {"open", "focus", "minimize", "maximize", "toggle_max", "close", "snap_left", "snap_right"}
    if action not in allowed:
        raise ControlError("acción de ventana no válida")
    if not window_id:
        raise ControlError("falta la ventana")
    with _lock:
        if SYSTEM == "Windows":
            if not window_id.isdigit():
                raise ControlError("ventana no válida")
            return _windows_action(int(window_id), action)
        if SYSTEM == "Darwin":
            return _mac_window_action(window_id, "maximize" if action in ("toggle_max", "open") else action)
        return _linux_window_action(window_id, action)


def _windows_list() -> list[dict[str, str]]:
    user32 = ctypes.windll.user32
    rows: list[dict[str, str]] = []

    try:
        dwmapi = ctypes.windll.dwmapi
    except OSError:
        dwmapi = None

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if dwmapi is not None:
            cloaked = ctypes.c_int(0)
            if dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4) == 0 and cloaked.value:
                return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title or title.lower() in _SKIP_TITLES:
            return True
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        path = _process_path(pid.value)
        process = path.rsplit("\\", 1)[-1]
        rows.append({"id": str(int(hwnd)), "title": title[:180], "process": process, "_exe": path})
        return True

    user32.EnumWindows(callback, 0)
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    front = str(int(user32.GetForegroundWindow() or 0))
    for row in rows:
        row["active"] = row["id"] == front
    return rows[:150]


def _hwnd(value: int) -> ctypes.c_void_p:
    return ctypes.c_void_p(int(value))


def _user32():
    user32 = ctypes.windll.user32
    void = ctypes.c_void_p
    user32.ShowWindow.argtypes = [void, ctypes.c_int]
    user32.ShowWindow.restype = ctypes.c_bool
    user32.SetForegroundWindow.argtypes = [void]
    user32.SetForegroundWindow.restype = ctypes.c_bool
    user32.BringWindowToTop.argtypes = [void]
    user32.BringWindowToTop.restype = ctypes.c_bool
    user32.GetForegroundWindow.restype = void
    user32.GetWindowThreadProcessId.argtypes = [void, ctypes.c_void_p]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool]
    user32.AttachThreadInput.restype = ctypes.c_bool
    user32.IsIconic.argtypes = [void]
    user32.IsIconic.restype = ctypes.c_bool
    user32.IsWindow.argtypes = [void]
    user32.IsWindow.restype = ctypes.c_bool
    user32.PostMessageW.argtypes = [void, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    user32.PostMessageW.restype = ctypes.c_bool
    return user32


def _is_foreground(hwnd: int) -> bool:
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    fg = user32.GetForegroundWindow()
    return bool(fg) and int(fg) == int(hwnd)


def _activate_window(hwnd: int) -> bool:
    """Pone esa ventana delante de verdad, para que la tecla no caiga en otra app."""
    user32 = _user32()
    _force_foreground(hwnd)
    if not _is_foreground(hwnd):
        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        rect = RECT()
        user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(RECT)]
        user32.GetWindowRect.restype = ctypes.c_bool
        user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
        user32.GetCursorPos.restype = ctypes.c_bool
        user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        user32.SetCursorPos.restype = ctypes.c_bool
        if user32.GetWindowRect(_hwnd(hwnd), ctypes.byref(rect)):
            point = POINT()
            user32.GetCursorPos(ctypes.byref(point))
            user32.SetCursorPos(int((rect.left + rect.right) / 2), int(rect.top) + 12)
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            user32.SetCursorPos(int(point.x), int(point.y))
            time.sleep(0.05)
            _force_foreground(hwnd)
    return _is_foreground(hwnd)


def _focus_for_keys(window_id: str) -> bool:
    if SYSTEM == "Windows":
        return _activate_window(int(window_id))
    _focus_unlocked(window_id)
    return True


def _force_foreground(hwnd: int) -> None:
    user32 = _user32()
    handle = _hwnd(hwnd)
    # SW_RESTORE (9) saca la ventana de maximizada. Solo si está minimizada.
    if user32.IsIconic(handle):
        user32.ShowWindow(handle, 9)
    fg = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    target_thread = user32.GetWindowThreadProcessId(handle, None)
    attached = bool(fg_thread and target_thread and fg_thread != target_thread)
    if attached:
        user32.AttachThreadInput(fg_thread, target_thread, True)
    user32.SetForegroundWindow(handle)
    user32.BringWindowToTop(handle)
    if attached:
        user32.AttachThreadInput(fg_thread, target_thread, False)


def _win_hotkey(*vks: int) -> None:
    user32 = ctypes.windll.user32
    for vk in vks:
        user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks):
        user32.keybd_event(vk, 0, 2, 0)


def _process_name(pid: int) -> str:
    return _process_path(pid).rsplit("\\", 1)[-1]


def _process_path(pid: int) -> str:
    if not pid:
        return ""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = ctypes.c_ulong(260)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value
    finally:
        kernel32.CloseHandle(handle)


_BROWSERS = ("chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe")


def pick_spotify_window(rows: list[dict[str, str]]) -> dict[str, str] | None:
    for row in rows:
        process = row.get("process", "").lower()
        title = row.get("title", "")
        title_l = title.lower()
        if process in _BROWSERS or any(mark in title_l for mark in ("google chrome", "mozilla firefox", "microsoft edge")):
            continue
        if process == "spotify.exe" or title_l in {"spotify", "spotify premium", "spotify free"}:
            return row
        if not process and "spotify" in title_l:
            return row
    return None


def _launch_spotify_app() -> None:
    import os

    candidates = [
        os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\Spotify.exe"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            subprocess.Popen([path])
            return
    subprocess.Popen(["cmd", "/c", "start", "", "spotify:"], close_fds=True, creationflags=_NO_WINDOW)


def _windows_action(hwnd: int, action: str) -> str:
    user32 = _user32()
    handle = _hwnd(hwnd)
    if not user32.IsWindow(handle):
        raise ControlError("Esa ventana ya se cerró. Pulsa Actualizar.")
    if action == "focus":
        _force_foreground(hwnd)
        return "Ventana al frente"
    if action == "open":
        # Tocar una ventana: delante y maximizada (si estaba minimizada, primero se restaura).
        if user32.IsIconic(handle):
            user32.ShowWindow(handle, 9)
        user32.ShowWindow(handle, 3)
        _force_foreground(hwnd)
        return "Ventana maximizada"
    if action == "minimize":
        user32.ShowWindow(handle, 6)
        return "Minimizada"
    if action == "maximize":
        user32.ShowWindow(handle, 3)
        return "Maximizada"
    if action == "toggle_max":
        user32.IsZoomed.argtypes = [ctypes.c_void_p]
        user32.IsZoomed.restype = ctypes.c_bool
        if user32.IsZoomed(handle) or user32.IsIconic(handle):
            user32.ShowWindow(handle, 9)
            _force_foreground(hwnd)
            return "Restaurada"
        user32.ShowWindow(handle, 3)
        return "Maximizada"
    if action == "close":
        user32.SendMessageTimeoutW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        user32.SendMessageTimeoutW.restype = ctypes.c_void_p
        answered = ctypes.c_size_t()
        user32.SendMessageTimeoutW(handle, 0x0010, 0, 0, 0x0002, 400, ctypes.byref(answered))
        if user32.IsWindow(handle):
            _force_foreground(hwnd)
            _win_hotkey(0x12, 0x73)
        return "Cerrada"
    if action == "snap_left":
        _force_foreground(hwnd)
        _win_hotkey(0x5B, 0x25)
        return "A la izquierda"
    _force_foreground(hwnd)
    _win_hotkey(0x5B, 0x27)
    return "A la derecha"


def _linux_windows() -> list[dict[str, str]]:
    if not _which("wmctrl"):
        raise ControlError("Instala wmctrl para ver las ventanas (sudo apt install wmctrl)")
    result = _run(["wmctrl", "-l"])
    if result.returncode != 0:
        raise ControlError("wmctrl no pudo listar las ventanas. En Wayland a veces hace falta una sesión Xorg.")
    classes = _run(["wmctrl", "-lx"])
    return parse_wmctrl(result.stdout, classes.stdout if classes.returncode == 0 else "", _linux_active())


def parse_wmctrl(plain: str, with_class: str = "", active: str = "") -> list[dict[str, Any]]:
    """Cruza «wmctrl -l» (título fiable) con «wmctrl -lx» (clase, que puede llevar espacios)."""
    lx = {}
    for line in with_class.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3:
            lx[parts[0]] = parts[2]
    rows = []
    for line in plain.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 3:
            continue
        wid = parts[0]
        host = parts[2]
        title = parts[3].strip() if len(parts) > 3 else ""
        if title == "N/A":
            title = "Sin título"
        if not title or title.lower() in _SKIP_TITLES:
            continue
        cls = ""
        rest = lx.get(wid, "")
        cut = rest.rfind(" " + host + " ") if title else -1
        if cut < 0 and rest.endswith(" " + host):
            cut = len(rest) - len(host) - 1
        if cut > 0:
            cls = rest[:cut].strip()
        process = cls.split(".", 1)[0].split(" (", 1)[0] if cls else ""
        try:
            is_active = bool(active) and int(wid, 16) == int(active, 16)
        except ValueError:
            is_active = False
        rows.append({"id": wid, "title": title[:180], "process": process, "active": is_active})
    return rows[:150]


def _linux_active() -> str:
    if not _which("xdotool"):
        return ""
    result = _run(["xdotool", "getactivewindow"], timeout=2)
    value = result.stdout.strip()
    return hex(int(value)) if value.isdigit() else ""


def _linux_window_action(window_id: str, action: str) -> str:
    if not re.fullmatch(r"0x[0-9a-fA-F]{1,10}", window_id):
        raise ControlError("ventana no válida")
    if not _which("wmctrl"):
        raise ControlError("Instala wmctrl")
    if not _linux_window_alive(window_id):
        raise ControlError("Esa ventana ya se cerró. Pulsa Actualizar.")
    if action == "focus":
        cmd = ["wmctrl", "-i", "-a", window_id]
        label = "Ventana al frente"
    elif action == "open":
        _run(["wmctrl", "-i", "-a", window_id])
        cmd = ["wmctrl", "-i", "-r", window_id, "-b", "add,maximized_vert,maximized_horz"]
        label = "Ventana maximizada"
    elif action == "minimize":
        cmd = ["wmctrl", "-i", "-r", window_id, "-b", "add,hidden"]
        label = "Minimizada"
    elif action == "maximize":
        cmd = ["wmctrl", "-i", "-r", window_id, "-b", "add,maximized_vert,maximized_horz"]
        label = "Maximizada"
    elif action == "toggle_max":
        cmd = ["wmctrl", "-i", "-r", window_id, "-b", "toggle,maximized_vert,maximized_horz"]
        label = "Maximizar / restaurar"
    elif action == "close":
        cmd = ["wmctrl", "-i", "-c", window_id]
        label = "Cerrar enviado"
    else:
        _run(["wmctrl", "-i", "-a", window_id])
        _run(["wmctrl", "-i", "-r", window_id, "-b", "remove,maximized_vert,maximized_horz"])
        geo = _desktop_size()
        width = max(400, geo[0] // 2)
        x = 0 if action == "snap_left" else width
        cmd = ["wmctrl", "-i", "-r", window_id, "-e", f"0,{x},0,{width},{geo[1]}"]
        label = "A la izquierda" if action == "snap_left" else "A la derecha"
    result = _run(cmd)
    if result.returncode != 0:
        raise ControlError("No pude mover esa ventana")
    return label


def _linux_window_alive(window_id: str) -> bool:
    result = _run(["wmctrl", "-l"])
    if result.returncode != 0 or not (result.stdout or "").strip():
        return True
    want = int(window_id, 16)
    for line in result.stdout.splitlines():
        head = line.split(None, 1)[0] if line.strip() else ""
        try:
            if int(head, 16) == want:
                return True
        except ValueError:
            continue
    return False


def _desktop_size() -> tuple[int, int]:
    result = _run(["wmctrl", "-d"])
    for line in result.stdout.splitlines():
        if "DG:" in line:
            chunk = line.split("DG:", 1)[1].split()[0]
            if "x" in chunk:
                w, h = chunk.split("x", 1)
                return int(w), int(h)
    return 1920, 1080


def _mac_windows() -> list[dict[str, str]]:
    script = r'''
set rows to {}
tell application "System Events"
  repeat with p in (every process whose background only is false)
    set pn to name of p
    try
      set i to 1
      repeat with w in windows of p
        set wn to name of w
        if wn is not "" then set end of rows to pn & tab & (i as text) & tab & wn
        set i to i + 1
      end repeat
    end try
  end repeat
end tell
set AppleScript's text item delimiters to linefeed
return rows as text
'''
    result = _run(["osascript", "-e", script], timeout=8)
    if result.returncode != 0:
        raise ControlError("macOS no dejó ver las ventanas. Da permiso de Accesibilidad a Terminal.")
    rows = []
    for line in result.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        app, index, title = parts
        rows.append({"id": f"{app}\t{index}", "title": f"{title[:140]}  ·  {app}"[:180]})
    return rows[:40]


def _mac_window_action(window_id: str, action: str) -> str:
    if "\t" not in window_id:
        raise ControlError("ventana no válida")
    app, index = window_id.split("\t", 1)
    if not index.isdigit() or not app:
        raise ControlError("ventana no válida")
    if action == "focus":
        body = "set frontmost to true\nperform action \"AXRaise\" of window IDX"
        label = "Ventana al frente"
    elif action == "minimize":
        body = 'set value of attribute "AXMinimized" of window IDX to true'
        label = "Minimizada"
    elif action == "maximize":
        body = 'click (first button of window IDX whose subrole is "AXFullScreenButton")'
        label = "Pantalla completa"
    elif action == "close":
        body = 'click (first button of window IDX whose subrole is "AXCloseButton")'
        label = "Cerrar enviado"
    elif action == "snap_left":
        body = 'set frontmost to true\nset position of window IDX to {0, 30}\nset size of window IDX to {720, 800}'
        label = "A la izquierda"
    else:
        body = 'set frontmost to true\nset position of window IDX to {740, 30}\nset size of window IDX to {720, 800}'
        label = "A la derecha"
    body = body.replace("IDX", index)
    script = f'''
tell application "System Events"
  tell process "{_as_escape(app)}"
    {body}
  end tell
end tell
'''
    result = _run(["osascript", "-e", script], timeout=8)
    if result.returncode != 0:
        raise ControlError("macOS no dejó tocar esa ventana. Revisa Accesibilidad.")
    return label


def _as_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _find_title(needle: str, exclude: str | None = None) -> dict[str, str] | None:
    needle = needle.lower()
    exclude_l = exclude.lower() if exclude else None
    for row in list_windows():
        title = row["title"].lower()
        if exclude_l and exclude_l in title:
            continue
        if needle in title:
            return row
    return None


_levels = {"youtube": 50, "spotify": 50, "youtube_speed": 1.0}
_YOUTUBE_SPEEDS = (1.0, 1.25, 1.5, 2.0)
_YOUTUBE_LADDER = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
_YOUTUBE_SPEED_TEXT = {1.0: "1.0", 1.25: "1.25", 1.5: "1.50", 2.0: "2"}


def match_youtube_speed(raw: object) -> float:
    rate = round(float(raw), 2)
    for item in _YOUTUBE_SPEEDS:
        if abs(rate - item) < 0.001:
            return item
    raise ControlError("velocidad no válida")


def youtube_speed_ups(raw: object) -> int:
    return _YOUTUBE_LADDER.index(match_youtube_speed(raw))


def youtube(action: str, extra: dict | None = None) -> dict[str, Any]:
    extra = extra or {}
    if action == "search":
        return _youtube_search(str(extra.get("query", "")))
    if action == "open":
        return _youtube_open(str(extra.get("video", "")))
    if action == "home":
        return _youtube_home()
    if action == "volume":
        return _youtube_volume(int(extra.get("level", _levels["youtube"])))
    if action == "speed":
        return _youtube_speed(extra.get("rate", _levels["youtube_speed"]))
    if action == "fullscreen":
        return _youtube_fullscreen()
    actions = {
        "play": ["k"],
        "mute": ["m"],
        "full": ["f"],
        "back": ["j"],
        "forward": ["l"],
        "volup": ["up"],
        "voldown": ["down"],
        "next": ["shift", "n"],
        "prev": ["shift", "p"],
        "restart": ["0"],
        "history_back": ["alt", "left"],
        "captions": ["c"],
        "theater": ["t"],
    }
    if action != "status" and action not in actions:
        raise ControlError("acción de YouTube no válida")
    with _lock:
        row = _find_youtube_unlocked()
        if row is None:
            if action == "status":
                return {"detail": "", "title": "", "level": _levels["youtube"], "playing": None, "missing": True}
            raise ControlError("No veo YouTube. Ábrelo en el navegador de este PC.")
    state = _yt_state(row)
    if action == "status":
        real = _win_is_fullscreen(row["id"])
        if real is not None:
            _yt["full"] = real
        return {"detail": "", "title": row["title"], "level": _levels["youtube"], "full": _yt["full"], **state}
    detail = "YouTube"
    if action == "prev":
        # Como un reproductor: si ya lleva más de 5 s, vuelve al 0:00; si no, al anterior.
        pos = state.get("pos")
        now = time.time()
        if pos is None:
            pos = now - _yt["since"] if _yt["since"] else 99
            if now - _yt["restart"] < 5:
                pos = 0
        if pos > 5:
            keys, detail = actions["restart"], "Al inicio del vídeo"
            _yt["restart"] = now
        else:
            # Shift+P solo vale en listas; «atrás» del navegador vale siempre.
            keys, detail = actions["history_back"], "Vídeo anterior"
            _yt["restart"] = 0.0
    else:
        keys = actions[action]
        if action == "next":
            detail = "Siguiente vídeo"
    if not _focus_for_keys(row["id"]):
        raise ControlError("No pude poner YouTube delante. Toca su ventana en el PC una vez.")
    time.sleep(0.18)
    with _lock:
        _yt_keys(keys)
    if action == "play":
        if state.get("playing") is not None:
            state["playing"] = not state["playing"]
        elif _yt["playing"] is not None:
            state["playing"] = _yt["playing"] = not _yt["playing"]
    if action in ("next", "prev") and detail != "Al inicio del vídeo":
        _yt["since"] = time.time()
        _yt["playing"] = True
    if action == "volup":
        _levels["youtube"] = min(100, _levels["youtube"] + 5)
    elif action == "voldown":
        _levels["youtube"] = max(0, _levels["youtube"] - 5)
    return {"detail": detail, "title": row["title"], "level": _levels["youtube"], **state}


_yt: dict[str, Any] = {"title": "", "since": 0.0, "restart": 0.0, "playing": None, "full": False}


def covers_monitor(win: tuple[int, int, int, int], mon: tuple[int, int, int, int]) -> bool:
    """0.46: pantalla completa = la ventana ocupa EXACTAMENTE su monitor (izq, arr, der, abajo).
    Una ventana maximizada no cuenta: deja la barra de tareas y sobresale unos píxeles."""
    return tuple(win) == tuple(mon) and mon[2] > mon[0] and mon[3] > mon[1]


def _win_is_fullscreen(window_id: str) -> bool | None:
    """True/False si Windows lo sabe; None si no se puede saber (otros sistemas)."""
    if SYSTEM != "Windows":
        return None
    try:
        from ctypes import wintypes

        user32 = _user32()
        handle = _hwnd(int(window_id))

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        user32.MonitorFromWindow.restype = ctypes.c_void_p
        user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.IsZoomed.argtypes = [ctypes.c_void_p]
        user32.IsZoomed.restype = ctypes.c_bool
        if user32.IsZoomed(handle):
            # Maximizada en un monitor sin barra de tareas ocupa todo el monitor, pero
            # NO es pantalla completa (visto en un segundo monitor real).
            return False
        rect = wintypes.RECT()
        if not user32.GetWindowRect(handle, ctypes.byref(rect)):
            return None
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        mon = user32.MonitorFromWindow(handle, 2)
        if not mon or not user32.GetMonitorInfoW(mon, ctypes.byref(info)):
            return None
        m = info.rcMonitor
        return covers_monitor((rect.left, rect.top, rect.right, rect.bottom), (m.left, m.top, m.right, m.bottom))
    except Exception:  # noqa: BLE001
        return None


def fullscreen_keys(is_full: bool) -> list[str]:
    """Entrar con «f» (atajo de YouTube); salir con Esc, que sale siempre aunque el
    foco no esté en el reproductor y no escribe nada si ya estaba fuera."""
    return ["escape"] if is_full else ["f"]


def _youtube_fullscreen() -> dict[str, Any]:
    with _lock:
        row = _find_youtube_unlocked()
        if row is None:
            raise ControlError("No veo YouTube. Ábrelo en el navegador de este PC.")
    real = _win_is_fullscreen(row["id"])
    is_full = _yt["full"] if real is None else real
    if not _focus_for_keys(row["id"]):
        raise ControlError("No pude poner YouTube delante. Toca su ventana en el PC una vez.")
    time.sleep(0.18)
    with _lock:
        _yt_keys(fullscreen_keys(is_full))
    _yt["full"] = not is_full
    if SYSTEM == "Windows":
        time.sleep(0.35)
        after = _win_is_fullscreen(row["id"])
        if after is not None:
            _yt["full"] = after
    return {
        "detail": "Pantalla completa" if _yt["full"] else "Salir de pantalla completa",
        "title": row["title"], "level": _levels["youtube"], "full": _yt["full"],
    }


def _yt_state(row: dict[str, str]) -> dict[str, Any]:
    """Estado real si el sistema lo da (play/pausa, posición); si no, lo que sabemos."""
    if row["title"] != _yt["title"]:
        if _yt["title"]:
            _yt["playing"] = True
        _yt["title"], _yt["since"] = row["title"], time.time()
    try:
        import medios

        info = medios.summary(medios.browser_session(row["title"]))
    except Exception:  # noqa: BLE001 (sin datos del sistema: seguimos sin ellos)
        info = {}
    if info.get("playing") is not None:
        _yt["playing"] = info["playing"]
        return {"playing": info["playing"], "pos": info["pos"], "len": info["len"], "real": True}
    return {"playing": _yt["playing"], "pos": None, "len": 0, "real": False}


_WIN_VK = {"escape": 0x1B, "shift": 0x10, "ctrl": 0x11, "alt": 0x12, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}


def _yt_keys(keys: list[str]) -> None:
    """Atajos con teclas reales. En Windows, pynput mandaba «N» como carácter suelto y
    YouTube no veía Mayús: por eso Siguiente no hacía nada."""
    if SYSTEM == "Windows":
        vks = []
        for k in keys:
            if k in _WIN_VK:
                vks.append(_WIN_VK[k])
            elif len(k) == 1 and k.isalnum():
                vks.append(ord(k.upper()))
        if len(vks) > 1 or (vks and keys[0] not in ("k", "m", "f", "j", "l", "c", "t")):
            _win_hotkey(*vks)
            return
    if SYSTEM == "Darwin" and keys == ["alt", "left"]:
        keys = ["cmd", "["]
    _chord(keys)


def _youtube_speed(raw: object) -> dict[str, Any]:
    rate = match_youtube_speed(raw)
    with _lock:
        row = _find_youtube_unlocked()
        if row is None:
            raise ControlError("No veo YouTube. Ábrelo en el navegador de este PC.")
    if not _focus_for_keys(row["id"]):
        raise ControlError("No pude poner YouTube delante. Toca su ventana en el PC una vez.")
    time.sleep(0.16)
    # YouTube solo salta 0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75 y 2.
    # Bajar del todo y luego subir deja la velocidad exacta, sin abrir ventanas.
    for _ in range(8):
        _speed_tap(False)
        time.sleep(0.04)
    for _ in range(youtube_speed_ups(rate)):
        _speed_tap(True)
        time.sleep(0.04)
    _levels["youtube_speed"] = rate
    label = _YOUTUBE_SPEED_TEXT[rate]
    return {
        "detail": f"Velocidad {label}",
        "title": row["title"],
        "level": _levels["youtube"],
        "rate": rate,
    }


def _speed_tap(faster: bool) -> None:
    if SYSTEM == "Windows" and _win_speed_key(faster):
        return
    _chord(["shift", "." if faster else ","])


def _win_speed_key(faster: bool) -> bool:
    extra = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", extra),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", extra),
        ]

    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

        _anonymous_ = ("u",)
        _fields_ = [("type", ctypes.c_ulong), ("u", _U)]

    if ctypes.sizeof(INPUT) != 40:
        return False
    # Shift + punto sube, Shift + coma baja. Son las teclas del vídeo, no un carácter.
    vk = 0xBE if faster else 0xBC
    steps = ((0x10, 0), (vk, 0), (vk, 0x0002), (0x10, 0x0002))
    batch = (INPUT * 4)()
    for index, (key, flags) in enumerate(steps):
        batch[index].type = 1
        batch[index].ki.wVk = key
        batch[index].ki.dwFlags = flags
    return ctypes.windll.user32.SendInput(4, batch, ctypes.sizeof(INPUT)) == 4


def _youtube_volume(level: int) -> dict[str, Any]:
    level = max(0, min(100, int(level)))
    steps = int(round((level - _levels["youtube"]) / 5))
    steps = max(-12, min(12, steps))
    with _lock:
        row = _find_youtube_unlocked()
        if row is None:
            raise ControlError("No veo YouTube. Ábrelo en el navegador de este PC.")
        if steps:
            if not _focus_for_keys(row["id"]):
                raise ControlError("No pude poner YouTube delante. Toca su ventana en el PC una vez.")
    if steps:
        time.sleep(0.12)
        with _lock:
            for _ in range(abs(steps)):
                _chord(["up" if steps > 0 else "down"])
        _levels["youtube"] = max(0, min(100, _levels["youtube"] + steps * 5))
    else:
        _levels["youtube"] = level
    return {"detail": "YouTube", "title": row["title"], "level": _levels["youtube"]}


def _youtube_home() -> dict[str, Any]:
    import webbrowser

    webbrowser.open_new("https://www.youtube.com/")
    return {"detail": "Inicio de YouTube", "title": "Inicio de YouTube", "level": _levels["youtube"]}


def _youtube_search(query: str) -> dict[str, Any]:
    import urllib.parse
    import webbrowser

    query = query.strip()[:120]
    if not query:
        raise ControlError("escribe qué buscar")
    webbrowser.open_new("https://www.youtube.com/results?search_query=" + urllib.parse.quote(query))
    return {
        "detail": "Búsqueda abierta en el PC",
        "title": query,
        "results": _youtube_hits(query),
        "level": _levels["youtube"],
    }


def _youtube_hits(query: str) -> list[dict[str, str]]:
    import html
    import re
    import urllib.parse
    import urllib.request

    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        page = urllib.request.urlopen(request, timeout=5).read().decode("utf-8", "replace")
    except Exception:
        return []
    hits: list[dict[str, str]] = []
    seen: set[str] = set()
    pattern = re.compile(r'"videoId":"([\w-]{11})".{0,500}?"text":"((?:\\.|[^"\\]){1,160})"')
    for video_id, title in pattern.findall(page):
        if video_id in seen:
            continue
        seen.add(video_id)
        try:
            title = html.unescape(title.encode("utf-8").decode("unicode_escape"))
        except UnicodeError:
            title = html.unescape(title)
        hits.append({"id": video_id, "title": title[:140]})
        if len(hits) >= 5:
            break
    return hits


def _youtube_open(video: str) -> dict[str, Any]:
    import re
    import webbrowser

    if not re.fullmatch(r"[\w-]{11}", video):
        raise ControlError("vídeo no válido")
    webbrowser.open_new(f"https://www.youtube.com/watch?v={video}")
    return {"detail": "Vídeo abierto en el PC", "title": "YouTube", "level": _levels["youtube"]}


def _find_youtube_unlocked() -> dict[str, str] | None:
    if SYSTEM == "Windows":
        rows = _windows_list()
    elif SYSTEM == "Darwin":
        rows = _mac_windows()
    else:
        rows = _linux_windows()
    for row in rows:
        title = row["title"].lower()
        if "youtube music" in title:
            continue
        if "youtube" in title:
            return row
    return None


def _focus_unlocked(window_id: str) -> None:
    if SYSTEM == "Windows":
        _windows_action(int(window_id), "focus")
    elif SYSTEM == "Darwin":
        _mac_window_action(window_id, "focus")
    else:
        _linux_window_action(window_id, "focus")


def move_tracks(tracks: list[str], index: int, direction: int) -> list[str]:
    step = 1 if direction > 0 else -1
    other = index + step
    if index < 0 or other < 0 or index >= len(tracks) or other >= len(tracks):
        return tracks
    tracks[index], tracks[other] = tracks[other], tracks[index]
    return tracks


_lab_queue: list[str] = []


def spotify(action: str, extra: dict | None = None) -> dict[str, Any]:
    extra = extra or {}
    allowed = {
        "play", "next", "prev", "volup", "voldown", "status", "volume", "mute", "search",
        "like", "queue", "queue_add", "queue_move",
    }
    if action not in allowed:
        raise ControlError("acción de Spotify no válida")
    if action == "queue_move":
        move_tracks(_lab_queue, int(extra.get("index", -1)), int(extra.get("dir", 0)))
        return {
            "detail": "Cola de prueba reordenada. Spotify no aplica ese orden.",
            "tracks": list(_lab_queue),
            "level": _levels["spotify"],
        }
    with _lock:
        if SYSTEM == "Darwin":
            return _mac_spotify(action, extra)
        if SYSTEM == "Linux":
            return _linux_spotify(action, extra)
        return _windows_spotify(action, extra)


def _mac_spotify(action: str, extra: dict | None = None) -> dict[str, Any]:
    extra = extra or {}
    if action == "search":
        return _spotify_search(str(extra.get("query", "")))
    if action in {"like", "queue", "queue_add"}:
        return _spotify_lab(action, extra)
    if action == "volume":
        level = max(0, min(100, int(extra.get("level", _levels["spotify"]))))
        command = f"set sound volume to {level}"
        _levels["spotify"] = level
    elif action == "mute":
        command = "set sound volume to 0" if _levels["spotify"] else "set sound volume to 40"
        _levels["spotify"] = 0 if _levels["spotify"] else 40
    else:
        commands = {
            "play": "playpause",
            "next": "next track",
            "prev": "previous track",
            "volup": "set sound volume to (sound volume + 10)",
            "voldown": "set sound volume to (sound volume - 10)",
            "status": "",
        }
        command = commands[action]
    script = f'''
tell application "Spotify"
  if it is not running then error "apagado"
  {command}
  set who to artist of current track
  set what to name of current track
  set loud to sound volume
  return who & " — " & what & tab & (loud as text)
end tell
'''
    result = _run(["osascript", "-e", script], timeout=6)
    if result.returncode != 0:
        raise ControlError("Abre la app de Spotify en el Mac")
    lines = result.stdout.strip().split("\t")
    title = lines[0][:180]
    if len(lines) > 1 and lines[1].isdigit():
        _levels["spotify"] = int(lines[1])
    return {"detail": "Spotify", "title": title, "level": _levels["spotify"]}


def _linux_spotify(action: str, extra: dict | None = None) -> dict[str, Any]:
    extra = extra or {}
    if action == "search":
        return _spotify_search(str(extra.get("query", "")))
    if action in {"like", "queue", "queue_add"}:
        return _spotify_lab(action, extra)
    if not _which("playerctl"):
        raise ControlError("Instala playerctl para Spotify (sudo apt install playerctl)")
    players = _run(["playerctl", "-l"])
    if players.returncode == 124:
        raise ControlError("Spotify no respondió a tiempo")
    names = [line.strip() for line in players.stdout.splitlines() if line.strip()]
    player = next((name for name in names if "spotify" in name.lower()), None)
    if player is None:
        raise ControlError("Abre Spotify en este PC")
    if action == "volume":
        level = max(0, min(100, int(extra.get("level", _levels["spotify"]))))
        verbs = ["volume", str(level / 100)]
        _levels["spotify"] = level
    elif action == "mute":
        verbs = ["volume", "0" if _levels["spotify"] else "0.4"]
        _levels["spotify"] = 0 if _levels["spotify"] else 40
    else:
        verbs = {
            "play": ["play-pause"],
            "next": ["next"],
            "prev": ["previous"],
            "volup": ["volume", "0.08+"],
            "voldown": ["volume", "0.08-"],
            "status": [],
        }[action]
    if action == "prev" and _num_out(_run(["playerctl", "-p", player, "position"]).stdout) > 5:
        verbs = ["position", "0"]
    if verbs:
        result = _run(["playerctl", "-p", player, *verbs])
        if result.returncode != 0:
            raise ControlError("Spotify no respondió")
    meta = _run(["playerctl", "-p", player, "metadata", "--format", "{{artist}} — {{title}}"])
    title = meta.stdout.strip() or "Spotify"
    st = _run(["playerctl", "-p", player, "status"]).stdout.strip().lower()
    playing = True if st == "playing" else False if st in ("paused", "stopped") else None
    return {"detail": "Spotify", "title": title[:180], "level": _levels["spotify"], "playing": playing}


def _num_out(text: str) -> float:
    try:
        return float((text or "").strip() or 0)
    except ValueError:
        return 0.0


def _windows_spotify(action: str, extra: dict | None = None) -> dict[str, Any]:
    extra = extra or {}
    if action == "search":
        return _spotify_search(str(extra.get("query", "")))
    if action in {"like", "queue", "queue_add"}:
        return _spotify_lab(action, extra)
    row = pick_spotify_window(_windows_list())
    if row is None:
        if action != "status":
            _launch_spotify_app()
        raise ControlError("Abro la app de Spotify del PC, no la web. Espera un segundo y pulsa otra vez.")
    title = _spotify_title(row)
    try:
        import medios

        sinfo = medios.summary(medios.spotify_session())
    except Exception:  # noqa: BLE001
        sinfo = {}
    extra_state = {"playing": sinfo.get("playing")}
    if action == "status":
        return {"detail": "Spotify", "title": title, "level": _levels["spotify"], **extra_state}
    if action == "volume":
        return _windows_spotify_volume(int(row["id"]), int(extra.get("level", _levels["spotify"])), title)
    if action == "mute":
        target = 0 if _levels["spotify"] else 40
        return _windows_spotify_volume(int(row["id"]), target, title)
    if not _focus_for_keys(row["id"]):
        raise ControlError("No pude poner Spotify delante. Toca su ventana en el PC una vez.")
    time.sleep(0.12)
    # Teclas de la propia app. La tecla global de reproducción también mueve YouTube.
    if action == "play":
        _win_hotkey(0x20)
    elif action == "next":
        _win_hotkey(0x11, 0x27)
    elif action == "prev":
        # Spotify reinicia la canción si lleva más de ~3 s. Queremos la regla de 5 s:
        # entre 3 y 5 s pulsamos dos veces para que pase de verdad a la anterior.
        pos = sinfo.get("pos")
        _win_hotkey(0x11, 0x25)
        if pos is not None and 2.5 < pos <= 5:
            time.sleep(0.15)
            _win_hotkey(0x11, 0x25)
    elif action == "volup":
        return _windows_spotify_volume(int(row["id"]), _levels["spotify"] + 10, title)
    elif action == "voldown":
        return _windows_spotify_volume(int(row["id"]), _levels["spotify"] - 10, title)
    time.sleep(0.2)
    fresh = pick_spotify_window(_windows_list())
    if fresh is not None:
        title = _spotify_title(fresh)
    if action == "play" and extra_state["playing"] is not None:
        extra_state["playing"] = not extra_state["playing"]
    return {"detail": "Spotify", "title": title, "level": _levels["spotify"], **extra_state}


def _spotify_now() -> str:
    try:
        if SYSTEM == "Darwin":
            info = _mac_spotify("status")
        elif SYSTEM == "Linux":
            info = _linux_spotify("status")
        else:
            info = _windows_spotify("status")
    except ControlError:
        return ""
    title = str(info.get("title") or "")
    return "" if title == "Spotify" else title


def _spotify_lab(action: str, extra: dict | None = None) -> dict[str, Any]:
    extra = extra or {}
    if action == "queue":
        return {
            "detail": "Spotify no publica las próximas" if not _lab_queue else "Cola de prueba",
            "tracks": list(_lab_queue),
            "title": _spotify_now(),
            "level": _levels["spotify"],
        }
    if action == "queue_add":
        title = _spotify_now()
        if not title:
            raise ControlError("No veo qué está sonando")
        if title not in _lab_queue:
            _lab_queue.append(title)
        return {"detail": "Sumada a la cola de prueba", "tracks": list(_lab_queue), "title": title, "level": _levels["spotify"]}
    if SYSTEM == "Windows":
        row = pick_spotify_window(_windows_list())
        if row is None:
            _launch_spotify_app()
            raise ControlError("Abro Spotify. Espera un segundo y pulsa otra vez.")
        if not _focus_for_keys(row["id"]):
            raise ControlError("No pude poner Spotify delante.")
        time.sleep(0.12)
        _win_hotkey(0x12, 0x10, 0x42)
        return {"detail": "Spotify me gusta", "title": _spotify_title(row), "level": _levels["spotify"]}
    if SYSTEM == "Darwin":
        _run(["osascript", "-e", 'tell application "Spotify" to activate'], timeout=4)
        result = _run(
            ["osascript", "-e", 'tell application "System Events" to keystroke "b" using {option down, shift down}'],
            timeout=4,
        )
        if result.returncode != 0:
            raise ControlError("Abre la app de Spotify en el Mac")
        return {"detail": "Spotify me gusta", "title": _spotify_now(), "level": _levels["spotify"]}
    raise ControlError("Me gusta está en prueba en Windows y Mac")


def clean_url(raw: str) -> str:
    text = str(raw or "").strip()[:200]
    if text.startswith(("http://", "https://")):
        return text
    if "://" in text or " " in text or "." not in text:
        raise ControlError("escribe una dirección web")
    return "https://" + text


def lab(action: str, extra: dict | None = None) -> dict[str, Any]:
    extra = extra or {}
    notices = {
        "desktop": "Escritorio",
        "alttab": "Cambiar de ventana",
        "back": "Atrás",
        "forward": "Adelante",
        "copy": "Copiar",
        "paste": "Pegar",
        "undo": "Deshacer",
        "close": "Cerrar ventana",
        "middle": "Clic central",
        "zoomin": "Zoom +",
        "zoomout": "Zoom −",
    }
    if action in notices:
        _lab_shortcut(action)
        return {"detail": notices[action]}
    if action == "open":
        import webbrowser

        url = clean_url(extra.get("url", ""))
        webbrowser.open(url)
        return {"detail": "Abierto en el PC"}
    if SYSTEM != "Windows":
        raise ControlError("Esa prueba está solo en Windows")
    if action == "lock":
        ctypes.windll.user32.LockWorkStation()
        return {"detail": "Windows bloqueado"}
    if action == "screen":
        user32 = ctypes.windll.user32
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)
        return {"detail": "Pantalla apagada"}
    if action == "sleep":
        ctypes.windll.Powrprof.SetSuspendState(0, 1, 0)
        return {"detail": "Windows suspendido"}
    if action == "shot":
        return {"detail": _windows_shot()}
    if action == "bright_up":
        return {"detail": _windows_brightness(10)}
    if action == "bright_down":
        return {"detail": _windows_brightness(-10)}
    if action == "battery":
        return {"detail": _windows_battery()}
    if action == "front":
        return {"detail": _windows_front() or "Sin ventana activa"}
    raise ControlError("prueba no válida")


def _lab_shortcut(action: str) -> None:
    _input()
    from pynput.keyboard import Key

    chords = {
        "desktop": ["cmd", "d"],
        "alttab": ["alt", "tab"],
        "back": ["alt", "left"],
        "forward": ["alt", "right"],
        "copy": ["ctrl", "c"],
        "paste": ["ctrl", "v"],
        "undo": ["ctrl", "z"],
        "close": ["alt", "f4"],
    }
    if action == "middle":
        mouse_click("middle")
        return
    if action in {"zoomin", "zoomout"}:
        _mouse, keyboard = _input()
        keyboard.press(Key.ctrl)
        try:
            mouse, _keyboard = _input()
            mouse.scroll(0, 1 if action == "zoomin" else -1)
        finally:
            keyboard.release(Key.ctrl)
        return
    _lab_chord(chords[action])


def _lab_chord(parts: list[str]) -> None:
    _input()
    from pynput.keyboard import Key

    table = {
        "shift": Key.shift,
        "ctrl": Key.ctrl,
        "alt": Key.alt,
        "cmd": Key.cmd,
        "tab": Key.tab,
        "left": Key.left,
        "right": Key.right,
        "f4": Key.f4,
    }
    _mouse, keyboard = _input()
    held = []
    try:
        for part in parts:
            key = table.get(part, part if len(part) == 1 else None)
            if key is None:
                raise ControlError("atajo no válido")
            keyboard.press(key)
            if part in table and part not in {"tab", "left", "right", "f4"}:
                held.append(key)
            else:
                keyboard.release(key)
    finally:
        for key in reversed(held):
            keyboard.release(key)


def _windows_shot() -> str:
    _files_dir.mkdir(parents=True, exist_ok=True)
    dest = _files_dir / f"captura-{time.strftime('%H%M%S')}.png"
    path = str(dest).replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
        "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
        "$g = [System.Drawing.Graphics]::FromImage($bmp); "
        "$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); "
        f"$bmp.Save('{path}', [System.Drawing.Imaging.ImageFormat]::Png); "
        "$g.Dispose(); $bmp.Dispose()"
    )
    result = _run(["powershell", "-NoProfile", "-Command", script], timeout=15)
    if result.returncode != 0 or not dest.is_file():
        raise ControlError("No pude guardar la captura")
    return "Captura en el puente"


def _windows_brightness(delta: int) -> str:
    script = (
        "$m = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop; "
        f"$n = [Math]::Max(0, [Math]::Min(100, [int]$m.CurrentBrightness + ({int(delta)}))); "
        "$w = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods; "
        "Invoke-CimMethod -InputObject $w -MethodName WmiSetBrightness -Arguments @{Timeout=1; Brightness=$n} | Out-Null; "
        "Write-Output $n"
    )
    result = _run(["powershell", "-NoProfile", "-Command", script], timeout=8)
    level = result.stdout.strip().splitlines()[-1:] or [""]
    if result.returncode != 0 or not level[0].isdigit():
        raise ControlError("Este PC no dejó cambiar el brillo")
    return f"Brillo {level[0]}"


def _windows_battery() -> str:
    script = "(Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue).EstimatedChargeRemaining"
    result = _run(["powershell", "-NoProfile", "-Command", script], timeout=8)
    text = result.stdout.strip().splitlines()[-1:] or [""]
    if not text[0].isdigit():
        return "Sin batería"
    return f"Batería {text[0]}%"


def _windows_front() -> str:
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value.strip()[:80]


def _spotify_title(row: dict[str, str]) -> str:
    title = row["title"]
    if title.lower() in {"spotify", "spotify premium", "spotify free"}:
        return "Spotify"
    return title[:180]


def _windows_spotify_volume(hwnd: int, level: int, title: str) -> dict[str, Any]:
    level = max(0, min(100, int(level)))
    steps = int(round((level - _levels["spotify"]) / 10))
    steps = max(-10, min(10, steps))
    if steps:
        if not _focus_for_keys(str(hwnd)):
            raise ControlError("No pude poner Spotify delante.")
        for _ in range(abs(steps)):
            _win_hotkey(0x11, 0x26 if steps > 0 else 0x28)
            time.sleep(0.03)
        _levels["spotify"] = max(0, min(100, _levels["spotify"] + steps * 10))
    else:
        _levels["spotify"] = level
    return {"detail": "Spotify", "title": title, "level": _levels["spotify"]}


def _spotify_search(query: str) -> dict[str, Any]:
    import urllib.parse

    query = query.strip()[:120]
    if not query:
        raise ControlError("escribe qué buscar")
    uri = "spotify:search:" + urllib.parse.quote(query)
    if SYSTEM == "Windows":
        subprocess.Popen(["cmd", "/c", "start", "", uri], close_fds=True, creationflags=_NO_WINDOW)
    elif SYSTEM == "Darwin":
        subprocess.Popen(["open", uri])
    else:
        subprocess.Popen(["xdg-open", uri])
    return {
        "detail": "Búsqueda en la app de Spotify",
        "title": query,
        "results": [],
        "level": _levels["spotify"],
    }


def status() -> dict[str, Any]:
    now = ""
    try:
        info = spotify("status")
        now = info.get("title", "")
    except ControlError:
        now = ""
    return {
        "platform": SYSTEM,
        "cursor": _cursor_mode,
        "spotify": now,
    }


def set_history_path(path: Path) -> None:
    global _history_path, _history, _history_loaded, _clip_seq
    _history_path = Path(path)
    _history = []
    _history_loaded = False
    _clip_seq = 0


def clipboard_history(text: str | None = None, auto: bool = False) -> dict[str, Any]:
    with _clip_lock:
        _load_history()
        if text is not None:
            clean = _clip_norm(text)
            if clean:
                _remember_clip(clean, auto)
        ranked = sorted(
            _history,
            key=lambda item: (float(item.get("at") or 0), int(item.get("seq") or 0)),
            reverse=True,
        )
        _history[:] = ranked
        return {"items": [dict(item) for item in _history]}


def _clip_norm(text: str) -> str:
    clean = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return clean[:_CLIP_CHARS]


def _remember_clip(clean: str, auto: bool) -> None:
    global _clip_seq
    for index, item in enumerate(_history):
        if _clip_norm(str(item.get("text") or "")) == clean:
            if auto:
                return
            _clip_seq += 1
            item["text"] = clean
            item["at"] = time.time()
            item["seq"] = _clip_seq
            _history.insert(0, _history.pop(index))
            _save_history()
            return
    _clip_seq += 1
    _history.insert(
        0,
        {"id": secrets.token_hex(4), "text": clean, "at": time.time(), "seq": _clip_seq},
    )
    del _history[_CLIP_LIMIT:]
    _save_history()


def _load_history() -> None:
    global _history_loaded
    if _history_loaded:
        return
    _history_loaded = True
    try:
        raw = json.loads(_open_seal(_history_path.read_bytes()).decode("utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return
    if not isinstance(raw, list):
        return
    kept: dict[str, tuple[tuple[float, int], dict[str, Any]]] = {}
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        clean = _clip_norm(item["text"])
        if not clean:
            continue
        stamp = (float(item.get("at") or 0), int(item.get("seq") or 0))
        previous = kept.get(clean)
        if previous is None or stamp >= previous[0]:
            kept[clean] = (stamp, item)
    ranked = sorted(kept.items(), key=lambda pair: pair[1][0], reverse=True)
    global _clip_seq
    for clean, (stamp, item) in ranked[:_CLIP_LIMIT]:
        seq = int(item.get("seq") or 0)
        _clip_seq = max(_clip_seq, seq)
        _history.append(
            {
                "id": str(item.get("id") or secrets.token_hex(4)),
                "text": clean,
                "at": stamp[0],
                "seq": seq,
            }
        )


def _save_history() -> None:
    try:
        raw = json.dumps(_history, ensure_ascii=False).encode("utf-8")
        _history_path.write_bytes(_seal(raw))
    except OSError:
        return


def _read_clipboard_text() -> str:
    try:
        if SYSTEM == "Windows":
            return _windows_clipboard()
        if SYSTEM == "Darwin":
            result = _run(["pbpaste"])
            return result.stdout if result.returncode == 0 else ""
        import os

        if os.environ.get("WAYLAND_DISPLAY") and _which("wl-paste"):
            result = _run(["wl-paste", "-n"])
            if result.returncode == 0:
                return result.stdout
        if _which("xclip"):
            result = _run(["xclip", "-selection", "clipboard", "-o"])
            if result.returncode == 0:
                return result.stdout
        if _which("xsel"):
            result = _run(["xsel", "--clipboard", "--output"])
            if result.returncode == 0:
                return result.stdout
    except Exception:
        return ""
    return ""


def _windows_clipboard() -> str:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_bool
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_bool
    if not user32.OpenClipboard(None):
        time.sleep(0.02)
        if not user32.OpenClipboard(None):
            return ""
    try:
        handle = user32.GetClipboardData(13)
        if not handle:
            return ""
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


_injected_until = 0.0
_clip_injected: tuple[str, float] | None = None  # 0.52: (huella, hasta) de lo que pusimos nosotros
_CLIP_MARGIN = 0.3


def _clip_digest(text: str) -> str:
    return hashlib.sha256(_clip_norm(text).encode("utf-8", "replace")).hexdigest()


def _mark_injected(text: str | None = None) -> None:
    """Marca algo inyectado por LaZoo. Sin texto: ratón (0,2 s). Con texto: portapapeles,
    para que el vigilante no lo vuelva a meter en el historial."""
    global _injected_until, _clip_injected
    if text is None:
        _injected_until = time.time() + 0.2
        return
    _clip_injected = (_clip_digest(text), time.time() + _CLIP_MARGIN)
    CLIP_WATCH.seen(text)


def _write_clipboard_text(text: str) -> bool:
    """0.52: escribe texto en el portapapeles del sistema. Devuelve si lo consiguió."""
    try:
        if SYSTEM == "Windows":
            return _windows_set_clipboard(text)
        if SYSTEM == "Darwin":
            return _run_input(["pbcopy"], text)
        if os.environ.get("WAYLAND_DISPLAY") and _which("wl-copy"):
            if _run_input(["wl-copy"], text):
                return True
        if _which("xclip"):
            return _run_input(["xclip", "-selection", "clipboard", "-i"], text)
        if _which("xsel"):
            return _run_input(["xsel", "--clipboard", "--input"], text)
    except Exception:
        return False
    return False


def _run_input(cmd: list[str], text: str) -> bool:
    # xclip/wl-copy se quedan sirviendo el portapapeles: sin esperar su salida.
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
        )
        assert proc.stdin is not None
        proc.stdin.write(text.encode("utf-8"))
        proc.stdin.close()
        try:
            return proc.wait(timeout=1.5) == 0
        except subprocess.TimeoutExpired:
            return True  # sigue vivo sirviendo la selección
    except OSError:
        return False


def _windows_set_clipboard(text: str) -> bool:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.EmptyClipboard.restype = ctypes.c_bool
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    data = (text.replace("\r\n", "\n").replace("\n", "\r\n") + "\x00").encode("utf-16-le")
    handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
    if not handle:
        return False
    ptr = kernel32.GlobalLock(handle)
    if not ptr:
        kernel32.GlobalFree(handle)
        return False
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(handle)
    for _ in range(5):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.03)
    else:
        kernel32.GlobalFree(handle)
        return False
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(13, handle):  # CF_UNICODETEXT; Windows se queda la memoria
            kernel32.GlobalFree(handle)
            return False
        return True
    finally:
        user32.CloseClipboard()


def clipboard_to_system(text: str) -> bool:
    """0.52: nota del móvil -> historial + portapapeles del PC, marcada como nuestra."""
    clean = _clip_norm(text)
    if not clean:
        raise ControlError("Nota vacía")
    _mark_injected(clean)
    ok = _write_clipboard_text(clean)
    _mark_injected(clean)  # el margen cuenta desde que ya está escrito
    return ok


class ClipWatch:
    """0.52: vigila el portapapeles del PC y añade lo nuevo al historial (auto=True).

    No apunta nada en logs ni guarda nada en el móvil. Ignora vacíos, repetidos
    seguidos, textos enormes y lo que acaba de poner LaZoo. Se apaga con
    `--sin-portapapeles` o `LAZO_SIN_PORTAPAPELES=1`."""

    INTERVAL = 1.5
    MAX_CHARS = 100_000  # más que esto no es una nota: se ignora sin recortar

    def __init__(self, read=None, add=None) -> None:
        self.enabled = os.environ.get("LAZO_SIN_PORTAPAPELES", "") not in ("1", "si", "sí", "true")
        self._read = read
        self._add = add
        self._last: str | None = None  # huella de lo último visto
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.added = 0

    def seen(self, text: str) -> None:
        self._last = _clip_digest(text)

    def poll(self, now: float | None = None) -> bool:
        """Una pasada. Devuelve True si añadió algo al historial."""
        read = self._read or _read_clipboard_text
        try:
            text = read() or ""
        except Exception:
            return False
        if not isinstance(text, str) or len(text) > self.MAX_CHARS:
            return False
        clean = _clip_norm(text)
        if not clean:
            return False
        digest = _clip_digest(clean)
        if digest == self._last:
            return False
        self._last = digest
        mark = _clip_injected
        if mark is not None and mark[0] == digest and (now or time.time()) <= mark[1]:
            return False  # lo pusimos nosotros (desde el móvil): ya está en el historial
        (self._add or (lambda t: clipboard_history(t, auto=True)))(clean)
        self.added += 1
        return True

    def start(self) -> bool:
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="lazo-portapapeles", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.INTERVAL):
            self.poll()


CLIP_WATCH = ClipWatch()


def watch_clipboard() -> bool:
    if "unittest" in sys.modules or "pytest" in sys.modules:
        return False  # en pruebas no se toca el portapapeles real
    return CLIP_WATCH.start()


class Vigilante:
    """Vigilante del ratón del PC (solo Windows).

    Qué hace: si pusiste el cursor grande o enorme desde el móvil y alguien mueve el
    ratón de verdad del PC, lo devuelve a tamaño normal. Para saberlo pone un gancho
    global de ratón (WH_MOUSE_LL) por el que Windows hace pasar TODOS los movimientos,
    también los del móvil. Al apagarlo solo se pierde esa vuelta automática al cursor
    normal: el ratón del móvil, los clics y el resto siguen igual.

    0.48: el gancho solo está puesto mientras el cursor NO es normal (antes estaba
    siempre). El callback no hace nada pesado: mira una bandera y avisa a otro hilo,
    que es el que cambia el cursor. Se puede apagar en caliente o al arrancar con
    `--sin-vigilante` o `LAZO_SIN_VIGILANTE=1`."""

    def __init__(self) -> None:
        import os

        self.enabled = os.environ.get("LAZO_SIN_VIGILANTE", "") not in ("1", "si", "sí", "true")
        self.always = os.environ.get("LAZO_VIGILANTE_SIEMPRE") == "1"  # pruebas: gancho puesto aunque el cursor sea normal
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._tid = 0
        self.installed = False
        self.events = 0
        self.real_events = 0
        self.cost_ns = 0
        self.cost_max_ns = 0
        self._wake = threading.Event()
        self._worker: threading.Thread | None = None

    def wanted(self) -> bool:
        return SYSTEM == "Windows" and self.enabled and (self.always or _cursor_mode != "normal")

    def set(self, on: bool) -> dict:
        self.enabled = bool(on)
        self.sync()
        return self.status()

    def status(self) -> dict:
        n = self.events
        return {
            "enabled": self.enabled,
            "installed": self.installed,
            "available": SYSTEM == "Windows",
            "events": n,
            "real_events": self.real_events,
            "avg_us": round(self.cost_ns / n / 1000, 1) if n else None,
            "max_us": round(self.cost_max_ns / 1000, 1) if n else None,
        }

    def sync(self) -> None:
        if SYSTEM != "Windows":
            return
        with self._lock:
            alive = self._thread is not None and self._thread.is_alive()
            if self.wanted() and not alive:
                ready = threading.Event()
                self._thread = threading.Thread(target=self._loop, args=(ready,), name="lazo-mouse", daemon=True)
                self._thread.start()
                ready.wait(2)
            elif not self.wanted() and alive:
                ctypes.windll.user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)  # WM_QUIT
                self._thread.join(2)

    def _restore(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            try:
                if _cursor_mode != "normal":
                    set_cursor_mode("normal")
            except Exception:
                pass

    def _loop(self, ready: threading.Event) -> None:
        import ctypes.wintypes as wt

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        LRESULT = ctypes.c_ssize_t
        user32.CallNextHookEx.restype = LRESULT
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        flags_at = 8 + 4  # MSLLHOOKSTRUCT: POINT pt (8), DWORD mouseData (4), DWORD flags
        read_u32 = ctypes.c_uint32.from_address
        clock = time.perf_counter_ns
        if self._worker is None:
            self._worker = threading.Thread(target=self._restore, name="lazo-cursor", daemon=True)
            self._worker.start()

        def _proc(code, wparam, lparam):
            t0 = clock()
            if code >= 0 and lparam:
                if not (read_u32(lparam + flags_at).value & 0x03):  # 0x01/0x02: inyectado
                    self.real_events += 1
                    if _cursor_mode != "normal" and time.time() > _injected_until:
                        self._wake.set()  # el trabajo pesado va en otro hilo
            spent = clock() - t0
            self.events += 1
            self.cost_ns += spent
            if spent > self.cost_max_ns:
                self.cost_max_ns = spent
            return user32.CallNextHookEx(None, code, wparam, lparam)

        proc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t)(_proc)
        self._tid = kernel32.GetCurrentThreadId()
        msg = wt.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # crea la cola antes de avisar
        hook = user32.SetWindowsHookExW(14, proc, None, 0)
        self.installed = bool(hook)
        ready.set()
        try:
            while hook and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if hook:
                user32.UnhookWindowsHookEx(hook)
            self.installed = False
            del proc


VIGILANTE = Vigilante()


def set_vigilante(on) -> dict:
    return VIGILANTE.set(bool(on))


def watch_physical_mouse() -> None:
    VIGILANTE.sync()


_files_dir = Path(__file__).with_name("nube")
_photos_dir = Path(__file__).with_name("Fotos")
_FILE_CAP = 80 * 1024 * 1024
_files_lock = threading.Lock()
_PHOTO_CAP = 1536 * 1024 * 1024
_PHOTO_TOTAL = 30 * 1024 * 1024 * 1024
_photo_lock = threading.Lock()


def set_files_dir(path: Path) -> None:
    global _files_dir
    _files_dir = Path(path)


def set_photos_dir(path: Path) -> None:
    global _photos_dir
    _photos_dir = Path(path)


def list_photos() -> dict[str, Any]:
    _photos_dir.mkdir(parents=True, exist_ok=True)
    rows = _photo_rows()
    return {"folder": str(_photos_dir), "count": len(rows), "bytes": sum(row["size"] for row in rows), "photos": rows[:60]}


def photo_status(name: str, size: int) -> dict[str, Any]:
    size = int(size)
    if size <= 0 or size > _PHOTO_CAP:
        raise ControlError("Pasa de 1,5 GB o está vacío")
    clean = _photo_name(name)
    path = _photos_dir / clean
    skip = path.is_file() and path.stat().st_size == size
    return {"skip": skip, "name": clean}


def start_photo(name: str, size: int) -> tuple[Path, Path] | None:
    size = int(size)
    if size <= 0 or size > _PHOTO_CAP:
        raise ControlError("Pasa de 1,5 GB o está vacío")
    clean = _photo_name(name)
    with _photo_lock:
        _photos_dir.mkdir(parents=True, exist_ok=True)
        current = _photos_dir / clean
        if current.is_file() and current.stat().st_size == size:
            return None
        used = sum(path.stat().st_size for path in _photos_dir.iterdir() if path.is_file() and not path.name.endswith(".part"))
        if used + size > _PHOTO_TOTAL:
            raise ControlError("La carpeta Fotos está llena")
        final = current if not current.exists() else _unique_photo(clean)
        part = Path(str(final) + ".part")
        part.write_bytes(b"")
        return part, final


def finish_photo(part: Path, final: Path, size: int) -> dict[str, Any]:
    if not part.is_file() or part.stat().st_size != int(size):
        part.unlink(missing_ok=True)
        raise ControlError("Se cortó el envío")
    if final.parent != _photos_dir:
        part.unlink(missing_ok=True)
        raise ControlError("nombre no válido")
    part.replace(final)
    return {"name": final.name, "size": int(size), "folder": str(_photos_dir)}


def open_photos_folder() -> dict[str, Any]:
    import os

    _photos_dir.mkdir(parents=True, exist_ok=True)
    if SYSTEM == "Windows":
        os.startfile(_photos_dir)  # type: ignore[attr-defined]
    elif SYSTEM == "Darwin":
        _run(["open", str(_photos_dir)])
    else:
        _run(["xdg-open", str(_photos_dir)])
    return {"folder": str(_photos_dir)}


def _photo_name(name: str) -> str:
    import puente

    return puente.clean_name(name, "foto")


def received_dir() -> Path:
    return _photos_dir


def _unique_photo(name: str) -> Path:
    stem, dot, ext = name.rpartition(".")
    if not dot or not stem:
        stem, ext = name, ""
    else:
        ext = "." + ext
    number = 2
    while True:
        candidate = _photos_dir / f"{stem} ({number}){ext}"
        if not candidate.exists():
            return candidate
        number += 1


def _photo_rows() -> list[dict[str, Any]]:
    if not _photos_dir.is_dir():
        return []
    rows = []
    for path in _photos_dir.iterdir():
        if not path.is_file() or path.name.endswith(".part") or path.name.startswith("."):
            continue
        stat = path.stat()
        rows.append({"name": path.name, "size": stat.st_size, "at": int(stat.st_mtime)})
    rows.sort(key=lambda row: (row["at"], row["name"]), reverse=True)
    return rows


def list_files() -> dict[str, Any]:
    return {"files": _file_rows()}


def save_file(name: str, data: bytes) -> dict[str, Any]:
    if not isinstance(data, bytes) or not data:
        raise ControlError("archivo vacío")
    if len(data) > _FILE_CAP:
        raise ControlError("El archivo pasa de 80 MB")
    _files_dir.mkdir(parents=True, exist_ok=True)
    _check_space(len(data))
    file_id = secrets.token_hex(4)
    (_files_dir / file_id).write_bytes(_seal(data))
    return _add_file_row({"id": file_id, "name": _nube_name(name), "size": len(data), "at": int(time.time())})


def save_file_stream(name: str, source, length: int, limit: int) -> dict[str, Any]:
    """Guarda un archivo grande del PC en la mesa leyendo a trozos, sin cargarlo entero.
    Va sin DPAPI (sería cargarlo en memoria): se queda en la carpeta `nube` del PC."""
    if length <= 0:
        raise ControlError("archivo vacío")
    if length > limit:
        raise ControlError("El archivo pasa del límite del puente")
    _files_dir.mkdir(parents=True, exist_ok=True)
    _check_space(length)
    file_id = secrets.token_hex(4)
    path = _files_dir / file_id
    left = length
    try:
        with path.open("wb") as out:
            while left > 0:
                chunk = source.read(min(1024 * 1024, left))
                if not chunk:
                    break
                out.write(chunk)
                left -= len(chunk)
    except OSError as exc:
        path.unlink(missing_ok=True)
        raise ControlError("No se pudo guardar en el PC") from exc
    if left:
        path.unlink(missing_ok=True)
        raise ControlError("Se cortó el envío")
    return _add_file_row({"id": file_id, "name": _nube_name(name), "size": length, "at": int(time.time()), "raw": True})


def _nube_name(name: str) -> str:
    import puente

    return puente.clean_name(name)[:120]


def _check_space(size: int) -> None:
    import puente

    free = shutil.disk_usage(_files_dir).free
    if free - size < puente.MARGIN:
        raise ControlError(f"No cabe en el PC: quedan {puente.human(max(0, free - puente.MARGIN))} libres")


def _add_file_row(row: dict[str, Any]) -> dict[str, Any]:
    with _files_lock:
        rows = _file_rows()
        rows.insert(0, row)
        for old in rows[30:]:
            (_files_dir / old["id"]).unlink(missing_ok=True)
        _write_file_rows(rows[:30])
    return {"file": row}


def file_path(file_id: str) -> tuple[dict[str, Any], Path]:
    row = _file_row(file_id)
    if row is None:
        raise ControlError("ese archivo ya no está")
    return row, _files_dir / row["id"]


def read_file(file_id: str) -> tuple[str, bytes]:
    row = _file_row(file_id)
    if row is None:
        raise ControlError("ese archivo ya no está")
    data = (_files_dir / row["id"]).read_bytes()
    return row["name"], data if row.get("raw") else _open_seal(data)


def delete_file(file_id: str) -> dict[str, Any]:
    with _files_lock:
        row = _file_row(file_id)
        rows = [item for item in _file_rows() if item["id"] != file_id]
        if row is not None:
            path = _files_dir / row["id"]
            if path.is_file():
                path.unlink()
        _write_file_rows(rows)
    return {"ok": True}


def _file_row(file_id: str) -> dict[str, Any] | None:
    if not isinstance(file_id, str) or len(file_id) != 8 or any(ch not in "0123456789abcdef" for ch in file_id):
        return None
    for row in _file_rows():
        if row["id"] == file_id:
            return row
    return None


def _file_rows() -> list[dict[str, Any]]:
    try:
        raw = json.loads((_files_dir / "index.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        file_id = str(item.get("id", ""))
        if len(file_id) != 8 or not (_files_dir / file_id).is_file():
            continue
        rows.append(
            {
                "id": file_id,
                "name": str(item.get("name") or "archivo")[:120],
                "size": int(item.get("size") or 0),
                "at": int(item.get("at") or 0),
                **({"raw": True} if item.get("raw") else {}),
            }
        )
    return rows


def _write_file_rows(rows: list[dict[str, Any]]) -> None:
    _files_dir.mkdir(parents=True, exist_ok=True)
    tmp = _files_dir / "index.json.tmp"
    tmp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_files_dir / "index.json")


def _seal(data: bytes) -> bytes:
    if SYSTEM != "Windows" or not data:
        return data
    sealed = _dpapi(data, True)
    if not sealed:
        return data
    return b"LZ1" + sealed


def _open_seal(data: bytes) -> bytes:
    if data.startswith(b"LZ1"):
        opened = _dpapi(data[3:], False)
        return opened or data
    return data


def _dpapi(data: bytes, protect: bool) -> bytes:
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.c_void_p)]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data)
    incoming = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.c_void_p))
    outgoing = DATA_BLOB()
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_wchar_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.argtypes = crypt32.CryptProtectData.argtypes
    crypt32.CryptProtectData.restype = ctypes.c_bool
    crypt32.CryptUnprotectData.restype = ctypes.c_bool
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(incoming), None, None, None, None, 0, ctypes.byref(outgoing)):
        return b""
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        kernel32.LocalFree(outgoing.pbData)





# --- Pantallas y pastilla Sistema (0.33) ---

MAX_SCREENS = 3
_screens_hook = None  # pruebas: función que devuelve la lista de pantallas


def set_screens_hook(fn) -> None:
    global _screens_hook
    _screens_hook = fn


def parse_xrandr_monitors(text: str) -> list[dict[str, Any]]:
    """Lee `xrandr --listmonitors`: ' 0: +*HDMI-1 1920/530x1080/300+0+0  HDMI-1'."""
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3 or not parts[0].rstrip(":").isdigit():
            continue
        geo = parts[2]
        try:
            size, x, y = geo.split("+")[:3]
            w = int(size.split("x")[0].split("/")[0])
            h = int(size.split("x")[1].split("/")[0])
            rows.append({"x": int(x), "y": int(y), "w": w, "h": h, "primary": "*" in parts[1]})
        except (ValueError, IndexError):
            continue
    return rows


def _number_screens(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """La principal es la 1; el resto de izquierda a derecha. Máximo 3."""
    rows = sorted(rows, key=lambda r: (not r.get("primary"), r["x"], r["y"]))[:MAX_SCREENS]
    for i, row in enumerate(rows, 1):
        row["n"] = i
    return rows


def list_screens() -> list[dict[str, Any]]:
    if _screens_hook is not None:
        return _number_screens([dict(r) for r in _screens_hook()])
    if SYSTEM == "Windows":
        return _number_screens(_windows_screens())
    if SYSTEM == "Linux" and _which("xrandr") and _display_ok():
        result = _run(["xrandr", "--listmonitors"])
        if result.returncode == 0:
            return _number_screens(parse_xrandr_monitors(result.stdout))
    return []


def screens_info() -> dict[str, Any]:
    try:
        rows = list_screens()
    except Exception:
        rows = []
    can_move = len(rows) > 1 and (SYSTEM == "Windows" or (SYSTEM == "Linux" and _which("wmctrl")) or _screens_hook is not None)
    return {"screens": rows, "count": len(rows), "can_move": can_move}


def _windows_screens() -> list[dict[str, Any]]:
    from ctypes import wintypes

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32 = ctypes.windll.user32
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    rows: list[dict[str, Any]] = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ssize_t)

    def callback(hmon, _hdc, _rect, _data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            w = info.rcWork
            m = info.rcMonitor
            rows.append({
                "x": m.left, "y": m.top, "w": m.right - m.left, "h": m.bottom - m.top,
                "wx": w.left, "wy": w.top, "ww": w.right - w.left, "wh": w.bottom - w.top,
                "primary": bool(info.dwFlags & 1),
            })
        return True

    cb = proto(callback)
    user32.EnumDisplayMonitors.argtypes = [ctypes.c_void_p, ctypes.c_void_p, proto, ctypes.c_ssize_t]
    user32.EnumDisplayMonitors(None, None, cb, 0)
    return rows


def place_on_screen(win: tuple[int, int, int, int], screens: list[dict[str, Any]], target: int) -> tuple[int, int, int, int]:
    """Nuevo (x, y, ancho, alto) para llevar la ventana a la pantalla `target`,
    con el mismo hueco relativo y sin salirse del área útil."""
    x, y, w, h = win
    dst = next((s for s in screens if s["n"] == target), None)
    if dst is None:
        raise ControlError("Esa pantalla no existe")
    cx, cy = x + w // 2, y + h // 2
    src = next((s for s in screens if s["x"] <= cx < s["x"] + s["w"] and s["y"] <= cy < s["y"] + s["h"]), screens[0])
    ax, ay = dst.get("wx", dst["x"]), dst.get("wy", dst["y"])
    aw, ah = dst.get("ww", dst["w"]), dst.get("wh", dst["h"])
    w, h = min(w, aw), min(h, ah)
    nx = ax + (x - src.get("wx", src["x"]))
    ny = ay + (y - src.get("wy", src["y"]))
    nx = max(ax, min(nx, ax + aw - w))
    ny = max(ay, min(ny, ay + ah - h))
    return nx, ny, w, h


def window_to_screen(window_id: str, target: int) -> str:
    try:
        target = int(target)
    except (TypeError, ValueError):
        raise ControlError("pantalla no válida") from None
    if not 0 <= target <= MAX_SCREENS:
        raise ControlError("pantalla no válida")
    if not window_id:
        raise ControlError("falta la ventana")
    screens = list_screens()
    if len(screens) < 2:
        raise ControlError("Solo hay una pantalla")
    if target == 0:
        # «Cambiar de pantalla» con dos pantallas: a la otra.
        if len(screens) != 2:
            raise ControlError("Elige la pantalla de destino")
        rect = _window_rect(window_id)
        here = screen_of(rect, screens) if rect else 0
        target = 2 if here == 1 else 1
    with _lock:
        if SYSTEM == "Windows":
            return _windows_to_screen(int(window_id), screens, target)
        if SYSTEM == "Linux":
            return _linux_to_screen(window_id, screens, target)
    raise ControlError("No disponible en este sistema")


def _window_rect(window_id: str) -> tuple[int, int, int, int] | None:
    if _swap_hook is not None:
        return dict(_swap_hook("list")).get(window_id)
    if SYSTEM == "Windows":
        from ctypes import wintypes

        user32 = _user32()
        user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        rect = wintypes.RECT()
        if user32.GetWindowRect(_hwnd(int(window_id)), ctypes.byref(rect)):
            return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
        return None
    if SYSTEM == "Linux" and _which("wmctrl"):
        return dict(_linux_rects()).get(window_id)
    return None


def screen_of(rect: tuple[int, int, int, int], screens: list[dict[str, Any]]) -> int:
    """Número de la pantalla donde cae el centro de la ventana (0 si ninguna)."""
    x, y, w, h = rect
    cx, cy = x + w // 2, y + h // 2
    for scr in screens:
        if scr["x"] <= cx < scr["x"] + scr["w"] and scr["y"] <= cy < scr["y"] + scr["h"]:
            return scr["n"]
    return 0


def plan_swap(wins: list[tuple[str, tuple[int, int, int, int]]], screens: list[dict[str, Any]], a: int, b: int) -> list[tuple[str, int]]:
    """Qué ventana va a qué pantalla para intercambiar las pantallas a y b."""
    plan = []
    for win_id, rect in wins:
        n = screen_of(rect, screens)
        if n == a:
            plan.append((win_id, b))
        elif n == b:
            plan.append((win_id, a))
    return plan


def swap_screens(a: Any = 1, b: Any = 2) -> dict[str, Any]:
    try:
        a, b = int(a), int(b)
    except (TypeError, ValueError):
        raise ControlError("pantalla no válida") from None
    screens = list_screens()
    if len(screens) < 2:
        raise ControlError("Solo hay una pantalla")
    nums = {s["n"] for s in screens}
    if a == b or a not in nums or b not in nums:
        raise ControlError("Elige dos pantallas distintas")
    with _lock:
        if _swap_hook is not None:
            wins = _swap_hook("list")
        elif SYSTEM == "Windows":
            wins = _windows_rects()
        elif SYSTEM == "Linux" and _which("wmctrl"):
            wins = _linux_rects()
        else:
            raise ControlError("No disponible en este sistema")
        plan = plan_swap(wins, screens, a, b)
        moved = 0
        for win_id, target in plan:
            try:
                if _swap_hook is not None:
                    _swap_hook("move", win_id, target)
                elif SYSTEM == "Windows":
                    _windows_to_screen(int(win_id), screens, target, focus=False)
                else:
                    _linux_to_screen(win_id, screens, target, focus=False)
                moved += 1
            except (ControlError, OSError, ValueError):
                continue
    if not plan:
        return {"detail": f"No hay ventanas abiertas en las pantallas {a} y {b}", "moved": 0}
    return {"detail": f"Pantallas {a} y {b} intercambiadas ({moved} ventanas)", "moved": moved}


_swap_hook = None


def set_swap_hook(fn) -> None:
    global _swap_hook
    _swap_hook = fn


def _windows_rects() -> list[tuple[str, tuple[int, int, int, int]]]:
    from ctypes import wintypes

    user32 = _user32()
    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    out = []
    for row in _windows_list():
        handle = _hwnd(int(row["id"]))
        if user32.IsIconic(handle):
            continue
        rect = wintypes.RECT()
        if user32.GetWindowRect(handle, ctypes.byref(rect)):
            out.append((row["id"], (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)))
    return out


def _linux_rects() -> list[tuple[str, tuple[int, int, int, int]]]:
    result = _run(["wmctrl", "-lG"])
    out = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 7)
        if len(parts) < 7 or not parts[0].startswith("0x") or parts[1] == "-1":
            continue
        try:
            out.append((parts[0], (int(parts[2]), int(parts[3]), int(parts[4]), int(parts[5]))))
        except ValueError:
            continue
    return out


def _windows_to_screen(hwnd: int, screens: list[dict[str, Any]], target: int, focus: bool = True) -> str:
    from ctypes import wintypes

    user32 = _user32()
    handle = _hwnd(hwnd)
    if not user32.IsWindow(handle):
        raise ControlError("Esa ventana ya se cerró. Pulsa Actualizar.")
    user32.IsZoomed.argtypes = [ctypes.c_void_p]
    user32.IsZoomed.restype = ctypes.c_bool
    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.MoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_bool]
    zoomed = bool(user32.IsZoomed(handle))
    if zoomed or user32.IsIconic(handle):
        user32.ShowWindow(handle, 9)
    rect = wintypes.RECT()
    user32.GetWindowRect(handle, ctypes.byref(rect))
    x, y, w, h = place_on_screen((rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top), screens, target)
    user32.MoveWindow(handle, x, y, w, h, True)
    if zoomed:
        user32.ShowWindow(handle, 3)
    if focus:
        _force_foreground(hwnd)
    return f"A la pantalla {target}"


def _linux_to_screen(window_id: str, screens: list[dict[str, Any]], target: int, focus: bool = True) -> str:
    if not window_id.startswith("0x") or not _which("wmctrl"):
        raise ControlError("No disponible en este sistema")
    dst = next((s for s in screens if s["n"] == target), None)
    if dst is None:
        raise ControlError("Esa pantalla no existe")
    _run(["wmctrl", "-i", "-r", window_id, "-b", "remove,maximized_vert,maximized_horz"])
    result = _run(["wmctrl", "-i", "-r", window_id, "-e", f"0,{dst['x'] + 40},{dst['y'] + 40},-1,-1"])
    if result.returncode != 0:
        raise ControlError("No pude mover esa ventana")
    if focus:
        _run(["wmctrl", "-i", "-a", window_id])
    return f"A la pantalla {target}"


SYSTEM_ACTIONS = {"vol_up", "vol_down", "vol_mute", "bright_up", "bright_down", "project", "lock", "swap_screens"}


def system_action(action: str, extra: dict | None = None) -> dict[str, Any]:
    if action not in SYSTEM_ACTIONS:
        raise ControlError("acción de sistema no válida")
    if action == "swap_screens":
        extra = extra or {}
        return swap_screens(extra.get("a", 1), extra.get("b", 2))
    if action.startswith("vol_"):
        delta = {"vol_up": 1, "vol_down": -1, "vol_mute": 0}[action]
        return {"detail": system_volume(delta)}
    if action.startswith("bright_"):
        return {"detail": _brightness(10 if action == "bright_up" else -10)}
    if action == "project":
        if SYSTEM != "Windows":
            raise ControlError("No disponible en este sistema")
        _win_hotkey(0x5B, 0x50)
        return {"detail": "Menú de pantallas abierto en el PC"}
    return {"detail": _lock_screen()}


def _brightness(delta: int) -> str:
    if SYSTEM == "Windows":
        try:
            return _windows_brightness(delta)
        except ControlError:
            raise ControlError("Brillo no disponible en este PC (solo portátiles o pantallas compatibles)") from None
    if SYSTEM == "Linux" and _which("brightnessctl"):
        result = _run(["brightnessctl", "set", "10%+" if delta > 0 else "10%-"])
        if result.returncode == 0:
            return "Brillo cambiado"
    raise ControlError("Brillo no disponible en este sistema")


def _lock_screen() -> str:
    if SYSTEM == "Windows":
        ctypes.windll.user32.LockWorkStation()
        return "PC bloqueado"
    if SYSTEM == "Linux":
        for cmd in (["loginctl", "lock-session"], ["xdg-screensaver", "lock"]):
            if _which(cmd[0]) and _run(cmd).returncode == 0:
                return "PC bloqueado"
    if SYSTEM == "Darwin":
        result = _run(["pmset", "displaysleepnow"])
        if result.returncode == 0:
            return "Pantalla del Mac apagada"
    raise ControlError("Bloquear no disponible en este sistema")


def system_caps() -> dict[str, Any]:
    """Qué botones de Sistema se pueden mostrar en este PC."""
    return {
        "system": SYSTEM,
        "brightness": SYSTEM == "Windows" or (SYSTEM == "Linux" and _which("brightnessctl")),
        "project": SYSTEM == "Windows",
        "swap": SYSTEM == "Windows" or (SYSTEM == "Linux" and _which("wmctrl")) or _swap_hook is not None,
        "lock": SYSTEM in {"Windows", "Darwin"} or (SYSTEM == "Linux" and (_which("loginctl") or _which("xdg-screensaver"))),
    }
