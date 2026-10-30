"""Pruebas de la cola de Descargatodo con un yt-dlp falso (sin internet)."""

import sys
import tempfile
import time
import unittest
from pathlib import Path

import descargas

FAKE = r'''
import sys, time, os
args = sys.argv[1:]
url = args[-1]
out = args[args.index("-P") + 1]
if "hang" in url:
    print("[generic] abc12345: Downloading webpage", flush=True)
    time.sleep(120)
if "boom" in url:
    print("ERROR: Requested format is not available", flush=True)
    sys.exit(1)
if "slow" in url:
    print("[generic] slow1234: Downloading webpage", flush=True)
    open(os.path.join(out, "x [slow1234].mp4.part"), "w").write("x")
    for i in range(200):
        print("LZP %d|1000|NA|10|5" % i, flush=True)
        time.sleep(0.1)
if "--encoding" not in args:
    print("ERROR: falta --encoding utf-8", flush=True)
    sys.exit(1)
if "garbled" in url:
    # yt-dlp en Windows escribía la ruta en la página de códigos de la consola: LaZoo no la
    # reconocía y decía «No salió ningún archivo» aunque el vídeo estaba bajado.
    print("[twitter] 99999: Downloading guest token", flush=True)
    real = os.path.join(out, "NASA \u2019 DART [88888].mp4")
    open(real, "w").write("video")
    print("LZF " + real.replace("\u2019", "?"), flush=True)
    sys.exit(0)
if "youtube.com" in url:
    client = args[args.index("--extractor-args") + 1] if "--extractor-args" in args else ""
    print("[youtube] botbotbotbo: Downloading webpage", flush=True)
    if "always" in url or "mweb" not in client:
        print("ERROR: [youtube] botbotbotbo: Sign in to confirm you\u2019re not a bot. Use --cookies", flush=True)
        sys.exit(1)
path = os.path.join(out, "ok [ok123456].mp4")
open(path, "w").write("video")
print("LZP 1000|1000|NA|10|0", flush=True)
print("LZF " + path, flush=True)
'''


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        fake = Path(self.tmp.name) / "fake.py"
        fake.write_text(FAKE, encoding="utf-8")
        self.old = (descargas.find_ytdlp, descargas.find_ffmpeg, descargas.find_deno)
        descargas.find_ytdlp = lambda: [sys.executable, str(fake)]
        descargas.find_ffmpeg = lambda: None
        descargas.find_deno = lambda: None
        self.q = descargas.Queue()
        self.q.out_dir = Path(self.tmp.name) / "out"
        self.q.idle_limit = 2

    def tearDown(self):
        descargas.find_ytdlp, descargas.find_ffmpeg, descargas.find_deno = self.old
        for job in list(self.q.jobs):
            self.q.cancel(job["id"])
        for proc in list(self.q.procs.values()):
            descargas._kill_tree(proc)
        time.sleep(0.3)
        self.tmp.cleanup()

    def wait(self, job_id, states, limit=15):
        end = time.time() + limit
        while time.time() < end:
            job = next((j for j in self.q.jobs if j["id"] == job_id), None)
            if job and job["state"] in states:
                return job
            time.sleep(0.1)
        self.fail(f"no llegó a {states}: {job}")

    def test_norm_url(self):
        n = descargas.norm_url
        self.assertEqual(n("https://www.youtube.com/watch?v=jNQXAC9IVRw&t=3s"), "yt:jNQXAC9IVRw")
        self.assertEqual(n("https://youtu.be/jNQXAC9IVRw?si=abc"), "yt:jNQXAC9IVRw")
        self.assertEqual(n("https://m.youtube.com/shorts/jNQXAC9IVRw"), "yt:jNQXAC9IVRw")
        self.assertEqual(n("https://twitter.com/a/status/123?s=20"), n("https://x.com/b/status/123"))
        self.assertEqual(n("https://ex.com/v?utm_source=x&id=2"), "ex.com/v?id=2")

    def test_duplicate(self):
        a = self.q.start("https://ex.com/slow?si=1", "best")
        with self.assertRaisesRegex(descargas.DlError, "Ya está en la cola"):
            self.q.start("https://ex.com/slow?si=2", "best")
        self.q.start("https://ex.com/slow", "audio")  # otro formato sí
        self.q.cancel(a["job"]["id"])

    def test_ok_and_duplicate_done(self):
        a = self.q.start("https://ex.com/ok", "best")
        job = self.wait(a["job"]["id"], ("hecha", "error"))
        self.assertEqual(job["state"], "hecha", job)
        with self.assertRaises(descargas.DlError):
            self.q.start("https://ex.com/ok", "best")

    def test_cancel_removes_and_cleans(self):
        a = self.q.start("https://ex.com/slow", "best")
        self.wait(a["job"]["id"], ("descargando",))
        time.sleep(0.3)
        self.q.cancel(a["job"]["id"])
        self.assertFalse(any(j["id"] == a["job"]["id"] for j in self.q.jobs))
        time.sleep(2)
        self.assertEqual([p.name for p in self.q.out_dir.glob("*.part")], [])
        b = self.q.start("https://ex.com/ok", "best")
        self.assertEqual(self.wait(b["job"]["id"], ("hecha", "error"))["state"], "hecha")

    def test_many_cancel_then_works(self):
        ids = [self.q.start(f"https://ex.com/slow/{i}", "best")["job"]["id"] for i in range(5)]
        for i in ids:
            self.q.cancel(i)
        b = self.q.start("https://ex.com/ok2", "best")
        self.assertEqual(self.wait(b["job"]["id"], ("hecha", "error"))["state"], "hecha")

    def test_error_then_next(self):
        a = self.q.start("https://ex.com/boom", "best")
        b = self.q.start("https://ex.com/ok", "best")
        ja = self.wait(a["job"]["id"], ("error",))
        self.assertIn("formato", ja["error"])
        self.assertEqual(self.wait(b["job"]["id"], ("hecha", "error"))["state"], "hecha")

    def test_idle_timeout(self):
        a = self.q.start("https://ex.com/hang", "best")
        job = self.wait(a["job"]["id"], ("error",), 20)
        self.assertIn("Sin avance", job["error"])

    def test_worker_recovers(self):
        orig = self.q._run
        calls = []

        def broken(job):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("fallo raro")
            return orig(job)
        self.q._run = broken
        a = self.q.start("https://ex.com/ok", "best")
        self.assertEqual(self.wait(a["job"]["id"], ("error",))["error"], "fallo raro")
        b = self.q.start("https://ex.com/ok3", "best")
        self.assertEqual(self.wait(b["job"]["id"], ("hecha", "error"))["state"], "hecha")
        # Si el hilo muere, status() lo vuelve a levantar.
        self.q.worker = None
        self.q.status()
        self.assertTrue(self.q.worker.is_alive())


    # --- 0.41: lo que pasaba en el PC real ---

    def test_path_with_bad_encoding_still_found(self):
        a = self.q.start("https://x.com/NASA/status/1574539270987173903?garbled", "best")
        job = self.wait(a["job"]["id"], ("hecha", "error"))
        self.assertEqual(job["state"], "hecha", job)
        self.assertIn("DART", job["name"])

    def test_youtube_bot_check_falls_back_to_other_client(self):
        a = self.q.start("https://www.youtube.com/watch?v=botbotbotbo", "best")
        job = self.wait(a["job"]["id"], ("hecha", "error"), 20)
        self.assertEqual(job["state"], "hecha", job)

    def test_youtube_bot_check_real_error_shown(self):
        a = self.q.start("https://www.youtube.com/watch?v=botbotbotbo&always=1", "best")
        job = self.wait(a["job"]["id"], ("error",), 20)
        self.assertIn("deno", job["error"])  # sin deno lo dice claro
        self.assertIn("bot", job["error"])
        self.assertTrue(job["update"])
        descargas.find_deno = lambda: "/x/deno"
        b = self.q.start("https://www.youtube.com/watch?v=botbotbotbo&always=2", "720")
        job = self.wait(b["job"]["id"], ("error",), 20)
        self.assertNotIn("deno", job["error"])
        self.assertIn("no eres un bot", job["error"])

    def test_list_param_ignored(self):
        cmd = descargas.download_cmd("https://www.youtube.com/watch?v=jNQXAC9IVRw&list=PL1", "best", Path("."), None, False)
        self.assertIn("--no-playlist", cmd)
        self.assertIn("--encoding", cmd)

    def test_helpers(self):
        self.assertTrue(descargas.should_retry("ERROR: Sign in to confirm you're not a bot"))
        self.assertTrue(descargas.should_retry("HTTP Error 429: Too Many Requests"))
        self.assertFalse(descargas.should_retry("ERROR: Private video"))
        self.assertTrue(descargas.needs_update("ERROR: Unable to extract uploader id"))
        self.assertFalse(descargas.needs_update("ERROR: Private video"))
        self.assertTrue(descargas.ytdlp_old("2024.01.01"))
        self.assertFalse(descargas.ytdlp_old(time.strftime("%Y.%m.%d")))
        self.assertFalse(descargas.ytdlp_old(""))
        self.assertTrue(descargas.is_youtube("https://youtu.be/x"))
        self.assertTrue(descargas.is_youtube("https://m.youtube.com/watch?v=x"))
        self.assertFalse(descargas.is_youtube("https://notyoutube.com/x"))
        self.assertTrue(descargas.deno_asset().startswith("deno-"))


if __name__ == "__main__":
    unittest.main()
