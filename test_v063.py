"""LaZoo 0.63: un móvil = una sesión, saltar anuncios, primer toque, «Portapapeles Wifi» y notas cifradas.

    python3 test_v063.py

- Expulsar: el mismo móvil con un id viejo (misma IP de la red y mismo tipo) se retira al
  aceptar el nuevo; desde 127.0.0.1 nunca; la APK tiene un id fijo (LaZooApp.deviceId) y se
  distingue del navegador; la lista dice «visto hace…» y «Este móvil».
- YouTube: anuncios.py pulsa «Saltar» por accesibilidad; la flecha ⏭ lo intenta primero; la
  ventana que estaba detrás espera a recibir el teclado antes de la tecla (primer toque).
- «Portapapeles Wifi»: notas, portapapeles y archivos en una sola pestaña y una sola caja del
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


def _idle(ap, who):
    ap.devices[who]["seen"] -= aprobacion.TWIN_IDLE + 1  # lleva rato sin hablar con el PC


class UnMovilUnaSesion(unittest.TestCase):
    """El mismo móvil con un id viejo se MARCA como antiguo; nunca se expulsa por eso."""

    def setUp(self):
        self.ap = aprobacion.Approvals()

    def ids(self, old=None):
        rows = self.ap.listing()
        return [d["id"][0] for d in rows if old is None or d["duplicado"] == old]

    def test_mismo_movil_con_id_nuevo_marca_el_viejo(self):
        _approve(self.ap, "a" * 32)
        _idle(self.ap, "a" * 32)
        _approve(self.ap, "b" * 32)
        self.assertEqual((self.ids(old=False), self.ids(old=True)), (["b"], ["a"]))
        self.assertTrue(self.ap.is_ok("a" * 32))  # sigue aprobado: no se expulsa

    def test_el_viejo_vuelve_dias_despues_y_entra_al_momento(self):
        changed = []
        self.ap.on_change.append(lambda: changed.append(1))
        _approve(self.ap, "a" * 32)
        _idle(self.ap, "a" * 32)
        _approve(self.ap, "b" * 32)
        self.ap.devices["a" * 32]["seen"] -= 3 * 86400  # tres días en el bolsillo
        self.assertEqual(self.ap.check("a" * 32, CHROME, "192.168.1.20"), "ok")  # sin QR ni aviso
        self.assertEqual(self.ids(old=True), [])
        self.assertTrue(changed)  # se guarda ya desmarcado

    def test_dos_moviles_iguales_en_uso_no_se_marcan(self):
        _approve(self.ap, "a" * 32)
        _approve(self.ap, "b" * 32)
        self.assertEqual(self.ids(old=True), [])

    def test_otro_movil_o_otra_ip_no(self):
        _approve(self.ap, "a" * 32)
        _idle(self.ap, "a" * 32)
        _approve(self.ap, "b" * 32, ip="192.168.1.21")          # otro móvil
        _approve(self.ap, "c" * 32, ua=WEBVIEW)                  # la APK en el mismo móvil
        _approve(self.ap, "d" * 32, ua="Mozilla/5.0 (iPhone) Safari/605.1")
        self.assertEqual(self.ids(old=True), [])

    def test_desde_el_propio_pc_nunca(self):
        _approve(self.ap, "a" * 32, ip="127.0.0.1")
        _idle(self.ap, "a" * 32)
        _approve(self.ap, "b" * 32, ip="127.0.0.1")
        self.assertEqual(self.ids(old=True), [])

    def test_rechazar_no_marca(self):
        _approve(self.ap, "a" * 32)
        _idle(self.ap, "a" * 32)
        self.ap.check("b" * 32, CHROME, "192.168.1.20")
        self.ap.decide("b" * 32, False)
        self.assertEqual(self.ids(old=True), [])

    def test_recordado_con_ip_y_marca(self):
        self.ap.preload([{"id": "a" * 32, "label": "Android · Chrome", "ip": "192.168.1.20"},
                         {"id": "c" * 32, "label": "Android · Chrome", "ip": "192.168.1.30", "duplicado": "1"}])
        rows = {d["id"][0]: d for d in self.ap.listing()}
        self.assertEqual(rows["a"]["ago"], -1)  # sin ver desde que arrancó
        self.assertTrue(rows["c"]["duplicado"])
        saved = {r["id"][0]: r for r in self.ap.approved_rows()}
        self.assertEqual((saved["a"]["ip"], saved["a"]["duplicado"], saved["c"]["duplicado"]), ("192.168.1.20", "", "1"))
        _approve(self.ap, "b" * 32)  # «a» no habló desde el arranque: queda como antiguo
        self.assertEqual(sorted(self.ids(old=True)), ["a", "c"])

    def test_etiqueta_de_la_apk(self):
        self.assertEqual(aprobacion.device_label(WEBVIEW), "Android · App LaZoo")
        self.assertEqual(aprobacion.device_label(CHROME), "Android · Chrome")

    def test_nada_se_expulsa_solo(self):
        self.assertNotIn("retire_device", LAZO)
        self.assertNotIn("on_retire", (ROOT / "aprobacion.py").read_text(encoding="utf-8"))

    def test_recordar_guarda_ip_y_marca(self):
        import recordar

        with tempfile.TemporaryDirectory() as tmp:
            store = recordar.Store(Path(tmp))
            store._save_list(True, [{"id": "a" * 32, "label": "x", "ip": "192.168.1.9", "duplicado": "1"}])
            self.assertEqual((store.devices()[0]["ip"], store.devices()[0]["duplicado"]), ("192.168.1.9", "1"))


class Despertar(unittest.TestCase):
    """Móvil bloqueado en el bolsillo horas o días: al abrirlo, reconecta ya y sin QR."""

    def test_movil(self):
        for piece in ("async function wakeUp(", "pointerSocket.close()", "connectPointer();",
                      'window.addEventListener("online"', "window.lazooDespierta = ", "now - lastTick > WAKE_AFTER_MS",
                      "Date.now() - hiddenAt > WAKE_AFTER_MS"):
            self.assertIn(piece, JS)
        body = JS[JS.index("async function wakeUp("):JS.index("window.setInterval(() => {\n  const now = Date.now();")]
        self.assertNotIn("forgetKey", body)   # despertar nunca borra la clave
        self.assertNotIn("showPin", body)

    def test_apk(self):
        on_resume = JAVA[JAVA.index("protected void onResume()"):JAVA.index("protected void onPause()")]
        self.assertIn("window.lazooDespierta", on_resume)


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
        self.assertIn('mine ? "Salir" : d.duplicado ? "Quitar" : "Expulsar"', JS)
        self.assertIn("id antiguo", MESA)


class FakeWin:
    """Windows de mentira para despierto.py."""

    def __init__(self):
        self.keeps, self.nudges, self.idle, self.is_locked = [], 0, 0.0, False

    def keep(self, on):
        self.keeps.append(on)

    def idle_seconds(self):
        return self.idle

    def locked(self):
        return self.is_locked

    def nudge(self):
        self.nudges += 1


class PcDespierto(unittest.TestCase):
    def make(self):
        import despierto

        self.d = despierto
        self.tmp = tempfile.TemporaryDirectory()
        self.now = [1000.0]
        self.win = FakeWin()
        return despierto.Despierto(system=self.win, file=Path(self.tmp.name) / "ajustes.json", clock=lambda: self.now[0])

    def tearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def test_sin_movil_no_hace_nada(self):
        d = self.make()
        self.assertFalse(d.tick()["activo"])
        self.assertEqual(self.win.nudges, 0)
        self.assertNotIn(True, self.win.keeps)

    def test_con_movil_mantiene_y_toca_sin_mover(self):
        d = self.make()
        d.touch()
        self.assertTrue(d.tick()["activo"])
        self.assertEqual(self.win.keeps[-1], True)
        self.assertEqual(self.win.nudges, 0)  # hay actividad reciente: no hace falta tocar
        self.win.idle = self.d.TOQUE_TRAS + 1
        self.assertTrue(d.tick()["toque"])
        self.assertEqual(self.win.nudges, 1)

    def test_ventana_1h21(self):
        self.make()
        self.assertEqual(self.d.VENTANA, 81 * 60)
        self.assertIn("1 h 21 min", HTML)
        self.assertIn("1 h 21 min", MESA)

    def test_una_hora_despues_suelta(self):
        d = self.make()
        d.touch()
        d.tick()
        self.now[0] += self.d.VENTANA + 1
        self.assertFalse(d.tick()["activo"])
        self.assertEqual(self.win.keeps[-1], False)

    def test_bloqueado_no_lo_mantiene(self):
        d = self.make()
        d.touch()
        self.win.is_locked = True
        self.win.idle = 999
        res = d.tick()
        self.assertTrue(res.get("bloqueado"))
        self.assertFalse(res["activo"])
        self.assertEqual(self.win.nudges, 0)

    def test_apagado_se_guarda_y_suelta(self):
        d = self.make()
        d.touch()
        d.tick()
        self.assertFalse(d.set_on(False)["on"])
        self.assertEqual(self.win.keeps[-1], False)
        self.assertFalse(json.loads(d.file.read_text())["despierto"])
        self.assertFalse(self.d.Despierto(system=FakeWin(), file=d.file).on)
        d.stop()

    def test_no_arranca_en_pruebas(self):
        import despierto

        self.assertFalse(despierto.watch())

    def test_cursor_quieto_y_rutas(self):
        src = (ROOT / "despierto.py").read_text(encoding="utf-8")
        self.assertIn("MOUSEINPUT(0, 0, 0, 0x0001", src)  # movimiento de 0 píxeles
        self.assertNotIn("SetCursorPos", src)
        self.assertIn("despierto.DESPIERTO.touch()", LAZO)
        self.assertIn('"/api/despierto"', LAZO)
        self.assertIn("--sin-despierto", LAZO)
        self.assertIn('id="sys-despierto"', HTML)
        self.assertIn("PREF_PUSH.push(syncDespierto)", JS)
        self.assertIn('devCall("/api/despierto"', MESA)


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
        self.assertIn('{ id: "bridge", name: "Portapapeles Wifi" }', JS)
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
        self.assertIn("<h2>Portapapeles Wifi</h2>", box)
        self.assertIn("No pasa por internet.", box)
        self.assertLess(box.index('id="clip-box"'), box.index('id="archivos"'))
        self.assertIn('"cola side pasar pasar"', MESA)  # 0.69: Conectar va en la columna `cola`

    def test_bandeja(self):
        import bandeja

        names = dict(bandeja.CUBES)
        self.assertEqual(names["bridge"], "Portapapeles Wifi")
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


import asyncio  # noqa: E402
import test_v057  # noqa: E402


@unittest.skipUnless(test_v057.CHROME and test_v057.importlib.util.find_spec("playwright"), "sin Chrome/Playwright")
class DespertarEnChrome(test_v057.Navegador):
    """El JS real: tras «dormir» (y con el PC sin contestar un momento), vuelve solo, con la
    misma clave, sin QR ni PIN, y abre un WebSocket nuevo para el ratón."""

    test_ciclo_completo = None  # ese ya corre en test_v057

    def test_vuelve_solo(self):
        asyncio.run(self._despertar())

    async def _despertar(self):
        from playwright.async_api import async_playwright

        lazo.set_remember(True)
        async with async_playwright() as p:
            b = await p.chromium.launch(executable_path=test_v057.CHROME, args=["--no-sandbox"])
            pg = await (await b.new_context(viewport={"width": 400, "height": 800})).new_page()
            errores, sockets = [], []
            pg.on("pageerror", lambda e: errores.append(str(e)))
            pg.on("websocket", lambda ws: sockets.append(ws))
            await pg.goto(lazo.PAIRING.phone_url("http", self.ip, self.port))
            st = await self._hasta(pg, lambda s: s["app"] and s["link"] == "on", aprobar=True)
            key = st["key"]
            await pg.evaluate("connectPointer()")
            await asyncio.sleep(0.5)
            antes = len(sockets)
            # El PC deja de contestar (como la Wi-Fi al desbloquear) y vuelve a los ~2 s.
            self.server.shutdown()
            self.server.server_close()
            await pg.evaluate("window.lazooDespierta()")
            await asyncio.sleep(2)
            self._restart()
            st = await self._hasta(pg, lambda s: s["app"] and s["link"] == "on" and not s["pin"])
            for _ in range(30):
                if len(sockets) > antes:
                    break
                await asyncio.sleep(0.2)
            self.assertGreater(len(sockets), antes, "no abrió un WebSocket nuevo al despertar")
            self.assertEqual(st["key"], key, "despertar no debe cambiar ni borrar la clave")
            await b.close()
            self.assertEqual(errores, [])
