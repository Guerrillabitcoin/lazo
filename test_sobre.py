"""Pruebas de «Sobre LaZoo»: python test_sobre.py"""

import json
import tempfile
import unittest
from pathlib import Path

import sobre

SP = "sp1q" + "q" * 112


class Sobre(unittest.TestCase):
    def test_version_parse(self):
        self.assertEqual(sobre.parse_version("0.37\n"), (0, 37))
        self.assertEqual(sobre.parse_version("1.10"), (1, 10))
        for bad in ("", "0.37-beta", "<b>1.0</b>", "1", "1.2.3", "9" * 11, None, "0.3 7"):
            self.assertIsNone(sobre.parse_version(bad), bad)

    def test_compare_numeric(self):
        self.assertEqual(sobre.compare("0.37", "0.38"), "nueva")
        self.assertEqual(sobre.compare("0.9", "0.10"), "nueva")
        self.assertEqual(sobre.compare("0.37", "0.37"), "igual")
        self.assertEqual(sobre.compare("0.37", "0.31"), "delante")
        self.assertEqual(sobre.compare("0.37", "nope"), "error")

    def test_check(self):
        self.assertEqual(sobre.check_update("0.37", lambda _u, _c: b"0.40\n")["message"], "Hay una versión nueva (0.40) en main")
        self.assertIn("más nueva", sobre.check_update("0.37", lambda _u, _c: b"0.31")["message"])
        def boom(_u, _c):
            raise OSError("x")
        res = sobre.check_update("0.37", boom)
        self.assertEqual((res["state"], res["message"]), ("error", "No se pudo comprobar"))

    def test_fallback_lazo_py(self):
        def get(url, _cap):
            if url.endswith("VERSION.txt"):
                raise OSError("404")
            return b'"""x"""\nVERSION = "0.31"\n'
        self.assertEqual(sobre.check_update("0.37", get)["state"], "delante")

    def _cfg(self, data):
        d = Path(tempfile.mkdtemp())
        if data is not None:
            (d / "about.json").write_text(json.dumps(data), encoding="utf-8")
        return sobre.load_config(d)

    def test_defaults(self):
        cfg = self._cfg(None)
        self.assertEqual([l["url"] for l in cfg["links"]], [sobre.REPO])
        self.assertEqual(cfg["donations"], [])

    def test_filters(self):
        cfg = self._cfg({
            "web": "javascript:alert(1)", "x": "https://x.com/a\"><script>", "nostr": "https://njump.me/npub1abc",
            "otros": [{"etiqueta": "<b>Blog</b>", "url": "https://blog.example"}, {"url": "data:text/html,1"}, "raro"],
            "lightning": "yo@example.com", "bolt12": "<img>", "silent_payment": SP,
            "onchain": "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
        })
        urls = [l["url"] for l in cfg["links"]]
        self.assertEqual(urls, [sobre.REPO, "https://njump.me/npub1abc", "https://blog.example"])
        self.assertEqual([d["kind"] for d in cfg["donations"]], ["lightning", "silent_payment", "onchain"])

    def test_bad_json(self):
        d = Path(tempfile.mkdtemp())
        (d / "about.json").write_text("{roto", encoding="utf-8")
        self.assertEqual(len(sobre.load_config(d)["links"]), 1)


if __name__ == "__main__":
    unittest.main()
