"""LaZoo 0.76: imágenes del portapapeles al cambiar de PC (Ctrl+Alt+L), en los dos sentidos.

Formato en el cable: PNG (como mucho MAX_IMAGEN bytes). Nunca se guarda en disco: va de la
memoria del portapapeles de un PC a la del otro por el canal sellado de «Controlar otro PC».

Leer y poner, SOLO bajo demanda (al cambiar de PC; nada de sondeos, como pide la 0.75):
    Windows  el formato registrado «PNG» si está; si no, CF_DIBV5/CF_DIB (una captura con
             Impr Pant o Recortes), pasado a PNG aquí. Al poner: CF_DIB y también «PNG».
    Linux    Wayland: `wl-paste --list-types` y `wl-paste --type image/png` / `wl-copy --type
             image/png`. Xorg: GTK de la bandeja (sin procesos) o, si no, xclip con image/png.

PNG en Python puro (zlib de la biblioteca estándar): se codifica sin filtro y se decodifica
cualquier PNG de 8 bits (gris, RGB, paleta, gris+alfa, RGBA; todos los filtros; sin entrelazar).
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
import zlib
from typing import Any

MAX_IMAGEN = 20_000_000          # bytes de PNG como mucho
MAX_PIXELES = 40_000_000         # ancho × alto como mucho al decodificar
MAX_DIB_PIXELES = 16_000_000     # al poner en Windows: por encima, solo «PNG» (sin CF_DIB)
FIRMA_PNG = b"\x89PNG\r\n\x1a\n"
ESPERA = 4.0                     # s como mucho para wl-paste/xclip


class ErrorImagen(ValueError):
    pass


# --- PNG ----------------------------------------------------------------------------------------


def _trozo(tipo: bytes, datos: bytes) -> bytes:
    return struct.pack(">I", len(datos)) + tipo + datos + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF)


def png_de_pixeles(ancho: int, alto: int, pixeles: bytes, canales: int = 4, nivel: int = 6) -> bytes:
    """Filas de arriba abajo, RGBA (4) o RGB (3), 8 bits. Sin filtro (0) por fila."""
    if canales not in (3, 4) or ancho <= 0 or alto <= 0 or len(pixeles) != ancho * alto * canales:
        raise ErrorImagen("imagen no válida")
    fila = ancho * canales
    crudo = bytearray((fila + 1) * alto)
    for y in range(alto):
        o = y * (fila + 1)
        crudo[o + 1:o + 1 + fila] = pixeles[y * fila:(y + 1) * fila]
    ihdr = struct.pack(">IIBBBBB", ancho, alto, 8, 6 if canales == 4 else 2, 0, 0, 0)
    return FIRMA_PNG + _trozo(b"IHDR", ihdr) + _trozo(b"IDAT", zlib.compress(bytes(crudo), nivel)) + _trozo(b"IEND", b"")


def es_png(datos: Any) -> bool:
    return isinstance(datos, (bytes, bytearray)) and bytes(datos[:8]) == FIRMA_PNG


def medidas_png(datos: bytes) -> tuple[int, int]:
    if not es_png(datos) or len(datos) < 33 or datos[12:16] != b"IHDR":
        raise ErrorImagen("no es un PNG")
    return struct.unpack(">II", datos[16:24])


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _desfiltrar(crudo: bytes, ancho_fila: int, alto: int, bpp: int) -> bytearray:
    salida = bytearray(ancho_fila * alto)
    previa = bytearray(ancho_fila)
    i = 0
    for y in range(alto):
        if i >= len(crudo):
            raise ErrorImagen("PNG cortado")
        filtro = crudo[i]
        fila = bytearray(crudo[i + 1:i + 1 + ancho_fila])
        if len(fila) != ancho_fila:
            raise ErrorImagen("PNG cortado")
        i += 1 + ancho_fila
        if filtro == 0:
            pass
        elif filtro == 1:
            for x in range(bpp, ancho_fila):
                fila[x] = (fila[x] + fila[x - bpp]) & 0xFF
        elif filtro == 2:
            for x in range(ancho_fila):
                fila[x] = (fila[x] + previa[x]) & 0xFF
        elif filtro == 3:
            for x in range(ancho_fila):
                izq = fila[x - bpp] if x >= bpp else 0
                fila[x] = (fila[x] + ((izq + previa[x]) >> 1)) & 0xFF
        elif filtro == 4:
            for x in range(ancho_fila):
                if x >= bpp:
                    fila[x] = (fila[x] + _paeth(fila[x - bpp], previa[x], previa[x - bpp])) & 0xFF
                else:
                    fila[x] = (fila[x] + previa[x]) & 0xFF
        else:
            raise ErrorImagen("filtro PNG no válido")
        salida[y * ancho_fila:(y + 1) * ancho_fila] = fila
        previa = fila
    return salida


def pixeles_de_png(datos: bytes) -> tuple[int, int, bytes]:
    """PNG de 8 bits sin entrelazar → (ancho, alto, RGBA de arriba abajo)."""
    if not es_png(datos):
        raise ErrorImagen("no es un PNG")
    i = 8
    ihdr = None
    paleta = b""
    trns = b""
    idat = []
    while i + 8 <= len(datos):
        largo, tipo = struct.unpack(">I4s", datos[i:i + 8])
        cuerpo = datos[i + 8:i + 8 + largo]
        i += 12 + largo
        if tipo == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", cuerpo[:13])
        elif tipo == b"PLTE":
            paleta = cuerpo
        elif tipo == b"tRNS":
            trns = cuerpo
        elif tipo == b"IDAT":
            idat.append(cuerpo)
        elif tipo == b"IEND":
            break
    if ihdr is None:
        raise ErrorImagen("PNG sin cabecera")
    ancho, alto, bits, color, _comp, _filt, entrelazado = ihdr
    if bits != 8 or entrelazado or color not in (0, 2, 3, 4, 6):
        raise ErrorImagen("PNG no soportado (solo 8 bits sin entrelazar)")
    if not 0 < ancho * alto <= MAX_PIXELES:
        raise ErrorImagen("imagen demasiado grande")
    canales = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    fila = ancho * canales
    d = zlib.decompressobj()
    crudo = d.decompress(b"".join(idat), (fila + 1) * alto + 1)
    px = _desfiltrar(crudo, fila, alto, canales)
    n = ancho * alto
    rgba = bytearray(n * 4)
    if color == 6:
        rgba[:] = px
    elif color == 2:
        rgba[0::4], rgba[1::4], rgba[2::4] = px[0::3], px[1::3], px[2::3]
        rgba[3::4] = b"\xff" * n
    elif color == 0:
        rgba[0::4] = rgba[1::4] = rgba[2::4] = px
        rgba[3::4] = b"\xff" * n
    elif color == 4:
        rgba[0::4] = rgba[1::4] = rgba[2::4] = px[0::2]
        rgba[3::4] = px[1::2]
    else:  # paleta
        if not paleta:
            raise ErrorImagen("PNG sin paleta")
        tabla = []
        for k in range(len(paleta) // 3):
            a = trns[k] if k < len(trns) else 255
            tabla.append(bytes(paleta[k * 3:k * 3 + 3]) + bytes([a]))
        tabla += [b"\0\0\0\xff"] * (256 - len(tabla))
        rgba[:] = b"".join(tabla[v] for v in px)
    return ancho, alto, bytes(rgba)


# --- DIB (Windows) ------------------------------------------------------------------------------


def dib_a_png(dib: bytes) -> bytes:
    """CF_DIB / CF_DIBV5 (BITMAPINFOHEADER o V5; 24 o 32 bits, BI_RGB o BI_BITFIELDS) → PNG."""
    if len(dib) < 40:
        raise ErrorImagen("imagen no válida")
    tam_cab, ancho, alto, _planos, bits, compresion = struct.unpack_from("<IiiHHI", dib, 0)
    colores = struct.unpack_from("<I", dib, 32)[0]
    if bits not in (24, 32) or compresion not in (0, 3) or ancho <= 0 or alto == 0:
        raise ErrorImagen("imagen de un tipo que LaZoo aún no pasa")
    arriba_abajo = alto < 0
    alto = abs(alto)
    if ancho * alto > MAX_PIXELES:
        raise ErrorImagen("imagen demasiado grande")
    inicio = tam_cab + colores * 4
    if compresion == 3 and tam_cab == 40:
        inicio += 12  # las tres máscaras van detrás de la cabecera
    paso = ((ancho * bits + 31) // 32) * 4
    if len(dib) < inicio + paso * alto:
        raise ErrorImagen("imagen cortada")
    bpp = bits // 8
    filas = []
    orden = range(alto) if arriba_abajo else range(alto - 1, -1, -1)
    for y in orden:
        o = inicio + y * paso
        filas.append(dib[o:o + ancho * bpp])
    bgr = b"".join(filas)
    n = ancho * alto
    if bpp == 4:
        alfa = bgr[3::4]
        if alfa.count(0) == n:  # CF_DIB de una captura: alfa a 0 = opaco
            rgb = bytearray(n * 3)
            rgb[0::3], rgb[1::3], rgb[2::3] = bgr[2::4], bgr[1::4], bgr[0::4]
            return png_de_pixeles(ancho, alto, bytes(rgb), 3)
        rgba = bytearray(n * 4)
        rgba[0::4], rgba[1::4], rgba[2::4], rgba[3::4] = bgr[2::4], bgr[1::4], bgr[0::4], alfa
        return png_de_pixeles(ancho, alto, bytes(rgba), 4)
    rgb = bytearray(n * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgr[2::3], bgr[1::3], bgr[0::3]
    return png_de_pixeles(ancho, alto, bytes(rgb), 3)


def png_a_dib(png: bytes) -> bytes:
    """PNG → CF_DIB (BITMAPINFOHEADER, 32 bits BI_RGB, de abajo arriba, BGRA)."""
    ancho, alto, rgba = pixeles_de_png(png)
    n = ancho * alto
    bgra = bytearray(n * 4)
    bgra[0::4], bgra[1::4], bgra[2::4], bgra[3::4] = rgba[2::4], rgba[1::4], rgba[0::4], rgba[3::4]
    paso = ancho * 4
    filas = [bytes(bgra[y * paso:(y + 1) * paso]) for y in range(alto - 1, -1, -1)]
    cab = struct.pack("<IiiHHIIiiII", 40, ancho, alto, 1, 32, 0, paso * alto, 2835, 2835, 0, 0)
    return cab + b"".join(filas)


# --- Portapapeles del sistema -------------------------------------------------------------------


def _windows_leer() -> bytes | None:  # pragma: no cover - solo Windows
    import ctypes
    import time

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.IsClipboardFormatAvailable.argtypes = [ctypes.c_uint]
    user32.RegisterClipboardFormatW.argtypes = [ctypes.c_wchar_p]
    user32.RegisterClipboardFormatW.restype = ctypes.c_uint
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    png_fmt = user32.RegisterClipboardFormatW("PNG")
    formatos = [(png_fmt, "png"), (17, "dib"), (8, "dib")]  # PNG, CF_DIBV5, CF_DIB
    if not any(user32.IsClipboardFormatAvailable(f) for f, _ in formatos):
        return None
    for _ in range(5):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.03)
    else:
        return None
    try:
        for fmt, tipo in formatos:
            if not user32.IsClipboardFormatAvailable(fmt):
                continue
            h = user32.GetClipboardData(fmt)
            if not h:
                continue
            tam = kernel32.GlobalSize(h)
            if not tam or tam > MAX_IMAGEN * 4:
                continue
            p = kernel32.GlobalLock(h)
            if not p:
                continue
            try:
                datos = ctypes.string_at(p, tam)
            finally:
                kernel32.GlobalUnlock(h)
            if tipo == "png" and es_png(datos):
                return datos
            if tipo == "dib":
                try:
                    return dib_a_png(datos)
                except ErrorImagen:
                    continue
    finally:
        user32.CloseClipboard()
    return None


def _windows_poner(png: bytes) -> bool:  # pragma: no cover - solo Windows
    import ctypes
    import time

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.EmptyClipboard.restype = ctypes.c_bool
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.RegisterClipboardFormatW.argtypes = [ctypes.c_wchar_p]
    user32.RegisterClipboardFormatW.restype = ctypes.c_uint
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]

    def memoria(datos: bytes) -> Any:
        h = kernel32.GlobalAlloc(0x0002, len(datos))  # GMEM_MOVEABLE
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        if not p:
            kernel32.GlobalFree(h)
            return None
        ctypes.memmove(p, datos, len(datos))
        kernel32.GlobalUnlock(h)
        return h

    dib = None
    try:
        ancho, alto = medidas_png(png)
        if ancho * alto <= MAX_DIB_PIXELES:
            dib = png_a_dib(png)
    except ErrorImagen:
        dib = None
    for _ in range(5):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.03)
    else:
        return False
    puesto = False
    try:
        user32.EmptyClipboard()
        for fmt, datos in ((8, dib), (user32.RegisterClipboardFormatW("PNG"), png)):
            if not datos:
                continue
            h = memoria(datos)
            if h is None:
                continue
            if user32.SetClipboardData(fmt, h):
                puesto = True
            else:
                kernel32.GlobalFree(h)
    finally:
        user32.CloseClipboard()
    return puesto


def _proceso(cmd: list[str], entrada: bytes | None = None) -> bytes | None:
    """Un programa del portapapeles (wl-paste, xclip) SOLO al cambiar de PC."""
    try:
        if entrada is None:
            r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=ESPERA)
            return r.stdout if r.returncode == 0 else None
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        assert proc.stdin is not None
        proc.stdin.write(entrada)
        proc.stdin.close()
        try:
            return b"" if proc.wait(timeout=1.5) == 0 else None
        except subprocess.TimeoutExpired:
            return b""  # sigue vivo sirviendo la imagen
    except (OSError, subprocess.SubprocessError):
        return None


def _gtk() -> Any:
    try:
        import control

        return control.GTK_CLIP
    except Exception:  # noqa: BLE001
        return None


def leer() -> bytes | None:
    """PNG del portapapeles de ESTE PC, o None si no hay imagen (o pasa de MAX_IMAGEN)."""
    try:
        if sys.platform == "win32":
            png = _windows_leer()
        elif sys.platform.startswith("linux"):
            png = None
            if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
                tipos = (_proceso(["wl-paste", "--list-types"]) or b"").decode("utf-8", "replace").split()
                if "image/png" in tipos:
                    png = _proceso(["wl-paste", "--no-newline", "--type", "image/png"])
            elif _gtk() is not None and hasattr(_gtk(), "leer_imagen"):
                png = _gtk().leer_imagen()
            elif os.environ.get("DISPLAY") and shutil.which("xclip"):
                tipos = (_proceso(["xclip", "-selection", "clipboard", "-t", "TARGETS", "-o"]) or b"").decode("utf-8", "replace").split()
                if "image/png" in tipos:
                    png = _proceso(["xclip", "-selection", "clipboard", "-t", "image/png", "-o"])
        else:
            png = None
    except Exception:  # noqa: BLE001
        return None
    if not png or not es_png(png) or len(png) > MAX_IMAGEN:
        return None
    return bytes(png)


def poner(png: bytes) -> bool:
    """Deja la imagen en el portapapeles de este PC (no se guarda en disco)."""
    if not es_png(png) or len(png) > MAX_IMAGEN:
        return False
    try:
        if sys.platform == "win32":
            return _windows_poner(png)
        if sys.platform.startswith("linux"):
            if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
                return _proceso(["wl-copy", "--type", "image/png"], png) is not None
            gtk = _gtk()
            if gtk is not None and hasattr(gtk, "escribir_imagen") and gtk.escribir_imagen(png):
                return True
            if os.environ.get("DISPLAY") and shutil.which("xclip"):
                return _proceso(["xclip", "-selection", "clipboard", "-t", "image/png", "-i"], png) is not None
    except Exception:  # noqa: BLE001
        return False
    return False


def describir(png: bytes) -> str:
    """«imagen 1280×720, 340 KB» para el aviso."""
    try:
        ancho, alto = medidas_png(png)
        return f"imagen {ancho}×{alto}, {max(1, len(png) // 1024)} KB"
    except ErrorImagen:
        return f"imagen de {max(1, len(png) // 1024)} KB"
