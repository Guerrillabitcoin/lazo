# LaZoo 0.42

Beta de la fase 1 (protocolo en `protocol.py`). La última versión estable y de referencia es la [0.31](https://github.com/Guerrillabitcoin/lazo/tree/v0.31.0).

Mando abierto para controlar **tu** PC desde el móvil, en la misma Wi-Fi. Nada sale a internet. En Windows el portapapeles y los archivos de la mesa se guardan cifrados para tu usuario.

- Ratón: trackpad, clic, clic derecho, arrastre y scroll
- Teclado, incluida la ñ, y una frase entera
- Ventanas: agrupadas por app con el icono real de cada programa (Windows; en Linux el del tema si lo hay). Si una app tiene una sola ventana sale como un botón directo. Tocar una ventana la trae delante maximizada; debajo salen Minimizar, Restaurar, Cambiar de pantalla y Cerrar. En Chrome/Edge en Windows, la lista de pestañas reales (solo la barra de pestañas, no el contenido de la página)
- YouTube: iconos de anterior, play/pausa y siguiente. El título y el estado se actualizan solos mientras miras la pastilla (en Windows leyendo las sesiones multimedia del sistema; en Linux con playerctl). Anterior vuelve al 0:00 si el vídeo lleva más de 5 s y, si no, va al vídeo anterior
- Spotify: los mismos iconos y la misma regla de 5 s en anterior, y volumen de la app
- Cursor del sistema: normal, grande o enorme
- Sistema: volumen de sistema, brillo del portátil (Windows; Linux con brightnessctl), intercambiar las ventanas entre dos pantallas y bloquear el PC (en rojo y con confirmación). El menú Win+P queda en Pruebas
- Puente: «Archivos» abre el selector de archivos del móvil (sin filtro de tipo, para que Android no lo mande a la galería), «Fotos y vídeos» la galería y «Carpeta» una carpeta entera, que llega al PC con sus subcarpetas
- Sin conexión: en la pantalla del PIN hay «Escanear QR». Por HTTP los navegadores no dejan usar la cámara en directo, así que abre la cámara del móvil, saca una foto del QR y la lee sin internet (BarcodeDetector o jsQR, Apache-2.0, en `static/jsqr.js`). También vale la app de cámara del móvil

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
| Ventanas en Linux | `sudo apt install wmctrl xdotool` (xdotool para pestañas) |
| Spotify en Linux | `sudo apt install playerctl` |
| Cursor grande en Linux | Escritorio GNOME (`gsettings`) |

YouTube se controla con los atajos del reproductor (`k`, `j`, `l`, flechas). Lazo pone esa ventana delante y pulsa la tecla.

## Permisos

- **macOS:** Ajustes del Sistema → Privacidad y seguridad → Accesibilidad y Monitorización de entrada. Activa Terminal (o la app desde la que lanzaste `python`).
- **Linux en Wayland:** el ratón y el teclado a veces no entran. Si no se mueve el cursor, entra en una sesión «GNOME en Xorg» o «Ubuntu en Xorg». El volumen con PipeWire y Spotify con `playerctl` sí suelen funcionar en Wayland.
- **Windows:** el cursor enorme usa el tamaño de puntero del sistema. Si no cambia al momento, cierra sesión una vez.

## Puente Wi-Fi

- **Del móvil al PC:** «Enviar archivos al PC» o «Enviar una carpeta». Cualquier tipo de archivo, varios a la vez y sin el tope de 80 MB (por defecto hasta 8 GB por archivo; se cambia con `--max-gb` o la variable `LAZO_MAX_GB`). Llega a la carpeta `Fotos` junto a LaZoo; «Abrir carpeta» en la ventana del PC la abre.
- Va en trozos de 4 MB, cada uno cifrado y firmado. Si se corta la Wi-Fi, reintenta solo. Si el PC se reinicia, vuelve a escanear el QR y elige el mismo archivo: sigue donde se quedó. Al final se comprueba el SHA-256 del archivo entero. Antes de empezar mira si cabe en el disco.
- Los envíos a medias que nadie retoma se borran a las 24 horas.
- **Del PC al móvil:** en la ventana del PC suelta archivos (o pulsa para elegir) y aparecen en el móvil en «Del PC al móvil».

## Sobre LaZoo

La última pastilla enseña el logo, la versión, la licencia (MIT), cómo protege LaZoo la conexión y tus enlaces. «Buscar actualización» solo consulta internet cuando lo pulsas: el PC pide `VERSION.txt` de la rama `main` en GitHub y lo compara con el tuyo.

Los enlaces y las direcciones de donación (solo Bitcoin: Lightning, BOLT12, pagos silenciosos `sp1...` y on-chain) salen de `about.json`. Copia `about.example.json` como `about.json` y rellénalo. Lo vacío o con formato raro no se muestra. Los QR se hacen en el PC, sin servicios externos. `about.json` no se sube al repositorio.

## Seguridad

- **Solo red local.** LaZoo solo acepta conexiones de tu red local: el propio PC (127.x, `::1`), direcciones privadas (10.x, 172.16–31.x, 192.168.x), link-local (169.254.x, `fe80::`), IPv6 local (`fc00::/7`) y esas mismas en forma `::ffff:a.b.c.d`. Cualquier otra se corta antes de leer nada y la consola dice «Rechazada conexión desde fuera de la red local: …» (una vez por minuto y dirección como mucho).
- No publiques LaZoo detrás de un proxy inverso: no está soportado. La cabecera `X-Forwarded-For` se ignora siempre.
- Para entrar por una VPN propia (por ejemplo Tailscale, 100.64.0.0/10), añade el rango: `python lazo.py --permitir-ip 100.64.0.0/10` (se puede repetir) o la variable `LAZO_ALLOW=100.64.0.0/10,otro/rango`. La consola avisa de que amplías el acceso.
- **Dispositivos nuevos.** La primera vez que un móvil entra (con QR o PIN), queda «Esperando aprobación en el PC…». En el PC se pregunta en la consola (S/N, 30 s), en Windows con un cuadro Sí/No y en la ventana del PC con Aceptar/Rechazar. Sin respuesta en 60 s, se rechaza. Rechazado = bloqueado 5 minutos. Lo aprobado vale hasta que cierras LaZoo.
- En la ventana del PC y en «Sobre LaZoo» hay una lista de dispositivos con «Expulsar» y «Expulsar a todos». Un expulsado tiene que volver a ser aprobado.
- Solo para pruebas automáticas: `LAZO_AUTOAPPROVE=1` (o `--auto-aprobar`) deja entrar sin preguntar. Nunca está activo por defecto; no lo uses en el día a día.


La clave viaja solo en el QR (o, si escribes el PIN de 6 dígitos, se entrega una vez al móvil). Cada petición va firmada y no vale dos veces; no hay cookie. El PIN es el camino menos seguro: si puedes, escanea el QR. Cada vez que reinicias el PC hay que volver a escanear el QR. No lo uses en una Wi-Fi pública. Quien tenga el PIN y esté en tu red puede mover el ratón, escribir y cerrar ventanas mientras Lazo está encendido.

Para pararlo: `Ctrl+C` en la terminal.

MIT. Úsalo en tus propios equipos.
