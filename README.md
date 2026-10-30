# LaZoo 0.37

Beta de la fase 1 (protocolo en `protocol.py`). La última versión estable y de referencia es la [0.31](https://github.com/Guerrillabitcoin/lazo/tree/v0.31.0).

Mando abierto para controlar **tu** PC desde el móvil, en la misma Wi-Fi. Nada sale a internet. En Windows el portapapeles y los archivos de la mesa se guardan cifrados para tu usuario.

- Ratón: trackpad, clic, clic derecho, arrastre y scroll
- Teclado, incluida la ñ, y una frase entera
- Ventanas: lista vertical con la activa resaltada; traer al frente, maximizar / restaurar, cerrar, mitad izquierda o derecha y mover a otra pantalla (hasta 3; Windows y Linux X11 con wmctrl)
- YouTube: play, salto de 10 s, volumen del vídeo, pantalla completa, siguiente
- Spotify: play, anterior, siguiente y volumen de la app
- Cursor del sistema: normal, grande o enorme
- Sistema: volumen (subir, bajar, silencio), brillo (Windows; Linux con brightnessctl), cambiar pantalla (Win+P) y bloquear el PC

No es una web suelta. El navegador del móvil no puede mover el ratón del ordenador. Lazo es un programa pequeño que arrancas **en el PC** y el móvil entra por la Wi-Fi.

## Arranque

Hace falta Python 3.10 o más nuevo. En Windows, al instalarlo, marca **Add python.exe to PATH**.

**Windows:** descomprime el ZIP y haz doble clic en `iniciar.bat`. La ventana no se cierra si algo falla: deja el texto a la vista.

**macOS y Linux:** en la carpeta descomprimida:

```bash
chmod +x iniciar.sh
./iniciar.sh
```

En el PC se abre una ventana con la dirección, por ejemplo `http://192.168.1.20:8787`, un QR y el PIN. El navegador puede decir que la conexión no es segura. En una dirección de casa eso solo significa que no hay candado: no es un aviso de sitio malicioso. No instales un certificado. La primera vez Windows pide permiso del firewall: acéptalo.

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

## Descargatodo

Pastilla «Descargatodo» en el móvil y sección del mismo nombre en la ventana del PC. Pegas un enlace (YouTube, Instagram, TikTok, X y casi cualquier web), pulsas «Buscar formatos» y eliges: mejor calidad, 1080p, 720p, 480p, solo audio MP3, solo audio original o, en «Avanzado», un formato concreto. Se descarga **en el PC**, en `Descargas/LaZoo`; desde el móvil, «Enviar al móvil» lo recibe cifrado como el puente (hasta 400 MB).

- Usa [yt-dlp](https://github.com/yt-dlp/yt-dlp) y ffmpeg, que no van dentro de LaZoo. «Instalar herramientas (una vez)» los baja a la carpeta `herramientas/` del programa: yt-dlp del release oficial de GitHub y, en Windows, ffmpeg del release de BtbN/FFmpeg-Builds (unos 200 MB). Solo HTTPS y con la huella SHA-256 oficial comprobada. En Linux y macOS, ffmpeg se instala con el gestor del sistema (`sudo apt install ffmpeg`, `brew install ffmpeg`). «Actualizar yt-dlp» cuando una web deje de funcionar.
- Privacidad: no usa cookies del navegador ni tu cuenta; el enlace solo lo ve el PC y la web de origen. Algunas webs piden iniciar sesión o bloquean descargas: entonces no funcionará.
- **Solo para uso personal. Respeta los derechos de autor y las normas de cada web.**

## Sobre LaZoo

La última pastilla enseña el logo, la versión, la licencia (MIT), cómo protege LaZoo la conexión y tus enlaces. «Buscar actualización» solo consulta internet cuando lo pulsas: el PC pide `VERSION.txt` de la rama `main` en GitHub y lo compara con el tuyo.

Los enlaces y las direcciones de donación (solo Bitcoin: Lightning, BOLT12, pagos silenciosos `sp1...` y on-chain) salen de `about.json`. Copia `about.example.json` como `about.json` y rellénalo. Lo vacío o con formato raro no se muestra. Los QR se hacen en el PC, sin servicios externos. `about.json` no se sube al repositorio.

## Seguridad

La clave viaja solo en el QR (o, si escribes el PIN de 6 dígitos, se entrega una vez al móvil). Cada petición va firmada y no vale dos veces; no hay cookie. El PIN es el camino menos seguro: si puedes, escanea el QR. Cada vez que reinicias el PC hay que volver a escanear el QR. No lo uses en una Wi-Fi pública. Quien tenga el PIN y esté en tu red puede mover el ratón, escribir y cerrar ventanas mientras Lazo está encendido.

Para pararlo: `Ctrl+C` en la terminal.

MIT. Úsalo en tus propios equipos.
