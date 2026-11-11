"""LaZoo 0.58: andamiaje de firmas (PGP, SHA256SUMS, atestación, keystore de la APK, SignPath).

    python3 test_v058.py

Comprueba que los archivos de firma existen, que el .gitignore deja fuera las claves, que el
workflow es YAML válido y que cada paso de firma es condicional, que no hay claves privadas ni
datos personales en el repo, que los scripts no llevan contraseñas y que la versión es la 0.58.
Si gpg/keytool están instalados, prueba los scripts con claves desechables en una carpeta temporal.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import sobre

ROOT = Path(__file__).resolve().parent
CI = (ROOT / "ci" / "construir.yml").read_text(encoding="utf-8")
FIRMAS = ROOT / "firmas"
SCRIPTS = ["generar_pgp.ps1", "generar_pgp.sh", "generar_keystore.ps1", "generar_keystore.sh",
           "verificar.ps1", "verificar.sh"]


def tracked() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        return [ROOT / p for p in out.splitlines() if p]
    except Exception:
        return [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]


class Archivos(unittest.TestCase):
    def test_presentes(self):
        for rel in ["docs/FIRMAS.md", "firmas/preparar_secretos.md", *[f"firmas/{s}" for s in SCRIPTS]]:
            self.assertTrue((ROOT / rel).is_file(), rel)
        self.assertIn("docs/FIRMAS.md", (ROOT / "README.md").read_text(encoding="utf-8"))

    def test_guia(self):
        doc = (ROOT / "docs" / "FIRMAS.md").read_text(encoding="utf-8")
        for bit in ("guerrilla@users.noreply.github.com", "revocación", "SHA256SUMS.asc", "gpg --verify",
                    "gh attestation verify", "apksigner verify --print-certs", "SignPath", "desinstalar",
                    "Rotación", "Privacidad", "0.59", "Jukebox", "Guerrilla Cards", "keytool"):
            self.assertIn(bit, doc)

    def test_secretos(self):
        doc = (FIRMAS / "preparar_secretos.md").read_text(encoding="utf-8")
        for name in ("ANDROID_KEYSTORE_B64", "ANDROID_KEYSTORE_PASSWORD", "ANDROID_KEY_ALIAS",
                     "ANDROID_KEY_PASSWORD", "PGP_PRIVATE_KEY", "PGP_PASSPHRASE", "SIGNPATH_API_TOKEN", "gh secret set"):
            self.assertIn(name, doc)

    def test_gitignore(self):
        gi = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
        for pat in ("*.jks", "*.keystore", "*.p12", "*.pfx", "*.gpg", "*.rev", "revocacion-*.asc", "!GUERRILLA.asc"):
            self.assertIn(pat, gi)


class Workflow(unittest.TestCase):
    def test_yaml_valido(self):
        try:
            import yaml  # type: ignore
        except ImportError:
            self.skipTest("sin PyYAML")
        data = yaml.safe_load(CI)
        jobs = data["jobs"]
        self.assertEqual(set(jobs), {"exe", "apk", "publicar"})
        self.assertEqual(data["permissions"], {"contents": "read"})
        pub = jobs["publicar"]
        self.assertEqual(pub["permissions"], {"contents": "write", "id-token": "write", "attestations": "write"})
        self.assertIn("refs/tags/v", pub["if"])
        steps = {s.get("name", s.get("uses", "")): s for j in jobs.values() for s in j["steps"]}
        self.assertEqual(steps["Restaurar keystore de lanzamiento (solo si existe el secreto)"]["if"], "env.HAY_KEYSTORE == 'true'")
        self.assertEqual(steps["Firma PGP (solo si existe el secreto)"]["if"], "env.HAY_PGP == 'true'")
        self.assertEqual(steps["Borrar keystore del runner"]["if"], "always()")
        self.assertEqual(steps["Borrar clave PGP del runner"]["if"], "always()")
        self.assertTrue(steps["Atestación de origen (GitHub)"]["continue-on-error"])

    def test_condicional_y_sin_fugas(self):
        self.assertIn("secrets.ANDROID_KEYSTORE_B64 != ''", CI)
        self.assertIn("secrets.PGP_PRIVATE_KEY != ''", CI)
        self.assertIn("actions/attest-build-provenance@v2", CI)
        self.assertIn("--prerelease", CI)
        self.assertIn("# - uses: signpath/github-action-submit-signing-request", CI)
        self.assertNotRegex(CI, r"echo[^\n]*\$\{\{\s*secrets\.")  # nunca imprimir secretos
        self.assertNotIn("set -x", CI)
        # sin secretos, el trabajo apk sigue construyendo con la clave de pruebas
        self.assertIn("LAZOO_KEYSTORE: ${{ runner.temp }}/lazoo-pruebas.jks", CI)

    def test_apk_script(self):
        sh = (ROOT / "android" / "construir_apk.sh").read_text(encoding="utf-8")
        self.assertIn("--ks-pass env:LAZOO_FIRMA_KS_PASS", sh)
        self.assertIn('if [ -n "${LAZOO_FIRMA_KS:-}" ]', sh)
        self.assertIn("lazoo-pruebas.jks", sh)  # por defecto, lo de siempre


class Privacidad(unittest.TestCase):
    PRIV = re.compile(r"-----BEGIN (?:PGP PRIVATE KEY BLOCK|(?:RSA |EC |ENCRYPTED )?PRIVATE KEY)-----")

    def test_sin_claves_privadas(self):
        for path in tracked():
            self.assertNotRegex(path.suffix.lower(), r"^\.(jks|keystore|p12|pfx|gpg|kbx|rev|pvk)$", str(path))
            if path.suffix.lower() in (".png", ".ico", ".jar", ".zip", ".apk", ".jpg", ".webp"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if path.name == "test_v058.py":
                continue
            self.assertIsNone(self.PRIV.search(text), str(path))

    def test_scripts_sin_contrasenas(self):
        bad = re.compile(r"(?:--passphrase\s+['\"][^'\"]+['\"]|-storepass\s+(?!:env)\S+|-keypass\s+(?!:env)\S+|(?<![a-z])(?-i:pass:)(?!env)[^\s\"]+|ConvertTo-SecureString\s+-String)", re.I)
        for name in SCRIPTS:
            text = (FIRMAS / name).read_text(encoding="utf-8")
            self.assertIsNone(bad.search(text), name)
            self.assertNotIn("C:\\Users\\", text)
            self.assertNotIn("/home/", text)

    def test_identidad(self):
        for name in ("generar_pgp.sh", "generar_pgp.ps1"):
            self.assertIn("guerrilla@users.noreply.github.com", (FIRMAS / name).read_text(encoding="utf-8"))
        for name in ("generar_keystore.sh", "generar_keystore.ps1"):
            text = (FIRMAS / name).read_text(encoding="utf-8")
            self.assertIn('CN=GUERRILLA, O=LaZoo', text)
            self.assertIn("10950", text)
            self.assertIn("-alias", text)


class Sobre(unittest.TestCase):
    def test_huellas(self):
        fpr = "D6CF C683 C6B8 EE41 C3CE  431B 0701 FD8C 8F93 E909"
        self.assertEqual(sobre.clean_fingerprint("pgp_huella", fpr.lower()), "D6CF C683 C6B8 EE41 C3CE 431B 0701 FD8C 8F93 E909")
        apk = "7b:e7" + ":ab" * 30
        self.assertEqual(sobre.clean_fingerprint("apk_huella", apk), apk.upper())
        for bad in ("", "xyz", "<b>", "A" * 39, "G" * 40, None, 5):
            self.assertEqual(sobre.clean_fingerprint("pgp_huella", bad), "")
        self.assertEqual(sobre.clean_fingerprint("otra", "A" * 40), "")
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "about.json").write_text(json.dumps({"pgp_huella": "A" * 40, "apk_huella": "nope"}), encoding="utf-8")
            data = sobre.load_config(Path(tmp))
            self.assertEqual([p["kind"] for p in data["fingerprints"]], ["pgp_huella"])
            self.assertEqual(sobre.load_config(Path(tmp) / "no")["fingerprints"], [])
        ex = json.loads((ROOT / "about.example.json").read_text(encoding="utf-8"))
        self.assertEqual(ex["pgp_huella"], "")
        self.assertEqual(ex["apk_huella"], "")

    def test_pastilla(self):
        js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function aboutPrints", js)
        self.assertIn('id="about-prints-box" class="about-box" hidden', html)


@unittest.skipUnless(shutil.which("gpg") and shutil.which("bash"), "sin gpg")
class ScriptsReales(unittest.TestCase):
    def test_pgp_y_verificar(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, GNUPGHOME=f"{tmp}/g", LAZOO_PGP_SIN_PASS="1")
            os.mkdir(env["GNUPGHOME"], 0o700)
            out = Path(tmp, "claves")
            subprocess.run(["bash", str(FIRMAS / "generar_pgp.sh"), "GUERRILLA", "guerrilla@users.noreply.github.com",
                            "1d", str(out)], env=env, check=True, capture_output=True)
            self.assertTrue((out / "GUERRILLA.asc").read_text().startswith("-----BEGIN PGP PUBLIC KEY BLOCK"))
            self.assertTrue((out / "revocacion-GUERRILLA.asc").exists())
            d = Path(tmp, "d"); d.mkdir()
            (d / "LaZoo-0.58.zip").write_bytes(b"hola")
            subprocess.run("sha256sum LaZoo-* > SHA256SUMS && gpg --batch -q --armor --detach-sign SHA256SUMS",
                           shell=True, cwd=d, env=env, check=True, capture_output=True)
            fpr = (out / "huella.txt").read_text().replace(" ", "").strip()
            ok = subprocess.run(["bash", str(FIRMAS / "verificar.sh"), str(d), str(out / "GUERRILLA.asc")],
                                env=dict(os.environ, LAZOO_PGP_HUELLA=fpr), capture_output=True, text=True)
            self.assertEqual(ok.returncode, 0, ok.stdout)
            self.assertIn("la huella coincide", ok.stdout)
            (d / "LaZoo-0.58.zip").write_bytes(b"cambiado")
            bad = subprocess.run(["bash", str(FIRMAS / "verificar.sh"), str(d), str(out / "GUERRILLA.asc")],
                                 capture_output=True, text=True)
            self.assertNotEqual(bad.returncode, 0)
            # se niega a escribir dentro del repo
            inside = subprocess.run(["bash", str(FIRMAS / "generar_pgp.sh"), "X", "x@users.noreply.github.com", "1d",
                                     str(ROOT / "firmas")], env=env, capture_output=True, text=True)
            self.assertNotEqual(inside.returncode, 0)


class Version(unittest.TestCase):
    def test_version(self):
        import lazo
        self.assertEqual(lazo.VERSION, "0.65")
        self.assertEqual((ROOT / "VERSION.txt").read_text().strip(), "0.65")
        apk = (ROOT / "android" / "AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:versionCode="65"', apk)
        self.assertIn('android:versionName="2"', apk)
        self.assertIn("# LaZoo 0.65", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("## Estado (0.61)", (ROOT / "AGENTS.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
