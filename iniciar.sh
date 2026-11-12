#!/bin/sh
# LaZoo en Linux y macOS. En Linux con escritorio abre el icono de la bandeja (0.67);
# sin escritorio, sin PyGObject o con --consola, sigue en esta consola como siempre.
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "No encuentro python3. Instálalo y vuelve a abrir este archivo."
  exit 1
fi
# --system-site-packages: así se ve PyGObject (python3-gi) del sistema para la bandeja.
if [ -f .venv/pyvenv.cfg ] && ! grep -q "include-system-site-packages = true" .venv/pyvenv.cfg; then
  rm -rf .venv
fi
if ! python3 -m venv --system-site-packages .venv; then
  rm -rf .venv  # 0.69: un entorno a medias haría fallar la próxima vez
  v=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
  echo "Falta el módulo venv de Python. En Ubuntu/Debian: sudo apt install python3-venv python$v-venv"
  echo "O ejecuta: sh instalar-linux.sh"
  exit 1
fi
. .venv/bin/activate
python -m pip install -r requirements.txt || exit 1
if [ "$(uname -s)" = "Linux" ] && ! command -v wl-copy >/dev/null 2>&1 \
   && ! command -v xclip >/dev/null 2>&1 && ! command -v xsel >/dev/null 2>&1; then
  # 0.69: sin esto «Al PC» guarda la nota pero no la pone en el portapapeles.
  echo "Aviso: para el portapapeles instala xclip (Xorg) o wl-clipboard (Wayland): sudo apt install xclip wl-clipboard"
fi
if [ "$(uname -s)" = "Linux" ] && [ "$1" != "--consola" ]; then
  python bandeja_linux.py "$@"
  estado=$?
  [ "$estado" -ne 2 ] && exit "$estado"
  echo "Sigo en la consola."
fi
[ "$1" = "--consola" ] && shift
exec python lazo.py "$@"
