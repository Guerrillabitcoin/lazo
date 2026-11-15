"""Pruebas de la 0.77: la dirección del QR no puede ser la de la VPN.

    python3 test_v077.py

El dueño: «en windows ahora aparece antes el enlace 10.2.0.2:8787 y no funciona la conexion con
la apk». Causa: `lan_ips()` ponía primera la IP de salida a internet (socket UDP a 8.8.8.8); con
ProtonVPN esa es la de la VPN, y con el PC por cable no había «Wi-Fi» delante.

1. Clasificación de interfaces (redes.py): Windows por IfType/nombre/descripción, Linux por nombre.
2. Orden: física con puerta de enlace > física > virtual > VPN; 192.168 > 10/172. La VPN nunca primera.
3. GetAdaptersAddresses: estructuras con los desplazamientos de iphlpapi.h (x64) y lectura de una
   lista enlazada hecha a mano; respaldo con `ipconfig /all` (español e inglés); /proc/net/route.
4. lazo: QR, /conectar, bandeja y PC a PC usan la física; el Panel recibe todas con su etiqueta,
   puede elegir otra (POST /api/red, solo loopback) y se recuerda; aviso de VPN.
5. Filtro de red local: el móvil entra por la IP física aunque haya VPN; regla de Windows profile=any.
6. Panel (mesa.html y docs/panel_prueba.py) y entrega (versión 0.77, APK sin cambios).
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

os.environ.setdefault("LAZO_DATOS", tempfile.mkdtemp())

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import aprobacion  # noqa: E402
import lazo  # noqa: E402
import redes  # noqa: E402

I = redes.interfaz
PROTON = I("10.2.0.2", "ProtonVPN", "vpn", "ProtonVPN", False, "ProtonVPN Tunnel")
CABLE = I("192.168.1.40", "Ethernet", "cable", "", True, "Realtek PCIe GbE Family Controller")
WIFI = I("192.168.1.41", "Wi-Fi", "wifi", "", True, "Intel(R) Wi-Fi 6 AX201")
HYPERV = I("172.29.48.1", "vEthernet (WSL)", "virtual", "Hyper-V", False, "Hyper-V Virtual Ethernet Adapter")

IPCONFIG_ES = """
Configuración IP de Windows

   Nombre de host. . . . . . . . . : DESKTOP-PRUEBA

Adaptador desconocido ProtonVPN:

   Sufijo DNS específico para la conexión. . :
   Descripción . . . . . . . . . . . . . . . : ProtonVPN Tunnel
   Dirección IPv4. . . . . . . . . . . . . . : 10.2.0.2(Preferido)
   Máscara de subred . . . . . . . . . . . . : 255.255.255.255
   Puerta de enlace predeterminada . . . . . : 0.0.0.0

Adaptador de Ethernet Ethernet:

   Descripción . . . . . . . . . . . . . . . : Realtek PCIe GbE Family Controller
   Dirección IPv4. . . . . . . . . . . . . . : 192.168.1.40(Preferido)
   Máscara de subred . . . . . . . . . . . . : 255.255.255.0
   Puerta de enlace predeterminada . . . . . : fe80::1%12
                                               192.168.1.1

Adaptador de Ethernet vEthernet (WSL):

   Descripción . . . . . . . . . . . . . . . : Hyper-V Virtual Ethernet Adapter
   Dirección IPv4. . . . . . . . . . . . . . : 172.29.48.1(Preferido)
   Puerta de enlace predeterminada . . . . . :
"""

IPCONFIG_EN = """
Unknown adapter WireGuard Tunnel:

   Description . . . . . . . . . . . : WireGuard Tunnel
   IPv4 Address. . . . . . . . . . . : 10.2.0.2(Preferred)
   Default Gateway . . . . . . . . . :

Wireless LAN adapter Wi-Fi:

   Description . . . . . . . . . . . : Intel(R) Wi-Fi 6 AX201 160MHz
   IPv4 Address. . . . . . . . . . . : 192.168.0.23(Preferred)
   Default Gateway . . . . . . . . . : 192.168.0.1
"""


class Clasificar(unittest.TestCase):
    def test_windows_por_iftype(self):
        self.assertEqual(redes.clasificar("Ethernet", "Realtek PCIe GbE", 6)[0], "cable")
        self.assertEqual(redes.clasificar("Wi-Fi", "Intel(R) Wi-Fi 6", 71)[0], "wifi")
        self.assertEqual(redes.clasificar("Conexión", "Algo", 23)[0], "vpn")  # PPP
        self.assertEqual(redes.clasificar("Túnel", "Algo", 131)[0], "vpn")
        self.assertEqual(redes.clasificar("Adaptador X", "Software", 53, "10.2.0.2"), ("vpn", "VPN"))
        self.assertEqual(redes.clasificar("Adaptador X", "Software", 53, "192.168.56.1")[0], "virtual")

    def test_windows_por_nombre(self):
        casos = {
            ("ProtonVPN", "ProtonVPN Tunnel"): ("vpn", "ProtonVPN"),
            ("Ethernet 3", "WireGuard Tunnel"): ("vpn", "WireGuard"),
            ("Ethernet 2", "TAP-Windows Adapter V9"): ("vpn", "OpenVPN"),
            ("OpenVPN Wintun", "Wintun Userspace Tunnel"): ("vpn", "OpenVPN"),
            ("Tailscale", "Tailscale Tunnel"): ("vpn", "Tailscale"),
            ("ZeroTier One [8056c2e21c]", "ZeroTier Virtual Port"): ("vpn", "ZeroTier"),
            ("NordLynx", "NordLynx Tunnel"): ("vpn", "NordVPN"),
            ("Mullvad", "Mullvad Tunnel"): ("vpn", "Mullvad"),
            ("vEthernet (Default Switch)", "Hyper-V Virtual Ethernet Adapter"): ("virtual", "Hyper-V"),
            ("vEthernet (WSL)", "Hyper-V Virtual Ethernet Adapter"): ("virtual", "Hyper-V"),
            ("VirtualBox Host-Only Network", "VirtualBox Host-Only Ethernet Adapter"): ("virtual", "VirtualBox"),
            ("VMware Network Adapter VMnet8", "VMware Virtual Ethernet Adapter"): ("virtual", "VMware"),
            ("vEthernet (Docker)", "Docker"): ("virtual", "Hyper-V"),
        }
        for (nombre, desc), esperado in casos.items():
            with self.subTest(nombre=nombre):
                self.assertEqual(redes.clasificar(nombre, desc, 6), esperado)

    def test_etiquetas(self):
        self.assertEqual(PROTON["label"], "VPN (ProtonVPN)")
        self.assertEqual(CABLE["label"], "Ethernet")
        self.assertEqual(WIFI["label"], "Wi-Fi")
        self.assertEqual(HYPERV["label"], "Virtual (Hyper-V)")
        self.assertEqual(redes.interfaz("10.8.0.2", "tun0", "vpn", "VPN")["label"], "VPN (tun0)")

    def test_linux_por_nombre(self):
        for n in ("tun0", "wg0", "tailscale0", "ztabcdef", "proton0", "pvpnksintrf0", "nordlynx", "ppp0"):
            self.assertEqual(redes.clasificar_linux(n)[0], "vpn", n)
        for n in ("docker0", "br-1a2b3c", "veth12ab", "virbr0", "vmnet8", "vboxnet0", "lo"):
            self.assertEqual(redes.clasificar_linux(n)[0], "virtual", n)
        for n in ("wlp3s0", "wlan0"):
            self.assertEqual(redes.clasificar_linux(n)[0], "wifi", n)
        for n in ("enp4s0", "eth0", "eno1"):
            self.assertEqual(redes.clasificar_linux(n)[0], "cable", n)


class Orden(unittest.TestCase):
    def test_vpn_nunca_primera(self):
        for lista in ([PROTON, CABLE], [PROTON, HYPERV, CABLE, WIFI], [PROTON, WIFI]):
            out = redes.ordenar(lista)
            self.assertNotEqual(out[0]["ip"], "10.2.0.2")
            self.assertEqual(out[-1]["ip"], "10.2.0.2")
            self.assertTrue(out[0]["qr"])

    def test_192_antes_que_10_fisicas(self):
        a = I("10.0.0.5", "Ethernet", "cable", "", True)
        b = I("192.168.1.5", "Wi-Fi", "wifi", "", True)
        self.assertEqual([x["ip"] for x in redes.ordenar([a, b])], ["192.168.1.5", "10.0.0.5"])
        # con puerta de enlace gana a una física sin ella
        c = I("192.168.137.1", "Conexión de área local* 2", "otra", "", False)
        self.assertEqual(redes.ordenar([c, a])[0]["ip"], "10.0.0.5")

    def test_virtual_antes_que_vpn_y_despues_de_fisica(self):
        out = [x["ip"] for x in redes.ordenar([PROTON, HYPERV, CABLE])]
        self.assertEqual(out, ["192.168.1.40", "172.29.48.1", "10.2.0.2"])

    def test_elegida_primera(self):
        out = redes.ordenar([PROTON, CABLE, WIFI], "192.168.1.41")
        self.assertEqual(out[0]["ip"], "192.168.1.41")
        self.assertTrue(out[0]["elegida"] and out[0]["qr"])
        # una IP elegida que ya no existe no rompe nada
        self.assertEqual(redes.ordenar([PROTON, CABLE], "192.168.9.9")[0]["ip"], "192.168.1.40")

    def test_sin_duplicados_y_solo_privadas(self):
        out = redes.ordenar([CABLE, I("192.168.1.40", "Red", "otra"), I("8.8.8.8", "x", "cable"), I("127.0.0.1", "lo", "virtual")])
        self.assertEqual([x["ip"] for x in out], ["192.168.1.40"])
        self.assertEqual(out[0]["label"], "Ethernet")


class Sistema(unittest.TestCase):
    def test_estructuras_iphlpapi(self):
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            self.skipTest("desplazamientos de x64")
        _s, u, g, a = redes.estructuras()
        self.assertEqual(a.FriendlyName.offset, 72)
        self.assertEqual(a.IfType.offset, 100)
        self.assertEqual(a.OperStatus.offset, 104)
        self.assertEqual(a.FirstGatewayAddress.offset, 208)
        self.assertEqual(u.Address.offset, 16)
        self.assertEqual(g.Address.offset, 16)

    def test_recorre_lista_enlazada(self):
        sa_t, u_t, g_t, a_t = redes.estructuras()
        guard = []

        def sockaddr(ip):
            sa = sa_t(family=2)
            for i, p in enumerate(ip.split(".")):
                sa.addr[i] = int(p)
            guard.append(sa)
            return ctypes.pointer(sa)

        def adapter(nombre, desc, iftype, ip, gw, up=1):
            ad = a_t()
            ad.FriendlyName, ad.Description, ad.IfType, ad.OperStatus = nombre, desc, iftype, up
            un = u_t()
            un.Address.lpSockaddr = sockaddr(ip)
            ad.FirstUnicastAddress = ctypes.pointer(un)
            if gw:
                gg = g_t()
                gg.Address.lpSockaddr = sockaddr(gw)
                ad.FirstGatewayAddress = ctypes.pointer(gg)
                guard.append(gg)
            guard.extend([ad, un])
            return ad

        a1 = adapter("ProtonVPN", "ProtonVPN Tunnel", 53, "10.2.0.2", None)
        a2 = adapter("Ethernet", "Realtek PCIe GbE Family Controller", 6, "192.168.1.40", "192.168.1.1")
        a3 = adapter("Wi-Fi", "Intel Wi-Fi", 71, "192.168.1.41", "192.168.1.1", up=2)  # apagada
        a1.Next = ctypes.pointer(a2)
        a2.Next = ctypes.pointer(a3)
        found = redes.recorre(ctypes.pointer(a1))
        self.assertEqual([(x["ip"], x["tipo"], x["puerta"]) for x in found],
                         [("10.2.0.2", "vpn", False), ("192.168.1.40", "cable", True)])
        self.assertEqual(redes.ordenar(found)[0]["ip"], "192.168.1.40")

    def test_ipconfig_es(self):
        out = redes.desde_ipconfig(IPCONFIG_ES)
        por_ip = {x["ip"]: x for x in out}
        self.assertEqual(por_ip["10.2.0.2"]["label"], "VPN (ProtonVPN)")
        self.assertTrue(por_ip["192.168.1.40"]["puerta"])
        self.assertEqual(por_ip["192.168.1.40"]["label"], "Ethernet")
        self.assertEqual(por_ip["172.29.48.1"]["tipo"], "virtual")
        self.assertEqual(redes.ordenar(out)[0]["ip"], "192.168.1.40")

    def test_ipconfig_en(self):
        out = redes.ordenar(redes.desde_ipconfig(IPCONFIG_EN))
        self.assertEqual([(x["ip"], x["label"]) for x in out],
                         [("192.168.0.23", "Wi-Fi"), ("10.2.0.2", "VPN (WireGuard)")])
        self.assertTrue(out[0]["puerta"])

    def test_linux_rutas(self):
        route = ("Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
                 "proton0\t00000000\t00000000\t0001\t0\t0\t0\t00000000\t0\t0\t0\n"
                 "enp4s0\t00000000\t0101A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
                 "enp4s0\t0001A8C0\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0\n"
                 "docker0\t000011AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0\n")
        puertas = redes.rutas_por_defecto(route)
        self.assertEqual(puertas, {"proton0", "enp4s0"})
        ipaddr = ("1: lo    inet 127.0.0.1/8 scope host lo\n"
                  "2: enp4s0    inet 192.168.1.50/24 brd 192.168.1.255 scope global enp4s0\n"
                  "3: docker0    inet 172.17.0.1/16 scope global docker0\n"
                  "5: proton0    inet 10.2.0.2/32 scope global proton0\n")
        out = redes.ordenar(redes.desde_ip_addr(ipaddr, puertas))
        self.assertEqual([x["ip"] for x in out], ["192.168.1.50", "172.17.0.1", "10.2.0.2"])
        self.assertEqual(out[-1]["label"], "VPN (ProtonVPN)")

    def test_sin_truco_udp(self):
        src = (ROOT / "lazo.py").read_text(encoding="utf-8")
        self.assertNotIn('sock.connect(("8.8.8.8", 80))', src)
        self.assertNotIn("8.8.8.8", (ROOT / "redes.py").read_text(encoding="utf-8"))

    def test_linux_sin_procesos(self):
        if not sys.platform.startswith("linux"):
            self.skipTest("Linux")
        with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("sin procesos")):
            out = redes.del_sistema()
        self.assertIsInstance(out, list)


class Lazo(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = (lazo._IPS_CACHE, list(lazo._IP_QR))
        lazo._IPS_CACHE = (0.0, [])
        lazo._IP_QR[:] = [""]
        self.p = mock.patch.object(lazo, "_ips_from_system_now", lambda: [PROTON, CABLE, WIFI, HYPERV])
        self.p.start()
        self.a = mock.patch.object(redes, "_ajustes", lambda: self.tmp / "ajustes.json")
        self.a.start()

    def tearDown(self):
        self.p.stop()
        self.a.stop()
        lazo._IPS_CACHE, qr = self.saved
        lazo._IP_QR[:] = qr
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_targets_sin_vpn(self):
        t = lazo.lan_targets()
        self.assertEqual(t[0], ("Wi-Fi", "192.168.1.41"))  # misma red que el móvil, como antes
        self.assertEqual(t[1], ("Ethernet", "192.168.1.40"))
        self.assertNotIn("10.2.0.2", [ip for _l, ip in t])
        self.assertNotIn("172.29.48.1", [ip for _l, ip in t])
        self.assertEqual(lazo.lan_ips()[0], "192.168.1.41")

    def test_caso_del_dueno_cable_y_protonvpn(self):
        """Windows por cable (sin Wi-Fi) y ProtonVPN: antes salía 10.2.0.2:8787 el primero."""
        with mock.patch.object(lazo, "_ips_from_system_now", lambda: redes.desde_ipconfig(IPCONFIG_ES)):
            lazo._IPS_CACHE = (0.0, [])
            self.assertEqual(lazo.lan_targets()[0], ("Ethernet", "192.168.1.40"))
            info = lazo.connection_info()
        self.assertEqual(info["targets"][0]["url"], "http://192.168.1.40:%d/" % lazo.PORT)
        self.assertEqual(info["redes"][-1]["label"], "VPN (ProtonVPN)")
        self.assertNotIn("10.2.0.2", lazo.connect_page().decode())

    def test_solo_vpn_se_ensena(self):
        with mock.patch.object(lazo, "_ips_from_system_now", lambda: [PROTON]):
            lazo._IPS_CACHE = (0.0, [])
            self.assertEqual(lazo.lan_targets(), [("VPN (ProtonVPN)", "10.2.0.2")])

    def test_conexion_lleva_todas_y_aviso(self):
        info = lazo.connection_info()
        self.assertEqual([r["label"] for r in info["redes"]], ["Wi-Fi", "Ethernet", "Virtual (Hyper-V)", "VPN (ProtonVPN)"])
        self.assertTrue(info["redes"][0]["qr"])
        self.assertEqual(info["targets"][0]["ip"], "192.168.1.41")
        self.assertEqual(info["vpn"], "ProtonVPN")
        self.assertIn("permitir red local", info["aviso_vpn"])
        self.assertIn("VPN activa", info["aviso_vpn"])
        self.assertTrue(info["redes"][0]["url"].endswith(":%d/" % lazo.PORT))

    def test_sin_vpn_sin_aviso(self):
        with mock.patch.object(lazo, "_ips_from_system_now", lambda: [CABLE]):
            lazo._IPS_CACHE = (0.0, [])
            info = lazo.connection_info()
        self.assertEqual(info["vpn"], "")
        self.assertEqual(info["aviso_vpn"], "")

    def test_elegir_y_recordar(self):
        out = lazo.elegir_ip("192.168.1.40")
        self.assertEqual(out["elegida"], "192.168.1.40")
        self.assertEqual(lazo.lan_targets()[0][1], "192.168.1.40")
        self.assertEqual(json.loads((self.tmp / "ajustes.json").read_text())["ip_qr"], "192.168.1.40")
        lazo._IP_QR[:] = []  # como al reiniciar
        self.assertEqual(lazo.ip_elegida(), "192.168.1.40")
        self.assertTrue(lazo.redes_lan()[0]["elegida"])
        lazo.elegir_ip("")
        self.assertEqual(lazo.lan_targets()[0][1], "192.168.1.41")
        self.assertNotIn("ip_qr", json.loads((self.tmp / "ajustes.json").read_text()))

    def test_elegir_no_vale_publica(self):
        for mala in ("8.8.8.8", "hola", "192.168.1.300"):
            with self.assertRaises(lazo.control.ControlError):
                lazo.elegir_ip(mala)

    def test_elegir_vpn_a_mano(self):
        lazo.elegir_ip("10.2.0.2")
        self.assertEqual(lazo.lan_targets()[0], ("VPN (ProtonVPN)", "10.2.0.2"))

    def test_conectar_y_pc_a_pc(self):
        html = lazo.connect_page().decode()
        self.assertIn("192.168.1.41", html)
        self.assertNotIn("10.2.0.2", html)
        src = (ROOT / "lazo.py").read_text(encoding="utf-8")
        self.assertIn('data["direcciones"] = [f"{ip}:{PORT}" for _label, ip in lan_targets()[:3]]', src)
        self.assertIn("lazo.lan_targets()", (ROOT / "bandeja.py").read_text(encoding="utf-8"))

    def test_diagnostico_dice_interfaz(self):
        self.assertIn("10.2.0.2 (VPN (ProtonVPN))", lazo.conn_diag())
        self.assertIn("192.168.1.41 (Wi-Fi, QR)", lazo.conn_diag())


class Servidor(unittest.TestCase):
    """POST /api/red solo desde la pantalla del PC; el móvil entra por la IP física con VPN."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = (lazo._IPS_CACHE, list(lazo._IP_QR))
        lazo._IPS_CACHE = (0.0, [])
        lazo._IP_QR[:] = [""]
        self.p = mock.patch.object(lazo, "_ips_from_system_now", lambda: [PROTON, CABLE])
        self.p.start()
        self.a = mock.patch.object(redes, "_ajustes", lambda: self.tmp / "ajustes.json")
        self.a.start()
        self.server = lazo.LazoServer(("0.0.0.0", 0), lazo.Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.p.stop()
        self.a.stop()
        lazo._IPS_CACHE, qr = self.saved
        lazo._IP_QR[:] = qr
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pide(self, path, body=None, host="127.0.0.1"):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"http://{host}:{self.port}{path}", data=data, method="POST" if data else "GET",
                                     headers={"X-Lazo-Local": "1", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.status, res.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def test_api_red_desde_el_panel(self):
        code, raw = self.pide("/api/red", {"ip": "192.168.1.40"})
        self.assertEqual(code, 200, raw)
        self.assertEqual(json.loads(raw)["elegida"], "192.168.1.40")
        code, raw = self.pide("/api/conexion")
        self.assertEqual(json.loads(raw)["elegida"], "192.168.1.40")
        code, raw = self.pide("/api/red", {"ip": "8.8.8.8"})
        self.assertGreaterEqual(code, 400)

    def test_api_red_no_desde_la_lan(self):
        mia = next((x["ip"] for x in redes.del_sistema() if x["tipo"] != "vpn"), "")
        if not mia:
            self.skipTest("sin IP privada en esta máquina")
        code, _raw = self.pide("/api/red", {"ip": "192.168.1.40"}, host=mia)
        self.assertEqual(code, 403)

    def test_movil_entra_por_ip_fisica_con_vpn(self):
        """El filtro mira la IP de origen: la del móvil (192.168.x) pasa, haya o no VPN en el PC."""
        self.addCleanup(lambda saved=list(aprobacion.EXTRA_NETS): aprobacion.EXTRA_NETS.__setitem__(slice(None), saved))
        aprobacion.EXTRA_NETS.clear()
        self.assertTrue(aprobacion.allowed("192.168.1.33"))
        self.assertTrue(aprobacion.allowed("::ffff:192.168.1.33"))
        self.assertFalse(aprobacion.allowed("8.8.8.8"))
        mia = next((x["ip"] for x in redes.del_sistema() if x["tipo"] != "vpn"), "")
        if not mia:
            self.skipTest("sin IP privada en esta máquina")
        code, _raw = self.pide("/", host=mia)  # como el móvil, por la IP física
        self.assertEqual(code, 200)

    def test_firewall_cualquier_perfil(self):
        ps = (ROOT / "permitir.ps1").read_text(encoding="utf-8")
        self.assertIn("localport=8787 profile=any", ps)
        self.assertNotIn("profile=private", ps.lower())


class Panel(unittest.TestCase):
    def test_mesa(self):
        html = (ROOT / "static" / "mesa.html").read_text(encoding="utf-8")
        for trozo in ('id="redes-lista"', 'id="vpn-aviso"', 'id="conn-vpn"', "function pintaRedes", '"/api/red"',
                      "Usar en el QR", "Automática", "Direcciones de este PC"):
            self.assertIn(trozo, html)

    def test_foto_panel(self):
        chrome = shutil.which("google-chrome") or shutil.which("chromium")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest("sin playwright")
        if not chrome:
            self.skipTest("sin Chrome")
        dest = Path(tempfile.mkdtemp())
        subprocess.run([sys.executable, str(ROOT / "docs" / "panel_prueba.py"), str(ROOT), str(dest)], check=True)
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=chrome, args=["--no-sandbox"])
            page = b.new_page(viewport={"width": 1400, "height": 1000})
            page.goto((dest / "mesa.html").as_uri())
            page.wait_for_selector("#redes-lista li")
            filas = page.locator("#redes-lista li").all_inner_texts()
            aviso = page.locator("#vpn-aviso").inner_text()
            visible = page.locator("#vpn-aviso").is_visible()
            out = os.environ.get("LAZO_FOTO_077")
            if out:
                page.locator("#redes-caja").scroll_into_view_if_needed()
                page.screenshot(path=out, full_page=True)
            b.close()
        self.assertEqual(len(filas), 3)
        self.assertIn("Ethernet", filas[0])
        self.assertIn("QR", filas[0])
        self.assertIn("VPN (ProtonVPN)", filas[2])
        self.assertIn("Usar en el QR", filas[2])
        self.assertTrue(visible)
        self.assertIn("permitir red local", aviso)


class Entrega(unittest.TestCase):
    def test_version(self):
        self.assertEqual(lazo.VERSION, "0.78")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.78")
        import pcapc
        self.assertEqual(pcapc.VERSION, "0.78")
        self.assertIn('PAGE_VERSION = "0.78"', (ROOT / "static" / "app.js").read_text(encoding="utf-8"))
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertTrue(readme.startswith("# LaZoo 0.78"))
        self.assertIn("Novedad 0.77", readme)
        self.assertIn("- 0.77", (ROOT / "AGENTS.md").read_text(encoding="utf-8"))

    def test_apk_sin_cambios(self):
        texto = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:versionCode="66"', texto)
        self.assertIn('android:versionName="3"', texto)
        r = subprocess.run(["git", "diff", "--quiet", "0d9dafc", "--", "android"], cwd=ROOT, capture_output=True)
        if r.returncode in (0, 1):
            self.assertEqual(r.returncode, 0, "android/ cambió: la APK dejaría de ser la App 3")


if __name__ == "__main__":
    unittest.main()
