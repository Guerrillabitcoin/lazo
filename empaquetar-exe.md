# LaZoo como .exe de Windows (Fase 2)

Hoja de ruta para pasar de `iniciar.bat` (con consola) a un programa con icono en la bandeja.

## Ya hecho en 0.43

- `LaZoo.pyw` + `bandeja.py`: LaZoo sin ventana negra, con icono en la bandeja (junto al sonido y la Wi-Fi).
  Doble clic en `LaZoo.pyw` (lo abre `pythonw`). `iniciar.bat` sigue igual, con su consola.
- Menú del icono (clic derecho): abrir la ventana del PC, mostrar el QR, Pastillas, Solicitudes pendientes
  (aceptar o rechazar), Dispositivos conectados (expulsar uno o a todos), Puente Wi-Fi, Propiedades,
  Iniciar con Windows (apagado por defecto) y Salir. Doble clic en el icono abre la ventana del PC.
- Un solo ejemplar: si ya está en marcha, abrir otro solo trae su ventana.
- Lo que antes salía en la consola va a `%LOCALAPPDATA%\LaZoo\lazoo.log`.
- Icono propio en `static/lazoo.ico` (lo genera `python icono.py`, solo biblioteca estándar).

## Construir el .exe

En Windows, con Python 3.10+ en el PATH, doble clic en `construir_exe.bat`. Hace esto:

1. Crea una venv temporal en `%TEMP%\lazoo-exe-venv` e instala PyInstaller ahí (no en tu Python).
2. `pyinstaller --noconsole --onedir --name LaZoo --icon static\lazoo.ico --add-data "static;static" ... LaZoo.pyw`
3. Deja el resultado en `dist\LaZoo\` y borra la venv.

Se reparte la **carpeta** `dist\LaZoo` entera (comprimida en zip). `--onedir` arranca más rápido y da
menos falsos positivos de antivirus que `--onefile`. El .exe no va dentro del zip de código.

No se puede construir desde Linux: PyInstaller solo genera ejecutables del sistema donde corre.

## Avisos de Windows

- **SmartScreen**: un .exe sin firma digital sale como «Windows protegió su PC». Se abre con
  «Más información» → «Ejecutar de todas formas». Para quitarlo hace falta un certificado de firma de código
  (de pago) y reputación con el tiempo.
- **Antivirus**: los .exe de PyInstaller sin firma a veces dan falsos positivos. Si pasa, se puede seguir usando
  `LaZoo.pyw` o `iniciar.bat`, que son el código a la vista.
- **Firewall**: la primera vez Windows pregunta por `LaZoo.exe`. Permite solo redes privadas.

## Pendiente

- Firmar el .exe y publicarlo como `LaZoo-X.Y-windows.zip` en el Release.
- Instalador opcional (acceso directo en el menú Inicio).
- En el .exe, las notas y la carpeta `nube` se guardan dentro de `_internal`; `Fotos` ya va junto al .exe.
  Moverlo todo a `%LOCALAPPDATA%\LaZoo` en una versión próxima.
- Bandeja en Linux y macOS (fase 3). Hoy `bandeja.py` solo avisa ahí; se usa `iniciar.sh`.
- APK de Android con lector de QR al abrir (fase 4).
