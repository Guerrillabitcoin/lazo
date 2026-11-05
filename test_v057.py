"""LaZoo 0.57: la conexión del móvil tras aceptar, expulsar, olvidar y reiniciar.

    python3 test_v057.py

Causa real (vista en el registro del .exe del usuario, %LOCALAPPDATA%\\LaZoo\\lazoo.log):
`control._dpapi` (portapapeles) cambiaba las firmas de `ctypes.windll.crypt32`, que es global,
y `recordar._dpapi` lanzaba `ctypes.ArgumentError` al guardar la clave justo después de aceptar.
Como no es OSError, salía de `persist_devices()` dentro de /api/pair/wait: el PC cortaba la
conexión sin responder y el móvil nunca recibía la clave (con «Recordar dispositivos», que va
activo de serie). Arreglo: DPAPI con crypt32 propio, `persist_devices` nunca lanza, la respuesta
sale antes de guardar y /api/pair/* siempre contesta.

La parte con navegador real (Chrome sin ventana + Playwright) se salta si no están.
"""
from __future__ import annotations

import asyncio
import ctypes
import importlib.util
import json
import os
import socket
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
import sys  # noqa: E402

sys.path.insert(0, str(ROOT))

import aprobacion  # noqa: E402
import lazo  # noqa: E402
import recordar  # noqa: E402
from test_v054 import Phone  # noqa: E402
from test_v056 import Base, CHROME  # noqa: E402

JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CONTROL = (ROOT / "control.py").read_text(encoding="utf-8")
RECORDAR = (ROOT / "recordar.py").read_text(encoding="utf-8")


class Servidor(Base):
    def setUp(self):
        super().setUp()
        self.server = lazo.LazoServer(("127.0.0.1", 0), lazo.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        lazo.Handler._loopback = lambda self: False
        lazo.KICKED.clear()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        lazo.KICKED.clear()
        super().tearDown()

    def test_fallo_al_guardar_no_impide_la_entrega(self):
        """El fallo real de 0.54-0.56: guardar lanzaba ctypes.ArgumentError dentro de /api/pair/wait."""
        def roto(*_a, **_k):
            raise ctypes.ArgumentError("argument 1: TypeError: expected LP_DATA_BLOB instance instead of pointer to BLOB")
        lazo.STORE.save = roto
        phone = Phone(self.port)
        self.assertEqual(phone.pair("pin", lazo.PAIRING.pin)[1]["state"], "pendiente")
        lazo.APPROVALS.decide(phone.who, True)
        status, data = phone.wait()
        self.assertEqual(status, 200)
        self.assertEqual(phone.key_from(data["box"]), lazo.PAIRING.key_text())
        for _ in range(40):  # se guarda justo después de responder
            if any("no pude guardar" in line for line in lazo.CONN_LOG):
                break
            time.sleep(0.05)
        self.assertTrue(any("no pude guardar" in line for line in lazo.CONN_LOG))

    def test_expulsado_recibe_401_kicked_y_puede_volver(self):
        phone = Phone(self.port)
        phone.pair("pin", lazo.PAIRING.pin)
        lazo.APPROVALS.decide(phone.who, True)
        phone.wait()
        self.assertTrue(lazo.kick_device(phone.who))
        status, data = phone.wait()
        self.assertNotIn("box", data)
        again = Phone(self.port, who=phone.who)
        self.assertEqual(again.pair("pin", lazo.PAIRING.pin)[1]["state"], "pendiente")
        self.assertNotIn(phone.who, lazo.KICKED)
        lazo.APPROVALS.decide(phone.who, True)
        self.assertEqual(again.wait()[0], 200)

    def test_tiempo_dice_version_y_protocolo(self):
        from test_v054 import _req
        data = json.loads(_req(self.port, "GET", "/api/time")[1])
        self.assertEqual((data["version"], data["proto"]), (lazo.VERSION, lazo.PROTO))

    def test_diag_sin_secretos(self):
        phone = Phone(self.port)
        phone.pair("pin", lazo.PAIRING.pin)
        lazo.APPROVALS.decide(phone.who, True)
        phone.wait()
        text = lazo.conn_diag()
        self.assertIn("aceptado", text)
        for secreto in (lazo.PAIRING.pin, lazo.PAIRING.key_text(), lazo.PAIRING.token_text(), phone.proof):
            self.assertNotIn(secreto, text)


class Fuente(unittest.TestCase):
    def test_dpapi_sin_windll_compartido(self):
        self.assertNotIn("crypt32, kernel32 = ctypes.windll", RECORDAR)
        self.assertIn('ctypes.WinDLL("crypt32"', RECORDAR)
        self.assertNotIn("crypt32.CryptProtectData.argtypes", CONTROL)

    def test_cliente(self):
        self.assertIn("forgetKey();", JS)
        self.assertIn("connDiagText", JS)
        self.assertIn('const PAGE_VERSION = "0.60"', JS)

    def test_version(self):
        self.assertEqual(lazo.VERSION, "0.60")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.60")
        apk = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:versionCode="60"', apk)
        self.assertIn("# LaZoo 0.60", (ROOT / "README.md").read_text(encoding="utf-8"))


def _ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        s.close()


@unittest.skipUnless(CHROME and importlib.util.find_spec("playwright"), "sin Chrome/Playwright")
class Navegador(Base):
    """El JS real en Chrome sin ventana: todo el ciclo de vida de la conexión."""

    def setUp(self):
        super().setUp()
        aprobacion.add_allowed("0.0.0.0/0")
        self.ip = _ip()
        if not self.ip or self.ip.startswith("127."):
            self.skipTest("sin IP de red")
        lazo.PAIRING.pin = "123456"
        lazo.KICKED.clear()
        if lazo.persist_devices not in lazo.APPROVALS.on_change:
            lazo.APPROVALS.on_change.append(lazo.persist_devices)
        self.port = 0
        self._serve()

    def _serve(self):
        self.server = lazo.LazoServer(("0.0.0.0", self.port), lazo.Handler)
        self.port = self.server.server_address[1]
        lazo.PORT = self.port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _restart(self):
        """Como cerrar y abrir el .exe: estado en memoria nuevo, mismo disco y puerto."""
        self.server.shutdown()
        self.server.server_close()
        lazo.APPROVALS.devices.clear()
        lazo.KICKED.clear()
        lazo.PAIRING.rekey()
        lazo.load_remembered()
        self._serve()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        lazo.KICKED.clear()
        super().tearDown()

    def test_ciclo_completo(self):
        asyncio.run(self._ciclo())

    async def _estado(self, pg):
        return await pg.evaluate("({app: !document.querySelector('#app').hidden, pin: !document.querySelector('#pin').hidden,"
                                 " wait: !document.querySelector('#wait').hidden, link: document.querySelector('#status').dataset.link,"
                                 " msg: (document.querySelector('#pin-msg')||{}).textContent || '', key: localStorage.getItem('lazo-key')})")

    async def _hasta(self, pg, cond, secs=12, aprobar=None):
        t0 = time.time()
        while time.time() - t0 < secs:
            if aprobar is not None:
                for d in [d for d in lazo.APPROVALS.listing() if d["state"] == "pendiente"]:
                    lazo.APPROVALS.decide(d["id"], aprobar)
            st = await self._estado(pg)
            if cond(st):
                return st
            await asyncio.sleep(0.3)
        self.fail(f"no llegó al estado esperado: {await self._estado(pg)}")

    async def _pin(self, pg, aprobar=True):
        await pg.goto(f"http://{self.ip}:{self.port}/")
        await self._hasta(pg, lambda s: s["pin"])
        await pg.fill("#pin-input", "123456")
        await pg.click("#pin-go")
        return await self._hasta(pg, (lambda s: s["app"] and s["link"] == "on") if aprobar else (lambda s: s["wait"]), aprobar=aprobar)

    async def _sin_bucle(self, pg, peticiones, secs=6):
        antes = len(peticiones)
        await asyncio.sleep(secs)
        self.assertLessEqual(len(peticiones) - antes, 3, f"bucle de peticiones con clave vieja: {peticiones[antes:]}")

    async def _ciclo(self):
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            ctx = await b.new_context(viewport={"width": 400, "height": 800})
            pg = await ctx.new_page()
            errores, peticiones = [], []
            pg.on("pageerror", lambda e: errores.append(str(e)))
            pg.on("request", lambda r: peticiones.append(r.url) if "/api/" in r.url else None)

            # (1) QR: aprobar, quedarse, recargar y reconectar.
            await pg.goto(lazo.PAIRING.phone_url("http", self.ip, self.port))
            st = await self._hasta(pg, lambda s: s["app"] and s["link"] == "on", aprobar=True)
            self.assertEqual(st["key"], lazo.PAIRING.key_text())
            await asyncio.sleep(3)
            self.assertTrue((await self._estado(pg))["app"], "se salió tras entrar")
            await pg.reload()
            await self._hasta(pg, lambda s: s["app"] and s["link"] == "on")
            self.assertTrue((lazo.STORE.folder / recordar.KEY_FILE).exists(), "no guardó la clave recordada")

            # (2) Reinicio con «Recordar» activo: reconecta solo, sin aviso.
            self._restart()
            await pg.reload()
            await self._hasta(pg, lambda s: s["app"] and s["link"] == "on")
            self.assertFalse([d for d in lazo.APPROVALS.listing() if d["state"] == "pendiente"])

            # (3) Expulsar: vuelve al emparejamiento, sin bucle, y puede volver aprobando otra vez.
            who = await pg.evaluate("localStorage.getItem('lazo-id')")
            lazo.kick_device(who)
            st = await self._hasta(pg, lambda s: s["pin"] and not s["app"])
            self.assertIsNone(st["key"])
            self.assertIn("expulsó", st["msg"])
            await self._sin_bucle(pg, peticiones)
            await self._pin(pg)

            # (4) Olvidar todos: igual, con la clave nueva.
            lazo.forget_all()
            st = await self._hasta(pg, lambda s: s["pin"] and not s["app"])
            self.assertIsNone(st["key"])
            await self._sin_bucle(pg, peticiones)
            await self._pin(pg)

            # (5) Reinicio con «Recordar» desactivado: pide emparejar, sin bucle.
            lazo.set_remember(False)
            self._restart()
            await pg.reload()
            st = await self._hasta(pg, lambda s: s["pin"])
            self.assertIsNone(st["key"])
            await self._sin_bucle(pg, peticiones)

            # (6) Rechazado.
            await self._pin(pg, aprobar=False)
            for _ in range(40):
                for d in [d for d in lazo.APPROVALS.listing() if d["state"] == "pendiente"]:
                    lazo.APPROVALS.decide(d["id"], False)
                if await pg.evaluate("document.querySelector('#wait').dataset.state") == "rechazado":
                    break
                await asyncio.sleep(0.3)
            self.assertEqual(await pg.evaluate("document.querySelector('#wait').dataset.state"), "rechazado")
            diag = await pg.evaluate("connDiagText()")
            self.assertIn("página 0.60", diag)
            self.assertIn("PC 0.60", diag)
            self.assertNotIn("123456", diag)

            # (7) Dos móviles a la vez.
            lazo.APPROVALS.devices.clear()
            m1 = await (await b.new_context()).new_page()
            m2 = await (await b.new_context()).new_page()
            for m in (m1, m2):
                m.on("pageerror", lambda e: errores.append(str(e)))
                await self._pin(m)
            await asyncio.sleep(2)
            self.assertTrue((await self._estado(m1))["app"] and (await self._estado(m2))["app"])
            self.assertEqual(lazo.PAIRING.phone_count(), 2)
            await b.close()
            self.assertEqual(errores, [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
