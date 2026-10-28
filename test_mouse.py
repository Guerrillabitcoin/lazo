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
        data=json.dumps({"pin": lazo.PIN}).encode(),
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
    lazo.PIN = "123456"
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


if __name__ == "__main__":
    os.environ.setdefault("LAZO_TEST", "1")
    test_backends()
    test_spotify_skips_web()
    test_clipboard_memory()
    test_notes_order()
    test_mesa_and_small_cursor()
    test_photos_folder()
    test_youtube_speeds()
    test_hook_speed()
    test_live_channel()
    print("ok windows=sendinput macos=cgevent linux-x11=xtest linux-wayland=ydotool")
