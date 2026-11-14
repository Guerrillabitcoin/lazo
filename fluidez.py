"""LaZoo 0.74: que el ratón no vaya a tirones (entre PCs y, de rebote, el del móvil).

Lo que hay aquí (solo biblioteca estándar):

- `Ritmo` y `resumen()`: apuntan instantes y dicen a cuántos Hz llega algo, el hueco más largo
  y cuánto baila (jitter). Un hueco de más de PAUSA s cuenta como «paraste el ratón», no como tirón.
- `reloj()`: duerme pasos de 4 ms y mide cuánto se pasa. Si el reloj de Windows va a saltos
  (plan de energía, ahorro de batería, el proceso «en segundo plano» frenado por Windows 11),
  el ratón del móvil y el de otro PC van a tirones aunque la red vaya bien.
- `no_frenar_proceso()`: en Windows 11, un programa sin ventana visible (LaZoo vive en la bandeja)
  puede quedar en «modo eficiencia» (EcoQoS) y Windows ignora su timeBeginPeriod(1): los sleeps
  de 4-6 ms pasan a 15,6 ms. Se pide que no lo haga (SetProcessInformation, ProcessPowerThrottling).
- `prioridad_hilo()`: sube el hilo del gancho del ratón y el que manda (solo Windows).
- `acelerar()`: mientras se controla otro PC (o te controlan), Python cambia de hilo cada 1 ms en
  vez de cada 5 ms: el gancho del ratón no espera a que otro hilo suelte el intérprete.
- `Suavizador`: en el PC controlado, reparte cada movimiento en pasos de 4 ms a lo largo del
  tiempo en que se hizo en el otro PC (marca de tiempo del emisor), con un colchón pequeño que se
  adapta a lo que baila la red. Interpola, no predice: nunca mueve algo que no se ha hecho.
  Guarda los decimales (nada se pierde al redondear) y nunca deja nada pendiente más de MAX_COLA.
- `veredicto()`: de las medidas, una frase clara en español y consejos.
"""
from __future__ import annotations

import collections
import math
import sys
import threading
import time
from typing import Any, Callable

PAUSA = 0.25          # s: un hueco mayor es que el ratón estaba quieto
PASO = 0.004          # s: el suavizador aplica cada 4 ms (250 Hz)
MAX_TRAMO = 0.030     # s: un movimiento se reparte como mucho en 30 ms
COLCHON_MIN = 0.004   # s
COLCHON_MAX = 0.040   # s: más colchón ya se notaría como retraso
MAX_COLA = 0.120      # s: si se acumula más, se aplica de golpe (mejor un salto que ir con retraso)
VENTANA = 2.0         # s de historia para el desfase de relojes y el colchón


# --- Medir ---------------------------------------------------------------------------------


def _pct(valores: list[float], p: float) -> float:
    if not valores:
        return 0.0
    v = sorted(valores)
    return v[min(len(v) - 1, max(0, int(math.ceil(p * len(v))) - 1))]


def resumen(tiempos: list[float], pausa: float = PAUSA) -> dict[str, Any]:
    """Instantes (s) → {"n", "hz", "hueco_max_ms", "p95_ms", "jitter_ms"} sin contar las pausas."""
    t = sorted(tiempos)
    huecos = [b - a for a, b in zip(t, t[1:]) if 0 <= b - a <= pausa]
    if not huecos:
        return {"n": len(t), "hz": 0, "hueco_max_ms": 0.0, "p95_ms": 0.0, "jitter_ms": 0.0}
    media = sum(huecos) / len(huecos)
    var = sum((h - media) ** 2 for h in huecos) / len(huecos)
    return {"n": len(t), "hz": round(1.0 / media) if media > 0 else 0, "hueco_max_ms": round(max(huecos) * 1000, 1),
            "p95_ms": round(_pct(huecos, 0.95) * 1000, 1), "jitter_ms": round(math.sqrt(var) * 1000, 1)}


class Ritmo:
    """Apunta instantes (desde cualquier hilo, sin bloquear: list.append es atómico)."""

    def __init__(self, reloj: Callable[[], float] = time.perf_counter, maximo: int = 20000) -> None:
        self.reloj = reloj
        self.maximo = maximo
        self.t: list[float] = []

    def apunta(self, t: float | None = None) -> None:
        if len(self.t) < self.maximo:
            self.t.append(self.reloj() if t is None else t)

    def resumen(self) -> dict[str, Any]:
        return resumen(list(self.t))

    def vaciar(self) -> None:
        self.t = []


def reloj(segundos: float = 2.0, paso: float = PASO, dormir: Callable[[float], None] = time.sleep,
          ahora: Callable[[], float] = time.perf_counter) -> dict[str, Any]:
    """Duerme `paso` una y otra vez y mide cuánto se pasa cada vez (ms)."""
    tarde: list[float] = []
    fin = ahora() + segundos
    while ahora() < fin:
        t0 = ahora()
        dormir(paso)
        tarde.append(max(0.0, ahora() - t0 - paso))
    if not tarde:
        return {"paso_ms": paso * 1000, "n": 0, "retraso_max_ms": 0.0, "retraso_p95_ms": 0.0, "retraso_medio_ms": 0.0}
    return {"paso_ms": round(paso * 1000, 1), "n": len(tarde), "retraso_max_ms": round(max(tarde) * 1000, 1),
            "retraso_p95_ms": round(_pct(tarde, 0.95) * 1000, 1),
            "retraso_medio_ms": round(sum(tarde) / len(tarde) * 1000, 2)}


# --- Windows: que no frene el proceso ni los hilos del ratón ----------------------------------


def no_frenar_proceso() -> bool:
    """Windows 10 1709+ / 11: fuera del «modo eficiencia» y respeta timeBeginPeriod(1) aunque LaZoo
    no tenga ventana visible. En otros sistemas no hace nada (False)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes as wt

        class PPT(ctypes.Structure):  # PROCESS_POWER_THROTTLING_STATE
            _fields_ = [("Version", wt.ULONG), ("ControlMask", wt.ULONG), ("StateMask", wt.ULONG)]

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.GetCurrentProcess.restype = wt.HANDLE
        k.SetProcessInformation.argtypes = [wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD]
        k.SetProcessInformation.restype = wt.BOOL
        # EXECUTION_SPEED (1) | IGNORE_TIMER_RESOLUTION (4); StateMask 0 = «no lo hagas».
        estado = PPT(1, 0x1 | 0x4, 0)
        ok = k.SetProcessInformation(k.GetCurrentProcess(), 4, ctypes.byref(estado), ctypes.sizeof(estado))
        if not ok:  # Windows 10 antiguo: sin IGNORE_TIMER_RESOLUTION
            estado = PPT(1, 0x1, 0)
            ok = k.SetProcessInformation(k.GetCurrentProcess(), 4, ctypes.byref(estado), ctypes.sizeof(estado))
        return bool(ok)
    except Exception:  # noqa: BLE001
        return False


def prioridad_hilo(nivel: int = 2) -> bool:
    """Prioridad del hilo actual en Windows (1 ABOVE_NORMAL, 2 HIGHEST). Nunca TIME_CRITICAL."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.GetCurrentThread.restype = ctypes.c_void_p
        k.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
        return bool(k.SetThreadPriority(k.GetCurrentThread(), max(0, min(2, int(nivel)))))
    except Exception:  # noqa: BLE001
        return False


_ACEL = {"n": 0, "antes": None}
_ACEL_LOCK = threading.Lock()


def acelerar(on: bool) -> float:
    """Cuenta quién lo pide: mientras alguien lo pida, sys.setswitchinterval(0.001)."""
    with _ACEL_LOCK:
        if on:
            if _ACEL["n"] == 0:
                _ACEL["antes"] = sys.getswitchinterval()
                sys.setswitchinterval(0.001)
            _ACEL["n"] += 1
        elif _ACEL["n"] > 0:
            _ACEL["n"] -= 1
            if _ACEL["n"] == 0 and _ACEL["antes"] is not None:
                sys.setswitchinterval(_ACEL["antes"])
        return sys.getswitchinterval()


# --- Receptor: suavizado sin predicción --------------------------------------------------------


class Suavizador:
    """Reparte los movimientos en pasos de PASO. `aplicar(dx, dy)` recibe enteros; los decimales
    se guardan para el siguiente paso. Con `hilo=False` (pruebas) se llama a `paso()` a mano."""

    def __init__(self, aplicar: Callable[[int, int], None], reloj: Callable[[], float] = time.monotonic,
                 hilo: bool = True, al_aplicar: Callable[[float], None] | None = None) -> None:
        self.aplicar = aplicar
        self.reloj = reloj
        self.al_aplicar = al_aplicar
        self.lock = threading.Lock()
        self.cola: collections.deque = collections.deque()  # [ini, fin, dx, dy, hecho(0..1)]
        self.resto = [0.0, 0.0]
        self.ultimo_fin = 0.0
        self.desfases: collections.deque = collections.deque()  # (llegada, llegada - t_emisor)
        self.retrasos: collections.deque = collections.deque(maxlen=128)
        self.base = 0          # para desenrollar los ms de 16 bits del emisor
        self.ultimo_raw = -1
        self.ultima_llegada = 0.0
        self.intervalo = 0.008
        self._ev = threading.Event()
        self._fin = False
        self._hilo: threading.Thread | None = None
        if hilo:
            self._hilo = threading.Thread(target=self._bucle, name="lazo-kvm-suave", daemon=True)
            self._hilo.start()

    # ms de 16 bits del emisor → segundos crecientes
    def _desenrollar(self, raw: int) -> float:
        raw &= 0xFFFF
        if self.ultimo_raw >= 0 and raw < self.ultimo_raw - 32768:
            self.base += 65536
        elif self.ultimo_raw >= 0 and raw > self.ultimo_raw + 32768:  # llegó una vieja tras dar la vuelta
            return (self.base - 65536 + raw) / 1000.0
        self.ultimo_raw = raw
        return (self.base + raw) / 1000.0

    def colchon(self) -> float:
        if not self.retrasos:
            return max(COLCHON_MIN, min(self.intervalo, 0.020))
        r = sorted(self.retrasos)
        p90 = r[min(len(r) - 1, int(0.9 * len(r)))]
        return max(COLCHON_MIN, min(COLCHON_MAX, p90 + 0.002))

    def meter(self, dx: int, dy: int, t_emisor_ms: int | None = None) -> None:
        if not (dx or dy):
            return
        ahora = self.reloj()
        with self.lock:
            if self.ultima_llegada and ahora - self.ultima_llegada < PAUSA:
                self.intervalo = 0.8 * self.intervalo + 0.2 * (ahora - self.ultima_llegada)
            self.ultima_llegada = ahora
            if t_emisor_ms is None:
                t_local = ahora
                col = max(COLCHON_MIN, min(self.intervalo, 0.020))
            else:
                te = self._desenrollar(int(t_emisor_ms))
                d = ahora - te
                while self.desfases and ahora - self.desfases[0][0] > VENTANA:
                    self.desfases.popleft()
                self.desfases.append((ahora, d))
                desfase = min(x[1] for x in self.desfases)  # la que menos tardó = sin cola de red
                t_local = te + desfase
                self.retrasos.append(max(0.0, ahora - t_local))
                col = self.colchon()
            fin = max(t_local + col, ahora)
            ini = max(self.ultimo_fin, fin - MAX_TRAMO, ahora - PASO)
            if fin <= ini:  # llegó tarde (o fuera de orden): se reparte en un intervalo, no de golpe
                fin = ini + max(PASO, min(self.intervalo, 0.020))
            if self.cola and fin - self.cola[0][0] > MAX_COLA:  # demasiado atrás: se pone al día
                self._todo()
                ini = fin = ahora
            self.cola.append([ini, fin, float(dx), float(dy), 0.0])
            self.ultimo_fin = fin
        self._ev.set()

    def _todo(self) -> tuple[float, float]:
        sx = sy = 0.0
        for s in self.cola:
            sx += s[2] * (1.0 - s[4])
            sy += s[3] * (1.0 - s[4])
        self.cola.clear()
        self.resto[0] += sx
        self.resto[1] += sy
        return sx, sy

    def _sacar(self) -> tuple[int, int]:
        ix, iy = int(round(self.resto[0])), int(round(self.resto[1]))
        self.resto[0] -= ix
        self.resto[1] -= iy
        return ix, iy

    def paso(self, ahora: float | None = None) -> tuple[int, int]:
        """Aplica lo que toca hasta `ahora`. Devuelve lo aplicado (enteros)."""
        ahora = self.reloj() if ahora is None else ahora
        with self.lock:
            # Los tramos van en orden y no se pisan (cada uno empieza donde acabó el anterior).
            for s in self.cola:
                ini, fin = s[0], s[1]
                if ahora <= ini and fin > ini:
                    break
                frac = 1.0 if fin <= ini or ahora >= fin else (ahora - ini) / (fin - ini)
                if frac > s[4]:
                    self.resto[0] += s[2] * (frac - s[4])
                    self.resto[1] += s[3] * (frac - s[4])
                    s[4] = frac
            while self.cola and self.cola[0][4] >= 1.0:
                self.cola.popleft()
            ix, iy = self._sacar()
        if ix or iy:
            self.aplicar(ix, iy)
            if self.al_aplicar is not None:
                self.al_aplicar(ahora)
        return ix, iy

    def vaciar(self) -> tuple[int, int]:
        """Todo lo pendiente, ya (antes de un clic o una tecla, o al cerrar)."""
        with self.lock:
            self._todo()
            ix, iy = self._sacar()
            self.resto = [0.0, 0.0]
            self.ultimo_fin = 0.0
        if ix or iy:
            self.aplicar(ix, iy)
        return ix, iy

    def pendiente(self) -> bool:
        with self.lock:
            return bool(self.cola)

    def _bucle(self) -> None:
        prioridad_hilo(2)
        while not self._fin:
            if not self.pendiente():
                self._ev.wait(1.0)
                self._ev.clear()
                continue
            try:
                self.paso()
            except Exception:  # noqa: BLE001 (el inyector falló: se descarta, nunca se queda colgado)
                with self.lock:
                    self.cola.clear()
                    self.resto = [0.0, 0.0]
            time.sleep(PASO)

    def cerrar(self) -> None:
        try:
            self.vaciar()
        except Exception:  # noqa: BLE001
            pass
        self._fin = True
        self._ev.set()


# --- Veredicto ---------------------------------------------------------------------------------

UMBRAL_HUECO = 35.0     # ms: un hueco mayor mientras mueves se ve como tirón
UMBRAL_RELOJ = 12.0     # ms de retraso al dormir 4 ms
UMBRAL_TARDE = 40.0     # ms que el gancho llega tarde
UMBRAL_RTT = 50.0       # ms de ida y vuelta (máximo)
UMBRAL_RTT_JITTER = 10.0


def _sistema() -> str:
    return "Windows" if sys.platform == "win32" else ("Linux" if sys.platform.startswith("linux") else "PC")


def veredicto(r: dict[str, Any], sistema: str | None = None, tecla: str = "Ctrl+Alt+L") -> dict[str, Any]:
    """{"nivel": "bien"|"mal"|"aviso", "texto": frase, "consejos": [..], "datos": [líneas]}."""
    sistema = sistema or _sistema()
    rel = r.get("reloj") or {}
    gan = r.get("gancho") or {}
    env = r.get("envio") or {}
    rtt = r.get("rtt") or {}
    rec = r.get("receptor") or {}
    datos: list[str] = []
    if rel:
        datos.append(f"Reloj de este PC: dormir 4 ms se pasa hasta {rel.get('retraso_max_ms', 0)} ms "
                     f"(normalmente {rel.get('retraso_p95_ms', 0)} ms).")
    if gan.get("n"):
        datos.append(f"Ratón de este PC: {gan.get('hz', 0)} Hz, hueco máximo {gan.get('hueco_max_ms', 0)} ms, "
                     f"baile {gan.get('jitter_ms', 0)} ms." + (f" El gancho llegó hasta {r['tarde_max_ms']} ms tarde."
                                                               if r.get("tarde_max_ms") else ""))
    if env.get("n"):
        datos.append(f"Envío al otro PC: {env.get('hz', 0)} tandas/s, hueco máximo {env.get('hueco_max_ms', 0)} ms.")
    if rtt.get("n"):
        datos.append(f"Red (ida y vuelta): media {rtt.get('medio_ms', 0)} ms, máximo {rtt.get('max_ms', 0)} ms.")
    if rec:
        datos.append(f"Otro PC: le llegan {rec.get('llegadas_hz', 0)} tandas/s con huecos de hasta "
                     f"{rec.get('hueco_max_ms', 0)} ms; aplica con huecos de hasta {rec.get('aplicado_hueco_max_ms', 0)} ms"
                     + (" (suavizado encendido)." if rec.get("suavizar") else " (suavizado apagado)."))
    consejos_pc = [f"Plan de energía «Alto rendimiento» (o «Máximo rendimiento») y el portátil enchufado.",
                   "Cierra lo que esté usando mucho la CPU o el disco (juegos, antivirus escaneando, actualizaciones).",
                   "El receptor del ratón en otro puerto USB, mejor directo al PC y no en un hub; actualiza el driver."]
    if sistema != "Windows":
        consejos_pc = ["Cierra lo que esté usando mucho la CPU.", "Prueba el ratón en otro puerto USB."]
    reloj_mal = rel.get("retraso_max_ms", 0) > UMBRAL_RELOJ
    if r.get("modo") == "local":
        if reloj_mal:
            return {"nivel": "mal", "texto": f"El reloj de este {sistema} va a saltos (hasta {rel['retraso_max_ms']} ms de retraso): "
                    "por eso el ratón del móvil y el de otro PC pueden ir a tirones aquí, aunque la red vaya bien.",
                    "consejos": consejos_pc, "datos": datos}
        return {"nivel": "bien", "texto": f"El reloj de este {sistema} va fino. Para medir también el ratón y la red, "
                f"pulsa «Probar fluidez», pasa al otro PC con {tecla} y mueve el ratón en círculos 5 s.",
                "consejos": [], "datos": datos}
    if gan.get("n", 0) < 40:
        return {"nivel": "aviso", "texto": "No llegó movimiento suficiente: repite moviendo el ratón en círculos, "
                "sin parar, los 5 s.", "consejos": [], "datos": datos}
    hueco_pc = max(gan.get("hueco_max_ms", 0), 0)
    if reloj_mal or hueco_pc > UMBRAL_HUECO or r.get("tarde_max_ms", 0) > UMBRAL_TARDE:
        cuanto = max(hueco_pc, r.get("tarde_max_ms", 0), rel.get("retraso_max_ms", 0))
        return {"nivel": "mal", "texto": f"Tu {sistema} entrega el ratón a tirones: huecos de {cuanto:g} ms "
                "antes de que salga nada hacia el otro PC. No es la red.", "consejos": consejos_pc, "datos": datos}
    red_mal = (rtt.get("max_ms", 0) > UMBRAL_RTT or rtt.get("jitter_ms", 0) > UMBRAL_RTT_JITTER
               or (rec and rec.get("hueco_max_ms", 0) > UMBRAL_HUECO and env.get("hueco_max_ms", 0) <= UMBRAL_HUECO))
    if red_mal:
        consejos = ["Mejor por cable; si es Wi-Fi, la de 5 GHz y cerca del router.",
                    "Que nadie esté bajando o subiendo algo grande a la vez."]
        if rec and not rec.get("suavizar"):
            consejos.insert(0, "En el otro PC, enciende «Suavizar ratón entre PCs» (Configuración → Otro PC).")
        peor = max(rtt.get("max_ms", 0), rec.get("hueco_max_ms", 0) if rec else 0)
        return {"nivel": "mal", "texto": f"La red da tirones: hay esperas de hasta {peor:g} ms entre los dos PCs. "
                "Este PC entrega el ratón bien." + (" El suavizado lo disimula." if rec.get("suavizar") else ""),
                "consejos": consejos, "datos": datos}
    if rec and rec.get("aplicado_hueco_max_ms", 0) > UMBRAL_HUECO:
        return {"nivel": "mal", "texto": f"El otro PC aplica el ratón a tirones (huecos de {rec['aplicado_hueco_max_ms']:g} ms) "
                "aunque le llega bien: está ocupado.", "consejos": ["En el otro PC, cierra lo que use mucha CPU."], "datos": datos}
    texto = f"Todo fino: el ratón sale a {gan.get('hz', 0)} Hz con huecos de {hueco_pc:g} ms"
    if rtt.get("n"):
        texto += f" y la red va en {rtt.get('medio_ms', 0):g} ms"
    return {"nivel": "bien", "texto": texto + ".", "consejos": [], "datos": datos}


def rtt_resumen(rtts: list[float]) -> dict[str, Any]:
    if not rtts:
        return {"n": 0}
    ms = [x * 1000 for x in rtts]
    media = sum(ms) / len(ms)
    return {"n": len(ms), "medio_ms": round(media, 1), "max_ms": round(max(ms), 1),
            "jitter_ms": round(math.sqrt(sum((x - media) ** 2 for x in ms) / len(ms)), 1)}


class Medida:
    """Una prueba de fluidez en el emisor (la llenan el gancho, el hilo que manda y el que lee)."""

    def __init__(self, ident: int, reloj: Callable[[], float] = time.perf_counter) -> None:
        self.id = ident
        self.reloj = reloj
        self.gancho = Ritmo(reloj)
        self.envio = Ritmo(reloj)
        self.latidos: dict[int, float] = {}
        self.rtts: list[float] = []
        self.tarde_max = 0.0
        self.receptor: dict[str, Any] | None = None
        self.listo = threading.Event()

    def tarde(self, ms: float) -> None:
        if 0 <= ms < 5000 and ms > self.tarde_max:
            self.tarde_max = float(ms)

    def latido(self, n: int) -> None:
        if len(self.latidos) < 1000:
            self.latidos[n] = self.reloj()

    def respuesta(self, n: int) -> None:
        t = self.latidos.pop(n, None)
        if t is not None:
            self.rtts.append(self.reloj() - t)

    def del_receptor(self, ev: tuple) -> None:
        if ev[1] != self.id:
            return
        self.receptor = {"llegadas_hz": ev[2], "hueco_max_ms": ev[3] / 10, "jitter_ms": ev[4] / 10,
                         "aplicado_hueco_max_ms": ev[5] / 10, "suavizar": bool(ev[6])}
        self.listo.set()

    def resultado(self) -> dict[str, Any]:
        return {"modo": "completa", "gancho": self.gancho.resumen(), "envio": self.envio.resumen(),
                "tarde_max_ms": round(self.tarde_max, 1), "rtt": rtt_resumen(self.rtts), "receptor": self.receptor}
