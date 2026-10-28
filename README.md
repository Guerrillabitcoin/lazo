# Lazo

Mando abierto para controlar **tu** PC desde el móvil, en la misma Wi-Fi.

- Ratón: trackpad, clic, clic derecho, arrastre y scroll
- Teclado, incluida la ñ, y una frase entera
- Ventanas: lista, traer al frente, minimizar, maximizar, izquierda, derecha, cerrar
- YouTube: play, salto de 10 s, volumen del vídeo, pantalla completa, siguiente
- Spotify: play, anterior, siguiente y volumen de la app
- Cursor del sistema: normal, grande o enorme
- Volumen del sistema

No es una web suelta. El navegador del móvil no puede mover el ratón del ordenador. Lazo es un programa pequeño que arrancas **en el PC** y el móvil entra por la Wi-Fi.

## Arranque

Hace falta Python 3.10 o más nuevo.

```bash
git clone https://github.com/Guerrillabitcoin/lazo.git
cd lazo
python -m venv .venv
```

Windows:

```bat
.venv\Scripts\activate
pip install -r requirements.txt
python lazo.py
```

macOS y Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
python lazo.py
```

En la terminal sale un PIN de 6 cifras y una dirección `http://192.168.x.x:8787`. En el móvil, con la **misma Wi-Fi**, abre esa dirección y mete el PIN.

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
