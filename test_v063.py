"""LaZoo 0.63: un móvil = una sesión, saltar anuncios, primer toque, «Pasar por wifi» y notas cifradas.

    python3 test_v063.py

- Expulsar: el mismo móvil con un id viejo (misma IP de la red y mismo tipo) se retira al
  aceptar el nuevo; desde 127.0.0.1 nunca; la APK tiene un id fijo (LaZooApp.deviceId) y se
  distingue del navegador; la lista dice «visto hace…» y «Este móvil».
- YouTube: anuncios.py pulsa «Saltar» por accesibilidad; la flecha ⏭ lo intenta primero; la
  ventana que estaba detrás espera a recibir el teclado antes de la tecla (primer toque).
- «Pasar por wifi»: notas, portapapeles y archivos en una sola pestaña y una sola caja del
  Panel, con el aviso de privacidad; borrar notas desde el móvil; notas cifradas también en
  Linux/Mac, archivo 600 en la carpeta privada; las copias marcadas como privadas por un
  gestor de contraseñas no entran en las notas.
- QR en la APK: los botones abren el escáner con cámara (test_qr_camara.py).
"""
from __future__ import annotations

import json
import os
import re
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import anuncios  # noqa: E402
import aprobacion  # noqa: E402
import control  # noqa: E402
import lazo  # noqa: E402
import protocol  # noqa: E402
import sigues  # noqa: E402
from test_v062 import Base, Phone  # noqa: E402

JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
MESA = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
JAVA = (ROOT / "android" / "src" / "net" / "lazoo" / "app" / "MainActivity.java").read_text(encoding="utf-8")
LAZO = (ROOT / "lazo.py").read_text(encoding="utf-8")
CHROME = "Mozilla/5.0 (Linux; Android 14; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"
WEBVIEW = "Mozilla/5.0 (Linux; Android 14; K; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/130.0 Mobile Safari/537.36"


def _approve(ap, who, ua=CHROME, ip="192.168.1.20"):
    ap.check(who, ua, ip)
    ap.decide(who, True)


class UnMovilUnaSesion(unittest.TestCase):
    def setUp(self):
        self.ap = aprobacion.Approvals()
        self.gone = []
        self.ap.on_retire.append(self.gone.append)

    def test_mismo_movil_con_id_nuevo_retira_el_viejo(self):
        _approve(self.ap, "a" * 32)
        _approve(self.ap, "b" * 32)
        self.assertEqual([d["id"] for d in self.ap.listing()], ["b" * 32])
        self.assertEqual(self.gone, ["a" * 32])

    def test_otro_movil_o_otra_ip_no(self):
        _approve(self.ap, "a" * 32)
        _approve(self.ap, "b" * 32, ip="192.168.1.21")          # otro móvil
        _approve(self.ap, "c" * 32, ua=WEBVIEW)                  # la APK en el mismo móvil
        _approve(self.ap, "d" * 32, ua="Mozilla/5.0 (iPhone) Safari/605.1")
        self.assertEqual(len(self.ap.listing()), 4)
        self.assertEqual(self.gone, [])

    def test_desde_el_propio_pc_nunca(self):
        _approve(self.ap, "a" * 32, ip="127.0.0.1")
        _approve(self.ap, "b" * 32, ip="127.0.0.1")
        self.assertEqual(len(self.ap.listing()), 2)

    def test_rechazar_no_retira(self):
        _approve(self.ap, "a" * 32)
        self.ap.check("b" * 32, CHROME, "192.168.1.20")
        self.ap.decide("b" * 32, False)
        self.assertIn("a" * 32, [d["id"] for d in self.ap.listing()])
        self.assertEqual(self.gone, [])

    def test_recordado_con_ip_tambien_se_junta(self):
        self.ap.preload([{"id": "a" * 32, "label": "Android · Chrome", "ip": "192.168.1.20"}])
        row = self.ap.listing()[0]
        self.assertEqual(row["ago"], -1)  # sin ver desde que arrancó
        self.assertEqual(self.ap.approved_rows()[0]["ip"], "192.168.1.20")
        _approve(self.ap, "b" * 32)
        self.assertEqual([d["id"] for d in self.ap.listing()], ["b" * 32])

    def test_etiqueta_de_la_apk(self):
        self.assertEqual(aprobacion.device_label(WEBVIEW), "Android · App LaZoo")
        self.assertEqual(aprobacion.device_label(CHROME), "Android · Chrome")

    def test_retirado_queda_fuera(self):
        lazo.KICKED.discard("e" * 32)
        lazo.retire_device("e" * 32)
        self.assertIn("e" * 32, lazo.KICKED)
        lazo.KICKED.discard("e" * 32)
        self.assertIn("APPROVALS.on_retire.append(retire_device)", LAZO)

    def test_recordar_guarda_la_ip(self):
        import recordar

        with tempfile.TemporaryDirectory() as tmp:
            store = recordar.Store(Path(tmp))
            store._save_list(True, [{"id": "a" * 32, "label": "x", "ip": "192.168.1.9"}])
            self.assertEqual(store.devices()[0]["ip"], "192.168.1.9")


class IdFijoDeLaApk(unittest.TestCase):
    def test_puente_java(self):
        self.assertIn("public String deviceId(String candidate)", JAVA)
        self.assertIn('prefs().getString("id", "")', JAVA)
        self.assertIn("SecureRandom", JAVA)

    def test_movil_lo_usa_y_cambia_de_clave_una_vez(self):
        head = JS[: JS.index("function forgetKey")]
        self.assertIn("app.deviceId(", head)
        self.assertIn('localStorage.removeItem("lazo-key");  // la clave era de otro id', head)

    def test_lista_clara(self):
        self.assertIn('mine ? "Este móvil" : d.label', JS)
        self.assertIn('"visto " + seenText(d.ago)', JS)
        self.assertIn("visto hace", MESA)
        self.assertIn('mine ? "Salir" : "Expulsar"', JS)


class SaltarAnuncios(unittest.TestCase):
    def make(self, res=None, hwnd="77"):
        self.tmp = tempfile.TemporaryDirectory()
        self.calls = []

        def probe(h):
            self.calls.append(h)
            return res if res is not None else {"ok": True, "visto": True, "pulsado": True, "verificado": True, "ms": 60}

        return anuncios.Anuncios(find=lambda: hwnd, probe=probe, file=Path(self.tmp.name) / "ajustes.json")

    def tearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def test_nombres(self):
        for n in ["Saltar", "Skip", "Skip Ad", "Saltar anuncio", "Omitir anuncios", " Skip ▶", "Saltar.", "Pular"]:
            self.assertTrue(anuncios.es_saltar(n), n)
        for n in ["Saltar navegación", "Skip navigation", "Suscribirse", "", "Siguiente", "Skip to content"]:
            self.assertFalse(anuncios.es_saltar(n), n)

    def test_script_sin_cursor_ni_teclas(self):
        ps = anuncios.ps_script()
        self.assertIn("InvokePattern", ps)
        self.assertIn("IsOffscreen", ps)
        self.assertIn("'reproductor de vídeo de youtube'", ps)
        for bad in ("SetCursorPos", "SendKeys", "SetFocus", "keybd_event", "mouse_event", "BringWindowToTop", "http"):
            self.assertNotIn(bad, ps)
        self.assertEqual(ps.count("::SetForegroundWindow("), 1)  # solo para devolver el foco
        anuncios.encoded()

    def test_pulsa_cuenta_y_guarda_aparte_de_sigues(self):
        a = self.make()
        self.assertTrue(a.on)
        self.assertTrue(a.check_once()["pulsado"])
        self.assertEqual(a.total, 1)
        data = json.loads(a.file.read_text())
        self.assertEqual(data["anuncios_contador"]["total"], 1)
        self.assertNotIn("contador", data)
        s = sigues.Sigues(find=lambda: None, probe=lambda h: {}, file=a.file)
        s.set_on(False)
        data = json.loads(a.file.read_text())
        self.assertEqual((data["sigues"], data["anuncios"]), (False, True))
        self.assertTrue(anuncios.Anuncios(file=a.file).on)

    def test_sin_boton_no_cuenta(self):
        a = self.make(res={"ok": True, "visto": False, "pulsado": False, "ms": 30})
        a.check_once()
        self.assertEqual(a.total, 0)
        self.assertFalse(a.saltar_ya())

    def test_flecha_lo_intenta_aunque_este_apagado(self):
        a = self.make()
        a.set_on(False)
        self.assertEqual(a.check_once(), {"skip": "apagado"})
        self.assertTrue(a.saltar_ya())
        self.assertEqual(a.total, 1)

    def test_pc_lento_espacia_y_la_flecha_no_espera(self):
        a = self.make()
        a.ultima_ms = anuncios.LENTO_MS + 1
        self.assertEqual(a.interval(), anuncios.LENTO)
        self.assertFalse(a.saltar_ya())
        a.ultima_ms = 50
        self.assertEqual(a.interval(), anuncios.INTERVALO)

    def test_no_arranca_en_pruebas(self):
        self.assertFalse(anuncios.watch())

    def test_flecha_siguiente_salta_primero(self):
        row = {"id": "5", "title": "Algo - YouTube"}
        with mock.patch.object(control, "_find_youtube_unlocked", return_value=row), \
                mock.patch.object(control, "_yt_state", return_value={}), \
                mock.patch.object(control, "_skip_ad_now", return_value=True), \
                mock.patch.object(control, "_focus_for_keys") as focus, \
                mock.patch.object(control, "_yt_keys") as keys:
            out = control.youtube("next")
        self.assertEqual(out["detail"], "Anuncio saltado")
        focus.assert_not_called()
        keys.assert_not_called()
        with mock.patch.object(control, "_find_youtube_unlocked", return_value=row), \
                mock.patch.object(control, "_yt_state", return_value={}), \
                mock.patch.object(control, "_skip_ad_now", return_value=False), \
                mock.patch.object(control, "_focus_for_keys", return_value=True), \
                mock.patch.object(control.time, "sleep"), \
                mock.patch.object(control, "_yt_keys") as keys:
            out = control.youtube("next")
        self.assertEqual(out["detail"], "Siguiente vídeo")
        keys.assert_called_once_with(["shift", "n"])

    def test_rutas_e_interfaz(self):
        self.assertIn('"/api/anuncios"', LAZO)
        self.assertIn("anuncios.watch()", LAZO)
        self.assertIn("--sin-anuncios", LAZO)
        self.assertIn('id="yt-anuncios"', HTML)
        self.assertIn("PREF_PUSH.push(syncAnuncios)", JS)
        self.assertIn('id="anuncios"', MESA)
        self.assertIn('devCall("/api/anuncios"', MESA)


class PrimerToque(unittest.TestCase):
    def test_espera_a_que_siga_delante(self):
        seq = iter([False, True, True, True])
        waits = []
        with mock.patch.object(control, "_is_foreground", side_effect=lambda h: next(seq, True)):
            self.assertTrue(control._settle_foreground(1, wait=waits.append))
        self.assertEqual(waits[-1], control.FOCUS_SETTLE)
        self.assertEqual(waits.count(0.04), 3)

    def test_se_rinde_sin_colgarse(self):
        waits = []
        with mock.patch.object(control, "_is_foreground", return_value=False):
            self.assertFalse(control._settle_foreground(1, wait=waits.append))
        self.assertLess(sum(waits), 1.2)

    def test_solo_si_estaba_detras(self):
        with mock.patch.object(control, "SYSTEM", "Windows"), \
                mock.patch.object(control, "_is_foreground", return_value=True), \
                mock.patch.object(control, "_activate_window", return_value=True), \
                mock.patch.object(control, "_settle_foreground") as settle:
            self.assertTrue(control._focus_for_keys("9"))
        settle.assert_not_called()
        with mock.patch.object(control, "SYSTEM", "Windows"), \
                mock.patch.object(control, "_is_foreground", return_value=False), \
                mock.patch.object(control, "_activate_window", return_value=True), \
                mock.patch.object(control, "_settle_foreground") as settle:
            self.assertTrue(control._focus_for_keys("9"))
        settle.assert_called_once_with(9)


class PasarPorWifi(unittest.TestCase):
    def test_una_pestana(self):
        self.assertIn('{ id: "bridge", name: "Pasar por wifi" }', JS)
        self.assertNotIn('{ id: "notes"', JS)
        self.assertNotIn('id="view-notes"', HTML)
        view = HTML[HTML.index('<div id="view-bridge"'):HTML.index('<div id="view-system"')]
        for piece in ('id="clip-form"', 'id="clips"', 'id="clip-to-pc"', 'id="send-input"', 'id="files"', 'id="clips-clear"'):
            self.assertIn(piece, view)
        self.assertIn("No pasa por internet.", view)
        self.assertIn("cifrad", view)
        self.assertIn("notes: \"bridge\"", JS)  # #pastilla=notes de la bandeja vieja

    def test_panel_una_caja(self):
        box = MESA[MESA.index('<section id="pasar"'):]
        self.assertIn("<h2>Pasar por wifi</h2>", box)
        self.assertIn("No pasa por internet.", box)
        self.assertLess(box.index('id="clip-box"'), box.index('id="archivos"'))
        self.assertIn('"conn side pasar pasar"', MESA)

    def test_bandeja(self):
        import bandeja

        names = dict(bandeja.CUBES)
        self.assertEqual(names["bridge"], "Pasar por wifi")
        self.assertNotIn("notes", names)

    def test_movil_borra_notas(self):
        self.assertIn('api("/api/clipboard/borrar", { id: item.id })', JS)
        self.assertIn('api("/api/clipboard/borrar", { all: true })', JS)


class NotasCifradas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = control._history_path
        control.set_history_path(Path(self.tmp.name) / "notas.lz")

    def tearDown(self):
        control.set_history_path(self.old)
        self.tmp.cleanup()

    def test_en_disco_cifrado_y_privado(self):
        with mock.patch.object(control, "SYSTEM", "Linux"):
            control.clipboard_history("contraseña-secreta-123")
            raw = control._history_path.read_bytes()
            self.assertTrue(raw.startswith(protocol.MAGIC))
            self.assertNotIn(b"secreta", raw)
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(control._history_path.stat().st_mode), 0o600)
                key = control._history_path.with_name(control.NOTES_KEY_FILE)
                self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
            control.set_history_path(control._history_path)  # se vuelve a leer del disco
            self.assertEqual(control.clipboard_history()["items"][0]["text"], "contraseña-secreta-123")

    def test_notas_viejas_en_claro_se_leen(self):
        control._history_path.write_text(json.dumps([{"id": "ab12cd34", "text": "vieja", "at": 1, "seq": 1}]))
        with mock.patch.object(control, "SYSTEM", "Linux"):
            control.set_history_path(control._history_path)
            self.assertEqual(control.clipboard_history()["items"][0]["text"], "vieja")
            control.clipboard_history("nueva")
            self.assertTrue(control._history_path.read_bytes().startswith(protocol.MAGIC))

    def test_borrar_todas(self):
        control.clipboard_history("uno")
        control.clipboard_history("dos")
        self.assertEqual(control.clear_clipboard()["items"], [])
        control.set_history_path(control._history_path)
        self.assertEqual(control.clipboard_history()["items"], [])

    def test_mover_a_la_carpeta_privada(self):
        with tempfile.TemporaryDirectory() as datos, mock.patch.dict(os.environ, {"LAZO_DATOS": datos}), \
                mock.patch.object(control, "SYSTEM", "Linux"):
            fake_old = Path(self.tmp.name) / "clipboard-history.json"
            fake_old.write_text(json.dumps([{"id": "ab12cd34", "text": "mía", "at": 1, "seq": 1}]))
            real_file = control.__file__
            try:
                control.__file__ = str(Path(self.tmp.name) / "control.py")
                new = control.use_private_history()
            finally:
                control.__file__ = real_file
            self.assertEqual(new, Path(datos) / "notas.lz")
            self.assertFalse(fake_old.exists())
            self.assertTrue(new.read_bytes().startswith(protocol.MAGIC))
            self.assertEqual(control.clipboard_history()["items"][0]["text"], "mía")

    def test_gestor_de_contrasenas_no_entra(self):
        self.assertIn("ExcludeClipboardContentFromMonitorProcessing", control._PRIVATE_FORMATS)
        w = control.ClipWatch(add=lambda t: None)
        self.assertIsNone(w._read)
        src = (ROOT / "control.py").read_text(encoding="utf-8")
        self.assertIn("read = self._read or _read_clipboard_for_history", src)
        self.assertIn("CanIncludeInClipboardHistory", src)


class BorrarDesdeElMovil(Base):
    def setUp(self):
        super().setUp()
        self.old = control._history_path
        control.set_history_path(self.tmp / "notas.lz")

    def tearDown(self):
        control.set_history_path(self.old)
        super().tearDown()

    def test_una_y_todas(self):
        phone = Phone(self.port)
        phone.pair_and_get_key()
        control.clipboard_history("uno")
        control.clipboard_history("dos")
        first = control.clipboard_history()["items"][0]["id"]
        st, raw = phone.signed_post("/api/clipboard/borrar", {"id": first})
        self.assertEqual(st, 200)
        self.assertEqual([i["text"] for i in phone.open(raw)["items"]], ["uno"])
        st, raw = phone.signed_post("/api/clipboard/borrar", {"all": True})
        self.assertEqual((st, phone.open(raw)["items"]), (200, []))

    def test_sin_firma_no(self):
        control.clipboard_history("secreto")
        from test_v062 import _req

        st, _raw = _req(self.port, "POST", "/api/clipboard/borrar", json.dumps({"all": True}).encode(),
                        {"Content-Type": "application/json"})
        self.assertIn(st, (401, 403))
        self.assertEqual(len(control.clipboard_history()["items"]), 1)


class Notas(unittest.TestCase):
    def test_documentado(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("0.63", agents)
        self.assertRegex(agents, re.compile(r"Pasar por wifi"))


if __name__ == "__main__":
    unittest.main()
