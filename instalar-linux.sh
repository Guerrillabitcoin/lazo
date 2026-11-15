#!/bin/sh
# LaZoo 0.67: instala lo que LaZoo necesita en Linux y lo pone en el menú de aplicaciones.
#   sh instalar-linux.sh            pregunta antes de instalar paquetes del sistema (sudo)
#   sh instalar-linux.sh --si       sin preguntar
#   sh instalar-linux.sh --quitar   quita el acceso del menú y el inicio con el sistema
#   sh instalar-linux.sh --ydotool  solo prepara el ratón en Wayland (ydotool)
#   sh instalar-linux.sh --pcapc    0.71: solo los permisos de «Controlar otro PC» (un paso, con sudo o pkexec)
#                                    0.78: añade --emisor para controlar otro PC desde este en Wayland (grupo «input»)
# No instala nada fuera de tu usuario salvo los paquetes del sistema, y solo si dices que sí.
cd "$(dirname "$0")" || exit 1
DIR="$(pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTO="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"

# 0.71 · «Controlar otro PC»: lo que hace falta como administrador, en un solo paso.
#   /dev/uinput para el grupo «uinput» (que otro PC mueva el ratón de este, también en Wayland)
#   y, SOLO con «--emisor» (0.78), el usuario también en «input» (leer el teclado y el ratón para
#   controlar otro PC desde este en Wayland). Con el grupo «input» cualquier programa del usuario
#   puede leer el teclado, contraseñas incluidas: para que te controlen basta «uinput».
# En Xorg no hace falta nada de esto: LaZoo usa XTest y XGrabKeyboard, sin permisos.
if [ "$1" = "--permisos-root" ]; then
  U="$2"
  if [ "$(id -u)" != "0" ] || [ -z "$U" ] || ! id "$U" >/dev/null 2>&1; then
    echo "Uso interno: como administrador, --permisos-root USUARIO [--emisor]"; exit 1
  fi
  groupadd -f uinput
  echo 'KERNEL=="uinput", GROUP="uinput", MODE="0660", OPTIONS+="static_node=uinput"' > /etc/udev/rules.d/80-lazoo-uinput.rules
  modprobe uinput 2>/dev/null
  echo uinput > /etc/modules-load.d/lazoo-uinput.conf 2>/dev/null
  udevadm control --reload-rules && udevadm trigger --name-match=uinput
  if [ "$3" = "--emisor" ]; then
    getent group input >/dev/null 2>&1 || groupadd -f input
    usermod -aG uinput,input "$U"
    echo "Permisos listos para $U (uinput e input). Cierra sesión y vuelve a entrar."
  else
    usermod -aG uinput "$U"
    echo "Permiso listo para $U (uinput: que otro PC controle este). Cierra sesión y vuelve a entrar."
  fi
  exit 0
fi

permisos_pcapc() {
  echo
  echo "Controlar otro PC: en Wayland, LaZoo necesita permiso para mover el ratón de este PC (/dev/uinput)."
  echo "Para controlar OTRO PC desde este también en Wayland, además hay que leer tu teclado y ratón"
  echo "(/dev/input, grupo «input»): ojo, cualquier programa tuyo podría leer el teclado, contraseñas incluidas."
  echo "Se hace una vez."
  EMISOR=""
  SI=""
  for A in "$1" "$2"; do
    [ "$A" = "--si" ] && SI=1
    [ "$A" = "--emisor" ] && EMISOR="--emisor"
  done
  if [ -n "$SI" ]; then RESP=s; else printf "¿Lo preparo ahora (pide tu contraseña)? [s/N] "; read -r RESP; fi
  case "$RESP" in
    s|S|si|sí|y|Y)
      # 0.78: el grupo «input» solo si lo pides (--emisor) o dices que sí aquí; con --si a secas, no.
      if [ -z "$EMISOR" ] && [ -z "$SI" ]; then
        printf "¿También controlar otro PC desde este en Wayland (grupo «input», lee el teclado)? [s/N] "; read -r R2
        case "$R2" in s|S|si|sí|y|Y) EMISOR="--emisor" ;; esac
      fi
      ;;
  esac
  case "$RESP" in
    s|S|si|sí|y|Y)
      if command -v sudo >/dev/null 2>&1 && [ -t 0 ]; then
        sudo sh "$DIR/instalar-linux.sh" --permisos-root "$USER" $EMISOR
      elif command -v pkexec >/dev/null 2>&1; then
        pkexec sh "$DIR/instalar-linux.sh" --permisos-root "$USER" $EMISOR
      else
        echo "No encuentro sudo ni pkexec: como administrador, ejecuta: sh $DIR/instalar-linux.sh --permisos-root $USER $EMISOR"
      fi
      echo "CIERRA SESIÓN Y VUELVE A ENTRAR para que valgan los permisos."
      ;;
    *) echo "Sin preparar. Puedes hacerlo luego con: sh instalar-linux.sh --pcapc (o el botón «Arreglar» del Panel)." ;;
  esac
}

if [ "$1" = "--pcapc" ]; then
  permisos_pcapc "$2" "$3"
  exit 0
fi

if [ "$1" = "--quitar" ]; then
  rm -f "$APPS/lazoo.desktop" "$AUTO/lazoo.desktop"
  systemctl --user disable --now lazoo-ydotoold.service 2>/dev/null
  rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/lazoo-ydotoold.service"
  echo "La regla /etc/udev/rules.d/80-lazoo-uinput.rules y los grupos «uinput» e «input» se quitan a mano (sudo)."
  echo "Quitado LaZoo del menú y del inicio con el sistema. La carpeta $DIR sigue aquí."
  exit 0
fi

# Paquetes por familia de distribución:
#   bandeja (PyGObject + indicador), ratón/teclado en X11 (pynput va por pip), ventanas,
#   multimedia (playerctl), volumen, brillo y avisos.
if command -v apt-get >/dev/null 2>&1; then
  PKGS="python3 python3-venv python3-pip python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 playerctl wmctrl xdotool pulseaudio-utils brightnessctl libnotify-bin wl-clipboard xclip ydotool libxtst6"
  INSTALL="sudo apt-get install -y"
elif command -v dnf >/dev/null 2>&1; then
  PKGS="python3 python3-pip python3-gobject gtk3 libayatana-appindicator-gtk3 playerctl wmctrl xdotool pulseaudio-utils brightnessctl libnotify wl-clipboard xclip ydotool libXtst"
  INSTALL="sudo dnf install -y"
elif command -v pacman >/dev/null 2>&1; then
  PKGS="python python-pip python-gobject gtk3 libayatana-appindicator playerctl wmctrl xdotool libpulse brightnessctl libnotify wl-clipboard xclip ydotool libxtst"
  INSTALL="sudo pacman -S --needed --noconfirm"
elif command -v zypper >/dev/null 2>&1; then
  PKGS="python3 python3-pip python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-3_0 typelib-1_0-AyatanaAppIndicator3-0_1 playerctl wmctrl xdotool pulseaudio-utils brightnessctl libnotify-tools wl-clipboard xclip ydotool libXtst6"
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

# 0.68 · Wayland: el ratón y el teclado de LaZoo van con ydotool y su servicio ydotoold.
# ydotoold escribe en /dev/uinput. Se da permiso SOLO a ese archivo, con un grupo propio
# («uinput»): el grupo «input» dejaría a cualquier programa tuyo leer lo que tecleas.
if [ "${XDG_SESSION_TYPE:-}" = "wayland" ] || [ "$1" = "--ydotool" ]; then
  echo
  if command -v ydotool >/dev/null 2>&1 && ! ydotool mousemove --help 2>&1 | grep -q -- "--xpos"; then
    echo "Tu ydotool es 0.1.x (el de Ubuntu y Debian): LaZoo no lo necesita. Usa /dev/uinput directamente."
    permisos_pcapc "$1"
  elif ! command -v ydotoold >/dev/null 2>&1; then
    echo "Tu sesión es Wayland y no hay ydotoold (ydotool 1.x): el ratón desde el móvil no se mueve en Wayland,"
    echo "pero «Controlar otro PC» va por /dev/uinput y no lo necesita."
    permisos_pcapc "$1"
  else
    echo "Tu sesión es Wayland: LaZoo mueve el ratón y pulsa teclas con ydotool."
    echo "Hace falta (una vez, con sudo): una regla para /dev/uinput y añadirte al grupo «uinput»."
    if [ "$1" = "--si" ]; then RESP=s; else printf "¿Lo preparo ahora? [s/N] "; read -r RESP; fi
    case "$RESP" in
      s|S|si|sí|y|Y)
        sudo groupadd -f uinput
        echo 'KERNEL=="uinput", GROUP="uinput", MODE="0660", OPTIONS+="static_node=uinput"' | sudo tee /etc/udev/rules.d/80-lazoo-uinput.rules >/dev/null
        sudo udevadm control --reload-rules && sudo udevadm trigger --name-match=uinput
        sudo usermod -aG uinput "$USER"
        UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
        mkdir -p "$UNIT"
        cat > "$UNIT/lazoo-ydotoold.service" <<EOF
[Unit]
Description=ydotoold para LaZoo (ratón y teclado en Wayland)

[Service]
ExecStart=$(command -v ydotoold) --socket-path=%t/.ydotool_socket --socket-own=%U:%G
Restart=on-failure

[Install]
WantedBy=default.target
EOF
        systemctl --user daemon-reload
        systemctl --user enable lazoo-ydotoold.service
        echo "Listo. CIERRA SESIÓN Y VUELVE A ENTRAR (o reinicia) para que valga el grupo «uinput»."
        permisos_pcapc --si
        ;;
      *) echo "Sin preparar. Puedes hacerlo luego con: sh instalar-linux.sh --ydotool" ;;
    esac
  fi
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
