@echo off
rem Construye dist\LaZoo\LaZoo.exe (carpeta, sin consola) con PyInstaller en una venv temporal.
rem No instala nada en tu Python ni pone LaZoo en el inicio de Windows.
setlocal
cd /d "%~dp0"
set "VENV=%TEMP%\lazoo-exe-venv"
python -m venv "%VENV%" || goto :fail
"%VENV%\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check pyinstaller -r requirements.txt || goto :fail
"%VENV%\Scripts\pyinstaller.exe" --noconfirm --clean --noconsole --onedir --name LaZoo ^
  --icon static\lazoo.ico ^
  --add-data "static;static" --add-data "VERSION.txt;." --add-data "medios.ps1;." ^
  --add-data "permitir.ps1;." --add-data "about.example.json;." ^
  --distpath dist --workpath build LaZoo.pyw || goto :fail
rmdir /s /q "%VENV%"
echo.
echo   Listo: dist\LaZoo\LaZoo.exe
echo   Copia la carpeta dist\LaZoo entera; el .exe solo no arranca.
pause
exit /b 0
:fail
echo.
echo   No se pudo construir el .exe. Mira el texto de arriba.
pause
exit /b 1
