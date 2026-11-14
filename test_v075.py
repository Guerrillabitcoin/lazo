"""Pruebas de la 0.75: en GNOME Wayland los iconos del dock ya no «bailan» con LaZoo abierto.

    python3 test_v075.py

Causa: el vigilante del portapapeles (control.ClipWatch) lanzaba `wl-paste` cada 1,5 s y en
GNOME wl-paste abre una ventanita para coger el foco, que salía y se iba del dock sin parar.
- Ningún bucle periódico de LaZoo lanza programas de portapapeles o con ventana (prueba con los
  hilos de verdad y Popen interceptado, y repaso del código de todos los bucles `while`).
- Bajo demanda (cambiar de PC, el móvil) wl-paste sigue valiendo.
- Registro de procesos lanzados (sinventana) y `linux_kvm.py --diagnostico`.
- APK sin cambios (App 3), versión 0.75.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("LAZO_DATOS", tempfile.mkdtemp())

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import control  # noqa: E402
import lazo  # noqa: E402
import linux_kvm  # noqa: E402
import pcapc  # noqa: E402
import sinventana  # noqa: E402

# Programas que no pueden lanzarse en bucle: portapapeles (en GNOME Wayland abren superficie) y
# cualquiera que abra ventana o notificación.
PROHIBIDOS_EN_BUCLE = ("wl-paste", "wl-copy", "xclip", "xsel", "zenity", "kdialog", "yad", "pkexec",
                       "xdg-open", "notify-send", "gnome-control-center", "xmessage", "xrandr")


class Espia:
    """Intercepta subprocess.Popen (y por tanto run/check_output): apunta y no lanza nada."""

    def __init__(self) -> None:
        self.lanzados: list[str] = []
        lanzados = self.lanzados

        def _init(_popen, *args, **kwargs):  # type: ignore[no-untyped-def]
            lanzados.append(sinventana._programa(args, kwargs))
            raise OSError("prueba: no se lanza nada")

        self._p = mock.patch.object(subprocess.Popen, "__init__", _init)

    def __enter__(self) -> "Espia":
        self._p.start()
        return self

    def __exit__(self, *exc) -> None:
        self._p.stop()

    def prohibidos(self) -> list[str]:
        return [p for p in self.lanzados if p in PROHIBIDOS_EN_BUCLE]


def entorno(**env: str):
    limpio = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "DISPLAY", "XDG_SESSION_TYPE")}
    limpio.update(env)
    return mock.patch.dict(os.environ, limpio, clear=True)


class GtkFalso:
    def __init__(self, texto: str) -> None:
        self.texto, self.lecturas = texto, 0

    def leer(self) -> str:
        self.lecturas += 1
        return self.texto


class VigilantePortapapeles(unittest.TestCase):
    def setUp(self) -> None:
        self._sys, self._gtk = control.SYSTEM, control.GTK_CLIP
        control.SYSTEM = "Linux"
        control.GTK_CLIP = None
        self.w = mock.patch.object(control, "_which", lambda name: True)  # wl-clipboard, xclip y xsel instalados
        self.w.start()

    def tearDown(self) -> None:
        self.w.stop()
        control.SYSTEM, control.GTK_CLIP = self._sys, self._gtk

    def correr_hilo(self, segundos: float = 0.3) -> tuple[control.ClipWatch, list[str]]:
        cw = control.ClipWatch(add=lambda t: None)
        cw.enabled = True
        cw.INTERVAL = 0.01
        with Espia() as espia:
            self.assertTrue(cw.start())
            time.sleep(segundos)
            cw.stop()
            cw._thread.join(1)
        return cw, espia.lanzados

    def test_gnome_wayland_el_bucle_no_lanza_wl_paste(self):
        with entorno(WAYLAND_DISPLAY="wayland-0", XDG_SESSION_TYPE="wayland", XDG_CURRENT_DESKTOP="ubuntu:GNOME"):
            cw, lanzados = self.correr_hilo()
            self.assertEqual(lanzados, [], "el vigilante del portapapeles lanzó procesos en bucle")
            self.assertFalse(cw.puede_sondear())
            self.assertIn("Wayland", cw.estado()["motivo"])

    def test_wayland_el_hilo_se_acaba_solo(self):
        with entorno(WAYLAND_DISPLAY="wayland-0"):
            cw = control.ClipWatch(add=lambda t: None)
            cw.enabled, cw.INTERVAL = True, 0.01
            with Espia() as espia:
                cw.start()
                cw._thread.join(1)
            self.assertFalse(cw._thread.is_alive())
            self.assertEqual(espia.lanzados, [])

    def test_xorg_sin_bandeja_no_lanza_xclip(self):
        with entorno(DISPLAY=":0", XDG_SESSION_TYPE="x11"):
            _cw, lanzados = self.correr_hilo()
            self.assertEqual(lanzados, [])

    def test_xorg_con_bandeja_lee_con_gtk_sin_procesos(self):
        gtk = GtkFalso("hola")
        control.GTK_CLIP = gtk
        vistos: list[str] = []
        with entorno(DISPLAY=":0", XDG_SESSION_TYPE="x11"):
            cw = control.ClipWatch(add=vistos.append)
            cw.enabled = True
            with Espia() as espia:
                self.assertTrue(cw.poll())
            self.assertEqual(espia.lanzados, [])
            self.assertEqual(vistos, ["hola"])
            self.assertGreater(gtk.lecturas, 0)
            self.assertTrue(cw.estado()["motivo"] == "")

    def test_wayland_con_gtk_tampoco(self):
        control.GTK_CLIP = GtkFalso("x")
        with entorno(WAYLAND_DISPLAY="wayland-0"):
            with Espia() as espia:
                self.assertEqual(control._read_clipboard_for_history(), "")
            self.assertEqual(espia.lanzados, [])

    def test_bajo_demanda_si_usa_wl_paste(self):
        """Al cambiar de PC (o desde el móvil) se lee una vez con wl-paste: eso no es un bucle."""
        with entorno(WAYLAND_DISPLAY="wayland-0"):
            with Espia() as espia:
                control._read_clipboard_text()
            self.assertEqual(espia.lanzados[:1], ["wl-paste"])

    def test_windows_y_mac_siguen_igual(self):
        control.SYSTEM = "Windows"
        self.assertTrue(control.ClipWatch.puede_sondear())
        control.SYSTEM = "Darwin"
        self.assertTrue(control.ClipWatch.puede_sondear())


def _fuentes() -> dict[str, ast.Module]:
    return {p.name: ast.parse(p.read_text(encoding="utf-8"))
            for p in sorted(ROOT.glob("*.py")) if not p.name.startswith("test_")}


def _nombre(llamada: ast.Call) -> str:
    f = llamada.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


def _malo(nodo: ast.AST) -> str:
    """Lo que un trozo de código hace mal si se ejecuta en bucle ("" = nada)."""
    for n in ast.walk(nodo):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in PROHIBIDOS_EN_BUCLE:
            return n.value
        if isinstance(n, ast.Call):
            nom = _nombre(n)
            if nom in ("Tk", "Toplevel"):
                return nom
            if nom == "_read_clipboard_text" and not any(k.arg == "sondeo" for k in n.keywords):
                return "_read_clipboard_text() sin sondeo=True"
    return ""


class NingunBucleLanzaVentanas(unittest.TestCase):
    """Repaso del código: todo bucle `while` (y lo que llama, hasta 4 niveles dentro del mismo
    módulo o de control.py) no puede lanzar programas de portapapeles/ventana."""

    # Bucles que no son periódicos: esperan a que llegue algo (petición del móvil, tecla).
    NO_PERIODICOS: set[tuple[str, str]] = set()

    def test_ningun_bucle(self):
        fuentes = _fuentes()
        defs: dict[str, dict[str, ast.AST]] = {}
        for mod, arbol in fuentes.items():
            d = defs.setdefault(mod, {})
            for n in ast.walk(arbol):
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    d.setdefault(n.name, n)
        malos = []
        for mod, arbol in fuentes.items():
            for fun in [n for n in ast.walk(arbol) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                for bucle in [n for n in ast.walk(fun) if isinstance(n, ast.While)]:
                    if (mod, fun.name) in self.NO_PERIODICOS:
                        continue
                    pendientes, vistos = [(bucle, 0)], set()
                    while pendientes:
                        nodo, nivel = pendientes.pop()
                        que = _malo(nodo) if nivel else ""
                        if not nivel:  # el propio bucle, sin entrar en otras funciones
                            que = _malo(ast.Module(body=bucle.body, type_ignores=[]))
                        if que:
                            malos.append(f"{mod}:{fun.name} (línea {bucle.lineno}) → {que}")
                            break
                        if nivel >= 4:
                            continue
                        for c in ast.walk(nodo):  # llamadas y también funciones pasadas por nombre
                            nom, donde = "", mod
                            if isinstance(c, ast.Attribute):
                                nom = c.attr
                                if isinstance(c.value, ast.Name) and c.value.id + ".py" in defs:
                                    donde = c.value.id + ".py"  # control._algo → control.py
                            elif isinstance(c, ast.Name):
                                nom = c.id
                            if nom and nom != "_read_clipboard_text":  # esa la juzga _malo según sondeo=
                                for m in (donde,):
                                    destino = defs.get(m, {}).get(nom)
                                    if destino is not None and (m, nom) not in vistos:
                                        vistos.add((m, nom))
                                        pendientes.append((destino, nivel + 1))
        self.assertEqual(malos, [], "bucles que lanzan programas con ventana o de portapapeles")

    def test_el_detector_ve_el_fallo_de_074(self):
        """El repaso habría pillado la 0.74: poll() → _read_clipboard_for_history() → _read_clipboard_text()."""
        viejo = ast.parse(
            "def _read_clipboard_text():\n    return _run(['wl-paste', '-n'])\n"
            "def _read_clipboard_for_history():\n    return _read_clipboard_text()\n"
        )
        f = viejo.body[1]
        self.assertEqual(_malo(f), "_read_clipboard_text() sin sondeo=True")
        self.assertEqual(_malo(viejo.body[0]), "wl-paste")


class HilosDeVerdad(unittest.TestCase):
    """Los hilos periódicos de LaZoo en un «Linux con GNOME Wayland» un rato: nada prohibido."""

    def test_hilos_periodicos(self):
        import despierto

        sys_, gtk = control.SYSTEM, control.GTK_CLIP
        control.SYSTEM, control.GTK_CLIP = "Linux", None
        try:
            with entorno(WAYLAND_DISPLAY="wayland-0", XDG_SESSION_TYPE="wayland", XDG_CURRENT_DESKTOP="ubuntu:GNOME"), \
                    mock.patch.object(control, "_which", lambda name: True), Espia() as espia:
                cw = control.ClipWatch(add=lambda t: None)
                cw.enabled, cw.INTERVAL = True, 0.01
                cw.start()
                d = despierto.Despierto()
                hilo = threading.Thread(target=lambda: [d.tick() for _ in range(20)], daemon=True)
                hilo.start()
                time.sleep(0.3)
                cw.stop()
                hilo.join(2)
            self.assertEqual(espia.prohibidos(), [])
        finally:
            control.SYSTEM, control.GTK_CLIP = sys_, gtk


class RegistroDeProcesos(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp()
        self.ruta = os.path.join(self.dir, "procesos.txt")

    def test_apunta_sin_argumentos(self):
        sinventana.install()
        with mock.patch.dict(os.environ, {"LAZO_REGISTRO_PROCESOS": self.ruta}):
            subprocess.run([sys.executable, "-c", "pass", "secreto-que-no-se-apunta"], check=True)
        texto = Path(self.ruta).read_text(encoding="utf-8")
        self.assertIn(os.path.basename(sys.executable), texto)
        self.assertNotIn("secreto", texto)
        self.assertTrue(any(p == os.path.basename(sys.executable) for _t, p, _h in sinventana.recientes(60)))

    def test_programa(self):
        self.assertEqual(sinventana._programa((["/usr/bin/wl-paste", "-n"],), {}), "wl-paste")
        self.assertEqual(sinventana._programa(("xdg-open http://x",), {"shell": True}), "xdg-open")
        self.assertEqual(sinventana._programa((), {"args": ["notify-send", "hola"]}), "notify-send")

    def test_diagnostico_lista_y_avisa(self):
        ahora = time.time()
        with open(self.ruta, "w", encoding="utf-8") as f:
            f.write("# LaZoo pid 123\n")
            for i in range(40):
                f.write(f"{ahora - i * 1.5:.3f}\twl-paste\tlazo-portapapeles\n")
            f.write(f"{ahora - 5:.3f}\tplayerctl\tThread-3\n")
            f.write(f"{ahora - 500:.3f}\tzenity\tviejo\n")
        r = linux_kvm.procesos_recientes(self.ruta, ahora=ahora)
        self.assertEqual(r["por_programa"]["wl-paste"]["veces"], 40)
        self.assertNotIn("zenity", r["por_programa"])
        self.assertEqual(r["sospechosos"], ["wl-paste"])
        texto = linux_kvm.texto_procesos(r)
        self.assertIn("wl-paste: 40 veces (hilos: lazo-portapapeles)", texto)
        self.assertIn("iconos del dock", texto)

    def test_diagnostico_sin_registro(self):
        r = linux_kvm.procesos_recientes(os.path.join(self.dir, "no"))
        self.assertFalse(r["hay_registro"])
        self.assertIn("sin registro", linux_kvm.texto_procesos(r))

    def test_texto_portapapeles(self):
        self.assertIn("apagado en Wayland", linux_kvm.texto_portapapeles({"WAYLAND_DISPLAY": "wayland-0"}))
        self.assertIn("GTK", linux_kvm.texto_portapapeles({"DISPLAY": ":0"}))

    def test_main_diagnostico(self):
        env = dict(os.environ, LAZO_REGISTRO_PROCESOS=self.ruta)
        r = subprocess.run([sys.executable, str(ROOT / "linux_kvm.py"), "--diagnostico"], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Historial automático del portapapeles", r.stdout)
        self.assertIn("Procesos lanzados por LaZoo", r.stdout)


class Entrega(unittest.TestCase):
    def test_version(self):
        self.assertEqual(lazo.VERSION, "0.76")
        self.assertEqual(pcapc.VERSION, "0.76")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.76")
        self.assertIn("Novedad 0.75", (ROOT / "README.md").read_text(encoding="utf-8"))

    def test_apk_sin_cambios(self):
        texto = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:versionName="3"', texto)
        r = subprocess.run(["git", "diff", "--quiet", "271efd4", "--", "android"], cwd=ROOT, capture_output=True)
        if r.returncode in (0, 1):
            self.assertEqual(r.returncode, 0, "android/ cambió: la APK dejaría de ser la App 3")


if __name__ == "__main__":
    unittest.main(verbosity=2)
