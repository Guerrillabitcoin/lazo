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
        self.old = (descargas.find_ytdlp, descargas.find_ffmpeg)
        descargas.find_ytdlp = lambda: [sys.executable, str(fake)]
        descargas.find_ffmpeg = lambda: None
        self.q = descargas.Queue()
        self.q.out_dir = Path(self.tmp.name) / "out"
        self.q.idle_limit = 2

    def tearDown(self):
        descargas.find_ytdlp, descargas.find_ffmpeg = self.old
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


if __name__ == "__main__":
    unittest.main()
