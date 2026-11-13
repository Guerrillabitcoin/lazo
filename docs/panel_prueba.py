"""Pinta el Panel (static/mesa.html) con datos de mentira, sin LaZoo ni red (0.71).

Uso: python3 docs/panel_prueba.py RAIZ DESTINO
Copia static/ de RAIZ a DESTINO, cambia fetch() por respuestas fijas (dos PCs, un móvil y un PC
aprobados) y, al terminar de pintar, apunta en <body data-medidas> el tamaño de cada línea de
tarjeta. test_v071.py lo abre con Chrome a 460 px y a 1400 px y comprueba que ninguna línea
sale letra a letra. Los nombres, IPs y huellas son inventados.
"""

import json, shutil, sys
from pathlib import Path
RAIZ = Path(sys.argv[1]); DEST = Path(sys.argv[2])
DATOS = {
  "/api/pcapc": {"permitir": True, "tecla": "Ctrl+Alt+L", "emergencia": "Ctrl+Alt+Esc", "portapapeles": True,
    "puede_mandar": True, "motivo": "", "tecla_ok": True, "recibiendo": "", "pin": "123456",
    "direcciones": ["192.168.1.144:8787"], "falta": "", "arreglable": False,
    "diagnostico": "Que otro PC controle este: xtest (Xorg con XTest (sin permisos extra).) · Controlar otro desde este: x11 (Xorg: XGrabKey y XGrabKeyboard/XGrabPointer (sin permisos extra).)",
    "control": {"estado": "libre", "nombre": "", "id": "", "mensaje": ""}, "emparejar": {"estado": "nada"},
    "pcs": [{"id": "a1b2c3d4e5f6a7b8", "nombre": "Portátil del salón", "apodo": "Portátil del salón", "nombre_pc": "DESKTOP-7Q2K9LM",
             "host": "192.168.1.144", "puerto": 8787, "fp": "23DF-2756-7B7A-91C2-0D4E-55AB", "fecha": "2026-11-13 01:20", "ultimo": True},
            {"id": "b1b2c3d4e5f6a7b8", "nombre": "PC-ESTUDIO-CON-UN-NOMBRE-MUY-LARGO-DE-VERDAD", "apodo": "", "nombre_pc": "PC-ESTUDIO-CON-UN-NOMBRE-MUY-LARGO-DE-VERDAD",
             "host": "192.168.1.25", "puerto": 8787, "fp": "AB12-CD34-EF56-7890-1122-3344", "fecha": "2026-11-12 22:05", "ultimo": False}]},
  "/api/dispositivos": {"devices": [
     {"id": "c1c2c3c4c5c6c7c8", "short": "c1c2", "state": "aprobado", "label": "Móvil de casa", "tipo": "Android · App LaZoo", "apodo": "Móvil de casa",
      "ip": "192.168.1.33", "left": 0, "ago": 5, "fp": "9F3A-77B1-0C2D-E4F5-6A7B-8C9D", "fecha": "2026-11-10", "recordado": True, "duplicado": False},
     {"id": "d1d2d3d4d5d6d7d8", "short": "d1d2", "state": "pendiente", "label": "PC · DESKTOP-7Q2K9LM", "tipo": "PC · DESKTOP-7Q2K9LM", "apodo": "",
      "ip": "192.168.1.144", "left": 42, "ago": 1, "fp": "23DF-2756-7B7A-91C2-0D4E-55AB", "fecha": "", "recordado": False, "duplicado": False}], "me": ""},
}
STUB = """<script>
window.__datos = %s;
window.fetch = async (url) => {
  const u = String(url).split("?")[0];
  const d = Object.prototype.hasOwnProperty.call(window.__datos, u) ? window.__datos[u] : {};
  return new Response(JSON.stringify(d), { status: 200, headers: { "Content-Type": "application/json" } });
};
window.addEventListener("load", () => setTimeout(() => {
  const malos = [], medidas = [];
  for (const el of document.querySelectorAll("#pc-lista .t-nombre, #pc-lista .t-linea, #devs .t-nombre, #devs .t-linea, #pc-lista button, #devs button")) {
    const r = el.getBoundingClientRect(), fs = parseFloat(getComputedStyle(el).fontSize) || 14;
    const lineas = Math.round(r.height / (fs * 1.25));
    medidas.push([el.textContent.slice(0, 30), Math.round(r.width), Math.round(r.height)]);
    if (el.textContent.length > 3 && r.width < 40) malos.push(["estrecho", el.textContent, r.width]);
    if (el.tagName !== "BUTTON" && r.height > fs * 2.2) malos.push(["varias lineas", el.textContent, r.height]);
  }
  const n = document.querySelectorAll("#pc-lista li.tarjeta").length + document.querySelectorAll("#devs li.tarjeta").length;
  document.body.setAttribute("data-medidas", JSON.stringify({ tarjetas: n, malos, medidas }));
}, 800));
</script>"""
DEST.mkdir(parents=True, exist_ok=True)
html = (RAIZ / "static" / "mesa.html").read_text(encoding="utf-8")
html = html.replace("<head>", "<head>" + STUB % json.dumps(DATOS), 1)
(DEST / "mesa.html").write_text(html, encoding="utf-8")
for f in ("logo.js",):
    if (RAIZ / "static" / f).exists(): shutil.copy(RAIZ / "static" / f, DEST / f)
if (RAIZ / "static" / "img").exists(): shutil.copytree(RAIZ / "static" / "img", DEST / "img", dirs_exist_ok=True)
