"""Pruebas de la 0.62: cada móvil tiene su propia clave y expulsar revoca de verdad.

Hasta 0.61 todos los móviles compartían la clave maestra y `X-Lazo-Id` no entraba en la
firma: un móvil expulsado volvía a entrar con solo poner el id de otro móvil aprobado.
Desde 0.62 el PC firma, sella y abre con la clave de cada id (`Pairing.device_key`).
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import struct
import secrets
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault("LAZO_DATOS", tempfile.mkdtemp())

import lazo  # noqa: E402
import protocol  # noqa: E402
import recordar  # noqa: E402


def _req(port, method, path, body=b"", headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body or None, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class Phone:
    """Un móvil de mentira: se empareja como static/app.js y firma con la clave que recibe."""

    def __init__(self, port, who=None):
        self.port, self.who = port, who or secrets.token_hex(8)
        self.key = None

    def post(self, path, data):
        status, raw = _req(self.port, "POST", path, json.dumps(data).encode(),
                           {"Content-Type": "application/json", "User-Agent": "Android Chrome/1"})
        return status, json.loads(raw or b"{}")

    def pair_and_get_key(self):
        priv, pub = protocol.x25519_keypair()
        status, hello = self.post("/api/pair/hello", {"id": self.who, "mode": "pin", "pub": protocol.b64u(pub)})
        assert status == 200, hello
        pc_pub = protocol.unb64u(hello["pub"])
        hk = protocol.handshake_key(("pin:" + lazo.PAIRING.pin).encode(), "pin", self.who, pub, pc_pub, protocol.x25519(priv, pc_pub))
        sid, proof = hello["sid"], protocol.proof(hk, "movil")
        status, claim = self.post("/api/pair/claim", {"sid": sid, "proof": proof})
        assert status == 200, claim
        lazo.APPROVALS.decide(self.who, True)
        status, data = self.post("/api/pair/wait", {"sid": sid, "proof": proof})
        assert data.get("state") == "aprobado", data
        text = protocol.open_sealed(protocol.unb64u(data["box"]), protocol.derive(hk, "lazo/pair/box/1")).decode()
        self.key = protocol.unb64u(text)
        return text

    # Lo mismo que hace static/app.js con la clave recibida.
    def _auth(self):
        return protocol.derive(self.key, "lazo/auth/1")

    def _seal_key(self):
        return protocol.derive(self.key, "lazo/seal/1")

    def headers(self, method, path, length=0, as_who=None):
        stamp = int(time.time() * 1000)
        nonce = secrets.token_hex(16)
        return {
            protocol.H_ID: as_who or self.who,
            protocol.H_T: str(stamp),
            protocol.H_N: nonce,
            protocol.H_S: protocol.sign_request(self._auth(), method, path, stamp, nonce, length),
            "X-Seal": "1",
        }

    def get(self, path, as_who=None):
        return _req(self.port, "GET", path, headers=self.headers("GET", path, 0, as_who))

    def signed_post(self, path, data, as_who=None):
        body = protocol.seal(json.dumps(data).encode(), self._seal_key())
        heads = {**self.headers("POST", path, len(body), as_who), "Content-Type": "application/octet-stream"}
        return _req(self.port, "POST", path, body, heads)

    def open(self, raw):
        return json.loads(protocol.open_sealed(raw, self._seal_key()))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.server = lazo.LazoServer(("127.0.0.1", 0), lazo.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.saved = (lazo.Handler._loopback, lazo.APPROVALS.auto, lazo.maybe_open_mesa, lazo.STORE, list(lazo.APPROVALS.on_change))
        lazo.APPROVALS.auto = False
        lazo.maybe_open_mesa = lambda: None
        lazo.STORE = recordar.Store(self.tmp)
        lazo.Handler._loopback = lambda self: False  # los «móviles» llegan como de la red
        lazo.PAIRING.rekey()
        lazo.APPROVALS.devices.clear()
        lazo.KICKED.clear()

    def tearDown(self):
        lazo.Handler._loopback, lazo.APPROVALS.auto, lazo.maybe_open_mesa, lazo.STORE, hooks = self.saved
        lazo.APPROVALS.on_change[:] = hooks
        lazo.APPROVALS.devices.clear()
        lazo.KICKED.clear()
        lazo.PAIRING.rekey()
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)


class ClavePorMovil(Base):
    def test_cada_movil_recibe_su_clave_y_nunca_la_maestra(self):
        a, b = Phone(self.port), Phone(self.port)
        ka, kb = a.pair_and_get_key(), b.pair_and_get_key()
        self.assertNotEqual(ka, kb)
        self.assertNotIn(lazo.PAIRING.key_text(), (ka, kb))
        self.assertEqual(ka, lazo.PAIRING.device_key_text(a.who))
        self.assertEqual(a.get("/api/status")[0], 200)
        self.assertEqual(b.get("/api/status")[0], 200)

    def test_expulsado_no_vuelve_con_el_id_de_otro(self):
        """El fallo de 0.61, reproducido como lo haría un móvil expulsado."""
        a, b = Phone(self.port), Phone(self.port)
        a.pair_and_get_key()
        b.pair_and_get_key()
        # A ve los ids completos de los demás (la lista de dispositivos lo permite).
        status, raw = a.get("/api/dispositivos")
        self.assertEqual(status, 200)
        self.assertIn(b.who, {d["id"] for d in a.open(raw)["devices"]})
        self.assertTrue(lazo.kick_device(a.who))
        status, raw = a.get("/api/status")
        self.assertEqual(status, 401)
        self.assertTrue(json.loads(raw).get("kicked"))
        # Con el id de B y su propia clave: la firma no es de B, así que no entra.
        status, raw = a.get("/api/status", as_who=b.who)
        self.assertEqual(status, 401, "un móvil expulsado no puede hacerse pasar por otro")
        self.assertTrue(json.loads(raw).get("stale"))
        status, _ = a.signed_post("/api/move", {"dx": 5, "dy": 5}, as_who=b.who)
        self.assertEqual(status, 401)
        # B sigue funcionando.
        self.assertEqual(b.get("/api/status")[0], 200)

    def test_un_movil_no_lee_ni_firma_lo_de_otro(self):
        a, b = Phone(self.port), Phone(self.port)
        a.pair_and_get_key()
        b.pair_and_get_key()
        status, raw = b.get("/api/status")
        self.assertEqual(status, 200)
        self.assertTrue(raw.startswith(protocol.MAGIC))
        with self.assertRaises(protocol.ProtocolError):
            a.open(raw)  # lo sellado para B no lo abre A
        b.open(raw)
        # Cuerpo sellado con la clave de A pero firmado como A con el id de B: fuera.
        body = protocol.seal(b'{"dx":1,"dy":1}', a._seal_key())
        heads = {**b.headers("POST", "/api/move", len(body)), "Content-Type": "application/octet-stream"}
        self.assertEqual(_req(self.port, "POST", "/api/move", body, heads)[0], 400, "sello de otro móvil")

    def test_websocket_solo_con_tramas_de_su_clave(self):
        moved = []
        real = lazo.control.move_mouse
        lazo.control.move_mouse = lambda dx, dy: moved.append((dx, dy))
        try:
            a, b = Phone(self.port), Phone(self.port)
            a.pair_and_get_key()
            b.pair_and_get_key()
            h = b.headers("GET", "/ws")
            query = f"?i={b.who}&t={h[protocol.H_T]}&n={h[protocol.H_N]}&s={h[protocol.H_S]}"
            sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
            sock.sendall((f"GET /ws{query} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                          "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
            head = sock.recv(1024)
            self.assertIn(b"101", head.split(b"\r\n", 1)[0])

            def frame(payload):
                mask = b"\0\0\0\0"
                return bytes([0x82, 0x80 | len(payload)]) + mask + payload

            sock.sendall(frame(protocol.seal(struct.pack("<ii", 3, 4), b._seal_key())))
            sock.sendall(frame(protocol.seal(struct.pack("<ii", 9, 9), a._seal_key())))  # de otro móvil: corta
            sock.sendall(frame(protocol.seal(struct.pack("<ii", 6, 6), b._seal_key())))
            deadline = time.time() + 2
            while (3, 4) not in moved and time.time() < deadline:
                time.sleep(0.02)
            time.sleep(0.2)
            sock.close()
            self.assertIn((3, 4), moved)
            self.assertNotIn((9, 9), moved)
            self.assertNotIn((6, 6), moved, "tras una trama ajena la conexión se corta")
        finally:
            lazo.control.move_mouse = real

    def test_aviso_de_reloj_legible_para_ese_movil(self):
        a = Phone(self.port)
        a.pair_and_get_key()
        stamp, nonce = int((time.time() - 300) * 1000), secrets.token_hex(16)
        heads = {protocol.H_ID: a.who, protocol.H_T: str(stamp), protocol.H_N: nonce, "X-Seal": "1",
                 protocol.H_S: protocol.sign_request(a._auth(), "GET", "/api/status", stamp, nonce, 0)}
        status, raw = _req(self.port, "GET", "/api/status", headers=heads)
        self.assertEqual(status, 401)
        self.assertTrue(a.open(raw).get("clock"), "el móvil puede leer que su reloj va mal")

    def test_sin_id_o_con_la_maestra_no_entra(self):
        a = Phone(self.port)
        a.pair_and_get_key()
        stamp, nonce = int(time.time() * 1000), secrets.token_hex(16)
        master = {protocol.H_ID: a.who, protocol.H_T: str(stamp), protocol.H_N: nonce,
                  protocol.H_S: protocol.sign_request(lazo.PAIRING.auth_key, "GET", "/api/status", stamp, nonce, 0)}
        self.assertEqual(_req(self.port, "GET", "/api/status", headers=master)[0], 401,
                         "desde fuera, la firma tiene que ser de la clave de ese móvil")


class Recordar(Base):
    def test_clave_guardada_lleva_marca_y_se_recupera(self):
        lazo.STORE.set_enabled(True)
        lazo.APPROVALS.on_change.append(lazo.persist_devices)
        a = Phone(self.port)
        key = a.pair_and_get_key()
        saved = recordar.Store(self.tmp).load()
        self.assertEqual(saved[0], lazo.PAIRING.key)
        blob = (self.tmp / recordar.KEY_FILE).read_bytes()
        self.assertNotIn(lazo.PAIRING.key, blob, "la maestra no se guarda en claro")
        lazo.PAIRING.rekey()
        lazo.APPROVALS.devices.clear()
        self.assertEqual(lazo.load_remembered(), 1)
        self.assertEqual(lazo.PAIRING.device_key_text(a.who), key, "reconecta sin QR tras reiniciar")
        self.assertEqual(a.get("/api/status")[0], 200)

    def test_clave_de_061_se_cambia_y_los_aprobados_se_conservan(self):
        """Una clave guardada por 0.54-0.61 la tenían todos los móviles: no se reutiliza."""
        store = recordar.Store(self.tmp)
        store.set_enabled(True)
        old = secrets.token_bytes(32)
        recordar._write_private(self.tmp / recordar.KEY_FILE, store._protect(old))  # formato de 0.61, sin marca
        store._save_list(True, [{"id": "ab" * 8, "label": "Móvil viejo", "fp": "X", "fecha": "2026-11-01 10:00"}])
        self.assertEqual(store.load(), (None, store.devices()))
        lazo.STORE = store
        lazo.APPROVALS.on_change.append(lazo.persist_devices)
        self.assertEqual(lazo.load_remembered(), 1)
        self.assertNotEqual(lazo.PAIRING.key, old, "clave nueva")
        self.assertTrue(lazo.APPROVALS.is_ok("ab" * 8), "el aprobado sigue aprobado")
        again = recordar.Store(self.tmp).load()
        self.assertEqual(again[0], lazo.PAIRING.key, "la clave nueva ya se guardó con marca")
        # Un móvil con la clave vieja (la maestra de 0.61) recibe «stale» y vuelve a escanear.
        stamp, nonce = int(time.time() * 1000), secrets.token_hex(16)
        heads = {protocol.H_ID: "ab" * 8, protocol.H_T: str(stamp), protocol.H_N: nonce,
                 protocol.H_S: protocol.sign_request(protocol.derive(old, "lazo/auth/1"), "GET", "/api/status", stamp, nonce, 0)}
        status, raw = _req(self.port, "GET", "/api/status", headers=heads)
        self.assertEqual(status, 401)
        self.assertTrue(json.loads(raw).get("stale"))


class Fuente(unittest.TestCase):
    def test_el_movil_no_necesita_cambios(self):
        """La página sigue derivando auth y seal de la clave que recibe: ahora es la suya."""
        js = (Path(__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('deriveKey(master, "lazo/seal/1")', js)
        self.assertIn('deriveKey(master, "lazo/auth/1")', js)

    def test_documentado(self):
        doc = (Path(__file__).parent / "protocol.py").read_text(encoding="utf-8")
        self.assertIn("lazo/dev/1|", doc)


if __name__ == "__main__":
    unittest.main()
