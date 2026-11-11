"""LaZoo 0.63: Panel rediseñado (Conectar, Portapapeles con papelera, Archivos unificados).

    python3 test_v061.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import control  # noqa: E402
import lazo  # noqa: E402

MESA = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")


class PanelHtml(unittest.TestCase):
    def test_conectar(self):
        self.assertIn(">Conectar<", MESA)
        self.assertIn('id="conexion"', MESA)
        self.assertIn('id="conn-qr"', MESA)
        self.assertIn('id="conn-pin"', MESA)
        self.assertIn("QR a pantalla completa", MESA)
        self.assertNotIn("<ol>", MESA)
        self.assertIn("140px", MESA)  # QR pequeño
        self.assertIn("body.connected #conexion", MESA)

    def test_portapapeles(self):
        self.assertIn("Portapapeles Móvil ↔ PC", MESA)
        self.assertIn('id="save"', MESA)
        self.assertIn("Guardar en el móvil", MESA)
        self.assertIn("/api/clipboard/", MESA)
        self.assertIn("Eliminar nota", MESA)

    def test_archivos_unificados(self):
        self.assertIn('id="archivos"', MESA)
        self.assertIn("Cambiar carpeta", MESA)
        self.assertIn('id="change-fotos"', MESA)
        self.assertIn('id="open-fotos"', MESA)
        self.assertIn("PC→móvil", MESA)
        self.assertIn("móvil→PC", MESA)
        self.assertNotIn('id="files-box"', MESA)
        self.assertNotIn('id="puente"', MESA)
        self.assertNotIn("Archivos para el móvil", MESA)
        self.assertNotIn("Recibido del móvil", MESA)
        self.assertIn('want === "puente"', MESA)  # bandeja antigua

    def test_conserva(self):
        for bit in ("recordar", "sigues", "sigues-cuenta", "ask", "dispositivos",
                    "kick-all", "forget-all", "conn-diag", "lz-logo"):
            self.assertIn(bit, MESA)


class ClipboardDelete(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        control.set_history_path(Path(self.tmp.name) / "h.json")
        control._history.clear()
        control._history_loaded = False
        control._clip_seq = 0

    def tearDown(self):
        self.tmp.cleanup()

    def test_borra_y_persiste(self):
        a = control.clipboard_history("uno")["items"][0]["id"]
        control.clipboard_history("dos")
        control.delete_clipboard(a)
        left = [i["text"] for i in control.clipboard_history()["items"]]
        self.assertEqual(left, ["dos"])
        control._history.clear()
        control._history_loaded = False
        self.assertEqual([i["text"] for i in control.clipboard_history()["items"]], ["dos"])

    def test_id_fantasma(self):
        with self.assertRaises(control.ControlError):
            control.delete_clipboard("deadbeef")


class PhotosDelete(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "Fotos"
        self.root.mkdir()
        control.set_photos_dir(self.root)
        (self.root / "foto.jpg").write_bytes(b"abc")
        (self.root / "x.part").write_bytes(b"no")

    def tearDown(self):
        self.tmp.cleanup()

    def test_borra(self):
        control.delete_photo("foto.jpg")
        self.assertFalse((self.root / "foto.jpg").is_file())

    def test_traversal(self):
        fuera = Path(self.tmp.name) / "secreto.txt"
        fuera.write_text("x")
        with self.assertRaises(control.ControlError):
            control.delete_photo("../secreto.txt")
        self.assertTrue(fuera.is_file())
        with self.assertRaises(control.ControlError):
            control.delete_photo("x.part")


class PhotosDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"LAZO_DATOS": self.tmp.name})
        self.env.start()
        self.folder = Path(self.tmp.name) / "recibidos"
        self.folder.mkdir()
        control.set_photos_dir(Path(self.tmp.name) / "Fotos")

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_guarda_y_aplica(self):
        control.save_photos_dir_ajuste(self.folder)
        data = json.loads((Path(self.tmp.name) / "ajustes.json").read_text(encoding="utf-8"))
        self.assertEqual(data["photos_dir"], str(self.folder))
        control.apply_saved_photos_dir()
        self.assertEqual(control.received_dir().resolve(), self.folder.resolve())

    def test_choose_cancelado(self):
        with mock.patch.object(control, "_pick_folder", return_value=None):
            out = control.choose_photos_dir()
        self.assertTrue(out.get("cancelled"))

    def test_choose_ok(self):
        with mock.patch.object(control, "_pick_folder", return_value=str(self.folder)):
            out = control.choose_photos_dir()
        self.assertFalse(out.get("cancelled"))
        self.assertEqual(Path(out["folder"]).resolve(), self.folder.resolve())


class Rutas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"LAZO_DATOS": self.tmp.name})
        self.env.start()
        control.set_history_path(Path(self.tmp.name) / "h.json")
        control._history.clear(); control._history_loaded = False; control._clip_seq = 0
        self.photos = Path(self.tmp.name) / "Fotos"; self.photos.mkdir()
        control.set_photos_dir(self.photos)
        (self.photos / "p.png").write_bytes(b"1234")
        self.cid = control.clipboard_history("nota panel")["items"][0]["id"]
        self.server = lazo.LazoServer(("127.0.0.1", 0), lazo.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close()
        self.env.stop(); self.tmp.cleanup()

    def req(self, method, path, body=None, local=True):
        from test_v054 import _req
        headers = {"Content-Type": "application/json"}
        if local:
            headers["X-Lazo-Local"] = "1"
        data = json.dumps(body).encode() if body is not None else (b"" if method != "GET" else b"")
        return _req(self.port, method, path, data, headers)

    def test_delete_clipboard_local(self):
        st, raw = self.req("DELETE", f"/api/clipboard/{self.cid}")
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(raw).get("ok"), True)

    def test_delete_photo_local(self):
        st, raw = self.req("DELETE", "/api/photos/p.png")
        self.assertEqual(st, 200)
        self.assertFalse((self.photos / "p.png").exists())

    def test_remoto_sin_cabecera_no(self):
        st, _ = self.req("DELETE", f"/api/clipboard/{self.cid}", local=False)
        self.assertIn(st, (401, 403))
        st, _ = self.req("POST", "/api/photos/carpeta", {}, local=False)
        self.assertIn(st, (401, 403))

    def test_carpeta_cancelada(self):
        with mock.patch.object(control, "_pick_folder", return_value=None):
            st, raw = self.req("POST", "/api/photos/carpeta", {})
        self.assertEqual(st, 200)
        self.assertTrue(json.loads(raw).get("cancelled"))


class Version(unittest.TestCase):
    def test_version(self):
        self.assertEqual(lazo.VERSION, "0.66")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.66")
        apk = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:versionCode="65"', apk)
        self.assertIn('android:versionName="2"', apk)
        self.assertIn('<p class="ver">0.66', MESA)
        self.assertIn("## Estado (0.61)", (ROOT / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertIn("# LaZoo 0.66", (ROOT / "README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
