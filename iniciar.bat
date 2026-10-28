@echo off
cd /d "%~dp0"
where py >nul 2>&1 && (set "PY=py") || (set "PY=python")
%PY% -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)"
if errorlevel 1 (
  echo No encuentro Python 3.10 o mas nuevo.
  echo Instálalo desde https://www.python.org/downloads/
  echo y marca "Add python.exe to PATH".
  pause
  exit /b 1
)
if not exist .venv (
  %PY% -m venv .venv
  if errorlevel 1 (
    echo No pude crear el entorno de Python.
    pause
    exit /b 1
  )
)
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo Fallo la instalacion. Copia el texto de esta ventana.
  pause
  exit /b 1
)
netsh advfirewall firewall delete rule name="Lazo" >nul 2>&1
netsh advfirewall firewall add rule name="Lazo" dir=in action=allow protocol=TCP localport=8787 profile=any >nul 2>&1
if errorlevel 1 (
  echo.
  echo El movil no entra si Windows bloquea Lazo. Acepta el permiso.
  powershell -NoProfile -Command "Start-Process -Verb RunAs -Wait -FilePath netsh -ArgumentList 'advfirewall','firewall','delete','rule','name=Lazo'"
  powershell -NoProfile -Command "Start-Process -Verb RunAs -Wait -FilePath netsh -ArgumentList 'advfirewall','firewall','add','rule','name=Lazo','dir=in','action=allow','protocol=TCP','localport=8787','profile=any'"
)
python lazo.py
echo.
echo Lazo se cerro.
pause
