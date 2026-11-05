# LaZoo · Genera la clave PGP de GUERRILLA EN TU PC con Gpg4win (nada sale a internet).
#   powershell -ExecutionPolicy Bypass -File firmas\generar_pgp.ps1 [-Alias GUERRILLA] [-Correo ...] [-Caduca 2y] [-Salida carpeta]
# Clave principal ed25519 (solo certificar) + subclave ed25519 de firma. La contraseña la pide
# gpg (pinentry): este script no la ve ni la guarda. Nada se escribe dentro del repositorio.
param(
    [string]$Alias = "GUERRILLA",
    [string]$Correo = "guerrilla@users.noreply.github.com",
    [string]$Caduca = "2y",
    [string]$Salida = (Join-Path $HOME "LaZoo-claves")
)
$ErrorActionPreference = "Stop"

if (-not (Get-Command gpg -ErrorAction SilentlyContinue)) {
    Write-Host "Falta gpg. Instala Gpg4win (https://gpg4win.org) y abre otra ventana."; exit 1
}
if ($Correo -notlike "*@users.noreply.github.com") {
    Write-Host "AVISO: el correo no es el noreply de GitHub. Usa ALIAS@users.noreply.github.com para no exponer datos."
    if ((Read-Host "¿Seguir igualmente? (s/N)") -ne "s") { exit 1 }
}
New-Item -ItemType Directory -Force -Path $Salida | Out-Null
$Salida = (Resolve-Path $Salida).Path
git -C $Salida rev-parse --is-inside-work-tree 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host "ERROR: $Salida está dentro de un repositorio git. Elige otra carpeta."; exit 1 }

$Uid = "$Alias <$Correo>"
gpg --batch --list-secret-keys "=$Uid" 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host "Ya existe una clave para $Uid. No creo otra."; exit 1 }

Write-Host "1/4 Creando la clave principal (solo certificar, caduca en $Caduca). gpg pedirá una contraseña larga."
gpg --batch --quick-generate-key $Uid ed25519 cert $Caduca
if ($LASTEXITCODE -ne 0) { throw "gpg no pudo crear la clave" }
$Fpr = (gpg --batch --with-colons --list-keys "=$Uid" | Where-Object { $_ -like "fpr:*" } | Select-Object -First 1).Split(":")[9]

Write-Host "2/4 Añadiendo la subclave de firma."
gpg --batch --quick-add-key $Fpr ed25519 sign $Caduca
if ($LASTEXITCODE -ne 0) { throw "gpg no pudo crear la subclave" }

Write-Host "3/4 Exportando la clave PÚBLICA y el certificado de revocación."
$Pub = Join-Path $Salida "GUERRILLA.asc"
gpg --batch --armor --output $Pub --yes --export $Fpr
$Home2 = if ($env:GNUPGHOME) { $env:GNUPGHOME } else { Join-Path $env:APPDATA "gnupg" }
$Rev = Join-Path $Home2 "openpgp-revocs.d\$Fpr.rev"
if (Test-Path $Rev) { Copy-Item $Rev (Join-Path $Salida "revocacion-GUERRILLA.asc") -Force }
Set-Content -Path (Join-Path $Salida "huella.txt") -Value $Fpr -Encoding ascii

Write-Host "4/4 Listo."
Write-Host ""
Write-Host "Huella (cópiala en README y en about.json -> pgp_huella):"
Write-Host "  $Fpr"
Write-Host ""
Write-Host "En $Salida :"
Write-Host "  GUERRILLA.asc             PÚBLICA: cópiala a la raíz del repo y a GitHub (Settings > SSH and GPG keys)"
Write-Host "  revocacion-GUERRILLA.asc  PRIVADA: a un USB fuera de línea"
Write-Host ""
Write-Host "COPIA DE SEGURIDAD ahora, en un USB cifrado (no en la nube ni en el repo):"
Write-Host "  gpg --armor --output E:\GUERRILLA-secreta.asc --export-secret-keys $Fpr"
Write-Host "Para GitHub Actions exporta SOLO la subclave de firma (firmas\preparar_secretos.md)."
