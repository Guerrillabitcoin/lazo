"""LaZoo 0.54: emparejamiento sin entregar la clave antes de aprobar, recordar dispositivos,
Panel de LaZoo sin botones de aceptar, YouTube (velocidad, título, ventana) y estado «esperando».

    python3 test_v054.py

Diseño del saludo (ver protocol.py y AGENTS.md):
  hello (X25519 efímero de los dos lados) -> claim (prueba HMAC con la ficha del QR o el PIN)
  -> pendiente -> wait ... -> solo con «aprobado» llega la clave, sellada con derive(hk, "lazo/pair/box/1").
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import aprobacion  # noqa: E402
import bandeja  # noqa: E402
import control  # noqa: E402
import lazo  # noqa: E402
import protocol  # noqa: E402
import recordar  # noqa: E402

HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
MESA = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
SEAL = (ROOT / "static" / "seal.js").read_text(encoding="utf-8")
APK = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
JAVA = (ROOT / "android" / "src" / "net" / "lazoo" / "app" / "MainActivity.java").read_text(encoding="utf-8")


def _req(port, method, path, body=b"", headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body or None, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class Phone:
    """Un móvil de mentira que habla el saludo igual que static/app.js."""

    def __init__(self, port, who=None):
        self.port, self.who = port, who or secrets.token_hex(8)
        self.hk = None

    def post(self, path, data):
        status, raw = _req(self.port, "POST", path, json.dumps(data).encode(),
                           {"Content-Type": "application/json", "User-Agent": "Android Chrome/1"})
        return status, json.loads(raw or b"{}")

    def pair(self, mode, secret_text):
        priv, pub = protocol.x25519_keypair()
        status, hello = self.post("/api/pair/hello", {"id": self.who, "mode": mode, "pub": protocol.b64u(pub)})
        if status != 200:
            return status, hello
        self.transcript = [json.dumps(hello)]
        pc_pub = protocol.unb64u(hello["pub"])
        secret = protocol.unb64u(secret_text) if mode == "qr" else ("pin:" + secret_text).encode()
        self.hk = protocol.handshake_key(secret, mode, self.who, pub, pc_pub, protocol.x25519(priv, pc_pub))
        self.sid, self.proof = hello["sid"], protocol.proof(self.hk, "movil")
        status, claim = self.post("/api/pair/claim", {"sid": self.sid, "proof": self.proof})
        self.transcript.append(json.dumps(claim))
        if status == 200:
            assert claim["proof"] == protocol.proof(self.hk, "pc"), "el PC no probó conocer el secreto"
        return status, claim

    def wait(self):
        status, data = self.post("/api/pair/wait", {"sid": self.sid, "proof": self.proof})
        self.transcript.append(json.dumps(data))
        return status, data

    def key_from(self, box):
        return protocol.open_sealed(protocol.unb64u(box), protocol.derive(self.hk, "lazo/pair/box/1")).decode()


class Server(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.server = lazo.LazoServer(("127.0.0.1", 0), lazo.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.saved = (lazo.Handler._loopback, lazo.APPROVALS.auto, lazo.maybe_open_mesa, lazo.STORE, list(lazo.APPROVALS.on_change))
        lazo.APPROVALS.auto = False
        lazo.maybe_open_mesa = lambda: None
        lazo.STORE = recordar.Store(self.tmp)
        if lazo.persist_devices not in lazo.APPROVALS.on_change:
            lazo.APPROVALS.on_change.append(lazo.persist_devices)
        lazo.Handler._loopback = lambda self: False  # el «móvil» llega como si fuera de la red
        lazo.PAIRING.rekey()
        lazo.APPROVALS.devices.clear()

    def tearDown(self):
        lazo.Handler._loopback, lazo.APPROVALS.auto, lazo.maybe_open_mesa, lazo.STORE, hooks = self.saved
        lazo.APPROVALS.on_change[:] = hooks
        lazo.APPROVALS.devices.clear()
        lazo.PAIRING.rekey()
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def local(self, method, path, body=None):
        real = lazo.Handler._loopback
        lazo.Handler._loopback = self.saved[0]
        try:
            data = json.dumps(body).encode() if body is not None else b""
            return _req(self.port, method, path, data, {"X-Lazo-Local": "1", "Content-Type": "application/json"})
        finally:
            lazo.Handler._loopback = real

    def assert_no_key(self, phone):
        # 0.62: ni la maestra ni la clave de ese móvil salen antes de aprobar.
        for key in (lazo.PAIRING.key_text(), lazo.PAIRING.device_key_text(phone.who)):
            for blob in phone.transcript:
                self.assertNotIn(key, blob, "la clave larga salió antes de aprobar")

    # 1. Ni QR ni PIN entregan la clave antes de aprobar; tras aprobar, sí.
    def test_qr_no_key_until_approved(self):
        url = lazo.PAIRING.phone_url("http", "192.168.1.5", 8787)
        self.assertIn("#p=", url)
        self.assertNotIn(lazo.PAIRING.key_text(), url)
        self.assertNotIn("#k=", url)
        phone = Phone(self.port)
        status, claim = phone.pair("qr", lazo.PAIRING.token_text())
        self.assertEqual(status, 200)
        self.assertEqual(claim["state"], "pendiente")
        status, data = phone.wait()
        self.assertEqual((status, data["state"]), (200, "pendiente"))
        self.assertNotIn("box", data)
        self.assert_no_key(phone)
        self.assertEqual(lazo.PAIRING.phone_count(), 0, "esperando = desconectado")
        token = lazo.PAIRING.token_text()
        self.assertTrue(lazo.APPROVALS.decide(phone.who, True))
        status, data = phone.wait()
        self.assertEqual(data["state"], "aprobado")
        self.assertEqual(phone.key_from(data["box"]), lazo.PAIRING.device_key_text(phone.who), "0.62: su clave, no la maestra")
        self.assertNotIn(lazo.PAIRING.device_key_text(phone.who), json.dumps(data), "la clave va sellada, no en claro")
        self.assertNotEqual(token, lazo.PAIRING.token_text(), "la ficha del QR se renueva tras entregar")
        # 0.56: una consulta repetida justo después recibe lo mismo (antes era 401 y el móvil
        # volvía al PIN); pasado DELIVERED_SECONDS la sesión ya no vale.
        again = phone.wait()
        self.assertEqual(again[0], 200)
        self.assertEqual(phone.key_from(again[1]["box"]), lazo.PAIRING.device_key_text(phone.who))
        self.assertEqual(token == lazo.PAIRING.token_text(), False)
        lazo.PAIRING.sessions[phone.sid]["at"] -= protocol.PAIR_SECONDS
        self.assertEqual(phone.wait()[0], 401, "la sesión del saludo no se reutiliza para siempre")

    def test_pin_no_key_until_approved_and_rejected_never(self):
        phone = Phone(self.port)
        status, claim = phone.pair("pin", lazo.PAIRING.pin)
        self.assertEqual((status, claim["state"]), (200, "pendiente"))
        self.assertNotIn("box", phone.wait()[1])
        self.assert_no_key(phone)
        lazo.APPROVALS.decide(phone.who, False)
        status, data = phone.wait()
        self.assertEqual(data["state"], "rechazado")
        self.assertNotIn("box", data)
        self.assert_no_key(phone)
        other = Phone(self.port)
        other.pair("pin", lazo.PAIRING.pin)
        lazo.APPROVALS.decide(other.who, True)
        self.assertEqual(other.key_from(other.wait()[1]["box"]), lazo.PAIRING.device_key_text(other.who))

    def test_old_login_gives_no_key(self):
        status, raw = _req(self.port, "POST", "/api/login", json.dumps({"pin": lazo.PAIRING.pin}).encode(), {"Content-Type": "application/json"})
        self.assertEqual(status, 410)
        self.assertNotIn(lazo.PAIRING.key_text().encode(), raw)

    def test_wrong_secret_and_growing_lock(self):
        bad = "000000" if lazo.PAIRING.pin != "000000" else "111111"
        for _ in range(protocol.MAX_FAILS):
            status, data = Phone(self.port).pair("pin", bad)
            self.assertIn(status, (401, 429))
        self.assertEqual(Phone(self.port).pair("pin", lazo.PAIRING.pin)[0], 429, "bloqueo tras 6 fallos")
        lazo.PAIRING._locked_until = 0
        self.assertEqual(Phone(self.port).pair("qr", protocol.b64u(secrets.token_bytes(32)))[0], 401)
        lazo.PAIRING._good()

    def test_passive_listener_cannot_open_box(self):
        phone = Phone(self.port)
        phone.pair("pin", lazo.PAIRING.pin)
        lazo.APPROVALS.decide(phone.who, True)
        box = phone.wait()[1]["box"]
        # Quien escucha sabe el PIN (peor caso) pero no el secreto X25519: no abre la caja.
        guess = protocol.handshake_key(("pin:" + lazo.PAIRING.pin).encode(), "pin", phone.who, b"\0" * 32, b"\0" * 32, b"\0" * 32)
        with self.assertRaises(protocol.ProtocolError):
            protocol.open_sealed(protocol.unb64u(box), protocol.derive(guess, "lazo/pair/box/1"))

    # 2. Recordar dispositivos y «Olvidar todos».
    def test_remember_persists_and_forget_clears(self):
        phone = Phone(self.port)
        phone.pair("qr", lazo.PAIRING.token_text())
        lazo.APPROVALS.decide(phone.who, True)
        key = phone.key_from(phone.wait()[1]["box"])
        saved = recordar.Store(self.tmp).load()
        self.assertIsNotNone(saved)
        self.assertEqual(protocol.b64u(saved[0]), lazo.PAIRING.key_text(), "se guarda la maestra")
        self.assertEqual(lazo.PAIRING.device_key_text(phone.who), key)
        row = next(r for r in saved[1] if r["id"] == phone.who)
        self.assertTrue(row["label"] and row["fp"] and row["fecha"])
        self.assertNotIn(key.encode(), (self.tmp / recordar.KEY_FILE).read_bytes(), "la clave no se guarda en claro")
        if sys.platform != "win32":
            self.assertEqual(oct((self.tmp / recordar.KEY_FILE).stat().st_mode)[-3:], "600")
        # «Reinicio»: un Pairing y unas aprobaciones nuevas cargan lo recordado.
        lazo.PAIRING.rekey()
        lazo.APPROVALS.devices.clear()
        self.assertEqual(lazo.load_remembered(), 1)
        self.assertEqual(lazo.PAIRING.device_key_text(phone.who), key, "misma clave tras reiniciar: reconexión sin QR/PIN")
        self.assertTrue(lazo.APPROVALS.is_ok(phone.who))
        heads = {protocol.H_ID: phone.who, **lazo.PAIRING.sign("GET", "/api/aprobacion", who=phone.who)}
        self.assertEqual(json.loads(_req(self.port, "GET", "/api/aprobacion", headers=heads)[1])["state"], "aprobado")
        # Olvidar todos (solo desde el propio PC)
        self.assertEqual(Phone(self.port).post("/api/olvidar", {})[0], 403)
        status, data = self.local("POST", "/api/olvidar", {})
        self.assertEqual(status, 200)
        self.assertIsNone(recordar.Store(self.tmp).load())
        self.assertNotEqual(lazo.PAIRING.device_key_text(phone.who), key, "clave nueva")
        self.assertFalse(lazo.APPROVALS.is_ok(phone.who), "hay que reaprobar")
        heads = {protocol.H_ID: phone.who, **protocol.Pairing().sign("GET", "/api/status")}
        self.assertEqual(_req(self.port, "GET", "/api/status", headers=heads)[0], 401)

    def test_remember_off_does_not_store(self):
        self.assertEqual(self.local("POST", "/api/recordar", {"on": False})[0], 200)
        self.assertFalse(lazo.STORE.enabled())
        phone = Phone(self.port)
        phone.pair("qr", lazo.PAIRING.token_text())
        lazo.APPROVALS.decide(phone.who, True)
        phone.wait()
        self.assertFalse((self.tmp / recordar.KEY_FILE).exists())
        self.assertIsNone(recordar.Store(self.tmp).load())
        self.assertEqual(lazo.load_remembered(), 0)
        self.assertEqual(self.local("POST", "/api/recordar", {"on": True})[0], 200)
        self.assertEqual(protocol.b64u(recordar.Store(self.tmp).load()[0]), lazo.PAIRING.key_text())

    def test_panel_status_lists_waiting(self):
        phone = Phone(self.port)
        phone.pair("pin", lazo.PAIRING.pin)
        status, raw = self.local("GET", "/api/conexion")
        info = json.loads(raw)
        self.assertEqual(info["connected"], 0)
        self.assertEqual(len(info["waiting"]), 1)
        self.assertTrue(info["waiting"][0]["fp"])
        self.assertIn("approve_where", info)


class Pure(unittest.TestCase):
    def test_x25519_rfc7748(self):
        k = bytes.fromhex("a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4")
        u = bytes.fromhex("e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c")
        self.assertEqual(protocol.x25519(k, u).hex(), "c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552")

    @unittest.skipUnless(shutil.which("node"), "sin node")
    def test_js_matches_python(self):
        priv, pub = protocol.x25519_keypair()
        pc_priv, pc_pub = protocol.x25519_keypair()
        shared = protocol.x25519(pc_priv, pub)
        hk = protocol.handshake_key(b"pin:123456", "pin", "ab" * 8, pub, pc_pub, shared)
        box = protocol.b64u(protocol.seal(b"CLAVE", protocol.derive(hk, "lazo/pair/box/1")))
        script = SEAL + f"""
const h = (s) => Uint8Array.from(Buffer.from(s, "hex"));
const shared = x25519(h("{priv.hex()}"), h("{pc_pub.hex()}"));
const hk = pairHandshakeKey(new TextEncoder().encode("pin:123456"), "pin", "{'ab' * 8}", h("{pub.hex()}"), h("{pc_pub.hex()}"), shared);
console.log(pairProof(hk, "movil") + " " + openText(b64urlToBytes("{box}"), deriveKey(hk, "lazo/pair/box/1")));
"""
        out = subprocess.run(["node", "-e", "globalThis.crypto ??= require('crypto').webcrypto;\n" + script],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.stdout.split(), [protocol.proof(hk, "movil"), "CLAVE"], out.stderr)

    def test_store_forget_and_toggle(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            store = recordar.Store(tmp)
            key = secrets.token_bytes(32)
            store.save(key, [{"id": "ab" * 8, "label": "Android · Chrome", "fp": "AAAA-BBBB", "fecha": "2026-11-04 10:00"}])
            self.assertEqual(store.load()[0], key)
            store.set_enabled(False)
            self.assertIsNone(store.load())
            self.assertFalse(store.enabled())
            self.assertFalse((tmp / recordar.KEY_FILE).exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_approvals_preload_and_change_hook(self):
        app = aprobacion.Approvals()
        hits = []
        app.on_change.append(lambda: hits.append(1))
        app.preload([{"id": "cd" * 8, "label": "iPhone", "fp": "F", "fecha": "x"}, {"id": "../mal"}])
        self.assertTrue(app.is_ok("cd" * 8))
        self.assertEqual(len(app.devices), 1)
        app.kick("cd" * 8)
        self.assertEqual(hits, [1])

    # 3. Una sola forma de aceptar: el Panel no tiene botones de aceptar/rechazar.
    def test_panel_without_accept_buttons(self):
        self.assertNotIn("Aceptar", MESA)
        self.assertNotIn("Rechazar", MESA)
        self.assertNotIn("/api/dispositivos/decidir", MESA)
        self.assertIn("acéptalo desde", MESA.lower())
        for bit in ('id="recordar"', 'id="forget-all"', "Olvidar todos", "/api/olvidar", "/api/recordar"):
            self.assertIn(bit, MESA)

    def test_tray_menu_accepts_and_remembers(self):
        listing = [{"id": "ab" * 8, "state": "pendiente", "label": "Android", "ip": "192.168.1.9", "left": 40}]
        model = bandeja.menu_model(listing)
        acc, rej, _d = model["pending"][0]
        self.assertEqual(bandeja.resolve(acc, listing), ("accept", "ab" * 8))
        self.assertEqual(bandeja.resolve(rej, listing), ("reject", "ab" * 8))
        self.assertEqual(bandeja.resolve(bandeja.ID_REMEMBER, []), ("remember", None))
        self.assertEqual(bandeja.resolve(bandeja.ID_FORGET, []), ("forget", None))
        src = (ROOT / "bandeja.py").read_text(encoding="utf-8")
        self.assertIn("Aceptar dispositivo pendiente", src)
        self.assertIn("Recordar dispositivos", src)

    # 4-5. Panel de LaZoo, apaisado.
    def test_panel_name(self):
        self.assertIn("<title>Panel de LaZoo</title>", MESA)
        self.assertIn("Panel de LaZoo", (ROOT / "bandeja.py").read_text(encoding="utf-8"))
        self.assertIn("Panel de LaZoo", lazo.connect_page().decode())
        self.assertIn("grid-template-areas", MESA)
        self.assertIn('"side clip files"', MESA)

    # 6. Título largo: 2 líneas, sin cortar palabras.
    def test_long_title_two_lines(self):
        rule = re.search(r"\.now\.now-line \{([^}]*)\}", CSS).group(1)
        self.assertIn("-webkit-line-clamp: 2", rule)
        self.assertIn("white-space: normal", rule)
        self.assertIn("word-break: normal", rule)
        self.assertNotIn("nowrap", rule)
        self.assertNotIn("break-all", rule)
        self.assertIn("function fitWords", JS)

    @unittest.skipUnless(shutil.which("node"), "sin node")
    def test_long_title_never_cuts_a_word(self):
        fn = JS[JS.index("function fitWords"):JS.index("function setMediaTitle")]
        title = "Documental completo sobre la historia de las criptomonedas y el futuro descentralizado del dinero"
        # Elemento de mentira: 30 letras por línea, caben 2 líneas.
        script = fn + f"""
const el = {{ textContent: "", clientHeight: 42,
  get scrollHeight() {{ let lines = 1, col = 0; for (const w of this.textContent.split(" ")) {{
    if (col && col + 1 + w.length > 30) {{ lines += 1; col = w.length; }} else col += (col ? 1 : 0) + w.length; }} return lines * 21; }} }};
console.log(fitWords(el, {json.dumps(title)}));
"""
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30).stdout.strip()
        self.assertTrue(out.endswith("…"))
        words = out[:-1].split(" ")
        self.assertEqual(words, title.split(" ")[:len(words)], "solo palabras enteras")
        self.assertGreater(len(words), 4)

    # 7. Velocidad: parte de la actual.
    def test_speed_from_current(self):
        self.assertEqual(control.youtube_speed_plan(1.5, 2.0), ([True, True], False))
        self.assertEqual(control.youtube_speed_plan(2.0, 1.0), ([False] * 4, False))
        self.assertEqual(control.youtube_speed_plan(1.25, 1.25), ([], False))
        self.assertEqual(control.youtube_speed_plan(0.75, 1.5), ([True] * 3, False))
        taps, reset = control.youtube_speed_plan(None, 1.25)
        self.assertTrue(reset)
        self.assertEqual(taps.count(True), 4)

    def test_speed_uses_measured_rate(self):
        taps = []
        old = (control._find_youtube_unlocked, control._focus_for_keys, control._speed_tap, control.time.sleep)
        import medios
        old_m = medios.browser_session
        try:
            control._find_youtube_unlocked = lambda: {"id": "77", "title": "Vídeo - YouTube"}
            control._focus_for_keys = lambda _id: True
            control._speed_tap = taps.append
            control.time.sleep = lambda _s: None
            medios.browser_session = lambda _t: {"status": "Playing", "rate": 1.5}
            out = control._youtube_speed(2.0)
            self.assertEqual((out["from"], taps, out["reset"]), (1.5, [True, True], False))
            taps.clear()
            medios.browser_session = lambda _t: None  # sin dato del sistema: lo recordado (2.0)
            out = control._youtube_speed(1.0)
            self.assertEqual((out["from"], taps), (2.0, [False] * 4))
        finally:
            control._find_youtube_unlocked, control._focus_for_keys, control._speed_tap, control.time.sleep = old
            medios.browser_session = old_m
            control._YT_MEM.update({"id": "", "title": "", "speed": None})

    # 8. Memoria de la ventana de YouTube.
    def test_youtube_window_memory(self):
        rows = [{"id": "1", "title": "Otro - YouTube - Google Chrome"}, {"id": "2", "title": "Gatos - YouTube - Google Chrome"}]
        self.assertEqual(control.pick_youtube(rows, {"id": "2", "title": "Perros - YouTube"})["id"], "2", "mismo id aunque cambie el vídeo")
        self.assertEqual(control.pick_youtube(rows, {"id": "9", "title": "Gatos - YouTube"})["id"], "2", "por título si cambió el id")
        self.assertEqual(control.pick_youtube(rows, {})["id"], "1")
        self.assertIsNone(control.pick_youtube([{"id": "3", "title": "Música - YouTube Music"}], {}))
        src = (ROOT / "control.py").read_text(encoding="utf-8")
        pick = src[src.index("def pick_youtube"):src.index("def remember_youtube")]
        self.assertNotIn("_focus", pick)

    # 9. Esperando = desconectado + aviso destacado (banner, notificación nativa en la APK).
    def test_waiting_is_disconnected(self):
        show = JS[JS.index("function showWait(state)"):JS.index("/* Saludo de emparejamiento")]
        self.assertIn('setLink("off"', show)
        self.assertIn("Desconectado · falta aceptarlo en el PC", JS)
        self.assertIn('id="wait-banner"', HTML)
        self.assertIn("waitNote", JS)
        self.assertIn("Notification", JS)
        self.assertIn("POST_NOTIFICATIONS", APK)
        self.assertIn("NotificationChannel", JAVA)
        self.assertIn("public void waitNote", JAVA)
        self.assertNotIn("com.google", JAVA)

    def test_js_never_reads_key_from_url(self):
        self.assertNotIn('hash.get("k")', JS)
        self.assertNotIn('data.key', JS)
        self.assertIn("/api/pair/hello", JS)

    def test_version(self):
        self.assertEqual(lazo.VERSION, "0.61")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.61")
        self.assertIn("0.61", MESA)
        self.assertIn("<title>LaZoo 0.61</title>", HTML)
        self.assertIn('android:versionName="0.61"', APK)
        self.assertIn('android:versionCode="61"', APK)


if __name__ == "__main__":
    unittest.main()
