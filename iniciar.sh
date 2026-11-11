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
python3 -m venv --system-site-packages .venv || exit 1
. .venv/bin/activate
python -m pip install -r requirements.txt || exit 1
if [ "$(uname -s)" = "Linux" ] && [ "$1" != "--consola" ]; then
  python bandeja_linux.py "$@"
  estado=$?
  [ "$estado" -ne 2 ] && exit "$estado"
  echo "Sigo en la consola."
fi
[ "$1" = "--consola" ] && shift
exec python lazo.py "$@"
