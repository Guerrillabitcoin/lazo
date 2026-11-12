"""LaZoo 0.56: emparejamiento que no se cae justo después de aceptar, y logotipo fiel al original.

    python3 test_v056.py

Fallo de 0.54/0.55 («aceptas en el PC, hace un amago de entrar y vuelve al PIN»): el móvil
preguntaba /api/pair/wait cada 1,5 s sin esperar a la respuesta anterior. Con Wi-Fi lenta dos
consultas se cruzaban: la primera recibía la clave y cerraba la sesión; la segunda recibía 401 y
el móvil volvía al PIN. Además, los ajustes del ratón salían sin clave a los 1,5 s de cargar
(401) y también mandaban al PIN. Arreglo: una consulta a la vez, la entrega se puede repetir
30 s, un 401 viejo no echa al móvil y los ajustes se mandan al entrar.

La prueba con navegador real (Chrome sin ventana + Playwright) se salta si no están.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import aprobacion  # noqa: E402
import lazo  # noqa: E402
import protocol  # noqa: E402
import recordar  # noqa: E402
from test_v054 import Phone  # noqa: E402

JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
LOGO = (ROOT / "static" / "logo.js").read_text(encoding="utf-8")
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
MESA = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
APK = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
JAVA = (ROOT / "android" / "src" / "net" / "lazoo" / "app" / "MainActivity.java").read_text(encoding="utf-8")
CHROME = next((p for p in ("/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser") if os.path.exists(p)), None)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = (lazo.Handler._loopback, lazo.APPROVALS.auto, lazo.maybe_open_mesa, lazo.STORE, list(lazo.APPROVALS.on_change), lazo.PORT)
        lazo.APPROVALS.auto = False
        lazo.maybe_open_mesa = lambda: None
        lazo.STORE = recordar.Store(self.tmp)
        lazo.PAIRING.rekey()
        lazo.APPROVALS.devices.clear()

    def tearDown(self):
        lazo.Handler._loopback, lazo.APPROVALS.auto, lazo.maybe_open_mesa, lazo.STORE, hooks, lazo.PORT = self.saved
        lazo.APPROVALS.on_change[:] = hooks
        lazo.APPROVALS.devices.clear()
        lazo.PAIRING.rekey()
        shutil.rmtree(self.tmp, ignore_errors=True)


class Servidor(Base):
    def setUp(self):
        super().setUp()
        self.server = lazo.LazoServer(("127.0.0.1", 0), lazo.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        lazo.Handler._loopback = lambda self: False

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def _flujo(self, mode):
        phone = Phone(self.port)
        secret = lazo.PAIRING.token_text() if mode == "qr" else lazo.PAIRING.pin
        status, claim = phone.pair(mode, secret)
        self.assertEqual((status, claim["state"]), (200, "pendiente"))
        self.assertTrue(lazo.APPROVALS.decide(phone.who, True))
        # Dos consultas cruzadas tras aceptar (lo que pasaba con Wi-Fi lenta): las dos valen.
        results = []
        hilos = [threading.Thread(target=lambda: results.append(phone.wait())) for _ in range(3)]
        [h.start() for h in hilos]
        [h.join() for h in hilos]
        self.assertEqual([r[0] for r in results], [200, 200, 200])
        keys = {phone.key_from(r[1]["box"]) for r in results}
        self.assertEqual(keys, {lazo.PAIRING.device_key_text(phone.who)})
        return phone

    def test_pin_consultas_cruzadas(self):
        self._flujo("pin")

    def test_qr_consultas_cruzadas_y_ficha_nueva_una_vez(self):
        token = lazo.PAIRING.token_text()
        self._flujo("qr")
        nueva = lazo.PAIRING.token_text()
        self.assertNotEqual(token, nueva, "el QR usado ya no vale")
        self.assertEqual(nueva, lazo.PAIRING.token_text(), "repetir la entrega no cambia la ficha otra vez")

    def test_entrega_caduca(self):
        phone = self._flujo("pin")
        lazo.PAIRING.sessions[phone.sid]["at"] -= protocol.PAIR_SECONDS
        self.assertEqual(phone.wait()[0], 401)

    def test_sin_prueba_no_hay_entrega(self):
        phone = self._flujo("pin")
        other = Phone(self.port)
        status, _ = other.post("/api/pair/wait", {"sid": phone.sid, "proof": "0" * 64})
        self.assertEqual(status, 401)

    def test_expulsado_no_recibe_otra_vez(self):
        phone = self._flujo("pin")
        lazo.APPROVALS.kick(phone.who)
        status, data = phone.wait()
        self.assertNotIn("box", data)


class Cliente(unittest.TestCase):
    def test_una_consulta_a_la_vez(self):
        self.assertIn("pairInFlight", JS)
        self.assertIn("approvalBusy", JS)
        self.assertRegex(JS, r"if \(pairing !== mine\)")

    def test_401_viejo_no_echa(self):
        self.assertIn("const sentWith = authKey;", JS)
        self.assertIn("if (sentWith && sentWith === authKey && !pairing) {", JS)

    def test_ajustes_al_entrar(self):
        for fn in ("pushPred", "pushIner", "pushCont", "pushSmooth"):
            self.assertNotRegex(JS, rf"setTimeout\({fn}, 1500\)", fn)
        self.assertIn("pushMousePrefs();", JS)
        self.assertIn("PREF_PUSH.push(", JS)

    def test_qr_viejo_no_tira_la_clave(self):
        self.assertIn("if (authKey && (await approvalState()) === \"aprobado\")", JS)
        self.assertIn("url.indexOf('#')", JAVA)

    def test_sin_crypto_subtle(self):
        for src in (JS, (ROOT / "static" / "seal.js").read_text(encoding="utf-8"), LOGO):
            self.assertNotIn("crypto.subtle", src)
            self.assertNotIn("randomUUID", src)


@unittest.skipUnless(CHROME and importlib.util.find_spec("playwright"), "sin Chrome/Playwright")
class Navegador(Base):
    """El JS real de static/ en Chrome sin ventana, con la red lenta y desigual."""

    def setUp(self):
        super().setUp()
        import socket

        aprobacion.add_allowed("0.0.0.0/0")
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            self.ip = s.getsockname()[0]
        except OSError:
            self.ip = ""
        finally:
            s.close()
        if not self.ip or self.ip.startswith("127."):
            self.skipTest("sin IP de red")
        lazo.PAIRING.pin = "123456"
        self.server = lazo.LazoServer(("0.0.0.0", 0), lazo.Handler)
        self.port = self.server.server_address[1]
        lazo.PORT = self.port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def _run(self, mode):
        import asyncio
        import random

        from playwright.async_api import async_playwright

        async def main():
            async with async_playwright() as p:
                b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
                pg = await (await b.new_context(viewport={"width": 400, "height": 800})).new_page()
                errores = []
                pg.on("pageerror", lambda e: errores.append(str(e)))

                cuenta = [0]

                async def lenta(route):
                    # Red lenta y desigual: una de cada dos consultas de espera tarda 2,6 s
                    # (más que el intervalo de 1,5 s), así que con 0.55 se cruzaban seguro.
                    if "/api/pair/wait" in route.request.url:
                        cuenta[0] += 1
                        await asyncio.sleep(2.6 if cuenta[0] % 2 else 0.2)
                    else:
                        await asyncio.sleep(random.random())
                    try:
                        await route.continue_()
                    except Exception:  # la página ya canceló esa petición
                        pass

                await pg.route("**/api/**", lenta)
                if mode == "qr":
                    await pg.goto(lazo.PAIRING.phone_url("http", self.ip, self.port))
                else:
                    await pg.goto(f"http://{self.ip}:{self.port}/")
                    await pg.fill("#pin-input", "123456")
                    await pg.click("#pin-go")
                estado = "[app.hidden, document.querySelector('#pin').hidden, document.querySelector('#link-label').textContent]"
                t0, aceptado, vistos = time.time(), False, []
                while time.time() - t0 < 26:
                    await asyncio.sleep(0.4)
                    if not aceptado and time.time() - t0 > 9:
                        for d in [d for d in lazo.APPROVALS.listing() if d["state"] == "pendiente"]:
                            aceptado = lazo.APPROVALS.decide(d["id"], True)
                    if aceptado:
                        vistos.append(await pg.evaluate(estado))
                clave = await pg.evaluate("localStorage.getItem('lazo-key')")
                await pg.unroute("**/api/**")
                await pg.reload()
                await asyncio.sleep(5)
                tras_recargar = await pg.evaluate(estado)
                await b.close()
                return aceptado, vistos, clave, tras_recargar, errores

        return asyncio.run(main())

    def _check(self, mode):
        aceptado, vistos, clave, recarga, errores = self._run(mode)
        self.assertTrue(aceptado, "el móvil no llegó a pedir permiso")
        self.assertEqual(errores, [])
        dentro = [i for i, v in enumerate(vistos) if v[0] is False]
        self.assertTrue(dentro, "no entró tras aceptar")
        for v in vistos[dentro[0]:]:
            self.assertFalse(v[0], f"salió de la app tras entrar: {v}")
            self.assertTrue(v[1], f"volvió al PIN tras entrar: {v}")
        aprobados = {d["id"] for d in lazo.APPROVALS.listing() if d["state"] == "aprobado"}
        self.assertIn(clave, {lazo.PAIRING.device_key_text(w) for w in aprobados}, "0.62: la clave de ese móvil")
        self.assertFalse(recarga[0], f"tras recargar no se reconecta solo: {recarga}")

    def test_pin_red_lenta(self):
        self._check("pin")

    def test_qr_red_lenta(self):
        self._check("qr")


class Logo(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "diseno"))
        import logos

        self.logos = logos
        self.t = json.loads((ROOT / "diseno" / "trazos.json").read_text(encoding="utf-8"))

    def test_logo_js_usa_los_trazos(self):
        for clave, nombre in (("letras", "LETRAS"), ("o1", "O1_TRAZO"), ("rojo", "ROJO_TRAZO"), ("verde", "VERDE_TRAZO")):
            self.assertIn(f'var {nombre} = "{self.t[clave]}";', LOGO)
        self.assertNotIn("Poppins", LOGO)

    def test_a_y_z_separadas(self):
        cajas = sorted((min(x for x, _ in s), max(x for x, _ in s)) for s in self.logos.subcaminos(self.t["letras"]))
        exteriores = [c for c in cajas if c[1] - c[0] > 60]  # L, a, Z (el hueco de la «a» es más estrecho)
        self.assertEqual(len(exteriores), 3)
        (_, a_fin), (z_ini, _) = exteriores[1], exteriores[2]
        self.assertGreater(z_ini - a_fin, 8, "la «a» y la «Z» no deben tocarse")

    def test_proporciones_del_original(self):
        x0, y0, x1, y1 = self.logos.caja(self.t["letras"])
        self.assertAlmostEqual(x0, 58, delta=1.5)
        self.assertAlmostEqual(x1, 382.5, delta=1.5)
        self.assertAlmostEqual(y1 - y0, 149, delta=2)
        for clave, (cx, w) in (("o1", (439.5, 112)), ("rojo", (556, 112)), ("verde", (505, 238))):
            a, _, b, _ = self.logos.caja(self.t[clave])
            self.assertAlmostEqual((a + b) / 2, cx, delta=2, msg=clave)
            self.assertAlmostEqual(b - a, w, delta=3, msg=clave)

    def test_iconos_con_un_hueco_por_lobulo(self):
        for clave in ("icono_naranja", "icono_rojo", "icono_verde", "verde"):
            self.assertEqual(len(self.logos.subcaminos(self.t[clave])), 3, clave)

    def test_reduced_motion_y_espera(self):
        self.assertIn("prefers-reduced-motion", LOGO)
        self.assertIn("lz-anillo", LOGO)
        self.assertIn(".lz-anillo", MESA)


class Version(unittest.TestCase):
    def test_version(self):
        self.assertEqual(lazo.VERSION, "0.69")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.69")
        self.assertIn("<title>LaZoo 0.69</title>", HTML)
        self.assertIn("/logo.js?v=0.69", MESA)
        self.assertIn('android:versionName="3"', APK)
        self.assertIn('android:versionCode="66"', APK)
        self.assertIn("# LaZoo 0.69", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("## Estado (0.61)", (ROOT / "AGENTS.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
