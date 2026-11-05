#!/usr/bin/env bash
# LaZoo · Crea la clave de LANZAMIENTO de la APK EN TU PC (nada sale a internet).
#   bash firmas/generar_keystore.sh [ARCHIVO.jks] [ALIAS]
# Por defecto: ~/LaZoo-claves/lazoo-lanzamiento.jks, alias lazoo, RSA 4096, validez 30 años.
# keytool pide la contraseña (2 veces): usa una larga (20+ caracteres) y guárdala en tu gestor.
# Este script no la ve ni la guarda. Si pierdes el archivo o la contraseña, NO podrás publicar
# actualizaciones que se instalen encima: haz 2 copias cifradas en sitios distintos.
set -euo pipefail
KS="${1:-$HOME/LaZoo-claves/lazoo-lanzamiento.jks}"
ALIAS="${2:-lazoo}"
command -v keytool >/dev/null || { echo "Falta keytool (viene con Java 17: apt install openjdk-17-jdk-headless)"; exit 1; }
[ -e "$KS" ] && { echo "Ya existe $KS. No lo sobrescribo."; exit 1; }
mkdir -p "$(dirname "$KS")"; chmod 700 "$(dirname "$KS")"
DIR="$(cd "$(dirname "$KS")" && pwd)"
if git -C "$DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "ERROR: $DIR está dentro de un repositorio git. Elige una carpeta fuera del repo."; exit 1
fi
# Solo para pruebas automáticas: si existe LAZOO_KS_PASS se lee de ahí (nunca en la línea de órdenes).
PASS=(); LISTA=()
if [ -n "${LAZOO_KS_PASS:-}" ]; then PASS=(-storepass:env LAZOO_KS_PASS -keypass:env LAZOO_KS_PASS); LISTA=(-storepass:env LAZOO_KS_PASS); fi
umask 077
keytool -genkeypair -v -storetype PKCS12 -keystore "$KS" -alias "$ALIAS" \
  -keyalg RSA -keysize 4096 -validity 10950 -dname "CN=GUERRILLA, O=LaZoo" "${PASS[@]}"
echo
echo "Huella SHA-256 del certificado (publícala en README y en about.json → apk_huella):"
keytool -list -v -keystore "$KS" -alias "$ALIAS" "${LISTA[@]}" 2>/dev/null | grep -E "SHA256:" | sed 's/^[[:space:]]*/  /' || true
echo
echo "Listo: $KS"
echo "AHORA: 2 copias cifradas (p. ej. USB cifrado + otra en un lugar distinto) del .jks y la contraseña por separado."
echo "Para GitHub: firmas/preparar_secretos.md"
