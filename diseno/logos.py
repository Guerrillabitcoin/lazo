"""Genera la identidad visual de LaZoo (herramienta de desarrollo, no se empaqueta).

0.56: ya no se usa ninguna tipografía. Todo sale TRAZADO de las imágenes originales de
static/img/original/ (mismas letras, espaciado, grosor y proporciones que el diseño):

  1) python diseno/logos.py --trazar   (necesita Pillow, numpy y potracer: pip install potracer)
     Vectoriza los originales ampliados x8 y guarda los contornos en diseno/trazos.json.
  2) python diseno/logos.py            (solo Pillow)
     A partir de diseno/trazos.json escribe los SVG y PNG de static/img, los .ico de la
     bandeja y del .exe, los mipmaps y vectores de Android y las constantes de static/logo.js.

Wordmark (unidades del original de 1280x720): «L», «a», «Z» y la primera «o» blancas, la
última «o» roja; conectado, las dos «o» son el infinito verde (trazado de la imagen derecha y
llevado a la misma escala que la izquierda). Los anillos y el infinito animados de logo.js se
ajustaron a esos contornos (anillo: radio 42,4 y grosor 30,4; infinito: lemniscata ajustada).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "static" / "img"
ORIG = IMG / "original"
RES = ROOT / "android" / "res"
TRAZOS = Path(__file__).resolve().parent / "trazos.json"

# Colores medidos en los originales (mediana de los píxeles de cada forma).
ROJO = "#ea0918"           # anillo del wordmark desconectado
VERDE = "#158941"          # infinito del wordmark conectado
NARANJA = "#ff813f"        # icono de la APK y del móvil (imagen 2)
ROJO_BANDEJA = "#f71224"   # bandeja sin conexión (imagen 3)
VERDE_BANDEJA = "#58c006"  # bandeja conectada (imagen 4)
BLANCO = "#ffffff"

VIEW = (50, 258, 584, 166)  # x, y, ancho, alto del viewBox del wordmark

# Del original derecho (conectado) al sistema del izquierdo: misma «L», «a», «Z».
DER_A_IZQ = (697, 274, 58, 266, 0.994, 0.987)


# ---------------------------------------------------------------- 1) trazar (potrace)

def _trazar(img: Image.Image, caja, tipo: str, tf=None, escala: int = 8, suave: float = 0.7, tolerancia: float = 0.4) -> str:
    import numpy as np
    import potrace
    from PIL import ImageFilter

    x0, y0, x1, y1 = caja
    a = np.array(img.convert("RGB").crop(caja)).astype(float)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    if tipo == "blanco":
        v = np.minimum(np.minimum(r, g), b)
    elif tipo == "verde":
        v = np.clip((g - np.maximum(r, b)) * 255 / 72.0, 0, 255)
    elif tipo == "rojo":
        v = np.clip((r - np.maximum(g, b)) * 255 / 210.0, 0, 255)
    else:  # color saturado sobre negro (iconos)
        s = a.max(2) - a.min(2)
        v = np.clip(s * 255 / np.median(s[s > 80]), 0, 255)
    grande = Image.fromarray(v.astype("uint8")).resize(((x1 - x0) * escala, (y1 - y0) * escala), Image.BICUBIC)
    grande = grande.filter(ImageFilter.GaussianBlur(escala * suave))
    fondo = np.array(grande) <= 128  # potracer traza lo que es False
    camino = potrace.Bitmap(fondo).trace(turdsize=40 * escala * escala, alphamax=1.0, opticurve=True, opttolerance=tolerancia)
    tf = tf or (lambda x, y: (x, y))

    def f(p):
        x, y = tf(x0 + p.x / escala, y0 + p.y / escala)
        return f"{x:.1f} {y:.1f}"

    d = ""
    for curva in camino:
        d += "M" + f(curva.start_point)
        for s in curva:
            d += ("L" + f(s.c) + "L" + f(s.end_point)) if s.is_corner else ("C" + f(s.c1) + " " + f(s.c2) + " " + f(s.end_point))
        d += "Z"
    return d


def trazar() -> None:
    w = Image.open(ORIG / "logo-wordmark.png")
    ax, ay, bx, by, sx, sy = DER_A_IZQ
    der = lambda x, y: (bx + (x - ax) / sx, by + (y - ay) / sy)
    datos = {
        "letras": _trazar(w, (50, 258, 383, 424), "blanco"),   # L a Z (la Z acaba en x=382)
        "o1": _trazar(w, (383, 292, 500, 424), "blanco"),
        "rojo": _trazar(w, (496, 292, 620, 424), "rojo"),
        "verde": _trazar(w, (1021, 298, 1268, 432), "verde", tf=der, suave=1.0, tolerancia=0.8),
    }
    for clave, archivo in (("icono_naranja", "icono-apk-movil.png"), ("icono_rojo", "tray-desconectado.png"),
                           ("icono_verde", "tray-conectado.png")):
        im = Image.open(ORIG / archivo)
        datos[clave] = _trazar(im, (0, 0, im.width, im.height), "color", escala=3, suave=1.6, tolerancia=1.0)
    TRAZOS.write_text(json.dumps(datos, indent=1) + "\n", encoding="utf-8")
    print("trazos:", TRAZOS)


# ---------------------------------------------------------------- 2) generar (Pillow)

def subcaminos(d: str):
    """Contornos de un path con solo M, L, C y Z absolutos (lo que escribe trazar())."""
    out, pts = [], []
    toks = re.findall(r"[MLCZ]|-?\d+(?:\.\d+)?", d)
    i, cur = 0, (0.0, 0.0)
    while i < len(toks):
        t = toks[i]
        i += 1
        if t == "M":
            cur = (float(toks[i]), float(toks[i + 1]))
            i += 2
            pts = [cur]
        elif t == "L":
            cur = (float(toks[i]), float(toks[i + 1]))
            i += 2
            pts.append(cur)
        elif t == "C":
            c = [float(v) for v in toks[i:i + 6]]
            i += 6
            p0 = cur
            for k in range(1, 13):
                u = k / 12
                m = 1 - u
                pts.append((m ** 3 * p0[0] + 3 * m * m * u * c[0] + 3 * m * u * u * c[2] + u ** 3 * c[4],
                            m ** 3 * p0[1] + 3 * m * m * u * c[1] + 3 * m * u * u * c[3] + u ** 3 * c[5]))
            cur = (c[4], c[5])
        elif t == "Z":
            out.append(pts)
    return out


def caja(d: str):
    xs = [x for s in subcaminos(d) for x, _ in s]
    ys = [y for s in subcaminos(d) for _, y in s]
    return min(xs), min(ys), max(xs), max(ys)


def transformar(d: str, k: float, dx: float, dy: float) -> str:
    """Escala y mueve un path M/L/C/Z absoluto (los números van en pares «x y»)."""
    return re.sub(r"(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)",
                  lambda m: f"{float(m[1]) * k + dx:.2f} {float(m[2]) * k + dy:.2f}", d)


def encajar(d: str, lado: float, margen: float) -> str:
    """Centra el path en un cuadrado de `lado`, con `margen` (fracción) a los lados."""
    x0, y0, x1, y1 = caja(d)
    k = lado * (1 - 2 * margen) / max(x1 - x0, y1 - y0)
    return transformar(d, k, lado / 2 - (x0 + x1) / 2 * k, lado / 2 - (y0 + y1) / 2 * k)


def pintar(d: str, size: int, color, fondo=None, ss: int = 8) -> Image.Image:
    """Rasteriza con relleno par-impar (los agujeros de la «o» y del infinito)."""
    big = size * ss
    masc = Image.new("1", (big, big), 0)
    for s in subcaminos(d):
        capa = Image.new("1", (big, big), 0)
        ImageDraw.Draw(capa).polygon([(x * ss, y * ss) for x, y in s], fill=1)
        masc = ImageChops.logical_xor(masc, capa)
    alfa = masc.convert("L").resize((size, size), Image.LANCZOS)
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0) if fondo is None else fondo)
    tinta = Image.new("RGBA", (size, size), color)
    im.paste(tinta, (0, 0), alfa)
    return im


def svg_icono(d: str, color: str, fondo: str | None = None, margen: float = 0.06) -> str:
    bg = f'<rect width="100" height="100" rx="22" fill="{fondo}"/>' if fondo else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">{bg}'
            f'<path fill="{color}" fill-rule="evenodd" d="{encajar(d, 100, margen)}"/></svg>\n')


def svg_wordmark(t: dict, conectado: bool) -> str:
    x, y, w, h = VIEW
    formas = (f'<path fill="{VERDE}" fill-rule="evenodd" d="{t["verde"]}"/>' if conectado else
              f'<path fill="{BLANCO}" fill-rule="evenodd" d="{t["o1"]}"/><path fill="{ROJO}" fill-rule="evenodd" d="{t["rojo"]}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {w} {h}" role="img" '
            f'aria-label="LaZoo {"conectado" if conectado else "desconectado"}">'
            f'<path fill="{BLANCO}" fill-rule="evenodd" d="{t["letras"]}"/>{formas}</svg>\n')


def guardar_ico(d: str, color: str, ruta: Path) -> None:
    tam = [16, 24, 32, 48, 64, 128, 256]
    # A tamaños pequeños, menos margen para que se vea grande en la bandeja.
    imgs = []
    for s in tam:
        m = 0.02 if s <= 32 else 0.06
        imgs.append(pintar(encajar(d, s, m), s, color))
    imgs[-1].save(ruta, format="ICO", sizes=[(s, s) for s in tam], append_images=imgs[:-1])


def vector_android(d: str, color: str, ancho_dp: int, lienzo: float, escala: float) -> str:
    """VectorDrawable del infinito (relleno par-impar) centrado en un lienzo."""
    dd = encajar(d, lienzo, (1 - escala) / 2)
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            f'<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="{ancho_dp}dp" '
            f'android:height="{ancho_dp}dp" android:viewportWidth="{lienzo}" android:viewportHeight="{lienzo}">\n'
            f'  <path android:fillColor="{color}" android:fillType="evenOdd" android:pathData="{dd}"/>\n</vector>\n')


def generar() -> None:
    t = json.loads(TRAZOS.read_text(encoding="utf-8"))
    IMG.mkdir(parents=True, exist_ok=True)
    (IMG / "logo-desconectado.svg").write_text(svg_wordmark(t, False), encoding="utf-8")
    (IMG / "logo-conectado.svg").write_text(svg_wordmark(t, True), encoding="utf-8")
    vieja = IMG / "letras-laz.txt"
    if vieja.exists():
        vieja.unlink()
    js = ROOT / "static" / "logo.js"
    texto = js.read_text(encoding="utf-8")
    for clave, nombre in (("letras", "LETRAS"), ("o1", "O1_TRAZO"), ("rojo", "ROJO_TRAZO"), ("verde", "VERDE_TRAZO")):
        texto = re.sub(rf'var {nombre} = ".*?";', lambda _m, v=t[clave], n=nombre: f'var {n} = "{v}";', texto, flags=re.S)
    js.write_text(texto, encoding="utf-8")
    nar, roj, ver = t["icono_naranja"], t["icono_rojo"], t["icono_verde"]
    (IMG / "infinito-naranja.svg").write_text(svg_icono(nar, NARANJA), encoding="utf-8")
    (IMG / "infinito-rojo.svg").write_text(svg_icono(roj, ROJO_BANDEJA), encoding="utf-8")
    (IMG / "infinito-verde.svg").write_text(svg_icono(ver, VERDE_BANDEJA), encoding="utf-8")
    (IMG / "icono-app.svg").write_text(svg_icono(nar, NARANJA, "#000000", 0.1), encoding="utf-8")
    for nombre, s in (("icono-192.png", 192), ("icono-512.png", 512), ("apple-touch-icon.png", 180)):
        pintar(encajar(nar, s, 0.1), s, NARANJA, fondo=(0, 0, 0, 255)).save(IMG / nombre)
    guardar_ico(nar, NARANJA, ROOT / "static" / "lazoo.ico")
    guardar_ico(roj, ROJO_BANDEJA, ROOT / "static" / "lazoo-rojo.ico")
    guardar_ico(ver, VERDE_BANDEJA, ROOT / "static" / "lazoo-verde.ico")
    # Android: mipmaps clásicos (fondo negro redondeado) + icono adaptable + notificación.
    for carpeta, s in (("mipmap-mdpi", 48), ("mipmap-hdpi", 72), ("mipmap-xhdpi", 96), ("mipmap-xxhdpi", 144), ("mipmap-xxxhdpi", 192)):
        (RES / carpeta).mkdir(parents=True, exist_ok=True)
        base = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        masc = Image.new("L", (s * 4, s * 4), 0)
        ImageDraw.Draw(masc).rounded_rectangle((0, 0, s * 4 - 1, s * 4 - 1), radius=s * 4 * 0.22, fill=255)
        base.paste((0, 0, 0, 255), (0, 0), masc.resize((s, s), Image.LANCZOS))
        base.alpha_composite(pintar(encajar(nar, s, 0.12), s, NARANJA))
        base.save(RES / carpeta / "ic_launcher.png")
    (RES / "drawable").mkdir(exist_ok=True)
    # Zona segura del icono adaptable: 66 de 108 dp.
    (RES / "drawable" / "ic_launcher_foreground.xml").write_text(vector_android(nar, NARANJA, 108, 108, 0.6), encoding="utf-8")
    (RES / "drawable" / "ic_notif.xml").write_text(vector_android(nar, "#FFFFFFFF", 24, 24, 0.92), encoding="utf-8")
    print("listo:", IMG)


if __name__ == "__main__":
    if "--trazar" in sys.argv:
        trazar()
    generar()
