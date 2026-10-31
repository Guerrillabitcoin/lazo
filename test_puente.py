#!/usr/bin/env python3
"""Pruebas del puente por trozos: nombres, reanudar, hash, disco lleno y la ruta firmada."""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import control
os.environ["LAZO_AUTOAPPROVE"] = "1"  # SOLO pruebas: sin pedir aprobación en el PC
import lazo  # noqa: E402

lazo.APPROVALS.auto = True  # SOLO pruebas
import protocol
import puente


def lan_ip() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return ""
    finally:
        probe.close()


class Names(unittest.TestCase):
    def test_clean(self) -> None:
        self.assertEqual(puente.clean_name("../../etc/passwd"), "passwd")
        self.assertEqual(puente.clean_name("..\\..\\win.ini"), "win.ini")
        self.assertEqual(puente.clean_name("CON"), "_CON")
        self.assertEqual(puente.clean_name("nul.txt"), "_nul.txt")
        self.assertEqual(puente.clean_name("com1.tar.gz"), "_com1.tar.gz")
        self.assertEqual(puente.clean_name("a:b"), "a_b")
        self.assertEqual(puente.clean_name("..."), "archivo")
        self.assertEqual(puente.clean_name("  fin. "), "fin")
        self.assertEqual(puente.clean_name("ñandú 🦊 vídeo.mp4"), "ñandú 🦊 vídeo.mp4")
        long = puente.clean_name("x" * 400 + ".zip")
        self.assertTrue(long.endswith(".zip") and len(long.encode()) <= 180)
        self.assertEqual(puente.clean_name("sinextension"), "sinextension")

    def test_unique(self) -> None:
        folder = Path(tempfile.mkdtemp())
        (folder / "a.txt").write_text("1")
        self.assertEqual(puente.unique_path(folder, "a.txt").name, "a (2).txt")


class Uploads(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.up = puente.Uploads(lambda: self.folder)

    def send(self, data: bytes, name: str = "x.bin", key: str = "k", stop: int | None = None) -> dict:
        start = self.up.start(name, len(data), key)
        for index in range(start["total"]):
            if index in start["have"]:
                continue
            if stop is not None and index >= stop:
                return start
            self.up.write(start["id"], index, data[index * start["chunk"] : (index + 1) * start["chunk"]])
        return self.up.finish(start["id"], hashlib.sha256(data).hexdigest())

    def test_roundtrip_and_resume(self) -> None:
        with mock.patch.object(puente, "CHUNK", 1000):
            data = os.urandom(5500)
            first = self.send(data, stop=3)
            self.assertEqual(first["have"], [])
            again = self.up.start("x.bin", len(data), "k")
            self.assertEqual(again["have"], [0, 1, 2])
            # otro proceso (PC reiniciado) lee lo mismo del disco
            self.up = puente.Uploads(lambda: self.folder)
            done = self.send(data)
            self.assertEqual((self.folder / done["name"]).read_bytes(), data)
            self.assertTrue(self.up.start("x.bin", len(data), "k2")["skip"])

    def test_empty_and_dupes(self) -> None:
        self.assertEqual(self.send(b"", "vacio")["name"], "vacio")
        self.assertEqual(self.send(b"abc", "a.txt")["name"], "a.txt")
        self.assertEqual(self.send(b"abcd", "a.txt", key="o")["name"], "a (2).txt")

    def test_bad_hash_and_chunk(self) -> None:
        start = self.up.start("y", 10, "")
        with self.assertRaises(puente.BridgeError):
            self.up.write(start["id"], 0, b"123")
        with self.assertRaises(puente.BridgeError):
            self.up.write(start["id"], 5, b"1" * 10)
        self.up.write(start["id"], 0, b"1" * 10)
        with self.assertRaises(puente.BridgeError):
            self.up.finish(start["id"], "00" * 32)
        self.assertFalse(any(self.folder.glob("y*")))

    def test_disk_full_and_limit(self) -> None:
        fake = mock.Mock(free=100 * 1024 * 1024)
        with mock.patch.object(puente.shutil, "disk_usage", return_value=fake):
            with self.assertRaisesRegex(puente.BridgeError, "No cabe"):
                self.up.start("big.mkv", 1024**3, "k")
        with mock.patch.object(puente, "MAX_FILE", 10):
            with self.assertRaisesRegex(puente.BridgeError, "límite"):
                self.up.start("z", 11, "k")

    def test_cancel_and_cleanup(self) -> None:
        start = self.up.start("c", 10, "k")
        self.up.cancel(start["id"])
        self.assertEqual(list((self.folder / puente.PART_DIR).iterdir()), [])
        start = self.up.start("d", 10, "k")
        old = 1_000_000
        for path in (self.folder / puente.PART_DIR).iterdir():
            os.utime(path, (old, old))
        self.assertEqual(self.up.cleanup(force=True), 2)
        with self.assertRaises(puente.BridgeError):
            self.up.write(start["id"], 0, b"1" * 10)

    def test_bad_id(self) -> None:
        with self.assertRaises(puente.BridgeError):
            self.up.write("../../x", 0, b"")


@unittest.skipUnless(lan_ip(), "sin red local")
class SignedRoute(unittest.TestCase):
    """Igual que el móvil: desde la IP de la red, firmado y sellado."""

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        control.set_photos_dir(self.folder)
        control.set_files_dir(self.folder / "nube")
        self.server = lazo.ThreadingHTTPServer((lan_ip(), 0), lazo.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.ip = lan_ip()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def call(self, method: str, path: str, body: bytes = b"", seal: bool = True) -> tuple[int, dict | bytes]:
        if seal and body:
            body = lazo.PAIRING.seal(body)
        headers = lazo.PAIRING.sign(method, path, len(body))
        headers[protocol.H_ID] = "ab" * 8
        if seal:
            headers["X-Seal"] = "1"
        conn = http.client.HTTPConnection(self.ip, self.port, timeout=10)
        conn.request(method, path, body=body, headers=headers)
        res = conn.getresponse()
        raw = res.read()
        conn.close()
        if raw.startswith(protocol.MAGIC):
            raw = lazo.PAIRING.open(raw)
        try:
            return res.status, json.loads(raw)
        except ValueError:
            return res.status, raw

    def test_upload_download(self) -> None:
        data = os.urandom(puente.CHUNK + 12345)
        status, start = self.call("POST", "/api/up/start", json.dumps({"name": "../NUL.mp4", "size": len(data), "key": "a"}).encode())
        self.assertEqual(status, 200, start)
        self.assertEqual(start["total"], 2)
        status, res = self.call("POST", f"/api/up/{start['id']}/0", data[: puente.CHUNK], seal=False)
        self.assertEqual(status, 400)  # sin sello desde la red, no
        for index in range(2):
            status, res = self.call("POST", f"/api/up/{start['id']}/{index}", data[index * puente.CHUNK : (index + 1) * puente.CHUNK])
            self.assertEqual(status, 200, res)
        status, res = self.call("POST", f"/api/up/{start['id']}/done", json.dumps({"sha256": hashlib.sha256(data).hexdigest()}).encode())
        self.assertEqual(status, 200, res)
        self.assertEqual(res["name"], "_NUL.mp4")
        self.assertEqual((self.folder / "_NUL.mp4").read_bytes(), data)
        # PC -> móvil por trozos
        row = control.save_file_stream("vuelta.bin", __import__("io").BytesIO(data), len(data), puente.MAX_FILE)["file"]
        status, info = self.call("GET", f"/api/get/nube/{row['id']}/info")
        self.assertEqual((status, info["total"], info["sha256"]), (200, 2, hashlib.sha256(data).hexdigest()))
        got = b"".join(self.call("GET", f"/api/get/nube/{row['id']}/{i}")[1] for i in range(2))
        self.assertEqual(got, data)
        status, _ = self.call("GET", f"/api/get/nube/{row['id']}/9")
        self.assertEqual(status, 404)

    def test_unsigned_refused(self) -> None:
        conn = http.client.HTTPConnection(self.ip, self.port, timeout=5)
        conn.request("POST", "/api/up/start", body=b"{}")
        self.assertEqual(conn.getresponse().status, 401)


class Static(unittest.TestCase):
    def test_etag(self) -> None:
        server = lazo.ThreadingHTTPServer(("127.0.0.1", 0), lazo.Handler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/app.js")
            res = conn.getresponse()
            res.read()
            tag = res.getheader("ETag")
            self.assertTrue(tag)
            conn.request("GET", "/app.js", headers={"If-None-Match": tag})
            res = conn.getresponse()
            res.read()
            self.assertEqual(res.status, 304)
            conn.request("GET", "/puente-worker.js")
            res = conn.getresponse()
            self.assertIn(b"importScripts", res.read())
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
