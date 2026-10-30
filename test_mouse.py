"""Pruebas del cursor en Windows, macOS y Linux, y del canal rápido."""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import threading
import time
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


def _login(port: int) -> str:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/login",
        data=json.dumps({"pin": lazo.PAIRING.pin}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3) as res:
        cookie = res.headers.get("Set-Cookie", "")
    return cookie.split(";", 1)[0]


def _ws(port: int, cookie: str, frames: list[tuple[int, int]]) -> float:
    sock = socket.create_connection(("127.0.0.1", port), timeout=3)
    key = base64.b64encode(b"lazo-test-key-0001").decode()
    sock.sendall(
        (
            f"GET /ws HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\nCookie: {cookie}\r\n\r\n"
        ).encode()
    )
    head = b""
    while b"\r\n\r\n" not in head:
        head += sock.recv(256)
    if b"101" not in head.split(b"\r\n", 1)[0]:
        raise SystemExit(head[:180])
    mask = b"\x01\x02\x03\x04"
    started = time.perf_counter()
    for dx, dy in frames:
        payload = struct.pack("<ii", dx, dy)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        sock.sendall(bytes([0x82, 0x80 | len(payload)]) + mask + masked)
    sent_ms = (time.perf_counter() - started) * 1000
    time.sleep(0.05)
    sock.close()
    return sent_ms


def test_live_channel() -> None:
    seen: list[tuple[int, int]] = []
    control.set_move_hook(lambda dx, dy: seen.append((dx, dy)))
    lazo.PAIRING.pin = "123456"
    server = lazo.ThreadingHTTPServer(("127.0.0.1", 0), lazo.Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        cookie = _login(port)
        frames = [(3, -2), (8, 1), (-4, 6), (1, 1)] * 50
        elapsed = _ws(port, cookie, frames)
        deadline = time.perf_counter() + 1
        while len(seen) < len(frames) and time.perf_counter() < deadline:
            time.sleep(0.01)
        if seen != frames:
            raise SystemExit(f"ws desordenado o incompleto: {len(seen)}/{len(frames)}")
        print(f"websocket {len(frames)} movimientos: {elapsed:.2f} ms")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/move",
            data=json.dumps({"dx": 5, "dy": -3}).encode(),
            headers={"Content-Type": "application/json", "Cookie": cookie},
        )
        started = time.perf_counter()
        with urllib.request.urlopen(req, timeout=3) as res:
            res.read()
        http_ms = (time.perf_counter() - started) * 1000
        if seen[-1] != (5, -3):
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

    pairing = protocol.Pairing("4321")
    if pairing.pin != "4321" or len(protocol.Pairing("12").pin) != 4:
        raise SystemExit("PIN")
    for _ in range(protocol.MAX_FAILS - 1):
        if pairing.login("0000") != "mal":
            raise SystemExit("PIN malo aceptado")
    if pairing.login("0000") != "mal" or pairing.login("4321") != "espera":
        raise SystemExit("no bloqueó tras ocho fallos")
    pairing = protocol.Pairing("4321")
    if pairing.phone_online() or pairing.login("4321") != "ok" or not pairing.phone_online():
        raise SystemExit("señal de vida")
    pairing.phone_gone()
    if pairing.phone_online():
        raise SystemExit("el móvil no se fue")
    if not pairing.authed(None, f"a=b; lazo={pairing.token}") or not pairing.authed(pairing.token, None):
        raise SystemExit("no aceptó el token")
    if pairing.authed("x" * len(pairing.token), "lazo=") or pairing.authed(None, None):
        raise SystemExit("aceptó un token falso")
    if not pairing.phone_url("http", "192.168.1.2", 8787).startswith("http://192.168.1.2:8787/#p=4321&k="):
        raise SystemExit("dirección del QR")
    if protocol.ws_accept("dGhlIHNhbXBsZSBub25jZQ==") != "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=":
        raise SystemExit("saludo del websocket")
    print("protocolo: sello LZ2 de la 0.31, PIN, token y websocket")


def test_sealed_channel() -> None:
    seen: list[tuple[int, int]] = []
    control.set_move_hook(lambda dx, dy: seen.append((dx, dy)))
    lazo.PAIRING.pin = "123456"
    server = lazo.ThreadingHTTPServer(("127.0.0.1", 0), lazo.Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        cookie = _login(port)
        sock = socket.create_connection(("127.0.0.1", port), timeout=3)
        key = base64.b64encode(b"lazo-test-key-0002").decode()
        sock.sendall(
            (
                f"GET /ws HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                f"Sec-WebSocket-Version: 13\r\nCookie: {cookie}\r\n\r\n"
            ).encode()
        )
        head = b""
        while b"\r\n\r\n" not in head:
            head += sock.recv(256)
        mask = b"\x01\x02\x03\x04"
        for payload, opcode in ((lazo.PAIRING.seal(struct.pack("<ii", 7, -9)), 0x2), (b"2 3", 0x1)):
            masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
            sock.sendall(bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + masked)
        deadline = time.perf_counter() + 1
        while len(seen) < 2 and time.perf_counter() < deadline:
            time.sleep(0.01)
        sock.close()
        if seen != [(7, -9), (2, 3)]:
            raise SystemExit(f"websocket sellado: {seen}")
        print("websocket sellado y de texto")
    finally:
        server.shutdown()
        control.set_move_hook(None)


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
    test_sealed_channel()
    print("ok windows=sendinput macos=cgevent linux-x11=xtest linux-wayland=ydotool")
