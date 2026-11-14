"""LaZoo 0.77: qué dirección de este PC se enseña al móvil (QR, Panel, bandeja, PC a PC).

Hasta la 0.76 la lista salía de `ipconfig` + «la IP con la que salgo a internet»
(un socket UDP hacia un servidor de internet). Con una VPN encendida (ProtonVPN, WireGuard, OpenVPN...)
la salida a internet va por la VPN, así que esa IP (p. ej. 10.2.0.2) se colaba la primera
en cuanto no había una «Wi-Fi» delante (PC por cable). El móvil no puede llegar a esa IP.

Ahora cada dirección lleva su interfaz y su tipo:

- Windows: GetAdaptersAddresses (ctypes, sin abrir procesos): IfType (6 Ethernet,
  71 Wi-Fi, 53 virtual, 23 PPP, 131 túnel), nombre, descripción y puerta de enlace.
  Si falla, se lee `ipconfig` como antes, pero clasificando en vez de descartar.
- Linux: nombres de interfaz (socket.if_nameindex + ioctl SIOCGIFADDR, sin procesos)
  y rutas por defecto de /proc/net/route. tun*, wg*, tailscale*, zt*, proton*... son VPN;
  docker*, br-*, veth*, virbr*, vmnet*... son virtuales.

Orden: físicas (Wi-Fi/Ethernet) con puerta de enlace, luego físicas sin ella, luego
virtuales y al final las VPN. Dentro de cada grupo, 192.168.x antes que 10.x/172.16-31.
Una VPN nunca va primera. El Panel enseña todas y deja elegir la del QR (`ip_qr` en
ajustes.json); si esa IP ya no existe, se vuelve al orden automático.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import struct
import sys
from pathlib import Path
from typing import Any, Iterable

IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
CLAVE = "ip_qr"
AVISO_VPN = ("Tienes una VPN activa; si el móvil no conecta, activa en la VPN "
             "\"permitir red local\".")

# IfType de Windows (ipifcons.h)
IF_ETHERNET = 6
IF_PPP = 23
IF_LOOPBACK = 24
IF_PROP_VIRTUAL = 53
IF_WIFI = 71
IF_TUNNEL = 131

# (palabra en nombre/descripción, nombre bonito). Se mira en minúsculas.
VPN_PALABRAS: tuple[tuple[str, str], ...] = (
    ("protonvpn", "ProtonVPN"), ("proton", "ProtonVPN"), ("wireguard", "WireGuard"),
    ("nordlynx", "NordVPN"), ("nordvpn", "NordVPN"), ("mullvad", "Mullvad"),
    ("openvpn", "OpenVPN"), ("tap-windows", "OpenVPN"), ("tap-protonvpn", "ProtonVPN"),
    ("wintun", "WireGuard"), ("tailscale", "Tailscale"), ("zerotier", "ZeroTier"),
    ("expressvpn", "ExpressVPN"), ("surfshark", "Surfshark"), ("cyberghost", "CyberGhost"),
    ("windscribe", "Windscribe"), ("hamachi", "Hamachi"), ("radmin", "Radmin VPN"),
    ("fortinet", "FortiClient"), ("forticlient", "FortiClient"), ("anyconnect", "Cisco AnyConnect"),
    ("globalprotect", "GlobalProtect"), ("pangp", "GlobalProtect"), ("warp", "Cloudflare WARP"),
    ("cloudflare", "Cloudflare WARP"), ("vpn", "VPN"),
)
VIRTUAL_PALABRAS: tuple[tuple[str, str], ...] = (
    ("hyper-v", "Hyper-V"), ("vethernet", "Hyper-V"), ("virtualbox", "VirtualBox"),
    ("vbox", "VirtualBox"), ("vmware", "VMware"), ("wsl", "WSL"), ("docker", "Docker"),
    ("npcap", "Npcap"), ("loopback", "Loopback"), ("bluetooth", "Bluetooth"),
    ("wan miniport", "WAN Miniport"), ("pseudo", "Virtual"), ("virtual", "Virtual"),
)
WIFI_PALABRAS = ("wi-fi", "wifi", "wlan", "wireless", "inalámbrica", "inalambrica", "802.11")
CABLE_PALABRAS = ("ethernet", "gigabit", "realtek pcie", "intel(r) ethernet", "lan")

# Linux: prefijos de nombre de interfaz
LINUX_VPN = (("tun", "VPN"), ("tap", "VPN"), ("wg", "WireGuard"), ("tailscale", "Tailscale"),
             ("zt", "ZeroTier"), ("proton", "ProtonVPN"), ("pvpn", "ProtonVPN"), ("nordlynx", "NordVPN"),
             ("nordtun", "NordVPN"), ("mullvad", "Mullvad"), ("ppp", "VPN"), ("ipsec", "VPN"),
             ("vti", "VPN"), ("gpd", "GlobalProtect"), ("cscotun", "Cisco AnyConnect"))
LINUX_VIRTUAL = (("docker", "Docker"), ("br-", "Docker"), ("veth", "Virtual"), ("virbr", "libvirt"),
                 ("vmnet", "VMware"), ("vboxnet", "VirtualBox"), ("lxcbr", "LXC"), ("lxdbr", "LXD"),
                 ("cni", "Kubernetes"), ("flannel", "Kubernetes"), ("podman", "Podman"), ("lo", "Loopback"))
LINUX_WIFI = ("wl", "wlan", "ath", "ra")
LINUX_CABLE = ("en", "eth", "em", "eno", "ens", "enp", "usb")


def privada(ip: str) -> bool:
    try:
        a, b, _c, _d = (int(part) for part in ip.split("."))
    except ValueError:
        return False
    return (a == 192 and b == 168) or a == 10 or (a == 172 and 16 <= b <= 31)


def _rango(ip: str) -> int:
    a, b = (int(part) for part in ip.split(".")[:2])
    if a == 192 and b == 168:
        return 0
    if a == 10 or (a == 172 and 16 <= b <= 31):
        return 1
    return 2


def _busca(texto: str, tabla: Iterable[tuple[str, str]]) -> str:
    low = texto.lower()
    for palabra, bonito in tabla:
        if palabra in low:
            return bonito
    return ""


def clasificar(nombre: str, descripcion: str = "", iftype: int | None = None, ip: str = "") -> tuple[str, str]:
    """(tipo, marca) con tipo en wifi|cable|vpn|virtual|otra. Windows y textos de ipconfig."""
    texto = f"{nombre} {descripcion}"
    vpn = _busca(texto, VPN_PALABRAS)
    if vpn:
        return "vpn", vpn
    if iftype in (IF_PPP, IF_TUNNEL):
        return "vpn", "VPN"
    virtual = _busca(texto, VIRTUAL_PALABRAS)
    if virtual:
        return "virtual", virtual
    if iftype == IF_PROP_VIRTUAL:
        # Adaptador «de software» sin nombre conocido. ProtonVPN reparte 10.2.0.x.
        return ("vpn", "VPN") if ip.startswith("10.2.0.") else ("virtual", "Virtual")
    if iftype == IF_LOOPBACK:
        return "virtual", "Loopback"
    if iftype == IF_WIFI:
        return "wifi", ""
    if iftype == IF_ETHERNET:
        return "cable", ""
    low = texto.lower()
    if any(p in low for p in WIFI_PALABRAS):
        return "wifi", ""
    if any(p in low for p in CABLE_PALABRAS):
        return "cable", ""
    if ip.startswith("10.2.0."):
        return "vpn", "VPN"
    return "otra", ""


def clasificar_linux(nombre: str) -> tuple[str, str]:
    low = nombre.lower()
    for pref, bonito in LINUX_VPN:
        if low.startswith(pref):
            return "vpn", bonito
    for pref, bonito in LINUX_VIRTUAL:
        if low == pref or (pref != "lo" and low.startswith(pref)):
            return "virtual", bonito
    if low.startswith(LINUX_WIFI):
        return "wifi", ""
    if low.startswith(LINUX_CABLE):
        return "cable", ""
    return "otra", ""


def etiqueta(tipo: str, marca: str, nombre: str) -> str:
    if tipo == "wifi":
        return "Wi-Fi"
    if tipo == "cable":
        return "Ethernet"
    if tipo == "vpn":
        return f"VPN ({marca})" if marca and marca != "VPN" else (f"VPN ({nombre[:24]})" if nombre else "VPN")
    if tipo == "virtual":
        return f"Virtual ({marca or nombre[:24]})"
    return (nombre or "Red")[:28]


def interfaz(ip: str, nombre: str, tipo: str, marca: str = "", puerta: bool = False, descripcion: str = "") -> dict:
    return {"ip": ip, "nombre": nombre, "descripcion": descripcion, "tipo": tipo, "marca": marca,
            "puerta": bool(puerta), "vpn": tipo == "vpn", "label": etiqueta(tipo, marca, nombre)}


_CLASE = {"wifi": 0, "cable": 0, "otra": 0, "virtual": 1, "vpn": 2}
_TIPO = {"wifi": 0, "cable": 1, "otra": 2, "virtual": 3, "vpn": 4}


def clave_orden(it: dict) -> tuple:
    clase = _CLASE.get(it["tipo"], 0)
    return (clase, 0 if it.get("puerta") else 1, _rango(it["ip"]), _TIPO.get(it["tipo"], 2), it["ip"])


def ordenar(lista: Iterable[dict], elegida: str = "") -> list[dict]:
    vistos: dict[str, dict] = {}
    for it in lista:
        ip = it.get("ip", "")
        if not privada(ip):
            continue
        antes = vistos.get(ip)
        # Si una IP sale dos veces (ctypes + getaddrinfo), gana la que sabe más.
        if antes is None or (antes["tipo"] == "otra" and it["tipo"] != "otra"):
            vistos[ip] = dict(it)
    out = sorted(vistos.values(), key=clave_orden)
    if elegida:
        for i, it in enumerate(out):
            if it["ip"] == elegida:
                out.insert(0, out.pop(i))
                break
    for i, it in enumerate(out):
        it["qr"] = i == 0
        it["elegida"] = bool(elegida) and it["ip"] == elegida
    return out


# ---- Windows: GetAdaptersAddresses -------------------------------------------------------

def estructuras():
    """Estructuras de iphlpapi.h (IP_ADAPTER_ADDRESSES_LH...) con tamaños fijos (ULONG = 32 bits)."""
    from ctypes import POINTER, Structure, Union, c_uint8, c_uint16, c_uint32, c_uint64, c_void_p, c_wchar_p, c_char_p, c_int

    class SOCKADDR(Structure):
        _fields_ = [("family", c_uint16), ("port", c_uint16), ("addr", c_uint8 * 4), ("zero", c_uint8 * 8)]

    class SOCKET_ADDRESS(Structure):
        _fields_ = [("lpSockaddr", POINTER(SOCKADDR)), ("iSockaddrLength", c_int)]

    class _LEN(Structure):
        _fields_ = [("Length", c_uint32), ("Flags", c_uint32)]

    class _HDR(Union):
        _fields_ = [("Alignment", c_uint64), ("s", _LEN)]

    class UNICAST(Structure):
        pass

    UNICAST._fields_ = [("h", _HDR), ("Next", POINTER(UNICAST)), ("Address", SOCKET_ADDRESS)]

    class GATEWAY(Structure):
        pass

    GATEWAY._fields_ = [("h", _HDR), ("Next", POINTER(GATEWAY)), ("Address", SOCKET_ADDRESS)]

    class ADAPTER(Structure):
        pass

    ADAPTER._fields_ = [
        ("h", _HDR), ("Next", POINTER(ADAPTER)), ("AdapterName", c_char_p),
        ("FirstUnicastAddress", POINTER(UNICAST)), ("FirstAnycastAddress", c_void_p),
        ("FirstMulticastAddress", c_void_p), ("FirstDnsServerAddress", c_void_p),
        ("DnsSuffix", c_wchar_p), ("Description", c_wchar_p), ("FriendlyName", c_wchar_p),
        ("PhysicalAddress", c_uint8 * 8), ("PhysicalAddressLength", c_uint32), ("Flags", c_uint32),
        ("Mtu", c_uint32), ("IfType", c_uint32), ("OperStatus", c_uint32), ("Ipv6IfIndex", c_uint32),
        ("ZoneIndices", c_uint32 * 16), ("FirstPrefix", c_void_p), ("TransmitLinkSpeed", c_uint64),
        ("ReceiveLinkSpeed", c_uint64), ("FirstWinsServerAddress", c_void_p),
        ("FirstGatewayAddress", POINTER(GATEWAY)),
    ]

    return SOCKADDR, UNICAST, GATEWAY, ADAPTER


def _windows_ctypes() -> list[dict]:
    import ctypes
    from ctypes import POINTER, c_uint32

    _sa, _u, _g, ADAPTER = estructuras()
    flags = 0x2 | 0x4 | 0x8 | 0x80  # sin anycast/multicast/dns, con puertas de enlace
    size = c_uint32(16 * 1024)
    iphlpapi = ctypes.WinDLL("iphlpapi")  # type: ignore[attr-defined]
    fn = iphlpapi.GetAdaptersAddresses
    fn.argtypes = [c_uint32, c_uint32, ctypes.c_void_p, ctypes.c_void_p, POINTER(c_uint32)]
    fn.restype = c_uint32
    for _ in range(4):
        buf = ctypes.create_string_buffer(size.value)
        res = fn(socket.AF_INET, flags, None, buf, ctypes.byref(size))
        if res == 111:  # ERROR_BUFFER_OVERFLOW
            continue
        if res != 0:
            return []
        break
    else:
        return []
    return recorre(ctypes.cast(buf, POINTER(ADAPTER)))


def recorre(ptr) -> list[dict]:
    """Lee la lista enlazada de IP_ADAPTER_ADDRESSES (solo adaptadores encendidos)."""
    found: list[dict] = []
    while ptr:
        ad = ptr.contents
        if ad.OperStatus == 1:  # IfOperStatusUp
            gw = False
            g = ad.FirstGatewayAddress
            while g:
                sa = g.contents.Address.lpSockaddr
                if sa and sa.contents.family == socket.AF_INET and bytes(sa.contents.addr) != b"\0\0\0\0":
                    gw = True
                g = g.contents.Next
            u = ad.FirstUnicastAddress
            while u:
                sa = u.contents.Address.lpSockaddr
                if sa and sa.contents.family == socket.AF_INET:
                    ip = ".".join(str(b) for b in sa.contents.addr)
                    nombre = ad.FriendlyName or ""
                    desc = ad.Description or ""
                    tipo, marca = clasificar(nombre, desc, int(ad.IfType), ip)
                    found.append(interfaz(ip, nombre, tipo, marca, gw, desc))
                u = u.contents.Next
        ptr = ad.Next
    return found


_GW_RE = re.compile(r"(puerta de enlace|default gateway|passerelle|gateway)", re.I)


def desde_ipconfig(texto: str) -> list[dict]:
    """Respaldo: bloques de `ipconfig`. La puerta de enlace puede venir en la línea siguiente."""
    found: list[dict] = []
    for block in re.split(r"\r?\n(?=\S)", texto):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        cab = lines[0].strip().rstrip(":")
        nombre = re.sub(r"^(adaptador de|adaptador|unknown adapter|ethernet adapter|wireless lan adapter|"
                        r"adaptador desconocido|adaptador de lan inalámbrica|adaptador de ethernet)\s+", "",
                        cab, flags=re.I).strip() or cab
        desc = ""
        ips: list[str] = []
        gw = False
        en_gw = False
        for line in lines[1:]:
            low = line.lower()
            if "descrip" in low and ":" in line:
                desc = line.split(":", 1)[1].strip()
            if "ipv4" in low:
                ips.extend(ip for ip in IP_RE.findall(line) if privada(ip))
                en_gw = False
            elif _GW_RE.search(line):
                gw = gw or bool(IP_RE.search(line.split(":", 1)[-1]))
                en_gw = True
            elif en_gw and ":" not in line and IP_RE.search(line):
                gw = True
            elif ":" in line:
                en_gw = False
        for ip in ips:
            tipo, marca = clasificar(cab, desc, None, ip)
            found.append(interfaz(ip, nombre, tipo, marca, gw, desc))
    return found


# ---- Linux / macOS -----------------------------------------------------------------------

def rutas_por_defecto(texto: str) -> set[str]:
    """Interfaces con ruta por defecto (Destination 00000000) en /proc/net/route."""
    out: set[str] = set()
    for line in texto.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 8 and parts[1] == "00000000" and parts[7] == "00000000":
            out.add(parts[0])
    return out


def desde_ip_addr(texto: str, puertas: set[str] | None = None) -> list[dict]:
    """`ip -4 -o addr`: «2: wlp3s0    inet 192.168.1.5/24 ...»."""
    found: list[dict] = []
    for line in texto.splitlines():
        m = re.match(r"\s*\d+:\s*([^\s:]+)\s+inet\s+((?:\d{1,3}\.){3}\d{1,3})", line)
        if m:
            nombre, ip = m.group(1).split("@", 1)[0], m.group(2)
            tipo, marca = clasificar_linux(nombre)
            found.append(interfaz(ip, nombre, tipo, marca, nombre in (puertas or set())))
    return found


def _linux_ioctl() -> list[dict]:
    import fcntl

    try:
        puertas = rutas_por_defecto(Path("/proc/net/route").read_text())
    except OSError:
        puertas = set()
    found: list[dict] = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for _idx, nombre in socket.if_nameindex():
            try:
                res = fcntl.ioctl(s.fileno(), 0x8915, struct.pack("256s", nombre.encode()[:15]))  # SIOCGIFADDR
            except OSError:
                continue
            ip = socket.inet_ntoa(res[20:24])
            tipo, marca = clasificar_linux(nombre)
            found.append(interfaz(ip, nombre, tipo, marca, nombre in puertas))
    finally:
        s.close()
    return found


def del_sistema() -> list[dict]:
    """Todas las IPv4 privadas con su interfaz (sin ordenar)."""
    found: list[dict] = []
    if sys.platform == "win32":
        try:
            found = _windows_ctypes()
        except Exception:  # noqa: BLE001
            found = []
        if not found:
            import subprocess

            import sinventana
            try:
                out = subprocess.check_output(["ipconfig", "/all"], stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                              timeout=3, text=True, errors="replace", creationflags=sinventana.flags())
                found = desde_ipconfig(out)
            except (OSError, subprocess.SubprocessError):
                found = []
    elif sys.platform.startswith("linux"):
        try:
            found = _linux_ioctl()
        except Exception:  # noqa: BLE001
            found = []
    if not found:
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ip = info[4][0]
                if privada(ip):
                    found.append(interfaz(ip, "Red", "otra"))
        except OSError:
            pass
    return [it for it in found if privada(it["ip"])]


# ---- elección guardada -------------------------------------------------------------------

def _ajustes() -> Path:
    import recordar

    return recordar.data_dir() / "ajustes.json"


def elegida(file: Path | None = None) -> str:
    try:
        data = json.loads((file or _ajustes()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    ip = data.get(CLAVE, "") if isinstance(data, dict) else ""
    return ip if isinstance(ip, str) and privada(ip) else ""


def guardar_elegida(ip: str, file: Path | None = None) -> str:
    """Guarda la IP del QR ("" = automática). Devuelve lo guardado."""
    ip = (ip or "").strip()
    if ip:
        ipaddress.IPv4Address(ip)  # ValueError si no es una IPv4
        if not privada(ip):
            raise ValueError("solo direcciones de la red local")
    path = file or _ajustes()
    import sigues  # mismo candado que el resto de ajustes.json

    with sigues._SAVE_LOCK:
        data: dict[str, Any] = {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        if ip:
            data[CLAVE] = ip
        else:
            data.pop(CLAVE, None)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    return ip
