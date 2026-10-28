# LaZoo 0.11

Mando abierto para controlar **tu** PC desde el móvil, en la misma Wi-Fi. La **0.11** devuelve el cursor a pequeño al usar el ratón del PC, y abre una mesa para pegar texto y pasar archivos.

- Ratón: trackpad, clic, clic derecho, arrastre y scroll
- Teclado, incluida la ñ, y una frase entera
- Ventanas: lista, traer al frente, minimizar, maximizar, izquierda, derecha, cerrar
- YouTube: play, salto de 10 s, volumen del vídeo, pantalla completa, siguiente
- Spotify: play, anterior, siguiente y volumen de la app
- Cursor del sistema: normal, grande o enorme
- Volumen del sistema

No es una web suelta. El navegador del móvil no puede mover el ratón del ordenador. Lazo es un programa pequeño que arrancas **en el PC** y el móvil entra por la Wi-Fi.

## Arranque

Hace falta Python 3.10 o más nuevo. En Windows, al instalarlo, marca **Add python.exe to PATH**.

**Windows:** descomprime el ZIP y haz doble clic en `iniciar.bat`. La ventana no se cierra si algo falla: deja el texto a la vista.

**macOS y Linux:** en la carpeta descomprimida:

```bash
chmod +x iniciar.sh
./iniciar.sh
```

En el PC se abre una ventana con la dirección, por ejemplo `http://192.168.1.20:8787`, un QR en blanco y negro y el PIN. En el móvil, misma Wi-Fi, abre Chrome y **escribe esa dirección**. Si el QR no abre nada, no importa: escribe la dirección a mano. Empieza por `http://`, no por `https://`. Luego mete el PIN.

No hace falta VPN. El móvil y el PC tienen que estar en la misma Wi-Fi de casa, no en datos móviles. Si Windows pregunta, permite Lazo: la Wi-Fi a veces está marcada como red pública y, si no se permite, el móvil no carga nada.

Si hay dos direcciones, usa la que dice **Wi-Fi**. Ignora las que empiezan por `172.`. La primera vez Windows pide permiso: acéptalo. Si lo cancelas, el móvil no entra.

Cuando Windows pregunte por el firewall, permite las redes privadas. No abras el puerto 8787 en el router: cualquiera de internet podría intentar entrar.

## Qué tiene que estar abierto

| Quieres | En el PC |
| --- | --- |
| YouTube | Una pestaña del navegador cuyo título diga YouTube |
| Spotify | La aplicación de Spotify, no hace falta que esté delante |
| Ventanas en Linux | `sudo apt install wmctrl` |
| Spotify en Linux | `sudo apt install playerctl` |
| Cursor grande en Linux | Escritorio GNOME (`gsettings`) |

YouTube se controla con los atajos del reproductor (`k`, `j`, `l`, flechas). Lazo pone esa ventana delante y pulsa la tecla.

## Permisos

- **macOS:** Ajustes del Sistema → Privacidad y seguridad → Accesibilidad y Monitorización de entrada. Activa Terminal (o la app desde la que lanzaste `python`).
- **Linux en Wayland:** el ratón y el teclado a veces no entran. Si no se mueve el cursor, entra en una sesión «GNOME en Xorg» o «Ubuntu en Xorg». El volumen con PipeWire y Spotify con `playerctl` sí suelen funcionar en Wayland.
- **Windows:** el cursor enorme usa el tamaño de puntero del sistema. Si no cambia al momento, cierra sesión una vez.

## Seguridad

El PIN y la cookie viven solo en tu red local. No lo uses en una Wi-Fi pública. Quien tenga el PIN y esté en tu red puede mover el ratón, escribir y cerrar ventanas mientras Lazo está encendido.

Para pararlo: `Ctrl+C` en la terminal.

MIT. Úsalo en tus propios equipos.
