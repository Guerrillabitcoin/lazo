#!/bin/sh
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "No encuentro python3. Instálalo y vuelve a abrir este archivo."
  exit 1
fi
python3 -m venv .venv || exit 1
. .venv/bin/activate
python -m pip install -r requirements.txt || exit 1
exec python lazo.py
