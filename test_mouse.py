"""Pruebas del cursor en Windows, macOS y Linux, y del canal rápido."""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import threading
import time
import urllib.error
import urllib.request

import control
import lazo
import protocol


def test_backends() -> None:
    cases = {
        ("Windows", None, None): "sendinput",
        ("Darwin", None, None): "cgevent",
        ("Linux", ":0", None): "xtest",
        ("Linux", None, "wayland-0"): "ydotool",
        ("Linux", None, None): "none",
    }
    for (system, display, wayland), expect in cases.items():
        got = control.backend_for(system, display, wayland)
        if got != expect:
            raise SystemExit(f"{system} {display} {wayland}: {got} != {expect}")


def test_spotify_skips_web() -> None:
    web = {"title": "Canción - Spotify - Google Chrome", "process": "chrome.exe"}
    app = {"title": "Spotify Premium", "process": "Spotify.exe"}
    got = control.pick_spotify_window([web, app])
    if got is not app:
        raise SystemExit(f"eligió la web: {got}")
    if control.pick_spotify_window([web]) is not None:
        raise SystemExit("no ignoró Chrome")
    if control._windows_base(1) != 32 or control._windows_base(15) != 256:
        raise SystemExit("tamaño de cursor mal calculado")
    print("spotify nativo y cursor 32/256")


def test_clean_url() -> None:
    assert control.clean_url("ejemplo.com") == "https://ejemplo.com"
    assert control.clean_url("http://192.168.1.2/a") == "http://192.168.1.2/a"
    try:
        control.clean_url("javascript:alert(1)")
    except control.ControlError:
        print("direcciones de prueba")
        return
    raise SystemExit("aceptó una dirección rara")


def test_queue_order() -> None:
    tracks = ["a", "b", "c"]
    control.move_tracks(tracks, 2, -1)
    assert tracks == ["a", "c", "b"]
    control.move_tracks(tracks, 0, -1)
    assert tracks == ["a", "c", "b"]
    moved = control.spotify("queue_move", {"index": 0, "dir": 1})
    assert "tracks" in moved
    print("cola de prueba")


def test_clipboard_memory() -> None:
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    control.set_history_path(folder / "clips.json")
    control.clipboard_history("uno")
    again = control.clipboard_history("uno")
    if len(again["items"]) != 1:
        raise SystemExit("duplicó el mismo texto")
    saved = control.clipboard_history("dos\nlineas")
    texts = [item["text"] for item in saved["items"]]
    if texts != ["dos\nlineas", "uno"]:
        raise SystemExit(texts)
    control.set_history_path(folder / "clips.json")
    loaded = control.clipboard_history("   ")
    if [item["text"] for item in loaded["items"]] != ["dos\nlineas", "uno"]:
        raise SystemExit("no recordó el archivo")
    control.set_history_path(Path(__file__).with_name("clipboard-history.json"))
    print("portapapeles con historial")


def test_notes_order() -> None:
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    control.set_history_path(folder / "clips.json")
    control.clipboard_history("uno")
    control.clipboard_history("uno\r\n", auto=True)
    control.clipboard_history("dos")
    control.clipboard_history("tres")
    listed = [item["text"] for item in control.clipboard_history(None)["items"]]
    if listed != ["tres", "dos", "uno"]:
        raise SystemExit(listed)
    control.set_history_path(Path(__file__).with_name("clipboard-history.json"))
    print("notas sin duplicar y la última arriba")


def test_mesa_and_small_cursor() -> None:
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    control.set_files_dir(folder)
    saved = control.save_file("../nota.txt", b"hola")
    file_id = saved["file"]["id"]
    name, data = control.read_file(file_id)
    if data != b"hola" or "/" in name or "\\" in name:
        raise SystemExit(f"archivo inseguro: {name}")
    control.delete_file(file_id)
    control.delete_file("../secret")
    if control.list_files()["files"]:
        raise SystemExit("no borró el archivo")
    if control._windows_base(1) != 32 or control._windows_base(15) != 256:
        raise SystemExit("el cursor normal no es el pequeño")
    if control.scroll_steps(400) != -2 or control.scroll_steps(-400) != 2 or control.scroll_steps(0) != 0:
        raise SystemExit("el scroll sigue acumulando demasiado")
    print("mesa y cursor pequeño")


def test_photos_folder() -> None:
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    control.set_photos_dir(folder)
    first = control.start_photo("../IMG_1.jpg", 4)
    if first is None or first[1].parent != folder or first[1].name != "IMG_1.jpg":
        raise SystemExit(first)
    first[0].write_bytes(b"foto")
    control.finish_photo(first[0], first[1], 4)
    if control.photo_status("IMG_1.jpg", 4)["skip"] is not True:
        raise SystemExit("volvió a copiar la misma foto")
    second = control.start_photo("IMG_1.jpg", 5)
    if second is None or second[1].name != "IMG_1 (2).jpg":
        raise SystemExit(second)
    second[0].write_bytes(b"foto2")
    control.finish_photo(second[0], second[1], 5)
    names = sorted(path.name for path in folder.iterdir())
    if names != ["IMG_1 (2).jpg", "IMG_1.jpg"]:
        raise SystemExit(names)
    control.set_photos_dir(Path(__file__).with_name("Fotos"))
    print("fotos sin repetir")


def test_youtube_speeds() -> None:
    for raw, expected, ups in ((1, 1.0, 3), (1.25, 1.25, 4), (1.50, 1.5, 5), (2, 2.0, 7)):
        if control.match_youtube_speed(raw) != expected or control.youtube_speed_ups(raw) != ups:
            raise SystemExit(raw)
    try:
        control.match_youtube_speed(1.1)
    except control.ControlError:
        print("velocidades de YouTube")
        return
    raise SystemExit("aceptó una velocidad que no está")


def test_hook_speed() -> None:
    seen: list[tuple[int, int]] = []
    control.set_move_hook(lambda dx, dy: seen.append((dx, dy)))
    started = time.perf_counter()
    for i in range(1000):
        control.move_mouse(i % 7 - 3, 2)
    elapsed = (time.perf_counter() - started) * 1000
    control.set_move_hook(None)
    if len(seen) != 1000:
        raise SystemExit(f"faltan movimientos: {len(seen)}")
    if elapsed > 80:
        raise SystemExit(f"el gancho tardó {elapsed:.1f} ms")
    print(f"hook 1000 movimientos: {elapsed:.2f} ms")


def _ws_open(port: int, extra_head: str = "", query: str = "", host: str | None = None) -> tuple[socket.socket, bytes]:
    sock = socket.create_connection(("127.0.0.1", port), timeout=3)
    key = base64.b64encode(b"lazo-test-key-0001").decode()
    sock.sendall(
        (
            f"GET /ws{query} HTTP/1.1\r\nHost: {host or f'127.0.0.1:{port}'}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n{extra_head}\r\n"
        ).encode()
    )
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = sock.recv(256)
        if not chunk:
            break
        head += chunk
    return sock, head


def _ws_send(sock: socket.socket, payload: bytes, opcode: int = 0x2) -> None:
    mask = b"\x01\x02\x03\x04"
    masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    sock.sendall(bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + masked)


def _ws(port: int, frames: list[tuple[int, int]]) -> float:
    sock, head = _ws_open(port)
    if b"101" not in head.split(b"\r\n", 1)[0]:
        raise SystemExit(head[:180])
    started = time.perf_counter()
    for dx, dy in frames:
        _ws_send(sock, struct.pack("<ii", dx, dy))
    sent_ms = (time.perf_counter() - started) * 1000
    time.sleep(0.05)
    sock.close()
    return sent_ms


def _post(port: int, path: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=3) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_live_channel() -> None:
    seen: list[tuple[int, int]] = []
    control.set_move_hook(lambda dx, dy: seen.append((dx, dy)))
    server = lazo.ThreadingHTTPServer(("127.0.0.1", 0), lazo.Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        frames = [(3, -2), (8, 1), (-4, 6), (1, 1)] * 50
        elapsed = _ws(port, frames)
        deadline = time.perf_counter() + 1
        while len(seen) < len(frames) and time.perf_counter() < deadline:
            time.sleep(0.01)
        if seen != frames:
            raise SystemExit(f"ws desordenado o incompleto: {len(seen)}/{len(frames)}")
        print(f"websocket {len(frames)} movimientos: {elapsed:.2f} ms")
        body = json.dumps({"dx": 5, "dy": -3}).encode()
        started = time.perf_counter()
        status, _ = _post(port, "/api/move", body, {"Content-Type": "application/json", "X-Lazo-Local": "1"})
        http_ms = (time.perf_counter() - started) * 1000
        if status != 200 or seen[-1] != (5, -3):
            raise SystemExit("http no movió")
        print(f"http un movimiento: {http_ms:.2f} ms")
    finally:
        server.shutdown()
        control.set_move_hook(None)


def test_protocol() -> None:
    import tempfile
    from pathlib import Path

    key = bytes(range(32))
    plain = b'{"dx":3,"dy":-2} ni\xc3\xb1o' * 5
    # Sello producido por la 0.31: no puede cambiar de formato.
    old = bytes.fromhex(
        "4c5a326465666768696a6b6c6d6e6f44cf21cdeb07bb378e33246f022a4c311625fc7fd96166d08fea90f32ca3b9947"
        "43f94ae8df319259f092cecc40c7d784fe27ddd7a30f49cc0343f5d3e1cf093466c64979139b678aa960aef01d84c6f6"
        "bbcdfa41ba1c5627a9e977fe7ff14fed26341b28ef8440449d63f54e2896df50dd976e1825cdfad9190f7cf9935"
    )
    if protocol.open_sealed(old, key) != plain:
        raise SystemExit("el sello LZ2 ya no coincide con la 0.31")
    for size in (0, 1, 31, 32, 33, 1000):
        data = os.urandom(size)
        if protocol.open_sealed(protocol.seal(data, key), key) != data:
            raise SystemExit(f"sello de {size} bytes")
    bad = bytearray(old)
    bad[20] ^= 1
    try:
        protocol.open_sealed(bytes(bad), key)
        raise SystemExit("aceptó un sello roto")
    except protocol.ProtocolError:
        pass
    folder = Path(tempfile.mkdtemp())
    big = os.urandom(600 * 1024)
    blob = protocol.seal(big, key)
    import io

    protocol.open_sealed_to(io.BytesIO(blob), len(blob), folder / "x", key)
    if (folder / "x").read_bytes() != big:
        raise SystemExit("sello en trozos")

    pairing = protocol.Pairing("432101")
    if pairing.pin != "432101" or len(protocol.Pairing("1234").pin) != 6:
        raise SystemExit("PIN de 6 dígitos")
    for _ in range(protocol.MAX_FAILS):
        if pairing.login("000000") != "mal":
            raise SystemExit("PIN malo aceptado")
    if pairing.login("432101") != "espera":
        raise SystemExit("no bloqueó tras los fallos")
    pairing._locked_until = 0
    for _ in range(protocol.MAX_FAILS):
        pairing.login("000000")
    if pairing._locked_until - time.time() < 2 * protocol.LOCK_SECONDS - 2:
        raise SystemExit("el segundo bloqueo no dura el doble")
    pairing = protocol.Pairing("432101")
    if pairing.login("432101") != "ok":
        raise SystemExit("PIN bueno rechazado")
    pairing.note_phone("a")
    pairing.note_phone("b")
    pairing.phone_gone("a")
    if pairing.phone_count() != 1 or not pairing.phone_online():
        raise SystemExit("presencia por mando")
    pairing.phone_gone("b")
    if pairing.phone_online():
        raise SystemExit("el móvil no se fue")
    good = pairing.sign("POST", "/api/move", 40)
    ask = (pairing.verify, "POST", "/api/move", 40, good[protocol.H_T], good[protocol.H_N], good[protocol.H_S])
    if ask[0](*ask[1:]) != "ok" or ask[0](*ask[1:]) != "repetida":
        raise SystemExit("la firma debe valer una sola vez")
    for method, path, length in (("GET", "/api/move", 40), ("POST", "/api/otra", 40), ("POST", "/api/move", 41)):
        fresh = pairing.sign("POST", "/api/move", 40)
        if pairing.verify(method, path, length, fresh[protocol.H_T], fresh[protocol.H_N], fresh[protocol.H_S]) != "firma":
            raise SystemExit(f"aceptó una firma cambiada: {method} {path} {length}")
    late = pairing.sign("GET", "/api/status", 0, now=time.time() - 300)
    if pairing.verify("GET", "/api/status", 0, late[protocol.H_T], late[protocol.H_N], late[protocol.H_S]) != "hora":
        raise SystemExit("aceptó una firma vieja")
    other = protocol.Pairing("432101").sign("GET", "/api/status", 0)
    if pairing.verify("GET", "/api/status", 0, other[protocol.H_T], other[protocol.H_N], other[protocol.H_S]) != "firma":
        raise SystemExit("aceptó la firma de otro anfitrión")
    url = pairing.phone_url("http", "192.168.1.2", 8787)
    if not url.startswith("http://192.168.1.2:8787/#k=") or "p=" in url:
        raise SystemExit("dirección del QR")
    if protocol.ws_accept("dGhlIHNhbXBsZSBub25jZQ==") != "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=":
        raise SystemExit("saludo del websocket")
    print("protocolo: sello LZ2 de la 0.31, PIN, token y websocket")


def test_remote_security() -> None:
    """El móvil entra firmando; el propio PC pide cabecera y Host; nada de cookies."""
    seen: list[tuple[int, int]] = []
    control.set_move_hook(lambda dx, dy: seen.append((dx, dy)))
    pairing = lazo.PAIRING
    server = lazo.ThreadingHTTPServer(("127.0.0.1", 0), lazo.Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    real_loopback = lazo.Handler._loopback
    ident = "ab" * 8
    try:
        # El propio PC: sin cabecera, con un Host ajeno o con Origin ajeno, no entra.
        move = json.dumps({"dx": 1, "dy": 1}).encode()
        if _post(port, "/api/move", move, {"Content-Type": "application/json"})[0] != 401:
            raise SystemExit("una web ajena pudo mover el ratón")
        if _post(port, "/api/move", move, {"X-Lazo-Local": "1", "Host": "malo.example"})[0] != 401:
            raise SystemExit("aceptó un Host ajeno (DNS rebinding)")
        _sock, head = _ws_open(port, extra_head="Origin: http://malo.example\r\n")
        if b"401" not in head.split(b"\r\n", 1)[0]:
            raise SystemExit("aceptó un websocket de otra web")
        if seen:
            raise SystemExit("se movió el ratón sin permiso")

        # Un mando remoto.
        lazo.Handler._loopback = lambda self: False
        sealed = pairing.seal(move)
        path = "/api/move"

        def signed(length: int = len(sealed), nonce_from=None) -> dict[str, str]:
            return {"Content-Type": "application/octet-stream", protocol.H_ID: ident, **pairing.sign("POST", path, length)}

        headers = signed()
        status, _ = _post(port, path, sealed, headers)
        if status != 200 or seen != [(1, 1)]:
            raise SystemExit(f"el mando firmado no entró: {status}")
        if not pairing.phone_online():
            raise SystemExit("no anotó el mando")
        if _post(port, path, sealed, headers)[0] != 401:
            raise SystemExit("aceptó repetir una petición capturada")
        if _post(port, path, move, signed(len(move)))[0] != 400:
            raise SystemExit("aceptó un cuerpo sin sellar")
        if _post(port, path, sealed, {**signed(), "Cookie": "lazo=x"})[0] != 200:
            raise SystemExit("la cookie estorba")
        broken = signed()
        broken[protocol.H_S] = "0" * 64
        if _post(port, path, sealed, broken)[0] != 401:
            raise SystemExit("aceptó una firma falsa")
        if _post(port, path, sealed, {"Content-Type": "application/octet-stream"})[0] != 401:
            raise SystemExit("aceptó una petición sin firma")
        late = {**signed(), **pairing.sign("POST", path, len(sealed), now=time.time() - 300)}
        status, body = _post(port, path, sealed, late)
        if status != 401 or b"reloj" not in body:
            raise SystemExit("no avisó del reloj")

        # Websocket del mando: firmado por la consulta y con tramas selladas.
        sig = pairing.sign("GET", "/ws", 0)
        query = f"?i={ident}&t={sig[protocol.H_T]}&n={sig[protocol.H_N]}&s={sig[protocol.H_S]}"
        sock, head = _ws_open(port, query=query)
        if b"101" not in head.split(b"\r\n", 1)[0]:
            raise SystemExit(f"websocket firmado rechazado: {head[:80]}")
        _ws_send(sock, pairing.seal(struct.pack("<ii", 7, -9)))
        _ws_send(sock, struct.pack("<ii", 100, 100))  # sin sellar: corta
        _ws_send(sock, pairing.seal(struct.pack("<ii", 5, 5)))
        deadline = time.perf_counter() + 1
        while (7, -9) not in seen and time.perf_counter() < deadline:
            time.sleep(0.01)
        time.sleep(0.1)
        sock.close()
        if (7, -9) not in seen or (100, 100) in seen or (5, 5) in seen:
            raise SystemExit(f"websocket sellado: {seen}")
        _sock, head = _ws_open(port, query=query)
        if b"401" not in head.split(b"\r\n", 1)[0]:
            raise SystemExit("aceptó repetir el saludo del websocket")
        _sock, head = _ws_open(port)
        if b"401" not in head.split(b"\r\n", 1)[0]:
            raise SystemExit("aceptó un websocket sin firma")

        # PIN: da la clave una vez bien puesto, sin cookie.
        plain = {"Content-Type": "application/json"}
        status, _ = _post(port, "/api/login", json.dumps({"pin": "000000"}).encode(), plain)
        if status != 401:
            raise SystemExit("PIN malo")
        status, body = _post(port, "/api/login", json.dumps({"pin": pairing.pin}).encode(), plain)
        if status != 200 or json.loads(body)["key"] != pairing.key_text():
            raise SystemExit("el PIN no entregó la clave")
        print("remoto: firma única, sin cookie, sellado obligatorio, PC protegido de webs ajenas")
    finally:
        lazo.Handler._loopback = real_loopback
        server.shutdown()
        control.set_move_hook(None)


class _Patch:
    """Cambia atributos de control solo durante la prueba (nada toca el PC real)."""

    def __init__(self, **values):
        self.values = values
        self.old = {}

    def __enter__(self):
        for name, value in self.values.items():
            self.old[name] = getattr(control, name)
            setattr(control, name, value)
        return self

    def __exit__(self, *_exc):
        for name, value in self.old.items():
            setattr(control, name, value)


class _Done:
    def __init__(self, code: int = 0, out: str = ""):
        self.returncode = code
        self.stdout = out


def test_screens() -> None:
    text = (
        "Monitors: 3\n"
        " 0: +*HDMI-1 1920/530x1080/300+0+0  HDMI-1\n"
        " 1: +DP-1 2560/600x1440/340+1920+0  DP-1\n"
        " 2: +DP-2 1280/300x1024/250+4480+0  DP-2\n"
    )
    rows = control.parse_xrandr_monitors(text)
    assert [r["w"] for r in rows] == [1920, 2560, 1280]
    assert rows[0]["primary"] and not rows[1]["primary"]
    four = rows + [{"x": 9000, "y": 0, "w": 800, "h": 600, "primary": False}]
    control.set_screens_hook(lambda: [four[2], four[3], four[1], four[0]])
    try:
        screens = control.list_screens()
        assert len(screens) == 3, screens
        assert screens[0]["primary"] and screens[0]["n"] == 1
        assert [s["x"] for s in screens] == [0, 1920, 4480]
        info = control.screens_info()
        assert info["count"] == 3 and info["can_move"]
    finally:
        control.set_screens_hook(None)
    control.set_screens_hook(lambda: [rows[0]])
    try:
        assert control.screens_info()["can_move"] is False
        try:
            control.window_to_screen("0x1", 2)
            raise AssertionError("una sola pantalla no debe mover")
        except control.ControlError:
            pass
    finally:
        control.set_screens_hook(None)


def test_place_on_screen() -> None:
    screens = control._number_screens([
        {"x": 0, "y": 0, "w": 1920, "h": 1080, "wx": 0, "wy": 0, "ww": 1920, "wh": 1040, "primary": True},
        {"x": 1920, "y": 0, "w": 1280, "h": 720, "primary": False},
    ])
    assert control.place_on_screen((100, 50, 800, 600), screens, 2) == (2020, 50, 800, 600)
    # una ventana grande se ajusta a la pantalla pequeña
    assert control.place_on_screen((0, 0, 1900, 1000), screens, 2) == (1920, 0, 1280, 720)
    # y vuelve a la principal sin salirse del área útil
    assert control.place_on_screen((2500, 300, 400, 300), screens, 1) == (580, 300, 400, 300)
    try:
        control.place_on_screen((0, 0, 10, 10), screens, 3)
        raise AssertionError("pantalla 3 no existe")
    except control.ControlError:
        pass


def test_move_window_linux() -> None:
    calls = []

    def fake_run(cmd, timeout=4):
        calls.append(cmd)
        return _Done()

    two = [{"x": 0, "y": 0, "w": 1920, "h": 1080, "primary": True}, {"x": 1920, "y": 0, "w": 1920, "h": 1080, "primary": False}]
    control.set_screens_hook(lambda: two)
    try:
        with _Patch(SYSTEM="Linux", _run=fake_run, _which=lambda name: True):
            assert control.window_to_screen("0x04000007", 2) == "A la pantalla 2"
            assert ["wmctrl", "-i", "-r", "0x04000007", "-e", "0,1960,40,-1,-1"] in calls
            for bad in ("0", "4", "x"):
                try:
                    control.window_to_screen("0x04000007", bad)
                    raise AssertionError(bad)
                except control.ControlError:
                    pass
            calls.clear()
            control.window_action("0x04000007", "toggle_max")
            assert calls[-1][-1] == "toggle,maximized_vert,maximized_horz"
        with _Patch(SYSTEM="Darwin"):
            try:
                control.window_to_screen("App\t1", 2)
                raise AssertionError("mac no mueve")
            except control.ControlError as exc:
                assert "No disponible" in str(exc)
    finally:
        control.set_screens_hook(None)


def test_system_pill() -> None:
    seen = []
    with _Patch(SYSTEM="Windows", system_volume=lambda d: seen.append(("vol", d)) or "Volumen",
                _windows_brightness=lambda d: seen.append(("bright", d)) or "Brillo 60",
                _win_hotkey=lambda *vks: seen.append(("keys", vks))):
        control.system_action("vol_up")
        control.system_action("vol_down")
        control.system_action("vol_mute")
        assert control.system_action("bright_up")["detail"] == "Brillo 60"
        control.system_action("bright_down")
        control.system_action("project")
        assert control.system_caps()["project"] and control.system_caps()["brightness"]
    assert seen == [("vol", 1), ("vol", -1), ("vol", 0), ("bright", 10), ("bright", -10), ("keys", (0x5B, 0x50))], seen

    def no_bright(_d):
        raise control.ControlError("x")

    with _Patch(SYSTEM="Windows", _windows_brightness=no_bright):
        try:
            control.system_action("bright_up")
            raise AssertionError("debe avisar")
        except control.ControlError as exc:
            assert "no disponible" in str(exc).lower()
    calls = []
    with _Patch(SYSTEM="Linux", _which=lambda name: name == "loginctl", _run=lambda cmd, timeout=4: calls.append(cmd) or _Done()):
        for action in ("project", "bright_up"):
            try:
                control.system_action(action)
                raise AssertionError(action)
            except control.ControlError as exc:
                assert "No disponible" in str(exc) or "no disponible" in str(exc)
        assert control.system_action("lock")["detail"] == "PC bloqueado"
        assert calls == [["loginctl", "lock-session"]]
        caps = control.system_caps()
        assert caps["lock"] and not caps["project"] and not caps["brightness"]
    try:
        control.system_action("rm -rf")
        raise AssertionError("acción rara")
    except control.ControlError:
        pass
    assert "system" in lazo.ACTIONS and "screen" in lazo.ACTIONS


SAMPLE_INFO = {
    "id": "abc123", "title": "Vídeo de prueba", "duration": 125, "uploader": "Canal",
    "thumbnail": "https://i.example/t.jpg",
    "formats": [
        {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a", "filesize": 2000000},
        {"format_id": "251", "ext": "webm", "vcodec": "none", "acodec": "opus"},
        {"format_id": "18", "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "height": 360},
        {"format_id": "136", "ext": "mp4", "vcodec": "avc1", "acodec": "none", "height": 720, "filesize_approx": 9000000},
        {"format_id": "137", "ext": "mp4", "vcodec": "avc1", "acodec": "none", "height": 1080},
    ],
}

FAKE_YTDLP = r"""
import json, os, sys, time
args = sys.argv[1:]
if "--version" in args:
    print("2099.01.01"); sys.exit(0)
url = args[args.index("--") + 1]
if "-J" in args:
    print(%s); sys.exit(0)
out = args[args.index("-P") + 1]
steps = 200 if "lento" in url else 3
for i in range(steps):
    print("LZP %%d|%%d|NA|1000|%%d" %% ((i + 1) * 10, steps * 10, steps - i), flush=True)
    time.sleep(0.05 if "lento" in url else 0)
path = os.path.join(out, "Fake [abc123].mp4")
with open(path, "wb") as fh:
    fh.write(b"video-falso" * 10)
print("LZF " + path, flush=True)
"""


def test_descargatodo() -> None:
    """Descargatodo sin red: enlaces, orden como lista, formatos, cola, cancelar y firma."""
    import sys
    import tempfile
    from pathlib import Path

    import descargas

    good = descargas.check_url("  https://www.youtube.com/watch?v=abc  ")
    if good != "https://www.youtube.com/watch?v=abc":
        raise SystemExit("no aceptó un enlace https")
    for bad in ("-x", "--exec=calc", "file:///etc/passwd", "", "   ", "ftp://a/b", "https://a b",
                "javascript:alert(1)", "https://" + "a" * 2050, None, "http://"):
        try:
            descargas.check_url(bad)
        except descargas.DlError:
            continue
        raise SystemExit(f"aceptó un enlace malo: {bad!r}")

    tmp = Path(tempfile.mkdtemp(prefix="lazo-dl-"))
    fake = tmp / "fake_ytdlp.py"
    fake.write_text(FAKE_YTDLP.replace("%%", "%").replace("%s", repr(json.dumps(SAMPLE_INFO))), encoding="utf-8")
    real_cmd, real_ff, real_out = descargas.ytdlp_cmd, descargas.find_ffmpeg, descargas.QUEUE.out_dir
    descargas.ytdlp_cmd = lambda: [sys.executable, str(fake)]
    descargas.find_ffmpeg = lambda: None
    descargas.QUEUE.out_dir = tmp / "out"
    try:
        cmd = descargas.download_cmd("https://x.com/a/status/1", "best", tmp / "out")
        if not isinstance(cmd, list) or cmd[-2:] != ["--", "https://x.com/a/status/1"]:
            raise SystemExit(f"la URL no va tras --: {cmd[-3:]}")
        if "--no-playlist" not in cmd or "--ignore-config" not in cmd or any("cookies" in a for a in cmd):
            raise SystemExit("orden sin las protecciones")
        if descargas.info_cmd("https://a.example/v")[-2:] != ["--", "https://a.example/v"]:
            raise SystemExit("info sin --")
        for bad_choice in ("-x", "f:--exec", "f:a;b", "f:1+2+3", "loquesea"):
            try:
                descargas.selector(bad_choice, True)
            except descargas.DlError:
                continue
            raise SystemExit(f"aceptó un formato malo: {bad_choice}")
        if descargas.selector("720", False)[0] != ["-f", "b[height<=720]/b"]:
            raise SystemExit("sin ffmpeg debe pedir un solo archivo")
        try:
            descargas.selector("mp3", False)
            raise SystemExit("MP3 sin ffmpeg")
        except descargas.DlError:
            pass

        parsed = descargas.parse_info(SAMPLE_INFO)
        ids = [c["id"] for c in parsed["choices"]]
        if ids != ["best", "1080", "720", "480", "mp3", "audio"] or parsed["duration"] != 125:
            raise SystemExit(f"opciones simples: {ids}")
        if {f["id"] for f in parsed["formats"]} != {"140", "251", "18", "136", "137"}:
            raise SystemExit("faltan formatos avanzados")
        small = descargas.parse_info({"title": "x", "formats": [{"format_id": "1", "height": 480, "vcodec": "h264", "acodec": "aac"}]})
        if [c["id"] for c in small["choices"]] != ["best", "480", "mp3", "audio"]:
            raise SystemExit("ofreció calidades que no hay")
        info = descargas.get_info("https://www.youtube.com/watch?v=abc123")
        if info["title"] != "Vídeo de prueba":
            raise SystemExit("no leyó la salida de yt-dlp")

        out = tmp / "out"
        out.mkdir()
        inside = out / "a.mp4"
        inside.write_bytes(b"x")
        if descargas.safe_output(str(inside), out) != inside.resolve():
            raise SystemExit("rechazó un archivo bueno")
        outside = tmp / "fuera.mp4"
        outside.write_bytes(b"x")
        if descargas.safe_output(str(outside), out) or descargas.safe_output(str(out / ".." / "fuera.mp4"), out):
            raise SystemExit("aceptó un archivo fuera de Descargas/LaZoo")

        queue = descargas.QUEUE
        done = queue.start("https://www.youtube.com/watch?v=abc123", "720", "Prueba")["job"]["id"]
        slow = queue.start("https://www.youtube.com/watch?v=lento", "best", "Lenta")["job"]["id"]
        deadline = time.time() + 20
        state = {}
        while time.time() < deadline:
            state = {j["id"]: j for j in queue.status()["jobs"]}
            if state[done]["state"] == "hecha" and state[slow]["state"] == "descargando" and state[slow]["pct"] > 0:
                break
            time.sleep(0.05)
        if state[done]["state"] != "hecha" or state[done]["name"] != "Fake [abc123].mp4" or "720p" not in " ".join(descargas.download_cmd("https://a.b/c", "720", tmp)):
            raise SystemExit(f"la descarga falsa no terminó: {state[done]}")
        if "url" in state[done] or "path" in state[done]:
            raise SystemExit("el estado enseña rutas o enlaces")
        if queue.file(done).read_bytes() != b"video-falso" * 10:
            raise SystemExit("archivo equivocado")
        queue.cancel(slow)
        while time.time() < deadline and any(p.poll() is None for p in list(queue.procs.values())):
            time.sleep(0.05)
        time.sleep(0.2)
        if {j["id"]: j for j in queue.status()["jobs"]}[slow]["state"] != "cancelada":
            raise SystemExit("no canceló")

        # Endpoints: el móvil firma y sella; sin firma, nada.
        server = lazo.ThreadingHTTPServer(("127.0.0.1", 0), lazo.Handler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        real_loopback = lazo.Handler._loopback
        pairing = lazo.PAIRING
        try:
            for path in ("/api/dl/info", "/api/dl/start", "/api/dl/cancel", "/api/dl/install", "/api/dl/update", "/api/dl/open"):
                if _post(port, path, b"{}", {"Content-Type": "application/json"})[0] != 401:
                    raise SystemExit(f"{path} sin cabecera local")
            lazo.Handler._loopback = lambda self: False
            for path in ("/api/dl/tools", "/api/dl/status", "/api/dl/file/" + done):
                req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
                try:
                    urllib.request.urlopen(req, timeout=5)
                    raise SystemExit(f"{path} sin firma")
                except urllib.error.HTTPError as exc:
                    if exc.code != 401:
                        raise SystemExit(f"{path}: {exc.code}")
            body = pairing.seal(json.dumps({"url": "https://www.youtube.com/watch?v=abc123"}).encode())
            headers = {"Content-Type": "application/octet-stream", "X-Seal": "1", protocol.H_ID: "cd" * 8, **pairing.sign("POST", "/api/dl/info", len(body))}
            status, raw = _post(port, "/api/dl/info", body, headers)
            if status != 200 or json.loads(pairing.open(raw))["title"] != "Vídeo de prueba":
                raise SystemExit(f"info firmada: {status}")
            plain = json.dumps({"url": "-x"}).encode()
            if _post(port, "/api/dl/info", plain, {protocol.H_ID: "cd" * 8, **pairing.sign("POST", "/api/dl/info", len(plain))})[0] != 400:
                raise SystemExit("aceptó cuerpo sin sellar")
            path = "/api/dl/file/" + done
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"X-Seal": "1", protocol.H_ID: "cd" * 8, **pairing.sign("GET", path, 0)})
            got = urllib.request.urlopen(req, timeout=5).read()
            if not got.startswith(protocol.MAGIC) or pairing.open(got) != b"video-falso" * 10:
                raise SystemExit("el archivo no llegó sellado")
        finally:
            lazo.Handler._loopback = real_loopback
            server.shutdown()
        print("descargatodo: enlaces validados, orden en lista con --, formatos, cola, cancelar y firma")
    finally:
        descargas.ytdlp_cmd, descargas.find_ffmpeg, descargas.QUEUE.out_dir = real_cmd, real_ff, real_out


if __name__ == "__main__":
    os.environ.setdefault("LAZO_TEST", "1")
    test_backends()
    test_spotify_skips_web()
    test_clean_url()
    test_queue_order()
    test_clipboard_memory()
    test_notes_order()
    test_mesa_and_small_cursor()
    test_photos_folder()
    test_youtube_speeds()
    test_hook_speed()
    test_live_channel()
    test_protocol()
    test_remote_security()
    test_screens()
    test_place_on_screen()
    test_move_window_linux()
    test_system_pill()
    test_descargatodo()
    print("ok windows=sendinput macos=cgevent linux-x11=xtest linux-wayland=ydotool")
