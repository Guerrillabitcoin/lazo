#!/usr/bin/env bash
# LaZoo · Comprueba una descarga (cualquiera puede usarlo; no necesita claves privadas).
#   bash firmas/verificar.sh [CARPETA_CON_DESCARGAS] [GUERRILLA.asc]
# Comprueba: 1) SHA256SUMS, 2) firma PGP de SHA256SUMS (si hay .asc), 3) huella de la APK.
# Huellas esperadas: variables LAZOO_PGP_HUELLA y LAZOO_APK_HUELLA, o las del README oficial.
# No toca tu llavero de gpg: importa la clave pública en una carpeta temporal.
set -uo pipefail
DIR="${1:-.}"
PUB="${2:-}"
cd "$DIR" || exit 1
FALLOS=0
ok() { echo "  OK  $*"; }
mal() { echo "  MAL $*"; FALLOS=$((FALLOS + 1)); }

echo "1) SHA256SUMS"
if [ -f SHA256SUMS ]; then
  if sha256sum -c --ignore-missing SHA256SUMS; then ok "las sumas cuadran"; else mal "alguna suma NO cuadra: no lo instales"; fi
else mal "no está SHA256SUMS en $DIR"; fi

echo "2) Firma PGP"
if [ -f SHA256SUMS.asc ] && command -v gpg >/dev/null; then
  TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
  [ -z "$PUB" ] && [ -f GUERRILLA.asc ] && PUB=GUERRILLA.asc
  if [ -n "$PUB" ] && [ -f "$PUB" ]; then
    GNUPGHOME="$TMP" gpg --batch --quiet --import "$PUB" 2>/dev/null
    SAL="$(GNUPGHOME="$TMP" gpg --batch --status-fd 1 --verify SHA256SUMS.asc SHA256SUMS 2>/dev/null)"
    FPR="$(printf '%s\n' "$SAL" | awk '/VALIDSIG/{print $NF; exit}')"
    if printf '%s\n' "$SAL" | grep -q "GOODSIG"; then
      ok "firma válida; clave principal $FPR"
      if [ -n "${LAZOO_PGP_HUELLA:-}" ]; then
        ESP="$(printf '%s' "$LAZOO_PGP_HUELLA" | tr -d ' :' | tr a-f A-F)"
        [ "$ESP" = "$FPR" ] && ok "la huella coincide con la esperada" || mal "la huella NO es la esperada ($ESP)"
      else echo "      Compara esa huella con la del README oficial."; fi
    else mal "la firma PGP no es válida"; fi
  else echo "  --  falta la clave pública (GUERRILLA.asc del repo): no se comprueba"; fi
else echo "  --  sin SHA256SUMS.asc o sin gpg: no se comprueba"; fi

echo "3) Certificado de la APK"
APK="$(ls LaZoo*.apk 2>/dev/null | head -1)"
if [ -n "$APK" ]; then
  AS="$(command -v apksigner || ls "${ANDROID_HOME:-$HOME/android-sdk}"/build-tools/*/apksigner 2>/dev/null | tail -1)"
  if [ -n "$AS" ]; then
    H="$("$AS" verify --print-certs "$APK" 2>/dev/null | awk -F': ' '/certificate SHA-256 digest/{print toupper($2); exit}')"
    if [ -n "$H" ]; then
      ok "$APK firmada; SHA-256 del certificado: $H"
      if [ -n "${LAZOO_APK_HUELLA:-}" ]; then
        ESP="$(printf '%s' "$LAZOO_APK_HUELLA" | tr -d ' :' | tr a-f A-F)"
        [ "$ESP" = "$H" ] && ok "coincide con la esperada" || mal "NO coincide con la esperada"
      else echo "      Compara con la huella del README oficial."; fi
    else mal "$APK no tiene una firma válida"; fi
  else echo "  --  falta apksigner (Android SDK build-tools): no se comprueba"; fi
else echo "  --  no hay APK en la carpeta"; fi

echo
if [ "$FALLOS" -eq 0 ]; then echo "Resultado: sin fallos."; else echo "Resultado: $FALLOS fallo(s). No uses estos archivos."; fi
exit "$FALLOS"
