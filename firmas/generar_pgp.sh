#!/usr/bin/env bash
# LaZoo · Genera la clave PGP de GUERRILLA EN TU PC (nada sale a internet).
#   bash firmas/generar_pgp.sh [ALIAS] [CORREO] [CADUCIDAD] [CARPETA_SALIDA]
# Por defecto: GUERRILLA, guerrilla@users.noreply.github.com, 2y, ~/LaZoo-claves
# - Clave principal ed25519 solo para certificar + subclave ed25519 de firma (caducan en 2 años).
# - La contraseña la pide gpg (pinentry). Este script NO la ve ni la guarda.
# - Deja en CARPETA_SALIDA: GUERRILLA.asc (PÚBLICA), revocacion-GUERRILLA.asc (PRIVADA: guárdala
#   fuera de línea) y huella.txt. Nunca dentro del repositorio.
set -euo pipefail
ALIAS="${1:-GUERRILLA}"
CORREO="${2:-guerrilla@users.noreply.github.com}"
CADUCA="${3:-2y}"
SALIDA="${4:-$HOME/LaZoo-claves}"

command -v gpg >/dev/null || { echo "Falta gpg. Linux: apt install gnupg · macOS: brew install gnupg"; exit 1; }
case "$CORREO" in *@users.noreply.github.com) ;; *)
  echo "AVISO: el correo no es el noreply de GitHub. Para no exponer datos personales usa ALIAS@users.noreply.github.com"
  read -r -p "¿Seguir igualmente? (s/N) " r; [ "$r" = "s" ] || exit 1 ;;
esac
mkdir -p "$SALIDA"; chmod 700 "$SALIDA"
SALIDA="$(cd "$SALIDA" && pwd)"
if git -C "$SALIDA" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "ERROR: $SALIDA está dentro de un repositorio git. Elige una carpeta fuera del repo."; exit 1
fi
UID_TXT="$ALIAS <$CORREO>"
if gpg --batch --list-secret-keys "=$UID_TXT" >/dev/null 2>&1; then
  echo "Ya tienes una clave para «$UID_TXT». No creo otra (bórrala o usa otro alias)."; exit 1
fi
# Solo para pruebas automáticas con claves desechables: LAZOO_PGP_SIN_PASS=1 (sin contraseña).
EXTRA=()
if [ "${LAZOO_PGP_SIN_PASS:-}" = "1" ]; then EXTRA=(--pinentry-mode loopback --passphrase ""); fi

echo "1/4 Creando la clave principal (solo certificar, caduca en $CADUCA). gpg te pedirá una contraseña larga."
gpg --batch "${EXTRA[@]}" --quick-generate-key "$UID_TXT" ed25519 cert "$CADUCA"
FPR="$(gpg --batch --with-colons --list-keys "=$UID_TXT" | awk -F: '/^fpr:/{print $10; exit}')"
echo "2/4 Añadiendo la subclave de firma."
gpg --batch "${EXTRA[@]}" --quick-add-key "$FPR" ed25519 sign "$CADUCA"

echo "3/4 Exportando la clave PÚBLICA y el certificado de revocación."
gpg --batch --armor --export "$FPR" > "$SALIDA/GUERRILLA.asc"
REV="${GNUPGHOME:-$HOME/.gnupg}/openpgp-revocs.d/$FPR.rev"
if [ -f "$REV" ]; then cp "$REV" "$SALIDA/revocacion-GUERRILLA.asc"; chmod 600 "$SALIDA/revocacion-GUERRILLA.asc"; fi
gpg --batch --fingerprint "$FPR" | sed -n '2p' | tr -s ' ' > "$SALIDA/huella.txt"

echo "4/4 Listo."
echo
echo "Huella (cópiala en README y en about.json → pgp_huella):"
echo "  $FPR"
echo
echo "Archivos en $SALIDA:"
echo "  GUERRILLA.asc              PÚBLICA → cópiala a la raíz del repo y a GitHub (Settings → SSH and GPG keys)"
echo "  revocacion-GUERRILLA.asc   PRIVADA → a un USB fuera de línea. Quien la tenga puede anular tu clave."
echo
echo "COPIA DE SEGURIDAD (hazla ahora, en un USB cifrado, no en la nube ni en el repo):"
echo "  gpg --armor --export-secret-keys $FPR > /ruta/usb/GUERRILLA-secreta.asc"
echo "Para GitHub Actions exporta SOLO la subclave de firma (ver firmas/preparar_secretos.md)."
