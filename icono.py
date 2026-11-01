"""Icono de LaZoo dibujado con la biblioteca estándar: una «Z» naranja sobre fondo oscuro.

`rgba(size)` da los píxeles, `ico_bytes()` un .ico (PNG dentro, de 16 a 256 px) y
`dib_icon(size)` el formato que acepta CreateIconFromResourceEx en Windows.
Ejecuta `python icono.py` para regenerar static/lazoo.ico.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

BG = (0x1b, 0x1b, 0x1f)
FG = (0xe0, 0x7a, 0x3d)


def _shape(x: float, y: float) -> tuple[float, float]:
    """(cubre_fondo, cubre_Z) para un punto en [0,1]²."""
    r = 0.22
    cx, cy = min(max(x, r), 1 - r), min(max(y, r), 1 - r)
    bg = 1.0 if (x - cx) ** 2 + (y - cy) ** 2 <= r * r else 0.0
    z = 0.0
    if 0.22 <= x <= 0.78 and (0.21 <= y <= 0.34 or 0.66 <= y <= 0.79):
        z = 1.0
    else:
        ax, ay, bx, by = 0.75, 0.30, 0.25, 0.70
        t = ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)
        if 0 <= t <= 1:
            px, py = ax + t * (bx - ax), ay + t * (by - ay)
            if (x - px) ** 2 + (y - py) ** 2 <= 0.075 ** 2:
                z = 1.0
    return bg, z


def rgba(size: int) -> bytes:
    out = bytearray()
    n = 4
    for j in range(size):
        for i in range(size):
            bg = z = 0.0
            for sj in range(n):
                for si in range(n):
                    a, b = _shape((i + (si + 0.5) / n) / size, (j + (sj + 0.5) / n) / size)
                    bg += a
                    z += min(a, b)
            bg, z = bg / n / n, z / n / n
            if bg <= 0:
                out += b"\0\0\0\0"
                continue
            mix = z / bg
            col = [round(BG[k] * (1 - mix) + FG[k] * mix) for k in range(3)]
            out += bytes(col + [round(255 * bg)])
    return bytes(out)


def png(size: int) -> bytes:
    raw = rgba(size)
    rows = b"".join(b"\0" + raw[y * size * 4:(y + 1) * size * 4] for y in range(size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")


def ico_bytes(sizes=(16, 24, 32, 48, 64, 256)) -> bytes:
    images = [png(s) for s in sizes]
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    table = b""
    for s, data in zip(sizes, images):
        table += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return head + table + b"".join(images)


def dib_icon(size: int = 32) -> bytes:
    """BITMAPINFOHEADER + BGRA de abajo arriba + máscara AND vacía."""
    raw = rgba(size)
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    pixels = bytearray()
    for y in range(size - 1, -1, -1):
        for x in range(size):
            r, g, b, a = raw[(y * size + x) * 4:(y * size + x) * 4 + 4]
            pixels += bytes((b, g, r, a))
    mask = b"\0" * (((size + 31) // 32) * 4 * size)
    return header + bytes(pixels) + mask


if __name__ == "__main__":
    target = Path(__file__).with_name("static") / "lazoo.ico"
    target.write_bytes(ico_bytes())
    print(f"Escrito {target.name} ({target.stat().st_size} bytes)")
