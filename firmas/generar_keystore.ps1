# LaZoo · Crea la clave de LANZAMIENTO de la APK EN TU PC (nada sale a internet).
#   powershell -ExecutionPolicy Bypass -File firmas\generar_keystore.ps1 [-Archivo ruta.jks] [-Alias lazoo]
# RSA 4096, validez 30 años. keytool pide la contraseña: este script no la ve ni la guarda.
param(
    [string]$Archivo = (Join-Path (Join-Path $HOME "LaZoo-claves") "lazoo-lanzamiento.jks"),
    [string]$Alias = "lazoo"
)
$ErrorActionPreference = "Stop"
if (-not (Get-Command keytool -ErrorAction SilentlyContinue)) {
    Write-Host "Falta keytool. Instala Java 17 (por ejemplo Temurin de adoptium.net) y abre otra ventana."; exit 1
}
if (Test-Path $Archivo) { Write-Host "Ya existe $Archivo. No lo sobrescribo."; exit 1 }
$Dir = Split-Path -Parent $Archivo
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
git -C $Dir rev-parse --is-inside-work-tree 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host "ERROR: $Dir está dentro de un repositorio git. Elige otra carpeta."; exit 1 }

keytool -genkeypair -v -storetype PKCS12 -keystore $Archivo -alias $Alias `
    -keyalg RSA -keysize 4096 -validity 10950 -dname "CN=GUERRILLA, O=LaZoo"
if ($LASTEXITCODE -ne 0) { throw "keytool no pudo crear la clave" }

Write-Host ""
Write-Host "Huella SHA-256 (publícala en README y en about.json -> apk_huella). keytool pedirá la contraseña:"
keytool -list -v -keystore $Archivo -alias $Alias | Select-String "SHA256:"
Write-Host ""
Write-Host "Listo: $Archivo"
Write-Host "AHORA: 2 copias cifradas del .jks en sitios distintos y la contraseña aparte, en tu gestor."
Write-Host "Para GitHub: firmas\preparar_secretos.md"
