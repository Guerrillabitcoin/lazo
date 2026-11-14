"""LaZoo 0.70-0.71: «Controlar otro PC». El ratón y el teclado de este PC manejan otro PC de la red
local, como Mouse Without Borders. Se cambia con una tecla rápida (Ctrl+Alt+L de serie), no por
el borde de la pantalla. Solo biblioteca estándar (ctypes en Windows y en X11).

Quién es quién
    - Emisor: el PC cuyo ratón y teclado se usan. En Windows pone dos ganchos de bajo nivel
      (WH_MOUSE_LL y WH_KEYBOARD_LL) en un hilo con su propio bucle de mensajes. Mientras
      controla, NINGUNA tecla ni clic llega a este PC (el gancho devuelve 1) y el puntero se queda
      quieto en el centro de la pantalla; todo va al otro PC.
    - Receptor: el PC controlado. Inyecta con lo mismo que ya usa LaZoo: SendInput en Windows,
      XTest en X11 y ydotool en Wayland (0.68). Solo si su dueño marcó «Permitir que otro PC me
      controle» (Panel → Configuración; apagado de serie).

Emparejar (lo mismo que un móvil, sin nada nuevo)
    El emisor hace el saludo de protocol.py con el PIN del receptor (`/api/pair/hello`, `claim`,
    `wait`), con el User-Agent `LaZoo-PC/VERSIÓN (sistema; nombre)`. En el receptor sale el aviso
    de siempre («PC · nombre quiere entrar») y la clave larga (la de ESE dispositivo) solo se
    entrega si se acepta. El emisor la guarda cifrada (DPAPI en Windows, sellada en Linux) en
    `otros-pcs.json`, en la carpeta de datos de LaZoo.

Canal (`GET /kvm`, WebSocket en el mismo puerto, solo red local)
    Firmado como el `/ws` del móvil: `?i=ID&t=MS&n=NONCE&s=FIRMA`, con la clave de ese
    dispositivo. Siempre firmado, también desde 127.0.0.1. Cada trama binaria va sellada (LZ2)
    con la clave de sello del dispositivo. Dentro:
        b"K1" + número_u32 (siempre sube: una trama repetida se rechaza) + eventos
    Eventos (little-endian), un byte de tipo y sus datos:
        1 MOVER  <hh  dx dy            (relativo; el emisor junta los movimientos cada ~6 ms)
        2 BOTON  <BB  botón 1-5, abajo (1 izq, 2 der, 3 central, 4 atrás, 5 adelante)
        3 RUEDA  <Bh  eje (0 vertical, 1 horizontal), delta (120 = una muesca; + arriba/derecha)
        4 TECLA  <HHB vk, scan, bits (1 = extendida, 2 = abajo)
        5 SOLTAR       suelta todas las teclas y botones pulsados
        6 LATIDO <I   el receptor contesta 7 RESPUESTA <I con el mismo número
    El emisor manda un latido cada 0,5 s. Si en 3 s no hay respuesta, suelta (vuelve a este
    PC). El receptor, si en 3 s no recibe nada, suelta todo lo pulsado y cierra.

Portapapeles (0.71)
    Al pasar al otro PC, el texto del portapapeles de este va al de aquel; al volver, el de aquel
    vuelve a este. Solo texto, hasta 1 MB, por el mismo canal sellado y solo si los DOS PCs tienen
    «Compartir portapapeles al cambiar de PC» (encendido de serie). No se guarda en disco.
        8 PIDE_PORTA <I   (en una trama K1) el emisor pide el portapapeles del receptor
        b"P1" + número_u32 + id_u32 + total_u32 + desde_u32 + trozo   un trozo del texto (UTF-8)
    Un P1 con total 0 = «no hay nada (o no se comparte)».

Linux (0.71, linux_kvm.py)
    Receptor: ratón y teclado virtuales en /dev/uinput; si no, XTest (Xorg) o ydotool con la
    sintaxis de su versión (Wayland). Emisor: evdev con EVIOCGRAB; si no, XGrabKeyboard (Xorg).

Teclas
    Ctrl+Alt+L (se cambia en el Panel) alterna. Ctrl+Alt+Esc suelta SIEMPRE (emergencia). Win y
    Alt+Tab se mandan. Ctrl+Alt+Supr y la pantalla de bloqueo o de UAC no se pueden capturar ni
    inyectar (Windows las reserva para el escritorio seguro).
"""

from __future__ import annotations

import base64
import json
import os
import platform
import re
import secrets
import socket
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import protocol

RUTA = "/kvm"
MAX_TRAMA = 40000      # 0.71: cabe un trozo del portapapeles
TROZO_PORTA = 32000
MAX_PORTA = 1_000_000  # bytes de texto (UTF-8) como mucho
ESPERA_PORTA = 1.5     # s que se espera el portapapeles del otro PC al volver
LOTE = 0.006           # s: los movimientos se juntan en tandas de ~6 ms
LATIDO = 0.5           # s entre latidos del emisor
SIN_RESPUESTA = 3.0    # s sin respuesta (emisor) o sin tramas (receptor): se suelta todo
ESPERA_APROBAR = 130   # s que el emisor espera a que el otro PC acepte
TECLA_DEFECTO = "Ctrl+Alt+L"
EMERGENCIA = "Ctrl+Alt+Esc"
UA_PREFIJO = "LaZoo-PC/"
ARCHIVO_PCS = "otros-pcs.json"
MAX_PCS = 20
VERSION = "0.73"

MOVER, BOTON, RUEDA, TECLA, SOLTAR, LATIDO_EV, RESPUESTA, PIDE_PORTA = 1, 2, 3, 4, 5, 6, 7, 8
PORTA = 9  # solo en tramas P1
_FORMATOS = {MOVER: struct.Struct("<hh"), BOTON: struct.Struct("<BB"), RUEDA: struct.Struct("<Bh"),
             TECLA: struct.Struct("<HHB"), SOLTAR: struct.Struct(""), LATIDO_EV: struct.Struct("<I"),
             RESPUESTA: struct.Struct("<I"), PIDE_PORTA: struct.Struct("<I")}
CABECERA = b"K1"
CABECERA_PORTA = b"P1"
_PORTA = struct.Struct("<IIII")
MAX_EVENTOS = 200


class ErrorPC(Exception):
    """Algo de «Controlar otro PC» que hay que decirle al usuario tal cual (en español)."""


# --- Mensajes -------------------------------------------------------------------------------


def _i16(v: int) -> int:
    return max(-32768, min(32767, int(v)))


def codificar(numero: int, eventos: list[tuple]) -> bytes:
    """Eventos a bytes (sin sellar). Un MOVER fuera de rango se parte en varios."""
    partes = [CABECERA, struct.pack("<I", numero & 0xFFFFFFFF)]
    for ev in eventos:
        tipo = ev[0]
        fmt = _FORMATOS.get(tipo)
        if fmt is None:
            raise protocol.ProtocolError("evento no válido")
        if tipo == MOVER:
            dx, dy = int(ev[1]), int(ev[2])
            while dx or dy:
                a, b = _i16(dx), _i16(dy)
                partes.append(bytes([MOVER]) + fmt.pack(a, b))
                dx, dy = dx - a, dy - b
            continue
        if tipo == RUEDA:
            partes.append(bytes([RUEDA]) + fmt.pack(int(ev[1]) & 1, _i16(ev[2])))
            continue
        partes.append(bytes([tipo]) + fmt.pack(*[int(x) for x in ev[1:]]))
    return b"".join(partes)


def codificar_porta(numero: int, ident: int, total: int, desde: int, trozo: bytes) -> bytes:
    """Un trozo del portapapeles (texto UTF-8)."""
    return CABECERA_PORTA + _PORTA.pack(numero & 0xFFFFFFFF, ident & 0xFFFFFFFF, total, desde) + bytes(trozo)


def trozos_porta(ident: int, texto: str | None) -> list[tuple[int, int, int, bytes]]:
    """(id, total, desde, trozo) para mandar un texto. Vacío, None o > MAX_PORTA: un único «nada»."""
    datos = (texto or "").encode("utf-8")
    if not datos or len(datos) > MAX_PORTA:
        return [(ident, 0, 0, b"")]
    return [(ident, len(datos), i, datos[i:i + TROZO_PORTA]) for i in range(0, len(datos), TROZO_PORTA)]


class Juntar:
    """Junta los trozos P1 de un texto (en orden: el canal es TCP). Devuelve el texto al completarse."""

    def __init__(self) -> None:
        self.ident = -1
        self.buf = bytearray()
        self.total = 0

    def trozo(self, ident: int, total: int, desde: int, datos: bytes) -> str | None:
        if total == 0:
            self.ident, self.buf, self.total = -1, bytearray(), 0
            return ""
        if desde == 0:
            self.ident, self.buf, self.total = ident, bytearray(), total
        if ident != self.ident or total != self.total or desde != len(self.buf):
            self.ident, self.buf, self.total = -1, bytearray(), 0
            return None
        self.buf += datos
        if len(self.buf) < self.total:
            return None
        texto = bytes(self.buf).decode("utf-8", "replace")
        self.ident, self.buf, self.total = -1, bytearray(), 0
        return texto


def decodificar(datos: bytes) -> tuple[int, list[tuple]]:
    if datos.startswith(CABECERA_PORTA):
        if len(datos) < 2 + _PORTA.size:
            raise protocol.ProtocolError("trozo de portapapeles no válido")
        numero, ident, total, desde = _PORTA.unpack_from(datos, 2)
        trozo = bytes(datos[2 + _PORTA.size:])
        if total > MAX_PORTA or len(trozo) > TROZO_PORTA or desde + len(trozo) > total or (total == 0 and trozo):
            raise protocol.ProtocolError("trozo de portapapeles no válido")
        return numero, [(PORTA, ident, total, desde, trozo)]
    if len(datos) < 6 or not datos.startswith(CABECERA):
        raise protocol.ProtocolError("trama de otro PC no válida")
    numero = struct.unpack_from("<I", datos, 2)[0]
    eventos: list[tuple] = []
    i = 6
    while i < len(datos):
        tipo = datos[i]
        fmt = _FORMATOS.get(tipo)
        if fmt is None or i + 1 + fmt.size > len(datos):
            raise protocol.ProtocolError("evento no válido")
        eventos.append((tipo, *fmt.unpack_from(datos, i + 1)))
        i += 1 + fmt.size
        if len(eventos) > MAX_EVENTOS:
            raise protocol.ProtocolError("demasiados eventos")
    for ev in eventos:
        if ev[0] == BOTON and not (1 <= ev[1] <= 5 and ev[2] in (0, 1)):
            raise protocol.ProtocolError("botón no válido")
        if ev[0] == RUEDA and ev[1] not in (0, 1):
            raise protocol.ProtocolError("rueda no válida")
        if ev[0] == TECLA and (ev[1] > 0xFF or ev[3] > 3):
            raise protocol.ProtocolError("tecla no válida")
    return numero, eventos


def trocear(eventos: list[tuple], tope: int = 150) -> list[list[tuple]]:
    return [eventos[i:i + tope] for i in range(0, len(eventos), tope)] or [[]]


def trama_cliente(opcode: int, payload: bytes) -> bytes:
    """Trama WebSocket del lado cliente (enmascarada, como manda el RFC 6455)."""
    n = len(payload)
    cabeza = bytes([0x80 | opcode])
    if n < 126:
        cabeza += bytes([0x80 | n])
    elif n < 65536:
        cabeza += bytes([0x80 | 126]) + n.to_bytes(2, "big")
    else:
        raise protocol.ProtocolError("trama larga")
    mascara = secrets.token_bytes(4)
    if n:
        flujo = (mascara * (n // 4 + 1))[:n]
        payload = (int.from_bytes(payload, "big") ^ int.from_bytes(flujo, "big")).to_bytes(n, "big")
    return cabeza + mascara + payload


def claves(kd: bytes) -> tuple[bytes, bytes]:
    """(firma, sello) del dispositivo a partir de su clave `kd` (lo mismo que hace el móvil)."""
    return protocol.derive(kd, "lazo/auth/1"), protocol.derive(kd, "lazo/seal/1")


# --- Tecla rápida ---------------------------------------------------------------------------

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8
_MODS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "ctl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT,
         "mayus": MOD_SHIFT, "mayús": MOD_SHIFT, "win": MOD_WIN}
_NOMBRES_MOD = ((MOD_CONTROL, "Ctrl"), (MOD_ALT, "Alt"), (MOD_SHIFT, "Shift"), (MOD_WIN, "Win"))


def leer_tecla(texto: str) -> tuple[int, int, str]:
    """"Ctrl+Alt+L" → (modificadores de RegisterHotKey, vk, texto limpio). Letras, números y F1-F12,
    con Ctrl, Alt o Win (al menos uno; Shift solo no vale)."""
    partes = [p.strip() for p in str(texto or "").replace("-", "+").split("+") if p.strip()]
    if len(partes) < 2 or len(partes) > 4:
        raise ErrorPC("Escribe la tecla como Ctrl+Alt+L")
    mods = 0
    for p in partes[:-1]:
        m = _MODS.get(p.lower())
        if m is None:
            raise ErrorPC(f"No conozco «{p}»: usa Ctrl, Alt, Shift o Win")
        mods |= m
    if not mods & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        raise ErrorPC("La tecla rápida necesita Ctrl, Alt o Win")
    tecla = partes[-1].upper()
    if re.fullmatch(r"[A-Z0-9]", tecla):
        vk = ord(tecla)
    elif re.fullmatch(r"F([1-9]|1[0-2])", tecla):
        vk = 0x70 + int(tecla[1:]) - 1
    else:
        raise ErrorPC("La última tecla tiene que ser una letra, un número o F1-F12")
    limpio = "+".join([n for m, n in _NOMBRES_MOD if mods & m] + [tecla])
    return mods, vk, limpio


# --- Ajustes (ajustes.json, la misma carpeta de datos que el resto) ----------------------------


def _carpeta() -> Path:
    import recordar

    return recordar.data_dir()


class Ajustes:
    """«Permitir que otro PC me controle» (apagado de serie), la tecla rápida y (0.71) «Compartir
    portapapeles al cambiar de PC» (encendido de serie; solo actúa con «Controlar otro PC»)."""

    def __init__(self) -> None:
        self.permitir = False
        self.tecla = TECLA_DEFECTO
        self.portapapeles = True
        self.nombre = ""  # 0.72: nombre de este PC para los móviles («Renombrar» en el Panel)
        self._lock = threading.Lock()

    def archivo(self) -> Path:
        return _carpeta() / "ajustes.json"

    def cargar(self) -> "Ajustes":
        try:
            data = json.loads(self.archivo().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        self.permitir = data.get("otro_pc_permitir") is True
        self.portapapeles = data.get("otro_pc_portapapeles") is not False
        try:
            import aprobacion

            self.nombre = aprobacion.limpiar_apodo(data.get("nombre_este_pc") or "")
        except (ValueError, TypeError):
            self.nombre = ""
        try:
            self.tecla = leer_tecla(str(data.get("otro_pc_tecla") or TECLA_DEFECTO))[2]
        except ErrorPC:
            self.tecla = TECLA_DEFECTO
        return self

    def _guardar(self, **cambios: Any) -> None:
        with self._lock:
            f = self.archivo()
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except (OSError, ValueError):
                data = {}
            data.update(cambios)
            try:
                f.parent.mkdir(parents=True, exist_ok=True)
                tmp = f.with_name(f"{f.name}.{os.getpid()}.{secrets.token_hex(3)}.tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, f)
            except OSError:
                pass

    def set_permitir(self, on: Any) -> bool:
        self.permitir = on is True
        self._guardar(otro_pc_permitir=self.permitir)
        return self.permitir

    def set_portapapeles(self, on: Any) -> bool:
        self.portapapeles = on is True
        self._guardar(otro_pc_portapapeles=self.portapapeles)
        return self.portapapeles

    def set_nombre(self, texto: Any) -> str:
        """0.72: nombre corto de este PC para la fila de PCs del móvil (vacío = el del sistema).
        Mismas reglas que «Renombrar»: 40 como mucho, sin HTML."""
        import aprobacion

        try:
            self.nombre = aprobacion.limpiar_apodo(texto)
        except ValueError as exc:
            raise ErrorPC(str(exc)) from exc
        self._guardar(nombre_este_pc=self.nombre)
        return self.nombre

    def set_tecla(self, texto: str) -> str:
        mods, vk, limpio = leer_tecla(texto)
        self.tecla = limpio
        self._guardar(otro_pc_tecla=limpio)
        return limpio


AJUSTES = Ajustes()


# --- Teclas para Linux: códigos de exploración de Windows → códigos del kernel (evdev) ----------

_EXT_EVDEV = {0x1C: 96, 0x1D: 97, 0x35: 98, 0x37: 99, 0x38: 100, 0x47: 102, 0x48: 103, 0x49: 104, 0x4B: 105,
              0x4D: 106, 0x4F: 107, 0x50: 108, 0x51: 109, 0x52: 110, 0x53: 111, 0x5B: 125, 0x5C: 126, 0x5D: 127,
              0x20: 113, 0x2E: 114, 0x30: 115, 0x22: 164, 0x24: 166, 0x10: 165, 0x19: 163, 0x6A: 158, 0x69: 159}
_VK_EVDEV = {0x13: 119, 0x90: 69, 0xAD: 113, 0xAE: 114, 0xAF: 115, 0xB0: 163, 0xB1: 165, 0xB2: 166, 0xB3: 164,
             0xA6: 158, 0xA7: 159, 0x2C: 99}
_OTRAS_EVDEV = {0x70: 93, 0x73: 89, 0x79: 92, 0x7B: 94, 0x7D: 124, 0x64: 183, 0x65: 184, 0x66: 185, 0x67: 186,
                0x68: 187, 0x69: 188, 0x6A: 189, 0x6B: 190, 0x6C: 191, 0x6D: 192, 0x6E: 193, 0x76: 194}


def evdev(vk: int, scan: int, ext: bool) -> int | None:
    """Código de tecla de Linux (input-event-codes.h) por la posición física. None = sin traducción."""
    if vk in _VK_EVDEV:
        return _VK_EVDEV[vk]
    if ext:
        return _EXT_EVDEV.get(scan)
    if 1 <= scan <= 88:
        return scan  # en el juego 1, del Esc (1) al F12 (88), coinciden
    return _OTRAS_EVDEV.get(scan)


def pasos_rueda(resto: list[int], eje: int, delta: int, x11: bool = False) -> list[int]:
    """Junta la rueda en muescas de 120. Devuelve, por muesca, el botón de X (4/5 vertical, 6/7
    horizontal) o, sin `x11`, +1/-1 (arriba/derecha = +1)."""
    resto[eje] += int(delta)
    n = int(resto[eje] / 120)
    resto[eje] -= n * 120
    if not n:
        return []
    if x11:
        par = (4, 5) if eje == 0 else (7, 6)  # (positivo, negativo): arriba/abajo, derecha/izquierda
        return [par[0] if n > 0 else par[1]] * abs(n)
    return [1 if n > 0 else -1] * abs(n)


# --- Inyectores (receptor) ------------------------------------------------------------------


class InyectorWindows:
    """SendInput (como el resto de LaZoo en Windows). Las teclas van por código de exploración,
    así salen con la distribución de teclado del PC controlado."""

    lento = False
    EXTRA = 0x4C5A3730  # «LZ70» en dwExtraInfo: se reconoce lo que inyecta LaZoo

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes as wt

        self.ct = ctypes

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                        ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]

        class _U(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("u",)
            _fields_ = [("type", wt.DWORD), ("u", _U)]

        self.INPUT = INPUT
        user32 = ctypes.WinDLL("user32", use_last_error=True)  # instancia propia: nadie más toca estas firmas
        self.send = user32.SendInput
        self.send.argtypes = [wt.UINT, ctypes.c_void_p, ctypes.c_int]
        self.send.restype = wt.UINT

    def _raton(self, flags: int, dx: int = 0, dy: int = 0, data: int = 0, extra: int | None = None) -> None:
        ev = self.INPUT()
        ev.type = 0
        ev.mi.dx, ev.mi.dy, ev.mi.mouseData, ev.mi.dwFlags = dx, dy, data & 0xFFFFFFFF, flags
        ev.mi.dwExtraInfo = self.EXTRA if extra is None else extra
        self.send(1, self.ct.byref(ev), self.ct.sizeof(ev))

    def mover(self, dx: int, dy: int) -> None:
        self._raton(0x0001, dx, dy)

    def boton(self, b: int, abajo: bool) -> None:
        if b in (4, 5):
            self._raton(0x0080 if abajo else 0x0100, data=b - 3)  # XBUTTON1 / XBUTTON2
            return
        base = {1: 0x0002, 2: 0x0008, 3: 0x0020}[b]
        self._raton(base if abajo else base << 1)

    def rueda(self, eje: int, delta: int) -> None:
        self._raton(0x1000 if eje else 0x0800, data=delta)

    def tecla(self, vk: int, scan: int, ext: bool, abajo: bool) -> None:
        ev = self.INPUT()
        ev.type = 1
        flags = (0x1 if ext else 0) | (0 if abajo else 0x2)
        if scan and vk != 0x13 and not 0xA6 <= vk <= 0xB7:  # Pausa y teclas multimedia, por vk
            ev.ki.wScan, ev.ki.wVk = scan, 0
            flags |= 0x8  # KEYEVENTF_SCANCODE
        else:
            ev.ki.wScan, ev.ki.wVk = scan, vk
        ev.ki.dwFlags, ev.ki.dwExtraInfo = flags, self.EXTRA
        self.send(1, self.ct.byref(ev), self.ct.sizeof(ev))


class InyectorX11:
    """XTest con ctypes y una conexión propia al servidor X (Xorg, o XWayland sin ydotool)."""

    lento = False

    def __init__(self) -> None:
        import ctypes

        x11 = ctypes.CDLL("libX11.so.6")
        xtst = ctypes.CDLL("libXtst.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XFlush.argtypes = [ctypes.c_void_p]
        xtst.XTestFakeRelativeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
        xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
        disp = x11.XOpenDisplay(None)
        if not disp:
            raise OSError("no hay pantalla X")
        self.x11, self.xtst, self.d = x11, xtst, disp
        self.resto = [0, 0]

    def _flush(self) -> None:
        self.x11.XFlush(self.d)

    def mover(self, dx: int, dy: int) -> None:
        self.xtst.XTestFakeRelativeMotionEvent(self.d, int(dx), int(dy), 0)
        self._flush()

    def boton(self, b: int, abajo: bool) -> None:
        self.xtst.XTestFakeButtonEvent(self.d, {1: 1, 2: 3, 3: 2, 4: 8, 5: 9}[b], 1 if abajo else 0, 0)
        self._flush()

    def rueda(self, eje: int, delta: int) -> None:
        for boton in pasos_rueda(self.resto, eje, delta, x11=True):
            self.xtst.XTestFakeButtonEvent(self.d, boton, 1, 0)
            self.xtst.XTestFakeButtonEvent(self.d, boton, 0, 0)
        self._flush()

    def tecla(self, vk: int, scan: int, ext: bool, abajo: bool) -> None:
        code = evdev(vk, scan, ext)
        if code is None:
            return
        self.xtst.XTestFakeKeyEvent(self.d, code + 8, 1 if abajo else 0, 0)  # en X, evdev + 8
        self._flush()


class InyectorYdotool:
    """Wayland (0.68-0.70), SOLO ydotool 1.x. Desde la 0.71 el receptor de Linux usa
    linux_kvm.py (uinput, o ydotool con la sintaxis de cada versión); esta clase se queda para
    quien la use directamente."""

    lento = True
    BOTONES = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4}

    def __init__(self, base: Any = None) -> None:
        if base is None:
            import ydo

            base = ydo._Base()
        self.b = base
        self.resto = [0, 0]

    def mover(self, dx: int, dy: int) -> None:
        self.b.ydo("mousemove", "-x", str(int(dx)), "-y", str(int(dy)))

    def boton(self, b: int, abajo: bool) -> None:
        self.b.ydo("click", f"0x{(0x40 if abajo else 0x80) | self.BOTONES[b]:02X}")

    def rueda(self, eje: int, delta: int) -> None:
        pasos = pasos_rueda(self.resto, eje, delta)
        if pasos:
            n = sum(pasos)
            self.b.ydo("mousemove", "-w", "-x", str(n if eje else 0), "-y", str(0 if eje else n))

    def tecla(self, vk: int, scan: int, ext: bool, abajo: bool) -> None:
        code = evdev(vk, scan, ext)
        if code is not None:
            self.b.ydo("key", f"{code}:{1 if abajo else 0}")


def inyector_para_este_pc() -> Any:
    """El inyector de este sistema, o ErrorPC con el motivo."""
    if sys.platform == "win32":
        return InyectorWindows()
    if sys.platform.startswith("linux"):
        import linux_kvm  # 0.71: uinput primero; ydotool según su versión; nunca XTest en Wayland

        return linux_kvm.inyector_linux()
    raise ErrorPC("El otro PC aún no puede ser controlado desde otro PC (sistema no soportado)")


# --- Portapapeles (0.71) ------------------------------------------------------------------------


def leer_portapapeles() -> str:
    """Texto del portapapeles de ESTE PC ("" si no hay o no es texto). Nada se guarda en disco."""
    try:
        import control

        texto = control._read_clipboard_text() or ""
    except Exception:  # noqa: BLE001
        return ""
    return texto if isinstance(texto, str) else ""


def poner_portapapeles(texto: str) -> bool:
    """Deja el texto en el portapapeles de este PC, marcado como de LaZoo para que el historial
    de notas no lo apunte (no va al historial del portapapeles)."""
    if not texto:
        return False
    if sys.platform != "win32":
        texto = texto.replace("\r\n", "\n")
    try:
        import control

        control._mark_injected(texto)
        return bool(control._write_clipboard_text(texto))
    except Exception:  # noqa: BLE001
        return False


# --- Receptor -------------------------------------------------------------------------------


class Receptor:
    """Aplica los eventos de UNA conexión y recuerda qué dejó pulsado para soltarlo al final."""

    def __init__(self, inyector: Any, marcar: Callable[[], None] | None = None,
                 porta_poner: Callable[[str], Any] | None = None) -> None:
        self.iny = inyector
        self.marcar = marcar or (lambda: None)
        self.porta_poner = porta_poner  # None = este PC no comparte el portapapeles
        self.juntar = Juntar()
        self.teclas: dict[tuple[int, int, int], tuple[int, int, bool]] = {}
        self.botones: set[int] = set()
        self.numero = -1
        self._mov = [0, 0]
        self._mcond = threading.Condition(threading.Lock())
        self._hilo: threading.Thread | None = None
        self._fin = False
        if getattr(inyector, "lento", False):
            self._hilo = threading.Thread(target=self._mover_lento, name="lazo-kvm-mover", daemon=True)
            self._hilo.start()

    def _mover_lento(self) -> None:
        while True:
            with self._mcond:
                while not self._fin and not (self._mov[0] or self._mov[1]):
                    self._mcond.wait(1.0)
                if self._fin:
                    return
                dx, dy = self._mov
                self._mov = [0, 0]
            try:
                self.iny.mover(dx, dy)
            except Exception:  # noqa: BLE001
                pass

    def _mover(self, dx: int, dy: int) -> None:
        self.marcar()
        if self._hilo is not None:
            with self._mcond:
                self._mov[0] += dx
                self._mov[1] += dy
                self._mcond.notify()
            return
        self.iny.mover(dx, dy)

    def _vaciar_mov(self) -> None:
        """Antes de un clic o una tecla, el movimiento pendiente (Wayland) se hace primero."""
        if self._hilo is None:
            return
        with self._mcond:
            dx, dy = self._mov
            self._mov = [0, 0]
        if dx or dy:
            self.iny.mover(dx, dy)

    def tratar(self, datos: bytes) -> list[tuple]:
        """Una trama ya abierta. Devuelve las respuestas (a los latidos)."""
        numero, eventos = decodificar(datos)
        if numero <= self.numero:
            raise protocol.ProtocolError("trama repetida")
        self.numero = numero
        respuestas: list[tuple] = []
        mx = my = 0
        for ev in eventos:
            tipo = ev[0]
            if tipo == MOVER:
                mx += ev[1]
                my += ev[2]
                continue
            if mx or my:
                self._mover(mx, my)
                mx = my = 0
            if tipo == LATIDO_EV:
                respuestas.append((RESPUESTA, ev[1]))
                continue
            if tipo == RESPUESTA:
                continue
            if tipo == PIDE_PORTA:
                respuestas.append((PIDE_PORTA, ev[1]))  # bucle_receptor contesta con el portapapeles
                continue
            if tipo == PORTA:
                texto = self.juntar.trozo(*ev[1:])
                if texto and self.porta_poner is not None:
                    self.porta_poner(texto)
                continue
            self._vaciar_mov()
            if tipo == SOLTAR:
                self.soltar_todo()
            elif tipo == BOTON:
                b, abajo = ev[1], bool(ev[2])
                if abajo:
                    self.botones.add(b)
                    self.iny.boton(b, True)
                elif b in self.botones:
                    self.botones.discard(b)
                    self.iny.boton(b, False)
            elif tipo == RUEDA:
                self.iny.rueda(ev[1], ev[2])
            elif tipo == TECLA:
                vk, scan, bits = ev[1], ev[2], ev[3]
                ext, abajo = bool(bits & 1), bool(bits & 2)
                clave = (vk, scan, int(ext))  # 0.71: con el scan (Linux manda vk 0 en muchas teclas)
                if abajo:
                    self.teclas[clave] = (vk, scan, ext)
                    self.iny.tecla(vk, scan, ext, True)
                elif clave in self.teclas:
                    del self.teclas[clave]
                    self.iny.tecla(vk, scan, ext, False)
        if mx or my:
            self._mover(mx, my)
        return respuestas

    def soltar_todo(self) -> int:
        """Suelta todo lo que esta conexión dejó pulsado. Devuelve cuántas cosas."""
        n = 0
        for vk, scan, ext in list(self.teclas.values())[::-1]:
            try:
                self.iny.tecla(vk, scan, ext, False)
            except Exception:  # noqa: BLE001
                pass
            n += 1
        self.teclas.clear()
        for b in sorted(self.botones):
            try:
                self.iny.boton(b, False)
            except Exception:  # noqa: BLE001
                pass
            n += 1
        self.botones.clear()
        return n

    def cerrar(self) -> None:
        self.soltar_todo()
        with self._mcond:
            self._fin = True
            self._mcond.notify()


def bucle_receptor(sock: socket.socket, receptor: Receptor, abrir: Callable[[bytes], bytes],
                   sellar: Callable[[bytes], bytes], vivo: Callable[[], bool], tocar: Callable[[], None] | None = None,
                   espera: float | None = None, porta_leer: Callable[[], str] | None = None) -> str:
    """Lee tramas del emisor hasta que cierra, calla `espera` s (SIN_RESPUESTA) o deja de estar
    permitido. SIEMPRE suelta lo pulsado al salir. Devuelve el motivo."""
    sock.settimeout(SIN_RESPUESTA if espera is None else espera)
    numero = 0
    motivo = "cerrado"
    try:
        while True:
            try:
                opcode, payload = protocol.ws_read(sock, MAX_TRAMA)
            except socket.timeout:
                motivo = "sin latido"
                break
            if opcode == 0x8:
                break
            if opcode == 0x9:
                protocol.ws_send(sock, 0xA, payload)
                continue
            if opcode != 0x2 or not payload.startswith(protocol.MAGIC):
                motivo = "trama sin sellar"
                break
            if not vivo():
                motivo = "no permitido"
                break
            respuestas = receptor.tratar(abrir(payload))
            if tocar is not None:
                tocar()
            pedidos = [r[1] for r in respuestas if r[0] == PIDE_PORTA]
            respuestas = [r for r in respuestas if r[0] != PIDE_PORTA]
            if respuestas:
                numero += 1
                protocol.ws_send(sock, 0x2, sellar(codificar(numero, respuestas)))
            for ident in pedidos:  # 0.71: el emisor vuelve a su PC y se lleva este portapapeles
                texto = porta_leer() if porta_leer is not None else ""
                for trozo in trozos_porta(ident, texto):
                    numero += 1
                    protocol.ws_send(sock, 0x2, sellar(codificar_porta(numero, *trozo)))
    except protocol.ProtocolError:
        motivo = "trama no válida"
    except (OSError, EOFError, ValueError):
        motivo = "conexión cortada"
    finally:
        receptor.cerrar()
    return motivo


class Recepcion:
    """El lado controlado: una sola conexión a la vez (la nueva sustituye a la vieja)."""

    def __init__(self, fabrica: Callable[[], Any] = inyector_para_este_pc,
                 porta_leer: Callable[[], str] = leer_portapapeles, porta_poner: Callable[[str], Any] = poner_portapapeles) -> None:
        self.fabrica = fabrica
        self.porta_leer, self.porta_poner = porta_leer, porta_poner
        self._iny: Any = None
        self.lock = threading.Lock()
        self.actual: dict | None = None
        self.escuchas: list[Callable[[str, str], None]] = []

    def inyector(self) -> Any:
        with self.lock:
            if self._iny is None:
                self._iny = self.fabrica()
            return self._iny

    def _avisar(self, evento: str, texto: str) -> None:
        for fn in list(self.escuchas):
            try:
                fn(evento, texto)
            except Exception:  # noqa: BLE001
                pass

    def nombre_actual(self) -> str:
        with self.lock:
            return self.actual["nombre"] if self.actual else ""

    def cortar(self, who: str | None = None) -> bool:
        """Corta la conexión actual (o la de `who`): se sueltan sus teclas al salir del bucle."""
        with self.lock:
            act = self.actual
        if act is None or (who and act["who"] != who):
            return False
        try:
            act["sock"].shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        return True

    def atender(self, sock: socket.socket, who: str, nombre: str, abrir: Callable[[bytes], bytes],
                sellar: Callable[[bytes], bytes], vivo: Callable[[], bool], tocar: Callable[[], None] | None = None,
                marcar: Callable[[], None] | None = None) -> str:
        comparte = AJUSTES.portapapeles
        receptor = Receptor(self.inyector(), marcar, porta_poner=self.porta_poner if comparte else None)
        yo = {"sock": sock, "who": who, "nombre": nombre}
        with self.lock:
            viejo, self.actual = self.actual, yo
        if viejo is not None:
            try:
                viejo["sock"].shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self._avisar("recibiendo", f"«{nombre}» está usando el ratón y el teclado de este PC.")
        motivo = "cerrado"
        try:
            motivo = bucle_receptor(sock, receptor, abrir, sellar, vivo, tocar,
                                    porta_leer=(lambda: self.porta_leer() if AJUSTES.portapapeles else ""))
        finally:
            receptor.cerrar()
            with self.lock:
                mio = self.actual is yo
                if mio:
                    self.actual = None
            if mio:
                self._avisar("fin", f"«{nombre}» dejó de controlar este PC.")
        return motivo


RECEPCION = Recepcion()


# --- Lista de PCs que este puede controlar --------------------------------------------------


def limpiar_nombre(texto: str) -> str:
    return re.sub(r"[^\w .-]", "", str(texto or ""))[:30].strip()


def nombre_de_este_pc() -> str:
    return limpiar_nombre(platform.node()) or "PC"


def user_agent() -> str:
    sistema = "Windows" if sys.platform == "win32" else "Linux" if sys.platform.startswith("linux") else "PC"
    return f"{UA_PREFIJO}{VERSION} ({sistema}; {nombre_de_este_pc()})"


def nombre_desde_ua(ua: str) -> str | None:
    """«PC · nombre» si quien llama es otro LaZoo de PC; None si no."""
    m = re.match(re.escape(UA_PREFIJO) + r"[\d.]+ \(([^;)]*);\s*([^)]*)\)", ua or "")
    if not m:
        return None
    return f"PC · {limpiar_nombre(m.group(2)) or 'sin nombre'}"


class PCs:
    """`otros-pcs.json`: los PCs que este puede controlar, con su clave cifrada en este PC."""

    def __init__(self, carpeta: Path | None = None) -> None:
        self._carpeta = carpeta
        self.lock = threading.Lock()

    def archivo(self) -> Path:
        return (self._carpeta or _carpeta()) / ARCHIVO_PCS

    def _store(self) -> Any:
        import recordar

        return recordar.Store(self.archivo().parent)

    def _leer(self) -> dict:
        try:
            data = json.loads(self.archivo().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        filas = [r for r in data.get("pcs") or [] if isinstance(r, dict) and re.fullmatch(r"[0-9a-f]{8,40}", str(r.get("id", "")))]
        return {"ultimo": str(data.get("ultimo") or ""), "pcs": filas[:MAX_PCS]}

    def _escribir(self, data: dict) -> None:
        import recordar

        recordar._write_private(self.archivo(), json.dumps(data, ensure_ascii=False, indent=1).encode())

    def listar(self) -> list[dict]:
        with self.lock:
            data = self._leer()
        return [{"id": r["id"], "nombre": str(r.get("apodo") or r.get("nombre", ""))[:40], "apodo": str(r.get("apodo", ""))[:40],
                 "nombre_pc": str(r.get("nombre", ""))[:40], "host": str(r.get("host", "")),
                 "puerto": int(r.get("puerto") or 8787), "fp": str(r.get("fp", "")), "fecha": str(r.get("fecha", "")),
                 "ultimo": r["id"] == data["ultimo"]} for r in data["pcs"]]

    def renombrar(self, pid: str, texto: Any) -> dict:
        """0.71: un nombre propio para ese PC (vacío = el suyo). Solo en este PC."""
        import aprobacion

        try:
            apodo = aprobacion.limpiar_apodo(texto)
        except ValueError as exc:
            raise ErrorPC(str(exc)) from exc
        with self.lock:
            data = self._leer()
            fila = next((r for r in data["pcs"] if r["id"] == pid), None)
            if fila is None:
                raise ErrorPC("Ese PC ya no está en la lista")
            if apodo:
                fila["apodo"] = apodo
            else:
                fila.pop("apodo", None)
            self._escribir(data)
        return next(r for r in self.listar() if r["id"] == pid)

    def buscar(self, pid: str | None) -> dict | None:
        filas = self.listar()
        if not pid:
            pid = next((r["id"] for r in filas if r["ultimo"]), filas[0]["id"] if filas else "")
        return next((r for r in filas if r["id"] == pid), None)

    def clave(self, pid: str) -> bytes:
        with self.lock:
            fila = next((r for r in self._leer()["pcs"] if r["id"] == pid), None)
        if not fila:
            raise ErrorPC("Ese PC ya no está en la lista")
        try:
            kd = self._store()._unprotect(base64.b64decode(str(fila.get("clave", ""))))
        except Exception as exc:  # noqa: BLE001
            raise ErrorPC("No pude abrir la clave guardada de ese PC: vuelve a añadirlo") from exc
        if len(kd) != 32:
            raise ErrorPC("La clave guardada de ese PC no vale: vuelve a añadirlo")
        return kd

    def guardar(self, fila: dict, kd: bytes) -> dict:
        blob = base64.b64encode(self._store()._protect(kd)).decode()
        nueva = {"id": fila["id"], "nombre": str(fila.get("nombre", ""))[:40], "host": str(fila["host"])[:100],
                 "puerto": int(fila["puerto"]), "fp": str(fila.get("fp", ""))[:40], "fecha": time.strftime("%Y-%m-%d %H:%M"),
                 "clave": blob}
        with self.lock:
            data = self._leer()
            mismo = [r for r in data["pcs"] if r.get("host") == nueva["host"] and int(r.get("puerto") or 0) == nueva["puerto"]]
            if mismo and mismo[-1].get("apodo"):
                nueva["apodo"] = str(mismo[-1]["apodo"])[:40]  # 0.71: al volver a añadirlo, conserva su nombre propio
            data["pcs"] = [r for r in data["pcs"] if r not in mismo]
            data["pcs"] = (data["pcs"] + [nueva])[-MAX_PCS:]
            data["ultimo"] = nueva["id"]
            self._escribir(data)
        return nueva

    def olvidar(self, pid: str) -> bool:
        with self.lock:
            data = self._leer()
            antes = len(data["pcs"])
            data["pcs"] = [r for r in data["pcs"] if r["id"] != pid]
            if data["ultimo"] == pid:
                data["ultimo"] = ""
            if len(data["pcs"]) == antes:
                return False
            self._escribir(data)
        return True

    def set_ultimo(self, pid: str) -> None:
        with self.lock:
            data = self._leer()
            if any(r["id"] == pid for r in data["pcs"]) and data["ultimo"] != pid:
                data["ultimo"] = pid
                self._escribir(data)


PCS = PCs()


# --- Red: solo LAN --------------------------------------------------------------------------


def partir_destino(texto: str) -> tuple[str, int]:
    """«192.168.1.20:8787», «192.168.1.20» (puerto 8787), «mipc.local:8787» o «[fe80::1]:8787»."""
    t = re.sub(r"^https?://", "", str(texto or "").strip()).split("/", 1)[0].split("#", 1)[0]
    m = re.fullmatch(r"\[([0-9A-Fa-f:.%a-z]+)\](?::(\d{1,5}))?", t) or re.fullmatch(r"([A-Za-z0-9.-]{1,100})(?::(\d{1,5}))?", t)
    if not m:
        raise ErrorPC("Escribe la IP del otro PC, por ejemplo 192.168.1.20:8787")
    puerto = int(m.group(2) or 8787)
    if not 1 <= puerto <= 65535:
        raise ErrorPC("Puerto no válido")
    return m.group(1), puerto


def ip_de_lan(host: str, puerto: int) -> str:
    """Resuelve y comprueba que es de la red local (lo mismo que acepta el servidor)."""
    import aprobacion

    try:
        infos = socket.getaddrinfo(host, puerto, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ErrorPC(f"No encuentro «{host}» en la red") from exc
    for info in infos:
        ip = str(info[4][0])
        if aprobacion.allowed(ip):
            return ip
    raise ErrorPC("Solo se puede controlar un PC de tu red local")


def _post(ip: str, puerto: int, ruta: str, cuerpo: dict, timeout: float = 6.0) -> tuple[int, dict]:
    import http.client

    con = http.client.HTTPConnection(ip, puerto, timeout=timeout)
    try:
        con.request("POST", ruta, body=json.dumps(cuerpo).encode(),
                    headers={"Content-Type": "application/json", "User-Agent": user_agent()})
        res = con.getresponse()
        raw = res.read(65536)
        try:
            data = json.loads(raw.decode() or "{}")
        except ValueError:
            data = {}
        return res.status, data if isinstance(data, dict) else {}
    except OSError as exc:
        raise ErrorPC(f"No llego al otro PC ({ip}:{puerto}): ¿está LaZoo abierto allí?") from exc
    finally:
        con.close()


class Emparejar:
    """Añadir un PC con su PIN (el saludo X25519 de protocol.py, como un móvil por PIN)."""

    def __init__(self, pcs: PCs, post: Callable[..., tuple[int, dict]] = _post, al_terminar: Callable[[], None] | None = None) -> None:
        self.pcs = pcs
        self.post = post
        self.al_terminar = al_terminar
        self.lock = threading.Lock()
        self.estado: dict = {"estado": "nada"}
        self._vez = 0

    def ver(self) -> dict:
        with self.lock:
            return dict(self.estado)

    def _poner(self, vez: int, **estado: Any) -> None:
        with self.lock:
            if vez == self._vez:
                self.estado = estado

    def empezar(self, destino: str, pin: str, esperar: bool = True) -> dict:
        """Saludo y prueba (rápido). Luego un hilo pregunta hasta que el otro PC decide."""
        host, puerto = partir_destino(destino)
        pin = re.sub(r"\D", "", str(pin or ""))
        if len(pin) != protocol.PIN_LEN:
            raise ErrorPC("El PIN tiene 6 números: míralo en el Panel del otro PC (Configuración → Otro PC)")
        ip = ip_de_lan(host, puerto)
        who = secrets.token_hex(16)
        priv, pub = protocol.x25519_keypair()
        code, r = self.post(ip, puerto, "/api/pair/hello", {"id": who, "mode": "pin", "pub": protocol.b64u(pub)})
        if code != 200:
            raise ErrorPC(r.get("error") or f"El otro PC no aceptó el saludo ({code})")
        try:
            suyo = protocol.unb64u(str(r.get("pub", "")))
            comun = protocol.x25519(priv, suyo)
        except protocol.ProtocolError as exc:
            raise ErrorPC("El otro PC contestó algo raro al saludo") from exc
        if comun == bytes(32):
            raise ErrorPC("El otro PC contestó algo raro al saludo")
        hk = protocol.handshake_key(protocol.pair_secret("pin", b"", pin), "pin", who, pub, suyo, comun)
        sid = str(r.get("sid", ""))
        prueba = protocol.proof(hk, "movil")
        code, r = self.post(ip, puerto, "/api/pair/claim", {"sid": sid, "proof": prueba})
        if code != 200:
            raise ErrorPC(r.get("error") or f"El otro PC dijo que no ({code})")
        if not secrets.compare_digest(str(r.get("proof", "")).lower(), protocol.proof(hk, "pc")):
            raise ErrorPC("La respuesta no es del PC con ese PIN: no sigo")
        fp = protocol.fingerprint(who, pub)
        with self.lock:
            self._vez += 1
            vez = self._vez
            self.estado = {"estado": "esperando", "fp": fp, "destino": f"{host}:{puerto}",
                           "mensaje": f"Acepta «{nombre_desde_ua(user_agent())}» en el otro PC (huella {fp})."}
        fila = {"id": who, "host": host, "puerto": puerto, "fp": fp, "nombre": ""}
        args = (vez, ip, puerto, sid, prueba, hk, fila)
        if esperar:
            threading.Thread(target=self.esperar, args=args, name="lazo-kvm-par", daemon=True).start()
            return self.ver()
        return {**self.ver(), "args": args}

    def esperar(self, vez: int, ip: str, puerto: int, sid: str, prueba: str, hk: bytes, fila: dict,
                dormir: Callable[[float], None] = time.sleep, plazo: float = ESPERA_APROBAR) -> dict:
        fin = time.monotonic() + plazo
        try:
            while time.monotonic() < fin:
                code, r = self.post(ip, puerto, "/api/pair/wait", {"sid": sid, "proof": prueba})
                estado = r.get("state")
                if code == 200 and estado == "aprobado" and r.get("box"):
                    caja = protocol.unb64u(str(r["box"]))
                    texto = protocol.open_sealed(caja, protocol.derive(hk, "lazo/pair/box/1")).decode()
                    kd = protocol.unb64u(texto)
                    if len(kd) != 32:
                        raise ErrorPC("La clave que llegó no vale")
                    fila["nombre"] = limpiar_nombre(r.get("nombre") or "") or f"PC {fila['host']}"
                    self.pcs.guardar(fila, kd)
                    self._poner(vez, estado="hecho", mensaje=f"Añadido «{fila['nombre']}». Pulsa {AJUSTES.tecla} para controlarlo.")
                    if self.al_terminar:
                        self.al_terminar()
                    return self.ver()
                if code != 200 or estado == "rechazado":
                    raise ErrorPC(r.get("error") or "El otro PC lo rechazó")
                dormir(1.0)
            raise ErrorPC("Nadie lo aceptó a tiempo en el otro PC")
        except (ErrorPC, protocol.ProtocolError, ValueError) as exc:
            self._poner(vez, estado="error", mensaje=str(exc))
        return self.ver()


# --- Emisor: conexión ------------------------------------------------------------------------


def mensaje_error(codigo: int, data: dict) -> str:
    if data.get("apagado"):
        return "El otro PC no deja que lo controlen: en su Panel → Configuración, marca «Permitir que otro PC me controle»."
    if data.get("pending"):
        return "El otro PC aún no ha aceptado a este: acéptalo allí."
    if data.get("rejected"):
        return "El otro PC rechazó a este. Vuelve a añadirlo y acéptalo allí."
    if data.get("kicked") or data.get("stale"):
        return "El otro PC ya no reconoce a este (lo expulsaron o se reinició sin «Recordar dispositivos»): vuelve a añadirlo."
    if data.get("clock"):
        return "El reloj de los dos PC no coincide: ponlos en hora."
    return str(data.get("error") or f"El otro PC no dejó conectar ({codigo})")


def conectar(host: str, puerto: int, who: str, kd: bytes, timeout: float = 3.0) -> socket.socket:
    """Abre `/kvm` firmado. Devuelve el socket listo, o ErrorPC con lo que dijo el otro PC."""
    ip = ip_de_lan(host, puerto)
    firma_k, _sello = claves(kd)
    stamp = int(time.time() * 1000)
    nonce = secrets.token_hex(16)
    firma = protocol.sign_request(firma_k, "GET", RUTA, stamp, nonce, 0)
    clave_ws = base64.b64encode(secrets.token_bytes(16)).decode()
    try:
        sock = socket.create_connection((ip, puerto), timeout=timeout)
    except OSError as exc:
        raise ErrorPC(f"No llego al otro PC ({host}:{puerto}): ¿está encendido y con LaZoo abierto?") from exc
    try:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        sock.sendall((f"GET {RUTA}?i={who}&t={stamp}&n={nonce}&s={firma} HTTP/1.1\r\nHost: {host}:{puerto}\r\n"
                      f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {clave_ws}\r\n"
                      f"Sec-WebSocket-Version: 13\r\nUser-Agent: {user_agent()}\r\n\r\n").encode())
        cabeza = b""
        while b"\r\n\r\n" not in cabeza:
            trozo = sock.recv(4096)
            if not trozo:
                raise ErrorPC("El otro PC cortó la conexión")
            cabeza += trozo
            if len(cabeza) > 65536:
                raise ErrorPC("Respuesta rara del otro PC")
        linea, _, resto = cabeza.partition(b"\r\n")
        partes = linea.split()
        codigo = int(partes[1]) if len(partes) > 1 and partes[1].isdigit() else 0
        cabeceras, _, cuerpo = resto.partition(b"\r\n\r\n")
        heads = {}
        for fila in cabeceras.split(b"\r\n"):
            k, _, v = fila.decode("latin-1").partition(":")
            heads[k.strip().lower()] = v.strip()
        if codigo == 101:
            if heads.get("sec-websocket-accept") != protocol.ws_accept(clave_ws) or cuerpo:
                raise ErrorPC("Respuesta rara del otro PC")
            sock.settimeout(None)
            return sock
        largo = min(int(heads.get("content-length") or 0), 65536)
        while len(cuerpo) < largo:
            trozo = sock.recv(4096)
            if not trozo:
                break
            cuerpo += trozo
        try:
            data = json.loads(cuerpo.decode() or "{}")
        except ValueError:
            data = {}
        raise ErrorPC(mensaje_error(codigo, data if isinstance(data, dict) else {}))
    except BaseException:
        sock.close()
        raise


# --- Emisor: el control ----------------------------------------------------------------------


class Control:
    """Estado del emisor. `mover`, `boton`, `rueda` y `tecla` los llama el gancho: solo apuntan en
    memoria. Un hilo manda las tandas (~6 ms) y los latidos; otro lee las respuestas."""

    def __init__(self, pcs: PCs = PCS, fabrica: Callable[["Control"], Any] | None = None,
                 conectar_fn: Callable[..., socket.socket] = conectar, reloj: Callable[[], float] = time.monotonic) -> None:
        self.pcs = pcs
        self.fabrica = fabrica
        self.conectar_fn = conectar_fn
        self.reloj = reloj
        self.lock = threading.RLock()
        self.estado = "libre"
        self.destino: dict | None = None
        self.mensaje = ""
        self.escuchas: list[Callable[[str, str], None]] = []
        self.captura: Any = None
        self._sock: socket.socket | None = None
        self._sello = b""
        self._sesion: object | None = None
        self._buf = threading.Lock()
        self._dx = self._dy = 0
        self._cola: list[tuple] = []
        self._despertar = threading.Event()
        self.ultimo_pong = 0.0
        self.enviadas = 0
        self._obrero: threading.Thread | None = None
        self._ordenes: list[Callable[[], Any]] = []
        self._ordenes_ev = threading.Event()
        # 0.71: portapapeles. Lo que sale (trozos P1) y lo que se espera al volver.
        self.porta_leer: Callable[[], str] = leer_portapapeles
        self.porta_poner: Callable[[str], Any] = poner_portapapeles
        self._porta_salida: list[tuple] = []
        self._porta_id = 0
        self._porta_espera: tuple[int, threading.Event, list] | None = None
        self._juntar = Juntar()

    # Lo llama el gancho (nada pesado) ------------------------------------------------------
    def vivo(self) -> bool:
        return self._sesion is not None and self.reloj() - self.ultimo_pong < SIN_RESPUESTA + 1.5

    def mover(self, dx: int, dy: int) -> None:
        with self._buf:
            self._dx += dx
            self._dy += dy
        self._despertar.set()

    def _evento(self, ev: tuple) -> None:
        with self._buf:
            if self._dx or self._dy:
                self._cola.append((MOVER, self._dx, self._dy))
                self._dx = self._dy = 0
            self._cola.append(ev)
        self._despertar.set()

    def boton(self, b: int, abajo: bool) -> None:
        self._evento((BOTON, b, 1 if abajo else 0))

    def rueda(self, eje: int, delta: int) -> None:
        self._evento((RUEDA, eje, delta))

    def tecla(self, vk: int, scan: int, ext: bool, abajo: bool) -> None:
        self._evento((TECLA, vk & 0xFF, scan & 0xFFFF, (1 if ext else 0) | (2 if abajo else 0)))

    def pedir(self, orden: str) -> None:
        """Desde el gancho, la tecla rápida o la bandeja: se hace en el hilo obrero, nunca en el gancho."""
        fn = {"alternar": self.alternar, "emergencia": lambda: self.parar("Tecla de emergencia: has vuelto a este PC."),
              "volver": lambda: self.parar("Has vuelto a este PC.", traer=True),
              "parar": lambda: self.parar("El otro PC no responde: has vuelto a este PC.")}.get(orden)
        if fn is None:
            return
        with self._buf:
            self._ordenes.append(fn)
            if self._obrero is None or not self._obrero.is_alive():
                self._obrero = threading.Thread(target=self._trabajar, name="lazo-kvm-obrero", daemon=True)
                self._obrero.start()
        self._ordenes_ev.set()

    def _trabajar(self) -> None:
        while True:
            self._ordenes_ev.wait(30)
            self._ordenes_ev.clear()
            with self._buf:
                ordenes, self._ordenes = self._ordenes, []
                if not ordenes:
                    self._obrero = None
                    return
            for fn in ordenes:
                try:
                    fn()
                except ErrorPC as exc:
                    self._avisar("error", str(exc))
                except Exception:  # noqa: BLE001
                    pass

    # Avisos ----------------------------------------------------------------------------------
    def _avisar(self, evento: str, texto: str) -> None:
        self.mensaje = texto
        for fn in list(self.escuchas):
            try:
                fn(evento, texto)
            except Exception:  # noqa: BLE001
                pass

    def nombre_controlado(self) -> str:
        d = self.destino
        return str(d.get("nombre") or d.get("host")) if (d and self.estado == "controlando") else ""

    def ver(self) -> dict:
        return {"estado": self.estado, "nombre": self.nombre_controlado(),
                "id": (self.destino or {}).get("id", "") if self.estado != "libre" else "", "mensaje": self.mensaje}

    # Captura -----------------------------------------------------------------------------------
    def _captura(self) -> Any:
        if self.captura is None:
            self.captura = (self.fabrica or captura_para_este_pc)(self)
        return self.captura

    def puede_mandar(self) -> tuple[bool, str]:
        if self.fabrica is not None or sys.platform == "win32":
            return True, ""
        if sys.platform.startswith("linux"):  # 0.71: evdev (X11 y Wayland) o, si no, X11
            import linux_kvm

            return linux_kvm.puede_capturar()
        return False, "Este sistema aún no puede controlar otro PC."

    def armar(self) -> bool:
        """Registra la tecla rápida solo si hay algún PC en la lista (si no, no se queda con ella)."""
        if not self.puede_mandar()[0]:
            return False
        try:
            hay = bool(self.pcs.listar())
            if not hay and self.captura is None:
                return False  # sin PCs no se arranca nada
            cap = self._captura()
            if cap is None or not hasattr(cap, "registrar"):
                return False
            if not hay:
                return bool(cap.registrar(0, 0))
            mods, vk, _ = leer_tecla(AJUSTES.tecla)
            return bool(cap.registrar(mods, vk))
        except Exception:  # noqa: BLE001
            return False

    # Empezar y parar -------------------------------------------------------------------------
    def alternar(self) -> dict:
        if self.estado != "libre":
            self.parar("Has vuelto a este PC.", traer=True)
            return self.ver()
        return self.iniciar(None)

    def iniciar(self, pid: str | None) -> dict:
        ok, motivo = self.puede_mandar()
        if not ok:
            raise ErrorPC(motivo)
        with self.lock:
            if self.estado != "libre":
                if self.destino and self.destino.get("id") == pid:
                    return self.ver()
                self.parar("")
            fila = self.pcs.buscar(pid)
            if fila is None:
                raise ErrorPC("No hay ningún PC añadido: usa «Añadir otro PC…»")
            kd = self.pcs.clave(fila["id"])
            cap = self._captura()
            if cap is None:
                raise ErrorPC("No puedo capturar el ratón y el teclado en este sistema")
            self.estado, self.destino = "conectando", fila
        try:
            sock = self.conectar_fn(fila["host"], fila["puerto"], fila["id"], kd)
        except BaseException:
            with self.lock:
                if self.destino is fila:
                    self.estado, self.destino = "libre", None
            raise
        sello = claves(kd)[1]
        with self.lock:
            if self.estado != "conectando" or self.destino is not fila:
                sock.close()
                return self.ver()
            sesion = object()
            self._sock, self._sello, self._sesion = sock, sello, sesion
            with self._buf:
                self._dx = self._dy = 0
                self._cola = []
                self._porta_salida = []
            self._juntar = Juntar()
            self.ultimo_pong = self.reloj()
            threading.Thread(target=self._leer, args=(sesion, sock, sello), name="lazo-kvm-leer", daemon=True).start()
            threading.Thread(target=self._enviar, args=(sesion, sock, sello), name="lazo-kvm-enviar", daemon=True).start()
            if not cap.empezar(self):
                self.parar("")
                raise ErrorPC("No pude capturar el ratón y el teclado de este PC")
            self.estado = "controlando"
            self.pcs.set_ultimo(fila["id"])
        if AJUSTES.portapapeles:  # 0.71: lo copiado aquí se pega allí
            texto = self.porta_leer()
            if texto and len(texto.encode("utf-8")) <= MAX_PORTA:
                with self._buf:
                    self._porta_id += 1
                    self._porta_salida = trozos_porta(self._porta_id, texto)
                self._despertar.set()
        nombre = fila.get("nombre") or fila["host"]
        self._avisar("controlando", f"Controlando «{nombre}». {AJUSTES.tecla} vuelve a este PC; {EMERGENCIA} suelta siempre.")
        return self.ver()

    def parar(self, motivo: str = "Has vuelto a este PC.", traer: bool = False) -> bool:
        """Vuelve a este PC. Con `traer` (la tecla rápida), antes de cerrar se trae el portapapeles
        del otro PC (como mucho ESPERA_PORTA s); el teclado y el ratón ya han vuelto antes."""
        espera = None
        with self.lock:
            if self.estado == "libre":
                return False
            if self.captura is not None:
                try:
                    self.captura.parar()  # lo primero: el teclado y el ratón vuelven a este PC
                except Exception:  # noqa: BLE001
                    pass
            if traer and AJUSTES.portapapeles and self.estado == "controlando" and self._sesion is not None:
                self.estado = "volviendo"
                with self._buf:
                    self._porta_id += 1
                    espera = (self._porta_id, threading.Event(), [None])
                    self._porta_espera = espera
                self._evento((PIDE_PORTA, espera[0]))
        if espera is not None:
            if espera[1].wait(ESPERA_PORTA) and espera[2][0]:
                self.porta_poner(espera[2][0])
            with self._buf:
                self._porta_espera = None
        with self.lock:
            if self.estado == "libre":
                return False
            sock, sello = self._sock, self._sello
            self._sock, self._sesion = None, None
            self.estado, self.destino = "libre", None
            self._despertar.set()
        if sock is not None:
            try:  # el otro PC suelta lo pulsado (también lo hace solo al cerrarse la conexión)
                sock.sendall(trama_cliente(0x2, protocol.seal(codificar(0xFFFFFFFF, [(SOLTAR,)]), sello)))
                sock.sendall(trama_cliente(0x8, b""))
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if motivo:
            self._avisar("libre", motivo)
        return True

    # Hilos de la conexión ---------------------------------------------------------------------
    def _enviar(self, sesion: object, sock: socket.socket, sello: bytes) -> None:
        numero = 0
        ultimo_envio = 0.0
        ultimo_latido = -LATIDO
        latido_n = 0
        try:
            while self._sesion is sesion:
                self._despertar.wait(LATIDO / 2)
                if self._sesion is not sesion:
                    return
                falta = ultimo_envio + LOTE - self.reloj()
                if falta > 0:
                    time.sleep(falta)  # junta lo que llegue en estos ms
                self._despertar.clear()
                with self._buf:
                    eventos, self._cola = self._cola, []
                    if self._dx or self._dy:
                        eventos.append((MOVER, self._dx, self._dy))
                        self._dx = self._dy = 0
                    porta, self._porta_salida = self._porta_salida[:4], self._porta_salida[4:]
                if self._porta_salida:
                    self._despertar.set()  # quedan trozos: en la siguiente vuelta, sin esperar
                for trozo in porta:
                    numero += 1
                    sock.sendall(trama_cliente(0x2, protocol.seal(codificar_porta(numero, *trozo), sello)))
                ahora = self.reloj()
                if ahora - self.ultimo_pong > SIN_RESPUESTA:
                    self.parar("El otro PC no responde: has vuelto a este PC.")
                    return
                if ahora - ultimo_latido >= LATIDO:
                    latido_n += 1
                    eventos.append((LATIDO_EV, latido_n))
                    ultimo_latido = ahora
                if not eventos:
                    continue
                for tanda in trocear(eventos):
                    numero += 1
                    sock.sendall(trama_cliente(0x2, protocol.seal(codificar(numero, tanda), sello)))
                    self.enviadas += 1
                ultimo_envio = self.reloj()
        except (OSError, protocol.ProtocolError):
            if self._sesion is sesion:
                self.parar("Se cortó la conexión con el otro PC: has vuelto a este PC.")

    def _leer(self, sesion: object, sock: socket.socket, sello: bytes) -> None:
        ultimo = 0
        juntar = self._juntar
        try:
            while self._sesion is sesion:
                opcode, payload = protocol.ws_read(sock, MAX_TRAMA)
                if opcode == 0x8:
                    break
                if opcode != 0x2:
                    continue
                numero, eventos = decodificar(protocol.open_sealed(payload, sello))
                if numero <= ultimo:
                    continue
                ultimo = numero
                if any(ev[0] == RESPUESTA for ev in eventos):
                    self.ultimo_pong = self.reloj()
                for ev in eventos:
                    if ev[0] == PORTA:
                        self.ultimo_pong = self.reloj()
                        texto = juntar.trozo(*ev[1:])
                        espera = self._porta_espera
                        if texto is not None and espera is not None and espera[0] == ev[1]:
                            espera[2][0] = texto
                            espera[1].set()
        except (OSError, EOFError, ValueError):
            pass
        if self._sesion is sesion:
            self.parar("Se cortó la conexión con el otro PC: has vuelto a este PC.")


# --- Captura en Windows ----------------------------------------------------------------------

WM_HOTKEY, WM_APP = 0x0312, 0x8000
_EMPEZAR, _PARAR, _REGISTRAR = WM_APP + 71, WM_APP + 72, WM_APP + 73
_VK_CTRL, _VK_ALT, _VK_SHIFT, _VK_WIN = (0xA2, 0xA3, 0x11), (0xA4, 0xA5, 0x12), (0xA0, 0xA1, 0x10), (0x5B, 0x5C)
_BOTONES_MSG = {0x201: (1, True), 0x202: (1, False), 0x204: (2, True), 0x205: (2, False), 0x207: (3, True), 0x208: (3, False)}


def mods_de(abajo: set[int]) -> int:
    m = 0
    if abajo & set(_VK_CTRL):
        m |= MOD_CONTROL
    if abajo & set(_VK_ALT):
        m |= MOD_ALT
    if abajo & set(_VK_SHIFT):
        m |= MOD_SHIFT
    if abajo & set(_VK_WIN):
        m |= MOD_WIN
    return m


class Filtro:
    """Lo que decide el gancho, sin Windows de por medio (se prueba en Linux).

    `tecla(...)` y `boton(...)` devuelven True si el evento se queda fuera de este PC (va al otro)
    y False si sigue aquí. Un «soltar» de algo pulsado ANTES de empezar a controlar (p. ej. el
    Ctrl+Alt de la propia tecla rápida) se deja pasar, para que aquí no se quede pulsado."""

    def __init__(self, sink: Any, mods: int, vk: int, abajo: set[int] | None = None) -> None:
        self.sink = sink
        self.mods, self.vk = mods, vk
        self.abajo: set[int] = set(abajo or ())
        self.teclas: set[tuple[int, int]] = set()
        self.botones: set[int] = set()

    def tecla(self, vk: int, scan: int, flags: int, abajo: bool) -> bool:
        if abajo:
            self.abajo.add(vk)
        else:
            self.abajo.discard(vk)
        sink = self.sink
        if sink is None:
            return False
        ambos = MOD_CONTROL | MOD_ALT
        if abajo and vk == 0x1B and mods_de(self.abajo) & ambos == ambos:  # Ctrl+Alt+Esc: emergencia
            self.sink = None
            sink.pedir("emergencia")
            return True
        if abajo and self.vk and vk == self.vk and mods_de(self.abajo) & self.mods == self.mods:
            self.sink = None
            sink.pedir("alternar")
            return True
        if vk == 0xA2 and scan & 0x200:  # Ctrl falso que Windows añade al AltGr: el otro PC pone el suyo
            return True
        ext = flags & 0x1
        clave = (vk, ext)
        if abajo:
            self.teclas.add(clave)
            sink.tecla(vk, scan & 0xFF, bool(ext), True)
            return True
        if clave in self.teclas:
            self.teclas.discard(clave)
            sink.tecla(vk, scan & 0xFF, bool(ext), False)
            return True
        return False

    def boton(self, b: int, abajo: bool) -> bool:
        sink = self.sink
        if sink is None:
            return False
        if abajo:
            self.botones.add(b)
            sink.boton(b, True)
            return True
        if b in self.botones:
            self.botones.discard(b)
            sink.boton(b, False)
            return True
        return False


class CapturaWindows:  # pragma: no cover - solo Windows
    """Un hilo con su bucle de mensajes: la tecla rápida (RegisterHotKey) mientras haya PCs en la
    lista, y los ganchos de bajo nivel SOLO mientras se controla. Los ganchos no hacen nada pesado:
    apuntan y vuelven (Windows quita un gancho que tarda)."""

    def __init__(self, control: Control) -> None:
        self.control = control
        self.filtro: Filtro | None = None
        self.tecla_ok = False
        self.instalada = False
        self._tid = 0
        self._hilo: threading.Thread | None = None
        self._listo = threading.Event()
        self._hecho = threading.Event()
        self._pedido: tuple = (0, 0)
        self._lock = threading.Lock()

    def _arrancar(self) -> None:
        if self._hilo is not None and self._hilo.is_alive():
            return
        self._listo.clear()
        self._hilo = threading.Thread(target=self._bucle, name="lazo-kvm-ganchos", daemon=True)
        self._hilo.start()
        self._listo.wait(3)

    def _post(self, msg: int) -> bool:
        import ctypes

        u = ctypes.WinDLL("user32")
        u.PostThreadMessageW.argtypes = [ctypes.c_ulong, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        self._hecho.clear()
        if not u.PostThreadMessageW(self._tid, msg, 0, 0):
            return False
        return self._hecho.wait(3)

    def registrar(self, mods: int, vk: int) -> bool:
        with self._lock:
            self._arrancar()
            self._pedido = (mods, vk)
            self._post(_REGISTRAR)
            return self.tecla_ok

    def empezar(self, sink: Control) -> bool:
        with self._lock:
            self._arrancar()
            mods, vk, _ = leer_tecla(AJUSTES.tecla)
            self.filtro = Filtro(sink, mods, vk)
            self._post(_EMPEZAR)
            return self.instalada

    def parar(self) -> None:
        f = self.filtro
        if f is not None:
            f.sink = None  # al momento: desde ya los ganchos dejan pasar todo
        if self._tid and threading.get_ident() != getattr(self._hilo, "ident", None):
            with self._lock:
                self._post(_PARAR)

    def _bucle(self) -> None:
        import ctypes
        from ctypes import wintypes as wt

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        try:
            winmm = ctypes.WinDLL("winmm")
        except OSError:
            winmm = None
        LRESULT = ctypes.c_ssize_t
        HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t)
        user32.CallNextHookEx.restype = LRESULT
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, wt.DWORD]
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
        user32.PeekMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT]
        user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
        user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        try:
            physical_pos = user32.GetPhysicalCursorPos
            physical_pos.argtypes = [ctypes.POINTER(wt.POINT)]
        except AttributeError:
            physical_pos = lambda _p: 0  # noqa: E731
        u32 = ctypes.c_uint32.from_address
        i32 = ctypes.c_int32.from_address
        # 0.71: el hilo de los ganchos, consciente de los DPI de cada monitor: así SetCursorPos y
        # el `pt` del gancho hablan en los mismos píxeles aunque Windows escale al 125 % o 150 %.
        try:
            user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
            user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            if not user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
                user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-3))
        except (AttributeError, OSError):
            pass
        CALIBRA = 0x4C5A4341  # «LZCA»: el movimiento nulo con el que se mide el centro
        extra_off = 24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 20
        calibrando = [False]
        try:
            calibrador: Any = InyectorWindows()
        except Exception:  # noqa: BLE001
            calibrador = None
        centro = [0, 0]
        guardado = wt.POINT()
        ganchos: list = []

        def raton(code, wparam, lparam):
            f = self.filtro
            if (code == 0 and lparam and calibrando[0] and wparam == 0x200 and u32(lparam + 12).value & 0x1
                    and ctypes.c_size_t.from_address(lparam + extra_off).value == CALIBRA):
                # 0.71: el centro, medido en las MISMAS coordenadas que dará el gancho. Antes, con
                # escalado de pantalla, el centro calculado no coincidía y cada movimiento sumaba un
                # desfase fijo: en el otro PC el puntero se iba a una esquina.
                centro[:] = [i32(lparam).value, i32(lparam + 4).value]
                calibrando[0] = False
                return 1
            if code == 0 and lparam and f is not None and f.sink is not None:
                if not (u32(lparam + 12).value & 0x1):  # LLMHF_INJECTED: lo inyectado pasa
                    if not f.sink.vivo():
                        f.sink, sink = None, f.sink
                        sink.pedir("parar")
                    elif wparam == 0x200:  # WM_MOUSEMOVE: delta respecto al centro; el puntero no se mueve
                        dx, dy = i32(lparam).value - centro[0], i32(lparam + 4).value - centro[1]
                        if dx or dy:
                            f.sink.mover(dx, dy)
                        return 1
                    elif wparam in (0x20A, 0x20E):  # rueda vertical y horizontal
                        delta = ctypes.c_int16((u32(lparam + 8).value >> 16) & 0xFFFF).value
                        f.sink.rueda(0 if wparam == 0x20A else 1, delta)
                        return 1
                    elif wparam in _BOTONES_MSG:
                        b, abajo = _BOTONES_MSG[wparam]
                        if f.boton(b, abajo):
                            return 1
                    elif wparam in (0x20B, 0x20C):  # botones X (atrás / adelante)
                        b = 4 if ((u32(lparam + 8).value >> 16) & 0xFFFF) == 1 else 5
                        if f.boton(b, wparam == 0x20B):
                            return 1
            return user32.CallNextHookEx(None, code, wparam, lparam)

        def teclado(code, wparam, lparam):
            f = self.filtro
            if code == 0 and lparam and f is not None:
                vk, scan, flags = u32(lparam).value, u32(lparam + 4).value, u32(lparam + 8).value
                if not (flags & 0x10):  # LLKHF_INJECTED: lo inyectado pasa
                    if f.sink is not None and not f.sink.vivo():
                        f.sink, sink = None, f.sink
                        sink.pedir("parar")
                    if f.tecla(vk, scan, flags, wparam in (0x100, 0x104)):
                        return 1
            return user32.CallNextHookEx(None, code, wparam, lparam)

        proc_r, proc_t = HOOKPROC(raton), HOOKPROC(teclado)  # se guardan: si el GC los recoge, Windows salta a la nada
        self._tid = kernel32.GetCurrentThreadId()
        msg = wt.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # crea la cola antes de avisar
        self._listo.set()

        def quitar() -> None:
            if not ganchos:
                return
            for h in ganchos:
                user32.UnhookWindowsHookEx(h)
            ganchos.clear()
            user32.SetCursorPos(guardado.x, guardado.y)  # el puntero vuelve a donde estaba
            if winmm is not None:
                winmm.timeEndPeriod(1)
            self.instalada = False

        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == 1:
                    self.control.pedir("alternar")
                elif msg.message == _REGISTRAR:
                    user32.UnregisterHotKey(None, 1)
                    mods, vk = self._pedido
                    self.tecla_ok = bool(vk) and bool(user32.RegisterHotKey(None, 1, mods | 0x4000, vk))  # MOD_NOREPEAT
                    self._hecho.set()
                elif msg.message == _EMPEZAR:
                    quitar()
                    f = self.filtro
                    if f is not None:
                        f.abajo = {vk for vk in (0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C)
                                   if user32.GetAsyncKeyState(vk) & 0x8000}
                    user32.GetCursorPos(ctypes.byref(guardado))
                    user32.SetCursorPos(user32.GetSystemMetrics(0) // 2, user32.GetSystemMetrics(1) // 2)
                    # El gancho da `pt` en píxeles físicos; con el escalado de Windows (125 %, 150 %...)
                    # GetCursorPos de un proceso sin DPI daría otra cosa. La referencia, en físicos.
                    fisico = wt.POINT()
                    if not physical_pos(ctypes.byref(fisico)):
                        user32.GetCursorPos(ctypes.byref(fisico))
                    centro[:] = [fisico.x, fisico.y]
                    for tipo, proc in ((14, proc_r), (13, proc_t)):  # WH_MOUSE_LL, WH_KEYBOARD_LL
                        h = user32.SetWindowsHookExW(tipo, proc, kernel32.GetModuleHandleW(None), 0)
                        if h:
                            ganchos.append(h)
                    self.instalada = len(ganchos) == 2
                    if not self.instalada:
                        if f is not None:
                            f.sink = None
                        quitar()
                        user32.SetCursorPos(guardado.x, guardado.y)
                    else:
                        if winmm is not None:
                            winmm.timeBeginPeriod(1)  # tandas de ~6 ms de verdad
                        if calibrador is not None:
                            calibrando[0] = True
                            try:
                                calibrador._raton(0x0001, 0, 0, extra=CALIBRA)  # movimiento nulo: lo ve el gancho
                            except Exception:  # noqa: BLE001
                                calibrando[0] = False
                    self._hecho.set()
                elif msg.message == _PARAR:
                    if self.filtro is not None:
                        self.filtro.sink = None
                    quitar()
                    self._hecho.set()
                else:
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self.filtro is not None:
                self.filtro.sink = None
            quitar()
            user32.UnregisterHotKey(None, 1)
            self.tecla_ok = False
            del proc_r, proc_t


def captura_para_este_pc(control: Control) -> Any:
    if sys.platform == "win32":
        return CapturaWindows(control)
    if sys.platform.startswith("linux"):  # 0.71: evdev con EVIOCGRAB, o X11
        import linux_kvm

        return linux_kvm.captura_linux(control)
    return None


CONTROL = Control()


def _tras_emparejar() -> None:
    CONTROL.armar()


EMPAREJAR = Emparejar(PCS, al_terminar=_tras_emparejar)


def _nombre_sistema() -> str:
    try:
        import control

        return control.pc_name()
    except Exception:  # noqa: BLE001
        return ""


def para_movil() -> dict:
    """0.72: lo que el móvil (aprobado, por /api/status sellado) necesita para nombrar los PCs:
    el nombre propio de este y los puestos con «Renombrar» a los de «Controlar otro PC», por
    IP:puerto (la misma dirección con la que la App los guarda)."""
    apodos = {}
    try:
        for pc in PCS.listar():
            if pc.get("apodo") and pc.get("host"):
                apodos[f"{pc['host']}:{pc['puerto']}"] = pc["apodo"]
    except Exception:  # noqa: BLE001
        apodos = {}
    return {"pc_nombre": AJUSTES.nombre, "pcs_apodos": dict(list(apodos.items())[:50])}


def estado() -> dict:
    """Para el Panel (solo local)."""
    ok, motivo = CONTROL.puede_mandar()
    cap = CONTROL.captura
    data = {"permitir": AJUSTES.permitir, "tecla": AJUSTES.tecla, "emergencia": EMERGENCIA,
            "portapapeles": AJUSTES.portapapeles, "nombre_este": AJUSTES.nombre, "nombre_sistema": _nombre_sistema(),
            "puede_mandar": ok, "motivo": motivo, "pcs": PCS.listar(), "control": CONTROL.ver(),
            "emparejar": EMPAREJAR.ver(), "recibiendo": RECEPCION.nombre_actual(),
            "tecla_ok": bool(getattr(cap, "tecla_ok", False)), "diagnostico": "", "falta": "", "arreglable": False}
    if sys.platform.startswith("linux"):
        data.update(diagnostico_linux())
    return data


_DIAG: list = [0.0, {}]


def diagnostico_linux(forzar: bool = False) -> dict:
    """0.71: qué método de inyección y de captura usa este Linux, por qué, y si falta algo
    (se calcula cada 30 s como mucho)."""
    if forzar or time.monotonic() - _DIAG[0] > 30 or not _DIAG[1]:
        try:
            import linux_kvm

            d = linux_kvm.diagnostico()
            _DIAG[1] = {"diagnostico": f"Que otro PC controle este: {d['receptor']} ({d['receptor_por']}) · "
                                       f"Controlar otro desde este: {d['emisor']} ({d['emisor_por']})",
                        "falta": linux_kvm.falta(d), "arreglable": bool(d.get("arreglable"))}
        except Exception as exc:  # noqa: BLE001
            _DIAG[1] = {"diagnostico": f"Sin diagnóstico ({exc.__class__.__name__})", "falta": "", "arreglable": False}
        _DIAG[0] = time.monotonic()
    return dict(_DIAG[1])


def olvidar(pid: str) -> dict:
    if CONTROL.destino and CONTROL.destino.get("id") == pid:
        CONTROL.parar("")
    hecho = PCS.olvidar(str(pid))
    CONTROL.armar()
    return {"ok": hecho}
