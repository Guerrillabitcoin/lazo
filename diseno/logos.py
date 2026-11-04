"""Genera la identidad visual de LaZoo 0.55 (herramienta de desarrollo, no se empaqueta).

Recrea en vector las imágenes de static/img/original/:
- wordmark «LaZoo»: letras L, a, Z de Poppins Bold (licencia OFL) convertidas a trazos,
  y las dos «o» como anillos que se transforman en el infinito (misma geometría que static/logo.js);
- el infinito (rojo, verde, naranja) en SVG, PNG, .ico multi-tamaño y mipmaps de Android.

Uso (necesita fontTools y Pillow): python diseno/logos.py
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "static" / "img"
RES = ROOT / "android" / "res"


def fuente() -> str:
    """Poppins Bold: ruta en LAZOO_FUENTE o la que encuentre fontconfig (fc-match)."""
    import os
    import subprocess

    ruta = os.environ.get("LAZOO_FUENTE")
    if not ruta:
        ruta = subprocess.run(["fc-match", "-f", "%{file}", "Poppins:bold"], capture_output=True, text=True).stdout
    if "Poppins-Bold" not in ruta:
        raise SystemExit("Falta Poppins Bold: instálala o indica su ruta en LAZOO_FUENTE")
    return ruta

ROJO = "#e8101c"
VERDE = "#1a8f3a"          # verde del wordmark conectado
VERDE_BANDEJA = "#5abf10"  # verde lima de la imagen de la bandeja (se ve bien a 16 px)
NARANJA = "#ff8040"        # infinito de la APK y del móvil (marca: #e07a3d)
BLANCO = "#ffffff"

# Geometría (unidades del wordmark original, 1280x720). La misma que static/logo.js.
VIEW = (50, 258, 584, 166)        # x, y, ancho, alto del viewBox del wordmark
ANILLO_R, TRAZO = 41.5, 27.5      # radio del anillo y grosor de trazo
O1, O2, CY = 439.5, 556.0, 358.5  # centros de las dos «o»
INF_C, INF_A, INF_SY = 505.5, 105.0, 1.25  # centro, semiancho y estiramiento vertical del infinito
N = 48                            # puntos por bucle


def lobulo(t: float) -> tuple[float, float]:
    """Lemniscata de Bernoulli estirada en vertical (centro en 0,0)."""
    d = 1 + math.sin(t) ** 2
    return INF_A * math.cos(t) / d, INF_SY * INF_A * math.sin(t) * math.cos(t) / d


def bucles(p: float) -> list[list[tuple[float, float]]]:
    """p=0: dos anillos («oo»); p=1: infinito. Mismo número de puntos en ambos."""
    out = []
    for lado, (cx, t0) in enumerate(((O1, math.pi / 2), (O2, -math.pi / 2))):
        pts = []
        for i in range(N):
            t = t0 + math.pi * i / N
            th = math.pi - 2 * t if lado == 0 else 2 * t  # mismo sentido que el lóbulo
            ax, ay = cx + ANILLO_R * math.cos(th), CY + ANILLO_R * math.sin(th)
            lx, ly = lobulo(t)
            bx, by = INF_C + lx, CY + ly
            pts.append((ax + (bx - ax) * p, ay + (by - ay) * p))
        out.append(pts)
    return out


def d_de(pts, dx=0.0, dy=0.0, k=1.0) -> str:
    return "M" + "L".join(f"{(x + dx) * k:.2f} {(y + dy) * k:.2f}" for x, y in pts) + "Z"


def letras() -> str:
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont

    f = TTFont(fuente())
    gs, cmap = f.getGlyphSet(), f.getBestCmap()
    cap = f["OS/2"].sCapHeight
    k = 148 / cap
    base = 414.5
    pen = SVGPathPen(gs, ntos=lambda v: f"{v:.1f}")
    for ch, x in (("L", 58), ("a", 162), ("Z", 274)):
        g = gs[cmap[ord(ch)]]
        from fontTools.pens.boundsPen import BoundsPen
        bp = BoundsPen(gs)
        g.draw(bp)
        xmin = bp.bounds[0]
        g.draw(TransformPen(pen, (k, 0, 0, -k, x - xmin * k, base)))
    return pen.getCommands()


def wordmark_svg(conectado: bool, d_letras: str) -> str:
    a, b = bucles(1.0 if conectado else 0.0)
    c1, c2 = (VERDE, VERDE) if conectado else (BLANCO, ROJO)
    x, y, w, h = VIEW
    attrs = f'fill="none" stroke-width="{TRAZO}" stroke-linejoin="round"'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x} {y} {w} {h}" role="img" '
            f'aria-label="LaZoo {"conectado" if conectado else "desconectado"}">'
            f'<path fill="{BLANCO}" d="{d_letras}"/>'
            f'<path {attrs} stroke="{c1}" d="{d_de(a)}"/><path {attrs} stroke="{c2}" d="{d_de(b)}"/></svg>\n')


def infinito_pts(size: float, margen: float = 0.06):
    """Bucles del infinito encajados en un cuadrado de lado `size`."""
    a, b = bucles(1.0)
    ancho = 2 * INF_A + TRAZO
    k = size * (1 - 2 * margen) / ancho
    dx, dy = -INF_C, -CY
    tr = lambda pts: [((x + dx) * k + size / 2, (y + dy) * k + size / 2) for x, y in pts]
    return tr(a), tr(b), TRAZO * k


def infinito_svg(color: str, fondo: str | None = None) -> str:
    a, b, w = infinito_pts(100)
    bg = f'<rect width="100" height="100" rx="22" fill="{fondo}"/>' if fondo else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">{bg}'
            f'<path fill="none" stroke="{color}" stroke-width="{w:.2f}" stroke-linejoin="round" '
            f'd="{d_de(a)}{d_de(b)}"/></svg>\n')


def infinito_png(size: int, color: str, fondo=None, margen=0.06, ss=8) -> Image.Image:
    big = size * ss
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0) if fondo is None else fondo)
    dr = ImageDraw.Draw(im)
    a, b, w = infinito_pts(big, margen)
    r = w / 2
    for pts in (a, b):
        ring = pts + [pts[0]]
        dr.line(ring, fill=color, width=int(round(w)), joint="curve")
        for x, y in ring:
            dr.ellipse((x - r, y - r, x + r, y + r), fill=color)
    return im.resize((size, size), Image.LANCZOS)


def guardar_ico(color: str, ruta: Path) -> None:
    tam = [16, 24, 32, 48, 64, 128, 256]
    # A tamaños pequeños, menos margen para que se vea grande en la bandeja.
    imgs = [infinito_png(s, color, margen=0.02 if s <= 32 else 0.06) for s in tam]
    imgs[-1].save(ruta, format="ICO", sizes=[(s, s) for s in tam], append_images=imgs[:-1])


def vector_android(color: str, ancho_dp: int, lienzo: float, escala: float) -> str:
    """VectorDrawable del infinito centrado en un lienzo de `lienzo` unidades."""
    a, b, w = infinito_pts(lienzo * escala, 0.0)
    off = lienzo * (1 - escala) / 2
    d = d_de(a, off / 1, off / 1) if False else None
    sh = lambda pts: [(x + off, y + off) for x, y in pts]
    d = d_de(sh(a)) + d_de(sh(b))
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            f'<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="{ancho_dp}dp" '
            f'android:height="{ancho_dp}dp" android:viewportWidth="{lienzo}" android:viewportHeight="{lienzo}">\n'
            f'  <path android:strokeColor="{color}" android:strokeWidth="{w:.2f}" android:strokeLineJoin="round" '
            f'android:fillColor="#00000000" android:pathData="{d}"/>\n</vector>\n')


def main() -> None:
    IMG.mkdir(parents=True, exist_ok=True)
    dl = letras()
    (IMG / "logo-desconectado.svg").write_text(wordmark_svg(False, dl), encoding="utf-8")
    (IMG / "logo-conectado.svg").write_text(wordmark_svg(True, dl), encoding="utf-8")
    (IMG / "letras-laz.txt").write_text(dl + "\n", encoding="utf-8")
    import re

    js = ROOT / "static" / "logo.js"
    js.write_text(re.sub(r'var LETRAS = ".*?";', lambda _m: f'var LETRAS = "{dl}";', js.read_text(encoding="utf-8"), flags=re.S), encoding="utf-8")
    for nombre, color in (("naranja", NARANJA), ("rojo", ROJO), ("verde", VERDE_BANDEJA)):
        (IMG / f"infinito-{nombre}.svg").write_text(infinito_svg(color), encoding="utf-8")
    (IMG / "icono-app.svg").write_text(infinito_svg(NARANJA, "#000000"), encoding="utf-8")
    infinito_png(192, NARANJA, fondo=(0, 0, 0, 255), margen=0.1).save(IMG / "icono-192.png")
    infinito_png(512, NARANJA, fondo=(0, 0, 0, 255), margen=0.1).save(IMG / "icono-512.png")
    infinito_png(180, NARANJA, fondo=(0, 0, 0, 255), margen=0.1).save(IMG / "apple-touch-icon.png")
    guardar_ico(NARANJA, ROOT / "static" / "lazoo.ico")
    guardar_ico(ROJO, ROOT / "static" / "lazoo-rojo.ico")
    guardar_ico(VERDE_BANDEJA, ROOT / "static" / "lazoo-verde.ico")
    # Android: mipmaps clásicos (fondo negro redondeado) + icono adaptable + notificación.
    for carpeta, s in (("mipmap-mdpi", 48), ("mipmap-hdpi", 72), ("mipmap-xhdpi", 96), ("mipmap-xxhdpi", 144), ("mipmap-xxxhdpi", 192)):
        (RES / carpeta).mkdir(parents=True, exist_ok=True)
        base = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        mask = Image.new("L", (s * 4, s * 4), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, s * 4 - 1, s * 4 - 1), radius=s * 4 * 0.22, fill=255)
        base.paste((0, 0, 0, 255), (0, 0), mask.resize((s, s), Image.LANCZOS))
        base.alpha_composite(infinito_png(s, NARANJA, margen=0.12))
        base.save(RES / carpeta / "ic_launcher.png")
    viejo = RES / "mipmap" / "ic_launcher.png"
    if viejo.exists():
        viejo.unlink()
        viejo.parent.rmdir()
    (RES / "mipmap-anydpi-v26").mkdir(exist_ok=True)
    (RES / "mipmap-anydpi-v26" / "ic_launcher.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '  <background android:drawable="@color/lazoo_fondo_icono"/>\n  <foreground android:drawable="@drawable/ic_launcher_foreground"/>\n'
        '  <monochrome android:drawable="@drawable/ic_launcher_foreground"/>\n</adaptive-icon>\n', encoding="utf-8")
    (RES / "drawable").mkdir(exist_ok=True)
    # Zona segura del icono adaptable: 66 de 108 dp.
    (RES / "drawable" / "ic_launcher_foreground.xml").write_text(vector_android(NARANJA, 108, 108, 0.6), encoding="utf-8")
    (RES / "drawable" / "ic_notif.xml").write_text(vector_android("#FFFFFFFF", 24, 24, 0.92), encoding="utf-8")
    (RES / "values" / "colors.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n  <color name="lazoo_fondo_icono">#000000</color>\n</resources>\n', encoding="utf-8")
    print("listo:", IMG)


if __name__ == "__main__":
    main()
