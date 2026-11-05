# LaZoo · Comprueba una descarga en Windows (no necesita claves privadas).
#   powershell -ExecutionPolicy Bypass -File firmas\verificar.ps1 [-Carpeta descargas] [-Publica GUERRILLA.asc] [-HuellaPgp ...] [-HuellaApk ...]
# 1) SHA256SUMS con Get-FileHash, 2) firma PGP (si hay gpg de Gpg4win), 3) huella de la APK (si hay apksigner).
param(
    [string]$Carpeta = ".",
    [string]$Publica = "",
    [string]$HuellaPgp = "",
    [string]$HuellaApk = ""
)
$Fallos = 0
function Ok($t) { Write-Host "  OK  $t" }
function Mal($t) { Write-Host "  MAL $t"; $script:Fallos++ }
function Limpia($t) { ($t -replace "[\s:]", "").ToUpperInvariant() }
Set-Location $Carpeta

Write-Host "1) SHA256SUMS"
if (Test-Path SHA256SUMS) {
    foreach ($linea in Get-Content SHA256SUMS) {
        if ($linea -notmatch "^([0-9a-fA-F]{64})\s+\*?(.+)$") { continue }
        $esperada = $Matches[1].ToUpperInvariant(); $nombre = $Matches[2].Trim()
        if (-not (Test-Path -LiteralPath $nombre)) { continue }
        $real = (Get-FileHash -Algorithm SHA256 -LiteralPath $nombre).Hash
        if ($real -eq $esperada) { Ok $nombre } else { Mal "$nombre NO cuadra: no lo instales" }
    }
} else { Mal "no está SHA256SUMS" }

Write-Host "2) Firma PGP"
if ((Test-Path SHA256SUMS.asc) -and (Get-Command gpg -ErrorAction SilentlyContinue)) {
    if (-not $Publica -and (Test-Path GUERRILLA.asc)) { $Publica = "GUERRILLA.asc" }
    if ($Publica -and (Test-Path $Publica)) {
        $tmp = Join-Path ([IO.Path]::GetTempPath()) ("lazoo-gpg-" + [guid]::NewGuid())
        New-Item -ItemType Directory -Path $tmp | Out-Null
        $antes = $env:GNUPGHOME; $env:GNUPGHOME = $tmp
        try {
            gpg --batch --quiet --import $Publica 2>$null
            $sal = gpg --batch --status-fd 1 --verify SHA256SUMS.asc SHA256SUMS 2>$null
            $valid = $sal | Where-Object { $_ -match "VALIDSIG" } | Select-Object -First 1
            if (($sal -match "GOODSIG") -and $valid) {
                $fpr = ($valid -split " ")[-1]
                Ok "firma válida; clave principal $fpr"
                if ($HuellaPgp) { if ((Limpia $HuellaPgp) -eq $fpr) { Ok "la huella coincide" } else { Mal "la huella NO es la esperada" } }
                else { Write-Host "      Compara esa huella con la del README oficial." }
            } else { Mal "la firma PGP no es válida" }
        } finally { $env:GNUPGHOME = $antes; Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue }
    } else { Write-Host "  --  falta GUERRILLA.asc: no se comprueba" }
} else { Write-Host "  --  sin SHA256SUMS.asc o sin gpg: no se comprueba" }

Write-Host "3) Certificado de la APK"
$apk = Get-ChildItem -Filter "LaZoo*.apk" -ErrorAction SilentlyContinue | Select-Object -First 1
$as = Get-Command apksigner -ErrorAction SilentlyContinue
if ($apk -and $as) {
    $linea = apksigner verify --print-certs $apk.FullName 2>$null | Select-String "certificate SHA-256 digest" | Select-Object -First 1
    if ($linea) {
        $h = Limpia (($linea.ToString() -split ": ")[-1])
        Ok "$($apk.Name) firmada; SHA-256 del certificado: $h"
        if ($HuellaApk) { if ((Limpia $HuellaApk) -eq $h) { Ok "coincide con la esperada" } else { Mal "NO coincide con la esperada" } }
        else { Write-Host "      Compara con la huella del README oficial." }
    } else { Mal "la APK no tiene una firma válida" }
} else { Write-Host "  --  sin APK o sin apksigner: no se comprueba" }

Write-Host ""
if ($Fallos -eq 0) { Write-Host "Resultado: sin fallos." } else { Write-Host "Resultado: $Fallos fallo(s). No uses estos archivos." }
exit $Fallos
