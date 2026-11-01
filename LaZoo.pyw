"""LaZoo sin consola: icono en la bandeja de Windows. Ábrelo con doble clic (pythonw).

iniciar.bat sigue funcionando igual, con su ventana de consola.
Lo que antes salía en la consola va a %LOCALAPPDATA%\\LaZoo\\lazoo.log.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.chdir(HERE)

if sys.stdout is None or sys.stderr is None:  # pythonw: sin consola, a un registro
    base = Path(os.environ.get("LOCALAPPDATA") or HERE) / "LaZoo"
    base.mkdir(parents=True, exist_ok=True)
    log = open(base / "lazoo.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log

import bandeja  # noqa: E402

sys.exit(bandeja.main(sys.argv[1:]))
