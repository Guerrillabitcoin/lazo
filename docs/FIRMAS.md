# Firmas y claves de LaZoo

Guía práctica para que cada descarga de LaZoo se pueda comprobar: que es tuya y que nadie la ha
cambiado. Vale igual para **Guerrilla Jukebox** (mismo alias, misma clave PGP; su APK, con su
propio keystore). **Guerrilla Cards** es web y privada: de momento le basta con tags firmados.

> Regla de oro: **ninguna clave privada, keystore ni contraseña entra en el repositorio ni en
> máquinas de terceros.** Se generan en tu PC con los scripts de `firmas/`, se guardan en copias
> cifradas fuera de línea y, a GitHub, solo como secretos cifrados.

## Qué hay hoy (0.58)

| Archivo | Firma hoy | Tras la 0.59 |
| --- | --- | --- |
| `LaZoo.exe` | Ninguna (SmartScreen avisa) | Igual, pero con `SHA256SUMS` + PGP + atestación. Luego SignPath. |
| `LaZoo.apk` | Clave de **pruebas** creada en cada build | Clave de **lanzamiento** propia, siempre la misma |
| Zip del código | Ninguna | `SHA256SUMS` + PGP + atestación |
| Tags de git | Sin firmar | Firmados con PGP («Verified» en GitHub) |

## Resumen: qué protege cada cosa

| Herramienta | Para qué sirve | Qué NO hace |
| --- | --- | --- |
| `SHA256SUMS` | Detectar archivos dañados o cambiados | No prueba quién los hizo |
| PGP (`.asc`) | Probar que lo firmó GUERRILLA | Windows y Chrome no lo leen: no quita avisos |
| Atestación de GitHub | Probar que salió de este repo y este commit, en Actions | No quita avisos |
| Keystore de la APK | Que Android acepte actualizaciones solo tuyas | Nada que ver con Google Play |
| Authenticode (SignPath / certificado) | Que Windows muestre editor y, con el tiempo, quite el aviso | Cuesta trámites o dinero |

---

## (a) Clave PGP de GUERRILLA

**Qué:** una clave nueva solo para firmar LaZoo y tus proyectos, con
`GUERRILLA <guerrilla@users.noreply.github.com>`. Sin nombre real.

**Diseño:**
- Clave principal **ed25519** solo para certificar. Se queda en tu PC y en la copia fuera de línea.
- Subclave **ed25519 de firma**. Es la única que va a GitHub Actions.
- Caducidad **2 años**. Se puede alargar antes de que caduque (`gpg --quick-set-expire`), sin cambiar la huella.
- **Certificado de revocación** guardado fuera de línea (USB). Sirve para anular la clave si la pierdes o te la roban.

**Crear (en tu PC):**
- Windows (instala [Gpg4win](https://gpg4win.org)): `powershell -ExecutionPolicy Bypass -File firmas\generar_pgp.ps1`
- Linux / macOS: `bash firmas/generar_pgp.sh`

gpg te pide la contraseña en su propia ventana: el script no la ve. Por defecto todo sale en
`~/LaZoo-claves` (`%USERPROFILE%\LaZoo-claves`), fuera del repo. El script se niega a escribir
dentro de un repositorio git.

**Copia de seguridad** (en dos USB cifrados, nunca en la nube ni en el repo):
```
gpg --armor --export-secret-keys HUELLA > E:\GUERRILLA-secreta.asc
```
Junto con `revocacion-GUERRILLA.asc`. Prueba a importarla en otro equipo una vez.

**Publicar la clave pública:**
1. Copia `GUERRILLA.asc` a la raíz del repo (es pública, se sube).
2. Pon la huella en el README (sección «Comprobar descargas») y en `about.json` → `pgp_huella`
   (sale en «Sobre LaZoo»).
3. En GitHub: **Settings → SSH and GPG keys → New GPG key** y pega el contenido de
   `GUERRILLA.asc`. El correo noreply debe estar en tu cuenta (lo está si usas el de tu usuario;
   comprueba en **Settings → Emails** cuál es el tuyo exacto: puede ser
   `NÚMERO+usuario@users.noreply.github.com`).
4. Opcional: subirla a `keys.openpgp.org` (solo publica la clave; para mostrar el correo pide
   confirmarlo).

**Tags firmados:**
```
git config --global user.signingkey HUELLA
git config --global gpg.program "C:/Program Files (x86)/GnuPG/bin/gpg.exe"   # solo Windows
git tag -s v0.59.0 -m "LaZoo 0.59"
git push origin v0.59.0
git tag -v v0.59.0
```

**Verificar una firma:**
```
gpg --import GUERRILLA.asc
gpg --verify SHA256SUMS.asc SHA256SUMS
```
Debe decir «Good signature from "GUERRILLA <guerrilla@users.noreply.github.com>"» y la huella
de la clave principal debe ser la del README. El aviso «not certified with a trusted signature»
es normal: significa que no has firmado tú esa clave, no que esté mal.

## (b) SHA256SUMS y SHA256SUMS.asc

El workflow crea `SHA256SUMS` con una línea por archivo (`.exe` en zip, `.apk`, zip del código)
y, si existe el secreto `PGP_PRIVATE_KEY`, firma `SHA256SUMS.asc` (y un `.asc` por archivo).

Comprobar a mano:
- Linux / macOS: `sha256sum -c --ignore-missing SHA256SUMS`
- Windows: `Get-FileHash LaZoo-0.59.apk` y comparar con la línea de `SHA256SUMS`.

O todo de una vez: `firmas/verificar.sh CARPETA` / `firmas\verificar.ps1 -Carpeta CARPETA`.

## (c) Atestaciones de GitHub

El paso `actions/attest-build-provenance` firma (con Sigstore, sin claves tuyas) que cada
archivo salió de `Guerrillabitcoin/lazo`, de ese commit y de ese workflow. Necesita los permisos
`id-token: write` y `attestations: write` (solo en el trabajo «publicar»). En repos públicos es
gratis.

Verificar (con la CLI `gh`):
```
gh attestation verify LaZoo-0.59.apk -R Guerrillabitcoin/lazo
```
Si el paso fallara (por ejemplo, por plan de la cuenta), el workflow sigue: está como
`continue-on-error`.

## (d) Keystore de la APK (clave de lanzamiento)

Android solo instala una actualización encima si va firmada con **la misma clave**. Hoy cada
build usa una clave de pruebas nueva, así que cada APK nueva obliga a desinstalar.

**Crear (en tu PC, con Java 17):**
- Windows: `powershell -ExecutionPolicy Bypass -File firmas\generar_keystore.ps1`
- Linux / macOS: `bash firmas/generar_keystore.sh`

Crea `~/LaZoo-claves/lazoo-lanzamiento.jks`: PKCS12, alias `lazoo`, RSA 4096, validez 30 años,
`CN=GUERRILLA, O=LaZoo`. keytool pide la contraseña: usa una **larga** (20+ caracteres,
generada por tu gestor de contraseñas).

**Copia de seguridad:** el `.jks` cifrado en **dos sitios distintos** (por ejemplo, dos USB
cifrados con VeraCrypt o BitLocker en lugares diferentes) y la contraseña aparte, en el gestor.

**Si se pierde** el `.jks` o la contraseña: nadie (ni tú) podrá publicar una actualización que
se instale encima. Habría que firmar con otra clave y todos tendrían que desinstalar e instalar
otra vez (y perderían los datos de la app: la dirección guardada del PC).

**Publicar la huella:** el script enseña la SHA-256 del certificado. Ponla en el README y en
`about.json` → `apk_huella`. Cualquiera la comprueba con:
```
apksigner verify --print-certs LaZoo-0.59.apk
```
(«Signer #1 certificate SHA-256 digest» debe coincidir).

**Migrar desde la clave de pruebas:** la primera APK con la clave de lanzamiento **no se
instala encima** de las anteriores. Hay que desinstalar la APK vieja una vez y luego instalar
la nueva; a partir de ahí, las actualizaciones van encima. Tras reinstalar, la app vuelve a
pedir el QR o el PIN (en el PC no cambia nada).

Cómo se usa en el build: `android/construir_apk.sh` firma con la clave de lanzamiento si existen
`LAZOO_FIRMA_KS` (ruta) y `LAZOO_FIRMA_KS_PASS` (+ opcional `LAZOO_FIRMA_ALIAS`,
`LAZOO_FIRMA_KEY_PASS`). Las contraseñas se pasan a `apksigner` por entorno (`env:`), no por la
línea de órdenes. Si no están, firma con la clave de pruebas de siempre.

## (e) El .exe de Windows

Ninguna firma PGP quita el aviso de SmartScreen ni el de Chrome. Para eso hace falta
**Authenticode**. Las condiciones de abajo pueden haber cambiado: compruébalas antes.

1. **SignPath Foundation (primera vía, gratis para código abierto).**
   - Requisitos habituales: licencia aprobada por OSI (MIT vale), repo público, proyecto mantenido
     y con alguna actividad, builds reproducibles desde GitHub Actions, sin malware ni «PUP»,
     y una página del proyecto que explique qué hace. El certificado sale a nombre de
     «SignPath Foundation», no al tuyo: buena noticia para la privacidad.
   - Pasos: leer las condiciones en signpath.org (sección para OSS), rellenar la solicitud con el
     repo, esperar la revisión, instalar su app de GitHub, crear el proyecto y la política de firma
     que te indiquen, crear el secreto `SIGNPATH_API_TOKEN` y las variables
     `SIGNPATH_ORGANIZATION_ID`, `SIGNPATH_PROJECT_SLUG`, `SIGNPATH_POLICY_SLUG`, y descomentar el
     bloque SignPath de `ci/construir.yml`.
   - Pegas honestas: hay que esperar a que lo aprueben y puede que pidan cambios (por ejemplo,
     una sola fuente de build, un código de conducta, o firmar solo desde `main`/releases).
     Cada firma puede requerir aprobación manual en su web.
2. **Certificado de pago con clave en la nube** (Azure Trusted Signing / «Artifact Signing», o
   una CA con HSM en la nube). Barato y automatizable, pero pide verificar identidad y ha tenido
   límites por país y por tipo de cuenta (persona/empresa). La firma mostraría el nombre
   verificado, no «GUERRILLA».
3. **Certificado autofirmado:** solo para tus pruebas. Windows no confía en él y SmartScreen
   sigue avisando.
4. **Mientras tanto:** publicar `SHA256SUMS` + PGP + atestación (es lo que hace la 0.59) y
   explicar en el README cómo pasar el aviso («Más información → Ejecutar de todos modos»).

Aunque se firme, SmartScreen da reputación por descargas: las primeras semanas puede seguir avisando.

## (f) Política de releases

Cada versión instalable:
1. Sube versión (`VERSION.txt`, `lazo.py`, manifiesto de Android…), commit en `beta`.
2. **Tag firmado** `git tag -s vX.Y.0` y push del tag.
3. El workflow construye y crea una **GitHub Release** (prerelease mientras sea 0.x) con:
   `LaZoo-X.Y-windows.zip`, `LaZoo-X.Y.apk`, `LaZoo-X.Y.zip` (código), `SHA256SUMS`,
   `SHA256SUMS.asc` y un `.asc` por archivo (si hay PGP), y notas que dicen qué va firmado.
4. Tú compruebas con `firmas/verificar.*` antes de anunciarla.

## (g) Rotación y revocación

- **PGP caduca a los 2 años:** un mes antes, `gpg --quick-set-expire HUELLA 2y` y
  `gpg --quick-set-expire HUELLA 2y '*'` (subclaves); vuelve a exportar `GUERRILLA.asc`, súbela
  al repo y a GitHub. La huella no cambia.
- **Se filtra el secreto de GitHub (subclave):** revoca solo esa subclave (`gpg --edit-key
  HUELLA`, `key N`, `revkey`), crea otra, actualiza `GUERRILLA.asc` y el secreto.
- **Se pierde o roba la clave principal:** importa `revocacion-GUERRILLA.asc`, publica la clave
  revocada, crea una nueva y avisa en el README y en la Release.
- **Keystore de la APK:** no rota (30 años). Si se filtra, Android no tiene forma de revocarlo
  fuera de Google Play: hay que avisar, cambiar de clave y pedir reinstalar.

## (h) Privacidad y metadatos

- Nada de nombre real: alias GUERRILLA y correo noreply en PGP, `CN=GUERRILLA, O=LaZoo` en el keystore.
- La firma PGP lleva **fecha y hora** (en UTC). Si te preocupa la zona horaria, firma en CI (ya lo hace) o pon `TZ=UTC`.
- Tags y commits: usa `git config user.name GUERRILLA` y el correo noreply; la fecha del commit lleva tu zona horaria (`+0100`). Para ocultarla: `TZ=UTC git commit …`.
- El `.exe` de PyInstaller y la APK se construyen en GitHub Actions: las rutas internas son del runner, no tuyas. Si construyes en tu PC, el `.exe` puede llevar rutas como `C:\Users\TU_USUARIO\…` (en mensajes de error y en el `.pyc`): para publicar, usa siempre el de Actions.
- El certificado de la APK solo lleva lo que pongas en `-dname`. No pongas ciudad ni país.

---

## Plan de versiones

- **0.58 (esta):** andamiaje sin romper nada. Guía, scripts, `.gitignore`, `construir_apk.sh`
  con firma opcional, workflow nuevo en `ci/construir.yml` (todo opcional) y huellas opcionales
  en «Sobre LaZoo». Sin secretos, el build sale igual que en la 0.57.
- **0.59:** primera release firmada: APK con clave de lanzamiento (hay que desinstalar la vieja
  una vez), `SHA256SUMS` + `.asc` + atestación, tag firmado, `GUERRILLA.asc` en el repo y huellas
  en el README.
- **Más adelante:** `.exe` con SignPath cuando lo aprueben. Guerrilla Jukebox usa el mismo
  esquema desde su primera versión (misma clave PGP, keystore propio con alias `jukebox`).

## Pasos para ti, en orden

1. **Generar la clave PGP** en tu PC: `firmas\generar_pgp.ps1`. Apunta la huella.
2. **Copia de seguridad** de la clave secreta y del certificado de revocación en dos USB.
3. **Subir la pública:** a GitHub (Settings → SSH and GPG keys) y `GUERRILLA.asc` a la raíz del
   repo (o pásamela y la subo yo). Huella en README y `about.json`.
4. **Keystore:** `firmas\generar_keystore.ps1`. Apunta la huella SHA-256. Dos copias cifradas.
5. **Secretos de GitHub:** sigue `firmas/preparar_secretos.md`.
6. **Copiar el workflow:** `ci/construir.yml` → `.github/workflows/construir.yml`, commit y push
   a `beta` (desde la web de GitHub o con tu usuario, que sí tiene permiso de workflows).
7. **Tag firmado de prueba:** `git tag -s v0.59.0 -m "LaZoo 0.59"` y `git push origin v0.59.0`
   (cuando la 0.59 esté lista).
8. **Verificar:** descarga los archivos de la Release y ejecuta `firmas\verificar.ps1`
   con `-HuellaPgp` y `-HuellaApk`. También `gh attestation verify`.
9. **Pedir SignPath** para el `.exe`.
