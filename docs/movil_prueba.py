"""Pinta la interfaz del móvil (static/index.html + app.js reales) en Chrome sin ventana y mide
desbordes (0.72). Sin PC de verdad detrás: arranca el servidor de LaZoo en este proceso con una
carpeta de datos temporal, empareja por el QR con aprobación automática y simula la App 3
(window.LaZooApp) con tres PCs guardados. Los nombres e IPs son inventados.

Uso: python3 docs/movil_prueba.py RAIZ DESTINO [anchos, p. ej. 360,460]
(test_v072.py lo usa también como módulo: capturar(destino, anchos, ...).)
Deja DESTINO/movil-<ancho>-<pestaña>.png y DESTINO/medidas.json con, por ancho y pestaña:
  fuera: elementos que se salen de su tarjeta o de la pantalla,
  cortados: textos de la cabecera o de las pastillas que no caben,
  lineas_estado: líneas que ocupa el estado de arriba.
Necesita Chrome/Chromium y el paquete playwright.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

CHROME = next((p for p in ("/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser") if os.path.exists(p)), None)
PESTANAS = ["mouse", "bridge", "windows", "youtube", "spotify", "system", "lab", "about"]

PUENTE = """
window.LaZooApp = {
  version: () => "3",
  pcs: () => JSON.stringify([
    {url: location.origin, nombre: "DESKTOP-L7JG8QK", sistema: "Windows", visto: Date.now()},
    {url: "http://192.168.1.25:8787", nombre: "portatil-salon-ubuntu", sistema: "Linux", visto: Date.now() - 60000},
    {url: "http://192.168.1.31:8787", nombre: "PC-ESTUDIO-CON-UN-NOMBRE-LARGO", sistema: "Windows", visto: Date.now() - 3600000}]),
  recordarPc: () => true, olvidarPc: () => true, anadirPc: () => true, open: () => true,
};
"""

MEDIR = """() => {
  const vw = innerWidth, fuera = [], cortados = [];
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const nombre = (el) => (el.id ? '#' + el.id : el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.split(' ')[0] : '')) + ' «' + (el.textContent || el.value || '').trim().slice(0, 30) + '»';
  document.querySelectorAll('.view:not([hidden]) .deck').forEach((deck) => {
    if (!vis(deck)) return;
    const d = deck.getBoundingClientRect();
    deck.querySelectorAll('*').forEach((el) => {
      if (!vis(el) || el.closest('select') || el.closest('[hidden]') || el.closest('details:not([open])')) return;
      if (el.closest('.pad') || getComputedStyle(el).position === 'fixed') return;
      const r = el.getBoundingClientRect();
      if (r.right > d.right + 1 || r.left < d.left - 1 || r.bottom > d.bottom + 1) fuera.push(nombre(el));
    });
  });
  document.querySelectorAll('body *').forEach((el) => {
    if (!vis(el) || el.closest('[hidden]') || el.closest('.dock-scroll') || el.closest('.pc-bar') || el.closest('.confirm')) return;
    const r = el.getBoundingClientRect();
    if (r.right > vw + 1 && getComputedStyle(el).position !== 'fixed') fuera.push('pantalla: ' + nombre(el));
  });
  document.querySelectorAll('#status *, .pc-chip').forEach((el) => {
    if (!vis(el) || el.children.length && !el.matches('.pc-chip')) return;
    if ((el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 2) && getComputedStyle(el).overflow !== 'visible') cortados.push(nombre(el));
  });
  const lab = document.querySelector('#link-label');
  const lh = parseFloat(getComputedStyle(lab).lineHeight) || 15;
  const q = (s) => document.querySelector(s);
  return {fuera: [...new Set(fuera)].slice(0, 40), cortados, lineas_estado: Math.round(lab.getBoundingClientRect().height / lh),
          estado: lab.textContent, dock: [...document.querySelectorAll('#dock button')].map((b) => b.textContent),
          pcs: [...document.querySelectorAll('#pc-bar .pc-chip')].map((b) => b.textContent),
          arriba: [...document.querySelectorAll('#status button')].filter(vis).map((b) => b.textContent),
          pred: q('#aim-pred') && q('#aim-pred').checked, suave: q('#aim-smooth') && q('#aim-smooth').checked,
          continuo: q('#aim-continuo') && q('#aim-continuo').checked,
          ancho_doc: document.documentElement.scrollWidth, vw};
}"""


def _ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def capturar(dest, anchos=(360, 460), pestanas=PESTANAS, almacen: dict | None = None, fotos: bool = True,
             espera_pref: float = 1.5) -> dict:
    """Arranca LaZoo aquí (con lo que ya esté importado), conecta un Chrome con el puente de la
    App y devuelve las medidas por ancho y pestaña. `almacen`: localStorage antes de cargar."""
    import aprobacion
    import control
    import lazo

    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    guardado = (control.pc_name, control.status, lazo.APPROVALS.auto, lazo.maybe_open_mesa, lazo.PORT)
    real_status = control.status

    def status():
        try:
            data = real_status()
        except Exception:  # noqa: BLE001
            data = {"cursor": "normal", "spotify": ""}
        data["platform"] = "Windows"
        data["pc"] = "DESKTOP-L7JG8QK"
        return data

    control.pc_name = lambda: "DESKTOP-L7JG8QK"
    control.status = status
    aprobacion.add_allowed("0.0.0.0/0")
    lazo.APPROVALS.auto = True
    lazo.maybe_open_mesa = lambda: None
    ip = _ip()
    server = lazo.LazoServer(("0.0.0.0", 0), lazo.Handler)
    port = server.server_address[1]
    lazo.PORT = port
    threading.Thread(target=server.serve_forever, daemon=True).start()
    previo = "" if not almacen else "if (!sessionStorage.getItem('lz-puesto')) {" + "".join(
        f"localStorage.setItem({json.dumps(k)}, {json.dumps(v)});" for k, v in almacen.items()) + "sessionStorage.setItem('lz-puesto', '1');}"

    async def main() -> dict:
        from playwright.async_api import async_playwright

        medidas: dict = {}
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            for ancho in anchos:
                alto = 800 if ancho <= 380 else 900
                ctx = await b.new_context(viewport={"width": ancho, "height": alto}, device_scale_factor=1, is_mobile=True, has_touch=True)
                await ctx.add_init_script(PUENTE + previo)
                pg = await ctx.new_page()
                errores: list = []
                pg.on("pageerror", lambda e: errores.append(str(e)))
                await pg.goto(lazo.PAIRING.phone_url("http", ip, port))
                t0 = time.time()
                while time.time() - t0 < 20:
                    for d in [d for d in lazo.APPROVALS.listing() if d["state"] == "pendiente"]:
                        lazo.APPROVALS.decide(d["id"], True)
                    if await pg.evaluate("!document.querySelector('#app').hidden && document.querySelector('#status').dataset.link === 'on'"):
                        break
                    await asyncio.sleep(0.3)
                await asyncio.sleep(espera_pref)
                medidas[ancho] = {}
                for tab in pestanas:
                    await pg.evaluate(f"openCube('{tab}')")
                    if tab == "mouse":
                        await pg.evaluate("(() => { const c = document.querySelector('#diag-on'); if (c && !c.checked) c.click(); })()")
                    await asyncio.sleep(0.6)
                    medidas[ancho][tab] = await pg.evaluate(MEDIR)
                    if not fotos:
                        continue
                    await pg.screenshot(path=str(dest / f"movil-{ancho}-{tab}.png"))
                    # Toda la vista, sin el recorte del scroll (para ver qué hay más abajo).
                    alto_vista = await pg.evaluate("(() => { const v = document.querySelector('.view:not([hidden])'); return v ? v.scrollHeight : 0; })()")
                    if alto_vista > alto - 200:
                        await pg.set_viewport_size({"width": ancho, "height": alto_vista + 260})
                        await asyncio.sleep(0.3)
                        await pg.screenshot(path=str(dest / f"movil-{ancho}-{tab}-entera.png"))
                        await pg.set_viewport_size({"width": ancho, "height": alto})
                medidas[ancho]["errores"] = errores
                await ctx.close()
            await b.close()
        return medidas

    try:
        return asyncio.run(main())
    finally:
        server.shutdown()
        server.server_close()
        control.pc_name, control.status, lazo.APPROVALS.auto, lazo.maybe_open_mesa, lazo.PORT = guardado


if __name__ == "__main__":
    raiz = Path(sys.argv[1]).resolve()
    destino = Path(sys.argv[2]).resolve()
    anchos = [int(x) for x in (sys.argv[3] if len(sys.argv) > 3 else "360,460").split(",")]
    os.environ.setdefault("LAZO_DATOS", tempfile.mkdtemp())
    sys.path.insert(0, str(raiz))
    res = capturar(destino, anchos)
    (destino / "medidas.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False)[:6000])
