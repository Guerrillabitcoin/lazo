# Secretos de GitHub para firmar LaZoo

Todo esto se hace **en tu PC**. Los secretos se guardan cifrados en GitHub y el workflow
(`ci/construir.yml`) solo los usa si existen. Si falta alguno, el build sigue como antes.

Dónde: repo → **Settings → Secrets and variables → Actions → New repository secret**.
O con la terminal: `gh secret set NOMBRE -R Guerrillabitcoin/lazo` (te pide el valor y no queda en el historial).

## Nombres exactos

| Secreto | Qué es | Obligatorio |
| --- | --- | --- |
| `ANDROID_KEYSTORE_B64` | El `.jks` de lanzamiento en base64 | Para firmar la APK |
| `ANDROID_KEYSTORE_PASSWORD` | Contraseña del `.jks` | Para firmar la APK |
| `ANDROID_KEY_ALIAS` | Alias de la clave (`lazoo`) | No (por defecto `lazoo`) |
| `ANDROID_KEY_PASSWORD` | Contraseña de la clave (en PKCS12 es la misma que la del `.jks`) | No |
| `PGP_PRIVATE_KEY` | **Solo la subclave de firma**, exportada en ASCII | Para las `.asc` |
| `PGP_PASSPHRASE` | Contraseña de esa subclave | Si la tiene |
| `SIGNPATH_API_TOKEN` | Token de SignPath (más adelante) | No |

## APK: keystore en base64

Linux / macOS:

```bash
base64 -w0 ~/LaZoo-claves/lazoo-lanzamiento.jks | gh secret set ANDROID_KEYSTORE_B64 -R Guerrillabitcoin/lazo
gh secret set ANDROID_KEYSTORE_PASSWORD -R Guerrillabitcoin/lazo     # pega la contraseña cuando la pida
gh secret set ANDROID_KEY_ALIAS -R Guerrillabitcoin/lazo --body lazoo
```

(En macOS usa `base64 -i archivo` sin `-w0`.)

Windows (PowerShell):

```powershell
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("$HOME\LaZoo-claves\lazoo-lanzamiento.jks"))
$b64 | gh secret set ANDROID_KEYSTORE_B64 -R Guerrillabitcoin/lazo
Remove-Variable b64
gh secret set ANDROID_KEYSTORE_PASSWORD -R Guerrillabitcoin/lazo
gh secret set ANDROID_KEY_ALIAS -R Guerrillabitcoin/lazo --body lazoo
```

Si lo haces por la web, no guardes el base64 en un archivo dentro del repo: cópialo y bórralo.

## PGP: solo la subclave de firma

Así, si alguien robara el secreto de GitHub, tu clave principal sigue a salvo y puedes
revocar solo la subclave.

```bash
gpg --list-keys --with-subkey-fingerprints GUERRILLA     # la subclave con [S] es la de firma
gpg --armor --export-secret-subkeys HUELLA_SUBCLAVE! | gh secret set PGP_PRIVATE_KEY -R Guerrillabitcoin/lazo
gh secret set PGP_PASSPHRASE -R Guerrillabitcoin/lazo
```

El `!` al final de la huella es importante: exporta solo esa subclave. En PowerShell pon la
huella entre comillas: `"HUELLA_SUBCLAVE!"`.

## Comprobar

`gh secret list -R Guerrillabitcoin/lazo` enseña los nombres (nunca los valores).
Para borrar uno: `gh secret delete NOMBRE -R Guerrillabitcoin/lazo`.
