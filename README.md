# LaZoo 0.51

Beta de las fases 2 y 4: icono en la bandeja de Windows (`LaZoo.pyw`) y primera APK de Android (`android/`). Protocolo en `protocol.py`. La última versión estable y de referencia es la [0.31](https://github.com/Guerrillabitcoin/lazo/tree/v0.31.0).

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

**Windows sin consola (nuevo en 0.43):** doble clic en `LaZoo.pyw`. LaZoo queda como icono en la bandeja, junto al sonido y la Wi-Fi, sin ventana negra. Clic derecho en el icono: abrir la ventana del PC, mostrar el QR, Pastillas, Solicitudes pendientes (aceptar o rechazar), Dispositivos conectados (expulsar uno o a todos), Puente Wi-Fi, Propiedades, Iniciar con Windows (apagado de serie) y Salir. Doble clic abre la ventana del PC. Si ya está en marcha, abrirlo otra vez solo trae su ventana. El registro va a `%LOCALAPPDATA%\LaZoo\lazoo.log`. Para hacer un `.exe`, mira `empaquetar-exe.md`. En Linux y macOS la bandeja llegará en la fase 3.

**Novedad 0.51:** el ratón simula un movimiento continuo, como el touchpad de un portátil. Con «Predicción de movimiento» (activada por defecto, en Ratón, junto a «Movimiento continuo») el PC calcula la velocidad del dedo y, cuando la Wi-Fi deja un hueco, sigue moviendo el cursor a esa velocidad frenando poco a poco (como mucho 150 ms). Cuando llegan los datos reales, lo ya movido se descuenta, así que el cursor acaba exactamente donde debe (deriva 0). Si paras el dedo sin soltarlo, lo que se haya adelantado se devuelve con suavidad. Clics, arrastres y rueda nunca usan la predicción. Nuevo: «Inercia al soltar» (apagada de serie; poca, media o mucha): al levantar el dedo el cursor desliza y frena; tocar o hacer clic lo para. Si apagas la predicción, todo va exactamente como en 0.50. Modo stats añade: predicción sí/no, inercia, píxeles predichos/s, error de predicción medio/máx. y deriva acumulada. El tamaño del móvil no cambia la sensibilidad: el desplazamiento se mide en píxeles CSS, que ya son independientes de la densidad de la pantalla, y no depende del ancho del touchpad (un móvil pequeño solo obliga a levantar el dedo más a menudo; para eso sirve la inercia).

**Novedad 0.50:** el ratón va más fluido aunque el Wi-Fi llegue a ráfagas. El móvil manda como máximo 60 movimientos por segundo y, si la red se atasca, junta los pendientes en uno solo (sin perder nada). El PC, con «Movimiento continuo» (activado por defecto, en Ratón), reparte lo recibido en pasos pequeños a unos 200 por segundo con un colchón de ~30 ms que se adapta solo. La APK mantiene el Wi-Fi del móvil despierto y en baja latencia mientras está abierta. Modo stats añade: movimiento continuo, colchón, pasos/s, cola pendiente máx. y fusionados.

**Novedad 0.49:** las estadísticas del ratón están ahora en la pestaña **Ratón**. Activa «Modo stats» debajo del touchpad y verás los números de fondo, semitransparentes, sin que estorben al dedo. Se guardan los últimos 15 segundos: mueve el ratón, suelta y pulsa «Copiar stats» (elige 5, 10 o 15 s). Copia un resumen en texto con versión, precisión, vigilante, eco mínimo/medio/máximo/p95, huecos y ráfagas. «Congelar» (o «Congelar al soltar el dedo») deja fijos los datos para leerlos con calma. El suavizado y el vigilante también están ahí.

**Novedad 0.48:** el «Diagnóstico del ratón» de Pruebas compara lo que **envía el móvil** con lo que **recibe el PC**: movimientos por segundo en cada lado, el tiempo normal y el peor entre dos movimientos, huecos de más de 50, 100 y 250 ms y si llegan a ráfagas. El eco de ida y vuelta se separa en red y tiempo del PC, y se mide si el navegador del móvil va sobrecargado. Debajo sale una frase que explica dónde está el atasco. Nueva casilla «Vigilante del ratón del PC»: es lo que devuelve el cursor a tamaño normal si usas el ratón de verdad del PC tras ponerlo grande desde el móvil. Ahora solo está activo mientras el cursor es grande o enorme, es más ligero y se puede apagar en caliente, o al arrancar con `--sin-vigilante` o `LAZO_SIN_VIGILANTE=1`. Al apagarlo solo se pierde esa vuelta automática al cursor normal. El «Suavizado en el PC» da ya pasos de 5 ms reales en Windows (antes 15 ms).

**Novedad 0.47:** el ratón va píxel a píxel cuando mueves el dedo muy despacio (antes saltaba de 2 en 2), y a velocidad normal o rápida va igual que antes. En la pastilla Ratón hay «Precisión»: Fina, Normal o Rápida (se guarda en el móvil). En Pruebas hay un «Diagnóstico del ratón» (movimientos por segundo, retraso de la Wi-Fi, si va por la conexión directa o por la lenta) y la opción «Suavizado en el PC», que reparte cada movimiento en pasos pequeños de 5 ms. Para construir el `.exe` y la APK en GitHub sin usar tu PC, mira `PUBLICAR.md`.

**Novedad 0.46:** la pastilla de YouTube tiene un botón grande «Pantalla completa». Pone el vídeo del PC a pantalla completa (tecla `f` de YouTube) y, al volver a pulsarlo, sale (tecla Esc). En Windows LaZoo mira si la ventana ocupa todo el monitor para saber en qué estado está.

**Arreglo 0.45:** con la 0.44 en Windows la barra de tareas y Chrome parpadeaban sin parar: la ventana del PC preguntaba cada 1,5 s por la red y LaZoo abría una ventana negra de `ipconfig` cada vez (unas 90 por minuto). Ahora ningún programa auxiliar abre ventana, la red se consulta como mucho cada 30 s y la ventana no pregunta si está oculta.

**Ventana del PC (nuevo en 0.44):** al arrancar `LaZoo.pyw` o el `.exe` (también con «Iniciar con Windows») se abre la ventana del PC. Mientras no haya ningún móvil conectado, arriba sale el panel «Conecta tu móvil» con el QR, el PIN, la dirección y botones (QR a pantalla completa, Puente Wi-Fi, Dispositivos). Al unirse un móvil aprobado, el panel se oculta y queda el puente. Si no queda ninguno (expulsado, cerrado o sin señal), vuelve solo. «Conectado» = un móvil aprobado que ha hablado con el PC en los últimos 5 segundos (la app lo hace sola cada pocos segundos). Para arrancar sin abrir la ventana: `LaZoo.pyw --sin-ventana`.

**Android (nuevo en 0.44):** instala `LaZoo-0.44.apk` (permite «instalar apps desconocidas»; está firmada con una clave propia de pruebas, no viene de Google Play). Al abrirla sale el escáner de QR: apunta al QR de la ventana del PC y entra. Sin servicios de Google, vale en GrapheneOS. Solo abre direcciones de tu red local. «Atrás» vuelve al escáner, que tiene «Volver al último PC» y un campo para escribir la dirección. Cómo compilarla: `android/README.md`.

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
- **Dispositivos nuevos.** La primera vez que un móvil entra (con QR o PIN), queda «Esperando aprobación en el PC…». En el PC se pregunta en la consola (S/N, 30 s), en Windows con un cuadro Sí/No y en la ventana del PC con Aceptar/Rechazar y en el menú del icono de la bandeja. Al aceptar, el móvil entra solo: con el QR no vuelve a pedir el PIN. Sin respuesta en 60 s, se rechaza. Rechazado = bloqueado 5 minutos. Lo aprobado vale hasta que cierras LaZoo.
- En la ventana del PC y en «Sobre LaZoo» hay una lista de dispositivos con «Expulsar» y «Expulsar a todos». Un expulsado tiene que volver a ser aprobado.
- Solo para pruebas automáticas: `LAZO_AUTOAPPROVE=1` (o `--auto-aprobar`) deja entrar sin preguntar. Nunca está activo por defecto; no lo uses en el día a día.


La clave viaja solo en el QR (o, si escribes el PIN de 6 dígitos, se entrega una vez al móvil). Cada petición va firmada y no vale dos veces; no hay cookie. El PIN es el camino menos seguro: si puedes, escanea el QR. Cada vez que reinicias el PC hay que volver a escanear el QR. No lo uses en una Wi-Fi pública. Quien tenga el PIN y esté en tu red puede mover el ratón, escribir y cerrar ventanas mientras Lazo está encendido.

Para pararlo: `Ctrl+C` en la terminal.

MIT. Úsalo en tus propios equipos.
