"""LaZoo 0.67: versión para Linux.

    python3 test_v067.py

- No bloquear el PC: inhibidor de GNOME o de systemd mientras se usa el móvil; se suelta al
  acabar; con la sesión bloqueada no se mantiene.
- Salto exacto y pausa con MPRIS (playerctl), comprobando que llegó; nombres de reproductor raros
  no pasan a la orden.
- Bandeja: el mismo menú (y los mismos ids) que en Windows; «Iniciar con el sistema» con
  ~/.config/autostart; sin escritorio o sin PyGObject, iniciar.sh sigue en la consola.
- YouTube por accesibilidad (AT-SPI) con un árbol de mentira: «¿Sigues ahí?», «Saltar», volumen,
  barra de direcciones sin entrar en la página, y las órdenes de patrocinios y mando con las
  mismas respuestas que el PowerShell de Windows.
- Cursor grande en KDE, Cinnamon, MATE, Xfce y GNOME. Paquete de Linux en ci/construir.yml.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("LAZO_DATOS", tempfile.mkdtemp())

ROOT = Path(__file__).resolve().parent

import bandeja  # noqa: E402
import bandeja_linux  # noqa: E402
import control  # noqa: E402
import despierto  # noqa: E402
import lazo  # noqa: E402
import linux_yt  # noqa: E402


# --- no bloquear el PC ------------------------------------------------------------------------
class Proc:
    def __init__(self, cmd):
        self.cmd, self.vivo = cmd, True

    def poll(self):
        return None if self.vivo else 0

    def terminate(self):
        self.vivo = False

    def wait(self, _t=None):
        return 0

    def kill(self):
        self.vivo = False


class DespiertoLinux(unittest.TestCase):
    def mk(self, env, tiene):
        self.lanzados = []
        self.ordenes = []

        def popen(cmd, **_kw):
            p = Proc(cmd)
            self.lanzados.append(p)
            return p

        def run(cmd, **_kw):
            self.ordenes.append(cmd)
            return SimpleNamespace(stdout=self.locked, returncode=0)

        self.locked = "no\n"
        return despierto.Linux(which=lambda n: f"/usr/bin/{n}" if n in tiene else None, popen=popen, run=run, env=env)

    def test_gnome_primero_y_si_no_systemd(self):
        l = self.mk({"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}, {"gnome-session-inhibit", "systemd-inhibit"})
        self.assertEqual(l.command()[:3], ["gnome-session-inhibit", "--inhibit", "idle:suspend"])
        l = self.mk({"XDG_CURRENT_DESKTOP": "KDE"}, {"gnome-session-inhibit", "systemd-inhibit"})
        self.assertEqual(l.command()[:2], ["systemd-inhibit", "--what=idle:sleep"])
        self.assertEqual(l.command()[-2:], ["sleep", "infinity"])
        self.assertIsNone(self.mk({}, set()).command())

    def test_un_solo_inhibidor_y_se_suelta(self):
        l = self.mk({"XDG_CURRENT_DESKTOP": "GNOME", "XDG_SESSION_TYPE": "wayland"}, {"gnome-session-inhibit"})
        l.keep(True)
        l.keep(True)
        self.assertEqual(len(self.lanzados), 1)
        l.keep(False)
        self.assertFalse(self.lanzados[0].vivo)
        self.assertIsNone(l.proc)
        self.assertEqual(self.ordenes, [])  # en Wayland no hace falta xdg-screensaver
        self.assertEqual(l.idle_seconds(), 0.0)  # nunca el toque de ratón

    def test_x11_reinicia_salvapantallas(self):
        l = self.mk({"XDG_SESSION_TYPE": "x11"}, {"systemd-inhibit", "xdg-screensaver"})
        l.keep(True)
        self.assertIn(["xdg-screensaver", "reset"], self.ordenes)

    def test_sesion_bloqueada(self):
        l = self.mk({"XDG_SESSION_ID": "3"}, {"loginctl"})
        self.assertFalse(l.locked())
        self.locked = "yes\n"
        self.assertTrue(l.locked())
        self.assertIn(["loginctl", "show-session", "3", "-p", "LockedHint", "--value"], self.ordenes)

    def test_despierto_lo_usa(self):
        l = self.mk({"XDG_CURRENT_DESKTOP": "GNOME"}, {"gnome-session-inhibit"})
        clock = [1000.0]
        d = despierto.Despierto(system=l, file=Path(tempfile.mkdtemp()) / "a.json", clock=lambda: clock[0])
        d.on = True
        d.touch()
        self.assertTrue(d.tick()["activo"])
        clock[0] += despierto.VENTANA + 1
        self.assertFalse(d.tick()["activo"])
        self.assertFalse(self.lanzados[0].vivo)
        with mock.patch.object(despierto.sys, "platform", "linux"):
            self.assertTrue(despierto.Despierto(file=Path(tempfile.mkdtemp()) / "b.json").available())


# --- MPRIS ----------------------------------------------------------------------------------
class Mpris(unittest.TestCase):
    def run_fake(self, pos_after):
        self.cmds = []

        def run(cmd, timeout=4):
            self.cmds.append(cmd)
            if cmd[-1] == "position":
                return SimpleNamespace(returncode=0, stdout=f"{pos_after}\n")
            return SimpleNamespace(returncode=0, stdout="")

        return run

    def sesion(self, app):
        return mock.patch("medios.browser_session", lambda _t: {"app": app})

    def test_salto_exacto_comprobado(self):
        with mock.patch.object(control, "_which", lambda n: "/usr/bin/playerctl"), self.sesion("brave.instance42"):
            self.assertTrue(control._mpris_seek("Lentejas - YouTube", 125, run=self.run_fake(125.4), wait=lambda _s: None))
        self.assertEqual(self.cmds[0], ["playerctl", "-p", "brave.instance42", "position", "125.00"])
        with mock.patch.object(control, "_which", lambda n: "/usr/bin/playerctl"), self.sesion("brave.instance42"):
            self.assertFalse(control._mpris_seek("x", 125, run=self.run_fake(10), wait=lambda _s: None))

    def test_nombre_raro_no_pasa(self):
        with mock.patch.object(control, "_which", lambda n: "/usr/bin/playerctl"), self.sesion("brave; rm -rf ~"):
            self.assertFalse(control._mpris_seek("x", 5, run=self.run_fake(5), wait=lambda _s: None))
            self.assertFalse(control._mpris_pause("x", run=self.run_fake(5)))
        with mock.patch.object(control, "_which", lambda n: None):
            self.assertFalse(control._mpris_seek("x", 5))

    def test_pausa(self):
        with mock.patch.object(control, "_which", lambda n: "/usr/bin/playerctl"), self.sesion("chromium.instance7"):
            self.assertTrue(control._mpris_pause("x", run=self.run_fake(0)))
        self.assertEqual(self.cmds[-1], ["playerctl", "-p", "chromium.instance7", "pause"])

    def test_seek_en_linux_usa_mpris(self):
        row = {"id": "0x1", "title": "Lentejas - YouTube"}
        with mock.patch.object(control, "SYSTEM", "Linux"), \
                mock.patch.object(control, "_find_youtube_unlocked", lambda: row), \
                mock.patch.object(control, "_yt_state", lambda _r: {"pos": 1.0, "len": 600.0, "real": True, "playing": True}), \
                mock.patch.object(control, "_mpris_seek", lambda t, s: True), \
                mock.patch.object(control, "_yt_keys", lambda k: self.fail("sin teclas")):
            self.assertEqual(control.youtube("seek", {"to": 90})["via"], "mpris")


class Cursor(unittest.TestCase):
    def test_por_escritorio(self):
        todo = lambda n: n  # noqa: E731
        cmds = lambda d: [c[0] for c, _l in control.linux_cursor_commands(48, d, todo)]  # noqa: E731
        self.assertEqual(cmds("KDE")[0], "kwriteconfig6")
        self.assertEqual(control.linux_cursor_commands(48, "X-Cinnamon", todo)[0][0][2], "org.cinnamon.desktop.interface")
        self.assertEqual(control.linux_cursor_commands(48, "MATE", todo)[0][0][2], "org.mate.peripherals-mouse")
        self.assertEqual(cmds("XFCE")[0], "xfconf-query")
        self.assertEqual(control.linux_cursor_commands(96, "ubuntu:GNOME", todo)[-1][0],
                         ["gsettings", "set", "org.gnome.desktop.interface", "cursor-size", "96"])
        self.assertEqual(control.linux_cursor_commands(48, "KDE", lambda n: None), [])


# --- bandeja -------------------------------------------------------------------------------
LISTING = [{"id": "aa11", "state": "pendiente", "label": "Android", "ip": "192.168.1.5", "left": 50},
           {"id": "bb22", "state": "aprobado", "label": "iPhone", "ip": "192.168.1.6"}]


def ids(items):
    for it in items:
        if it[0] in ("item", "check"):
            yield it[1]
        elif it[0] == "sub":
            yield from ids(it[2])


class Bandeja(unittest.TestCase):
    def test_mismo_menu_que_windows(self):
        items = bandeja_linux.menu_items(LISTING, True, False)
        todos = list(ids(items))
        for i in todos:
            self.assertNotEqual(bandeja.resolve(i, LISTING)[0], "", i)
        acciones = {bandeja.resolve(i, LISTING)[0] for i in todos}
        for a in ("open", "qr", "cube", "accept", "reject", "kick", "kickall", "remember", "forget", "folder",
                  "bridge", "props", "autorun", "quit"):
            self.assertIn(a, acciones)
        textos = json.dumps(items, ensure_ascii=False)
        self.assertIn("Aceptar dispositivo pendiente: Android", textos)
        self.assertIn("Iniciar con el sistema", textos)
        self.assertIn('"check", 1009, "Recordar dispositivos", true', textos)

    def test_iconos(self):
        self.assertEqual(bandeja_linux.state(0)[0].name, "infinito-rojo.svg")
        self.assertEqual(bandeja_linux.state(2)[0].name, "infinito-verde.svg")
        for c in ("rojo", "verde", "naranja"):
            self.assertTrue(bandeja_linux.icon_path(c).is_file())

    def test_iniciar_con_el_sistema(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d}):
            self.assertFalse(bandeja_linux.autostart_enabled())
            bandeja_linux.set_autostart(True)
            f = Path(d) / "autostart" / "lazoo.desktop"
            txt = f.read_text(encoding="utf-8")
            self.assertIn("Name=LaZoo", txt)
            self.assertIn("bandeja_linux.py", txt)
            self.assertIn("--sin-ventana", txt)
            bandeja_linux.set_autostart(False)
            self.assertFalse(f.exists())
        with mock.patch.dict(os.environ, {"APPIMAGE": "/home/u/LaZoo it.AppImage"}):
            self.assertEqual(bandeja_linux.autostart_command(), "'/home/u/LaZoo it.AppImage'")

    def test_sin_escritorio_vuelve_a_la_consola(self):
        with mock.patch.object(bandeja_linux, "diagnose", lambda: {"gtk": False, "pantalla": False, "indicador": ""}):
            self.assertEqual(bandeja_linux.main([]), 2)
        self.assertIn("python3-gi", bandeja_linux.consejo({"gtk": False, "pantalla": True}))
        self.assertIn("AppIndicator", bandeja_linux.consejo({"gtk": True, "pantalla": True, "indicador": "x", "escritorio": "GNOME"}))
        with mock.patch.object(bandeja, "AVAILABLE", False), mock.patch.object(bandeja.sys, "platform", "linux"), \
                mock.patch.object(bandeja_linux, "main", lambda argv=None: 7):
            self.assertEqual(bandeja.main([]), 7)

    def test_iniciar_sh(self):
        sh = (ROOT / "iniciar.sh").read_text(encoding="utf-8")
        self.assertIn("venv --system-site-packages", sh)
        self.assertIn("python bandeja_linux.py", sh)
        self.assertIn('[ "$estado" -ne 2 ] && exit', sh)
        self.assertIn("exec python lazo.py", sh)
        for f in ("iniciar.sh", "instalar-linux.sh"):
            self.assertEqual(subprocess.run(["sh", "-n", str(ROOT / f)]).returncode, 0, f)
        inst = (ROOT / "instalar-linux.sh").read_text(encoding="utf-8")
        for pkg in ("gir1.2-ayatanaappindicator3-0.1", "playerctl", "python3-gobject", "libayatana-appindicator"):
            self.assertIn(pkg, inst)
        self.assertIn("¿Los instalo ahora con sudo? [s/N]", inst)  # pregunta antes de usar sudo


# --- AT-SPI de mentira ------------------------------------------------------------------------
class N:
    def __init__(self, role, name="", hijos=(), visible=True, activo=False, texto="", valor=None, al_pulsar=None):
        self.role, self.name, self.kids, self.vis, self.act = role, name, list(hijos), visible, activo
        self.txt, self.val, self.al_pulsar, self.parent = texto, valor, al_pulsar, None
        for k in self.kids:
            k.parent = self
        self.pulsado = 0


class T:
    def __init__(self, raiz):
        self.raiz = raiz

    def hijos(self, n):
        return list(n.kids)

    def padre(self, n):
        return n.parent

    def nombre(self, n):
        return n.name

    def rol(self, n):
        return n.role

    def visible(self, n):
        return n.vis

    def activo(self, n):
        return n.act

    def texto(self, n):
        return n.txt

    def valor(self, n):
        return n.val

    def pulsar(self, n):
        n.pulsado += 1
        if n.al_pulsar:
            n.al_pulsar()
        return True

    def escritorio(self):
        return self.raiz


def pagina():
    saltar = N("push button", "Saltar anuncio")
    vol = N("slider", "Volumen", valor=(35.0, 100.0))
    mute = N("push button", "Silenciar (m)")
    repro = N("section", "Reproductor de vídeo de YouTube", [saltar, vol, mute])
    si = N("push button", "Sí")
    aviso = N("dialog", "", [N("label", "¿Quieres seguir viendo?"), si])
    doc = N("document web", "Lentejas", [repro, aviso, N("entry", "Buscar", texto="lentejas")])
    barra = N("entry", "Barra de direcciones", texto="youtube.com/watch?v=dQw4w9WgXcQ")
    marco = N("frame", "Lentejas - YouTube - Brave", [N("tool bar", "", [barra]), doc], activo=True)
    brave = N("application", "Brave", [marco])
    otro = N("application", "gedit", [N("frame", "YouTube notas.txt")])
    raiz = N("desktop", "main", [otro, brave])
    saltar.al_pulsar = lambda: repro.kids.remove(saltar)
    si.al_pulsar = lambda: doc.kids.remove(aviso)
    return SimpleNamespace(raiz=raiz, saltar=saltar, si=si, doc=doc, repro=repro, vol=vol, mute=mute)


class AtSpi(unittest.TestCase):
    def setUp(self):
        self.p = pagina()
        self.t = T(self.p.raiz)
        self.sesiones = [{"app": "brave.instance1", "titulo": "Lentejas", "estado": "playing", "pos": 61.0, "len": 600.0,
                          "vel": 1.0, "saltar": True}]
        self.saltos = []
        self.l = linux_yt.Linux(arbol=self.t, sesiones=lambda: self.sesiones,
                                saltar=lambda titulo, s: self.saltos.append((titulo, s)) or True, espera=lambda _s: None)

    def test_ventana_y_barra(self):
        v = linux_yt.ventanas_youtube(self.t)
        self.assertEqual([x[1] for x in v], ["Lentejas - YouTube - Brave"])  # gedit no es navegador
        self.assertEqual(self.l.find_row(), {"id": "atspi", "title": "Lentejas - YouTube - Brave", "active": True})
        self.assertEqual(linux_yt.barra_direcciones(self.t, v[0][0]), "youtube.com/watch?v=dQw4w9WgXcQ")

    def test_barra_no_entra_en_la_pagina(self):
        self.p.doc.kids.append(N("entry", "x", texto="youtube.com/watch?v=AAAAAAAAAAA"))
        marco = linux_yt.ventanas_youtube(self.t)[0][0]
        marco.kids[0].kids.clear()  # sin barra fuera de la página
        self.assertEqual(linux_yt.barra_direcciones(self.t, marco), "")

    def test_anuncio_pulsado_y_verificado(self):
        r = self.l.anuncios("x")
        self.assertEqual((r["pulsado"], r["verificado"]), (True, True))
        self.assertEqual(self.p.saltar.pulsado, 1)
        self.assertEqual(self.l.anuncios("x")["pulsado"], False)  # ya no está

    def test_saltar_oculto_no_se_pulsa(self):
        self.p.saltar.vis = False
        self.assertFalse(self.l.anuncios("x")["pulsado"])

    def test_sigues_ahi(self):
        r = self.l.sigues("x")
        self.assertEqual((r["pulsado"], r["verificado"]), (True, True))

    def test_si_sin_aviso_no_se_pulsa(self):
        self.p.doc.kids.append(N("push button", "Sí"))
        self.p.doc.kids.remove(self.p.si.parent)
        self.assertFalse(self.l.sigues("x")["pulsado"])

    def test_ordenes_de_mando(self):
        vol = self.l.orden(json.dumps({"c": "vol", "hwnd": "1"}))
        self.assertEqual(vol["vol"], {"hay": True, "nivel": 35, "boton": "Silenciar (m)"})
        self.assertEqual(self.l.orden(json.dumps({"c": "url", "hwnd": "1"}))["url"], "youtube.com/watch?v=dQw4w9WgXcQ")
        ir = self.l.orden(json.dumps({"c": "ir", "titulo": "Lentejas - YouTube", "a": 125}))
        self.assertTrue(ir["verificado"])
        self.assertEqual(self.saltos, [("Lentejas - YouTube", 125.0)])
        self.assertFalse(self.l.orden("{roto")["ok"])

    def test_ordenes_de_patrocinios(self):
        mira = self.l.orden(json.dumps({"c": "mira", "hwnd": "atspi", "url": True, "foco": True}))
        self.assertEqual(mira["url"], "youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(mira["sesiones"][0]["app"], "brave.instance1")
        self.assertIsNone(mira["texto"])  # no se sabe: patrocinios no pulsa teclas
        salta = self.l.orden(json.dumps({"c": "salta", "app": "brave.instance1", "titulo": "Lentejas", "desde": 60, "hasta": 95}))
        self.assertEqual((salta["aceptado"], salta["verificado"], salta["antes"]), (True, True, 61.0))
        self.assertEqual(self.saltos[-1], ("Lentejas", 95.0))
        self.sesiones[0]["pos"] = 100.0
        fuera = self.l.orden(json.dumps({"c": "salta", "titulo": "Lentejas", "desde": 60, "hasta": 95}))
        self.assertTrue(fuera["fuera"])
        self.assertFalse(fuera["aceptado"])

    def test_patrocinios_entero_con_linux(self):
        import patrocinios

        p = patrocinios.Patrocinios(probe=self.l.orden, find=self.l.find_row, file=Path(tempfile.mkdtemp()) / "a.json",
                                    fetch=lambda vid: [{"desde": 60.0, "hasta": 95.0, "categoria": "sponsor"}])
        p.on = True
        with mock.patch.object(patrocinios, "validos", lambda lista, _len: lista), \
                mock.patch.object(patrocinios, "decidir", lambda *a, **k: {"accion": "saltar", "clave": "60", "desde": 60.0, "hasta": 95.0, "s": 0}):
            p.check_once()
        self.assertEqual(self.saltos[-1], ("Lentejas", 95.0))
        self.assertEqual(p.total, 1)

    def test_instalar_solo_en_linux_con_atspi(self):
        with mock.patch.object(linux_yt.sys, "platform", "win32"):
            self.assertFalse(linux_yt.instalar())
        with mock.patch.object(linux_yt.sys, "platform", "linux"), mock.patch.object(linux_yt, "Arbol", side_effect=ImportError):
            self.assertFalse(linux_yt.instalar())
        import anuncios, mando, patrocinios, sigues  # noqa: E401

        antes = (sigues.SIGUES.probe, sigues.SIGUES.find, anuncios.ANUNCIOS.probe, anuncios.ANUNCIOS.find,
                 patrocinios.PATROCINIOS.probe, patrocinios.PATROCINIOS.find, mando.MANDO.probe)
        try:
            with mock.patch.object(linux_yt.sys, "platform", "linux"), mock.patch.object(linux_yt, "Arbol", lambda: self.t):
                self.assertTrue(linux_yt.instalar())
                self.assertTrue(anuncios.ANUNCIOS.available())
                self.assertTrue(mando.MANDO.available())
                self.assertEqual(sigues.SIGUES.find(), "atspi")
                self.assertEqual(patrocinios.PATROCINIOS.find()["title"], "Lentejas - YouTube - Brave")
        finally:
            (sigues.SIGUES.probe, sigues.SIGUES.find, anuncios.ANUNCIOS.probe, anuncios.ANUNCIOS.find,
             patrocinios.PATROCINIOS.probe, patrocinios.PATROCINIOS.find, mando.MANDO.probe) = antes
            linux_yt.LINUX = None

    def test_consejos(self):
        self.assertIn("gir1.2-atspi-2.0", linux_yt.consejo({"atspi": False}))
        self.assertIn("toolkit-accessibility", linux_yt.consejo({"atspi": True, "playerctl": True, "youtube": "x", "pagina": False}))
        self.assertEqual(linux_yt.consejo({"atspi": True, "playerctl": True, "youtube": "x", "pagina": True}), "")

    def test_sin_internet(self):
        for f in ("linux_yt.py", "bandeja_linux.py"):
            src = (ROOT / f).read_text(encoding="utf-8")
            for prohibido in ("urllib", "urlopen", "socket", "http.client"):
                self.assertNotIn(prohibido, src, f)


class Paquete(unittest.TestCase):
    def test_ci_linux(self):
        ci = (ROOT / "ci" / "construir.yml").read_text(encoding="utf-8")
        self.assertIn("  linux:\n", ci)
        self.assertIn("needs: [exe, apk, linux]", ci)
        self.assertIn('LaZoo-$VER-linux.tar.gz', ci)
        self.assertIn("sh instalar-linux.sh", ci)


class Version(unittest.TestCase):
    def test_067(self):
        self.assertEqual(lazo.VERSION, "0.70")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.70")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("# LaZoo 0.70", readme)
        self.assertIn("**Novedad 0.67 (Linux):**", readme)
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for txt in ("linux_yt.py", "bandeja_linux.py", "test_v067.py"):
            self.assertIn(txt, agents)
        apk = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:versionName="3"', apk)  # la APK sirve igual para Windows y Linux


if __name__ == "__main__":
    unittest.main()
