#!/bin/sh
# LaZoo 0.67: instala lo que LaZoo necesita en Linux y lo pone en el menú de aplicaciones.
#   sh instalar-linux.sh            pregunta antes de instalar paquetes del sistema (sudo)
#   sh instalar-linux.sh --si       sin preguntar
#   sh instalar-linux.sh --quitar   quita el acceso del menú y el inicio con el sistema
# No instala nada fuera de tu usuario salvo los paquetes del sistema, y solo si dices que sí.
cd "$(dirname "$0")" || exit 1
DIR="$(pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTO="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"

if [ "$1" = "--quitar" ]; then
  rm -f "$APPS/lazoo.desktop" "$AUTO/lazoo.desktop"
  echo "Quitado LaZoo del menú y del inicio con el sistema. La carpeta $DIR sigue aquí."
  exit 0
fi

# Paquetes por familia de distribución:
#   bandeja (PyGObject + indicador), ratón/teclado en X11 (pynput va por pip), ventanas,
#   multimedia (playerctl), volumen, brillo y avisos.
if command -v apt-get >/dev/null 2>&1; then
  PKGS="python3 python3-venv python3-pip python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 playerctl wmctrl xdotool pulseaudio-utils brightnessctl libnotify-bin"
  INSTALL="sudo apt-get install -y"
elif command -v dnf >/dev/null 2>&1; then
  PKGS="python3 python3-pip python3-gobject gtk3 libayatana-appindicator-gtk3 playerctl wmctrl xdotool pulseaudio-utils brightnessctl libnotify"
  INSTALL="sudo dnf install -y"
elif command -v pacman >/dev/null 2>&1; then
  PKGS="python python-pip python-gobject gtk3 libayatana-appindicator playerctl wmctrl xdotool libpulse brightnessctl libnotify"
  INSTALL="sudo pacman -S --needed --noconfirm"
elif command -v zypper >/dev/null 2>&1; then
  PKGS="python3 python3-pip python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-3_0 typelib-1_0-AyatanaAppIndicator3-0_1 playerctl wmctrl xdotool pulseaudio-utils brightnessctl libnotify-tools"
  INSTALL="sudo zypper install -y"
else
  PKGS=""
  INSTALL=""
fi

if [ -n "$INSTALL" ]; then
  echo "LaZoo necesita estos paquetes del sistema:"
  echo "  $PKGS"
  if [ "$1" = "--si" ]; then RESP=s; else printf "¿Los instalo ahora con sudo? [s/N] "; read -r RESP; fi
  case "$RESP" in
    s|S|si|sí|y|Y) $INSTALL $PKGS || echo "Algún paquete no se pudo instalar: LaZoo arranca igual con lo que haya." ;;
    *) echo "Sin instalar. Puedes hacerlo luego con: $INSTALL $PKGS" ;;
  esac
else
  echo "No reconozco el gestor de paquetes. Instala a mano: python3, PyGObject (gi) con GTK 3 y AyatanaAppIndicator, playerctl, wmctrl y xdotool."
fi

# Wayland: mover el ratón desde fuera necesita ydotool (o una sesión X11).
if [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
  echo
  echo "Tu sesión es Wayland: el ratón de LaZoo va con ydotool (y su servicio ydotoold)."
  echo "Si el ratón no se mueve, elige «Ubuntu en Xorg» (o «Plasma X11») en la pantalla de entrada."
fi

mkdir -p "$APPS"
cat > "$APPS/lazoo.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=LaZoo
Comment=Ratón y teclado del PC desde el móvil
Exec=sh "$DIR/iniciar.sh"
Icon=$DIR/static/img/infinito-naranja.svg
Terminal=false
Categories=Utility;
EOF
chmod +x iniciar.sh 2>/dev/null
echo
echo "Listo. Abre «LaZoo» desde el menú de aplicaciones (o: sh iniciar.sh)."
echo "Para arrancarlo con el sistema: menú del icono → «Iniciar con el sistema»."
