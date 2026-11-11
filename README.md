# LaZoo 0.68

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

**Windows sin consola (nuevo en 0.43):** doble clic en `LaZoo.pyw`. LaZoo queda como icono en la bandeja, junto al sonido y la Wi-Fi, sin ventana negra. Clic derecho en el icono: abrir el Panel de LaZoo, mostrar el QR, Pastillas, Solicitudes pendientes (aceptar o rechazar), Dispositivos conectados (expulsar uno o a todos), Puente Wi-Fi, Propiedades, Iniciar con Windows (apagado de serie) y Salir. Doble clic abre la ventana del PC. Si ya está en marcha, abrirlo otra vez solo trae su ventana. El registro va a `%LOCALAPPDATA%\LaZoo\lazoo.log`. Para hacer un `.exe`, mira `empaquetar-exe.md`. En Linux, desde 0.67, también hay bandeja (mira «Novedad 0.67»); en macOS llegará más adelante.

**Novedad 0.68 (Linux con Wayland):** LaZoo funciona en el Ubuntu de hoy (GNOME en Wayland) sin cambiar de sesión. **Ratón y teclado** con `ydotool`: `instalar-linux.sh` lo deja preparado (una regla solo para `/dev/uinput` con un grupo propio, `uinput`, y el servicio de usuario `lazoo-ydotoold`); hay que cerrar sesión una vez. El texto con ñ, acentos o símbolos se pega (y el portapapeles de antes vuelve). **YouTube sin teclas:** play/pausa, ±10 s, siguiente, anterior y la barra van por los controles multimedia (`playerctl`); silencio, subtítulos, modo cine, pantalla completa y el volumen exacto, pulsando los botones del propio reproductor por accesibilidad. Encuentra la ventana de YouTube también con Firefox de Ubuntu. En Wayland aún no van la velocidad ni el tamaño de los subtítulos desde el móvil (avisa). **La pestaña Ventanas no sale con un PC Linux.** Lista de pruebas: [`docs/PRUEBAS-LINUX.md`](docs/PRUEBAS-LINUX.md).

**Novedad 0.67 (Linux):** LaZoo funciona en Linux casi como en Windows. Descomprime `LaZoo-0.67-linux.tar.gz`, ejecuta `sh instalar-linux.sh` (dice qué paquetes del sistema faltan y solo usa `sudo` si le dices que sí) y abre **LaZoo** desde el menú de aplicaciones.
- **Icono en la bandeja** con el mismo menú que en Windows, cuadro para aceptar móviles nuevos (60 s) e «Iniciar con el sistema». KDE, Cinnamon, Xfce y Ubuntu lo enseñan tal cual; en GNOME puro hace falta la extensión «AppIndicator and KStatusNotifierItem Support». Sin escritorio, `iniciar.sh` sigue en la consola (`--consola` lo fuerza).
- **No bloquear el PC** mientras usas el móvil (inhibidor de GNOME o de systemd; el cursor no se toca).
- **Barra de progreso con salto exacto** y pausa de «Seguir viendo en el móvil» con los controles multimedia de Linux (`playerctl`), sin teclas.
- **«¿Sigues ahí?», saltar anuncios y patrocinios, volumen real, «Seguir viendo en el móvil» y el historial** con la accesibilidad de Linux (AT-SPI). Chrome y Brave necesitan la accesibilidad activada: `gsettings set org.gnome.desktop.interface toolkit-accessibility true` y reabrir el navegador. `python3 linux_yt.py --diagnostico` dice si LaZoo ve YouTube.
- **Cursor grande** en GNOME, KDE, Cinnamon, MATE y Xfce.
- Límites: en Wayland el ratón va con `ydotool` (o elige la sesión Xorg al entrar); la pastilla YouTube encuentra la ventana con `wmctrl`, que en Wayland solo ve los navegadores que van por XWayland (Chrome y Brave, de serie). La APK es la misma para Windows y Linux.

**Novedad 0.66:** el Panel de LaZoo ordena sus ajustes en una caja **Configuración** (antes iban sueltos en la barra de arriba): Dispositivos, YouTube y Este PC. Debajo, **Anuncios y patrocinios saltados**: cada salto de verdad con la hora, el vídeo (con enlace al minuto, si se sabe cuál), el tramo m:ss → m:ss y el tiempo ahorrado. La lista se borra entera o de una en una; el **tiempo ahorrado desde siempre** se queda y solo se pone a cero con su propio botón. En los anuncios el tiempo es una estimación («≈»): lo que le quedaba según los controles multimedia de Windows; si Windows no lo dice, sale «¿?». Todo se guarda en la carpeta de datos de LaZoo, nada sale a internet y solo se ve desde este PC (`/mesa#pastilla=config` o `#pastilla=historial`).

**Novedad 0.65:** el mando de YouTube del móvil sabe cómo está el vídeo de verdad y hace más cosas, sin tocar la página de YouTube y sin salir a internet. **Barra de progreso:** enseña el minuto y la duración, avanza sola y, al arrastrar, dice «Ir a 12:34 de 45:00»; el salto se hace al soltar (se le pide a Windows y, si el navegador no lo deja, con las teclas de YouTube). **Velocidad y volumen reales:** la velocidad la publica Windows y el volumen se lee del propio reproductor (también si está en silencio); si no se puede leer, el número lleva «≈». **Tamaño de los subtítulos:** botones A − y A +. **Seguir viendo en el móvil:** el PC pausa el vídeo y el móvil lo abre en el mismo minuto (2 s antes), en Brave si está instalado; hace falta la App 2. Solo Windows.

**App 2 (0.65):** la app del móvil puede abrir un enlace de YouTube fuera de LaZoo, en Brave o en el navegador, solo cuando tocas «Seguir viendo en el móvil». Con la App 1 todo lo demás sigue igual.

**Novedad 0.64:** LaZoo salta los patrocinios que van dentro del propio vídeo de YouTube, el rato en que el youtuber habla de su patrocinador. Los tramos los marca la comunidad de [SponsorBlock](https://sponsor.ajay.app). Para saber dónde están, el PC pregunta con solo 4 letras del SHA-256 del id del vídeo: SponsorBlock devuelve los tramos de unos cien vídeos y LaZoo se queda con el suyo, así que nadie fuera de tu PC sabe qué vídeo ves. Es la única conexión a internet que añade LaZoo y se apaga con la casilla. El salto se le pide a Windows, como si arrastraras la barra del panel multimedia: no mueve el ratón, no pulsa teclas y no trae la ventana delante. Cada tramo se salta una vez: si vuelves atrás para verlo, se queda. El Panel cuenta «Patrocinios saltados: N · hoy: H · ahorrado: 4 min». **Desde 0.65 viene apagado de serie:** se enciende en el Panel o en la pestaña YouTube del móvil («Saltar patrocinios del vídeo») y LaZoo lo recuerda; `--con-patrocinios` o `LAZO_CON_PATROCINIOS=1` lo encienden solo para esa sesión. `--sin-patrocinios` o `LAZO_SIN_PATROCINIOS=1` lo apagan del todo y mandan sobre lo demás. Mientras está apagado, LaZoo no pregunta nada a SponsorBlock. Solo Windows, con YouTube como pestaña activa de su ventana.

**App del móvil con número propio (0.64):** la APK pasa a llamarse «App 1» y solo sube de número cuando cambia ella misma. Las funciones y los rediseños llegan con el `.exe`, porque la interfaz del móvil la pone el PC: no hace falta reinstalar la app. «Sobre LaZoo» enseña el número de la app y, en «Cuándo sale algo a internet», todo lo que conecta fuera.

**Novedad 0.61:** el Panel se rediseña: caja «Conectar» a la izquierda (se oculta al conectar), «Portapapeles Móvil ↔ PC» con papelera en cada nota, y una sola caja «Archivos» (carpeta de recibidos + drop + lista con PC→móvil / móvil→PC).

**Novedad 0.60:** el Panel cuenta cuántas veces LaZoo ha quitado el aviso «¿Sigues ahí?» de YouTube («Avisos quitados: N · hoy: H · último: hoy 14:32»). Solo cuenta si el aviso desapareció de verdad; se guarda al reiniciar y se pone a cero con «Poner a cero».

**Novedad 0.59:** YouTube ya no se queda parado en «Vídeo en pausa. ¿Quieres seguir viendo?». Si aparece, el PC pulsa «Sí» por accesibilidad de Windows (UI Automation): no mueve el ratón, no pulsa teclas y no trae la ventana delante. Se apaga en el Panel o en la pestaña YouTube del móvil («Evitar el aviso ‘¿Sigues ahí?’ de YouTube»), o con `--sin-sigues`. Solo Windows por ahora.

**Novedad 0.58:** preparación de las firmas, sin cambiar nada de uso. Guía en [docs/FIRMAS.md](docs/FIRMAS.md) y scripts en `firmas/` para crear **en tu PC** la clave PGP de GUERRILLA y la clave de lanzamiento de la APK, más `verificar.ps1`/`verificar.sh` para que cualquiera compruebe una descarga. El workflow nuevo (en `ci/construir.yml`) crea `SHA256SUMS`, firma PGP, atestación de GitHub y una Release, todo opcional: sin secretos sale igual que antes. «Sobre LaZoo» puede enseñar las huellas (`pgp_huella`, `apk_huella` en `about.json`).

**Novedad 0.57:** arreglada de verdad la conexión del móvil tras aceptarlo en el PC. Con el `.exe` (y con «Recordar dispositivos», activado de serie), al aceptar el móvil el PC fallaba al guardar la clave cifrada (DPAPI): el vigilante del portapapeles cambiaba una pieza de Windows que compartía con «Recordar», y la respuesta con la clave nunca llegaba al móvil. Ahora cada parte usa la suya, el PC responde primero y guarda después, y un fallo al guardar ya no corta nada. Además: un móvil expulsado o tras «Olvidar todos» vuelve solo a la pantalla del QR/PIN con el motivo (sin bucles con la clave vieja) y puede emparejar de nuevo; si al abrir no contesta el PC, reintenta cada 5 s sin borrar la clave; los mensajes dicen en qué paso falló; y hay un botón **«Copiar diagnóstico de conexión»** en el móvil (pantalla del PIN y de espera) y en el Panel de LaZoo, con la fase, el último error y las versiones (nunca la clave ni el PIN).

**Novedad 0.56:** arreglado el emparejamiento que fallaba justo después de aceptar el móvil en el PC («hace un amago de entrar pero no»). El móvil preguntaba al PC cada 1,5 s sin esperar la respuesta anterior; con la Wi-Fi lenta dos preguntas se cruzaban, la primera recibía la clave y la segunda, ya sin sesión, mandaba el móvil de vuelta al PIN. Ahora el móvil hace una sola pregunta a la vez, el PC repite la entrega si hace falta durante 30 s, una respuesta vieja ya no echa al móvil y los ajustes del ratón se mandan al entrar (antes salían sin clave al cargar). Si la APK reabre una dirección con un QR ya usado, entra con la clave guardada. Logotipo: «LaZoo», el anillo rojo y el infinito verde son ahora los contornos trazados de la imagen original (misma forma de letras, separación entre «a» y «Z», grosor y tamaño de las «o»), y los iconos de la bandeja y de la APK salen trazados de sus imágenes.

**Novedad 0.55:** nuevo logotipo. En el Panel de LaZoo y en el móvil, «LaZoo» lleva la última «o» como un anillo rojo mientras no hay conexión; al conectar, las dos «o» se funden en un infinito verde con una animación de un segundo (y al desconectar vuelve al anillo rojo; si tienes activado «reducir movimiento» en el sistema, cambia sin animar). Mientras el móvil espera aprobación, el anillo es naranja y late suave. El icono de la bandeja de Windows es un infinito rojo sin móviles y verde con al menos uno conectado, con el texto «LaZoo · sin dispositivos» o «LaZoo · N dispositivo(s) conectado(s)». El `.exe`, la APK, el favicon y el icono de pantalla de inicio del móvil usan el infinito naranja.

**Novedad 0.54:** emparejamiento más seguro y reconexión automática. El QR y el PIN ya no llevan ni entregan la clave larga: solo sirven para que el móvil se identifique y pida permiso. El móvil se ve **desconectado** con un aviso naranja arriba (y, con la APK, una notificación en la barra del teléfono) hasta que lo aceptas en el PC; solo entonces le llega la clave, cifrada con un secreto de un solo uso. Se acepta en un único sitio: el aviso de Windows o el menú del icono de la bandeja («Aceptar/Rechazar dispositivo pendiente»). **Recordar dispositivos** (activado de serie, en el icono de la bandeja y en el Panel): guarda la clave cifrada en este PC (DPAPI en Windows; en Linux/macOS, archivo cifrado con permisos 600) y la lista de aprobados con nombre, fecha y huella, así que los móviles se reconectan solos al reiniciar el PC, también con «Iniciar con Windows». **Olvidar todos** borra todo eso, cambia la clave y obliga a emparejar y aceptar de nuevo. La ventana del PC se llama ahora **Panel de LaZoo**, apaisada: QR, PIN y pasos arriba mientras espera; estado, dispositivos, portapapeles, archivos y lo recibido del móvil en columnas cuando está conectado. YouTube: el título ocupa hasta 2 líneas sin cortar palabras, la velocidad cambia desde la actual (no baja siempre a 0,25x) y LaZoo recuerda la ventana de YouTube que usas aunque cambie de vídeo.

**Novedad 0.53:** ajuste fino del ratón. «Modo stats» pasa a llamarse «Ajuste fino / stats» (en Ratón, debajo del touchpad) y, al activarlo, aparecen todas las opciones de fluidez, cada una con una línea de ayuda: corrección suave de la predicción (2-4 pasos en vez de un salto), mezcla al llegar datos reales, interpolación en pasos de 5 ms solo tras un hueco de red, colchón adaptativo con rango (15-40 ms por defecto) o fijo, pasos del PC (125/200/250/500 Hz), duración y frenado de la predicción, sub-píxeles con redondeo estable, límite de cola, «reciente primero», temporizador de alta resolución y envíos del móvil (30/60/90/120 por segundo). Presets: «Equilibrado» (por defecto), «Máxima fluidez», «Mínimo retraso» y «Como 0.50», y «Restablecer valores». El móvil recuerda la elección; el PC valida cada valor. «Copiar stats» añade el preset, las opciones, el rango del colchón, las correcciones suaves y los pasos interpolados por segundo. Guía de pruebas: [`docs/PRUEBAS-RATON.md`](docs/PRUEBAS-RATON.md).

**Novedad 0.52:** portapapeles compartido. El PC vigila su portapapeles (cada 1,5 s) y lo que copies aparece en Notas del móvil; nada pasa solo al móvil: para traerlo pulsa «Copiar». En Notas, el botón «Al PC» guarda la nota y la deja en el portapapeles del PC, lista para Ctrl+V. Todo se guarda solo en el PC (`clipboard-history.json`), nada en el móvil, y va por la red local cifrado como siempre. Para apagar el vigilante: `--sin-portapapeles` o `LAZO_SIN_PORTAPAPELES=1`.

**Novedad 0.51:** el ratón simula un movimiento continuo, como el touchpad de un portátil. Con «Predicción de movimiento» (activada por defecto, en Ratón, junto a «Movimiento continuo») el PC calcula la velocidad del dedo y, cuando la Wi-Fi deja un hueco, sigue moviendo el cursor a esa velocidad frenando poco a poco (como mucho 150 ms). Cuando llegan los datos reales, lo ya movido se descuenta, así que el cursor acaba exactamente donde debe (deriva 0). Si paras el dedo sin soltarlo, lo que se haya adelantado se devuelve con suavidad. Clics, arrastres y rueda nunca usan la predicción. Nuevo: «Inercia al soltar» (apagada de serie; poca, media o mucha): al levantar el dedo el cursor desliza y frena; tocar o hacer clic lo para. Si apagas la predicción, todo va exactamente como en 0.50. Modo stats añade: predicción sí/no, inercia, píxeles predichos/s, error de predicción medio/máx. y deriva acumulada. El tamaño del móvil no cambia la sensibilidad: el desplazamiento se mide en píxeles CSS, que ya son independientes de la densidad de la pantalla, y no depende del ancho del touchpad (un móvil pequeño solo obliga a levantar el dedo más a menudo; para eso sirve la inercia).

**Novedad 0.50:** el ratón va más fluido aunque el Wi-Fi llegue a ráfagas. El móvil manda como máximo 60 movimientos por segundo y, si la red se atasca, junta los pendientes en uno solo (sin perder nada). El PC, con «Movimiento continuo» (activado por defecto, en Ratón), reparte lo recibido en pasos pequeños a unos 200 por segundo con un colchón de ~30 ms que se adapta solo. La APK mantiene el Wi-Fi del móvil despierto y en baja latencia mientras está abierta. Modo stats añade: movimiento continuo, colchón, pasos/s, cola pendiente máx. y fusionados.

**Novedad 0.49:** las estadísticas del ratón están ahora en la pestaña **Ratón**. Activa «Ajuste fino / stats» (antes «Modo stats») debajo del touchpad y verás los números de fondo, semitransparentes, sin que estorben al dedo. Se guardan los últimos 15 segundos: mueve el ratón, suelta y pulsa «Copiar stats» (elige 5, 10 o 15 s). Copia un resumen en texto con versión, precisión, vigilante, eco mínimo/medio/máximo/p95, huecos y ráfagas. «Congelar» (o «Congelar al soltar el dedo») deja fijos los datos para leerlos con calma. El suavizado y el vigilante también están ahí.

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
| Cursor grande en Linux | GNOME, KDE, Cinnamon, MATE o Xfce |
| Todo lo de Linux de una vez | `sh instalar-linux.sh` |

YouTube se controla con los atajos del reproductor (`k`, `j`, `l`, flechas). Lazo pone esa ventana delante y pulsa la tecla.

## Permisos

- **macOS:** Ajustes del Sistema → Privacidad y seguridad → Accesibilidad y Monitorización de entrada. Activa Terminal (o la app desde la que lanzaste `python`).
- **Linux en Wayland:** el ratón y el teclado a veces no entran. Si no se mueve el cursor, entra en una sesión «GNOME en Xorg» o «Ubuntu en Xorg». El volumen con PipeWire y Spotify con `playerctl` sí suelen funcionar en Wayland.
- **Windows:** el cursor enorme usa el tamaño de puntero del sistema. Si no cambia al momento, cierra sesión una vez.

## Pasar por wifi (antes «Puente Wi-Fi» y «Notas»)

Desde 0.63 las notas, el portapapeles compartido y los archivos están en una sola pestaña, «Pasar por wifi», y en una sola caja del Panel. Nada pasa por internet: va directo entre el móvil y el PC por tu Wi-Fi, cifrado (LZ2) con una clave que solo tienen el PC y cada móvil aceptado. Las notas se guardan cifradas en el PC (Windows: con tu cuenta; Linux y Mac: con una clave local solo legible por tu usuario) en la carpeta privada de LaZoo, y se pueden borrar una a una o todas desde el móvil. Lo que un gestor de contraseñas marca como privado al copiarlo no entra en las notas.

### Puente Wi-Fi

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
- **Dispositivos nuevos.** La primera vez que un móvil entra (con QR o PIN), queda «Esperando aprobación en el PC…» y se ve desconectado. En Windows se acepta en el cuadro Sí/No o en el menú del icono de la bandeja; en Linux/macOS, en la consola (S/N, 30 s). El Panel de LaZoo solo enseña que hay uno esperando. Al aceptar, el móvil recibe la clave y entra solo. Sin respuesta en 60 s, se rechaza. Rechazado = bloqueado 5 minutos. Con «Recordar dispositivos», lo aprobado sigue valiendo tras reiniciar; sin él, vale hasta que cierras LaZoo.
- En el Panel de LaZoo y en «Sobre LaZoo» hay una lista de dispositivos con «Expulsar» y «Expulsar a todos». Un expulsado tiene que volver a ser aprobado. «Olvidar todos» (Panel o bandeja) borra la clave guardada y la lista y cambia la clave.
- Solo para pruebas automáticas: `LAZO_AUTOAPPROVE=1` (o `--auto-aprobar`) deja entrar sin preguntar. Nunca está activo por defecto; no lo uses en el día a día.


Desde la 0.54 la clave no va en el QR ni sale por el PIN: el móvil y el PC hacen un saludo X25519 efímero, el móvil prueba que conoce el QR o el PIN y, solo cuando aceptas el dispositivo en el PC, recibe la clave sellada con un secreto de ese saludo. Quien escuche la Wi-Fi no puede sacarla. Cada petición va firmada y no vale dos veces; no hay cookie. El PIN sigue siendo el camino menos seguro (alguien que se meta en medio justo al emparejar podría adivinarlo): si puedes, escanea el QR. Sin «Recordar dispositivos», cada vez que reinicias el PC hay que volver a emparejar. No lo uses en una Wi-Fi pública. Quien tenga el PIN y esté en tu red puede mover el ratón, escribir y cerrar ventanas mientras Lazo está encendido.

Para pararlo: `Ctrl+C` en la terminal.

MIT. Úsalo en tus propios equipos.

## Comprobar descargas

Guía completa: [docs/FIRMAS.md](docs/FIRMAS.md). En cada Release habrá `SHA256SUMS` y, cuando estén activas, su firma `SHA256SUMS.asc` y la atestación de GitHub.

- Huella PGP de GUERRILLA: *pendiente (0.59)*. Clave pública: `GUERRILLA.asc` en la raíz del repo.
- Huella SHA-256 del certificado de la APK: *pendiente (0.59)*. Hasta entonces la APK va firmada con una clave de pruebas que cambia en cada build.
- `.exe`: sin firma de Windows todavía (SmartScreen avisa).

Comprobar: `firmas/verificar.sh CARPETA` o `powershell -ExecutionPolicy Bypass -File firmas\verificar.ps1 -Carpeta CARPETA`, y `gh attestation verify ARCHIVO -R Guerrillabitcoin/lazo`.

## Identidad visual

| Uso | Color | Hex |
| --- | --- | --- |
| Anillo «desconectado» del wordmark | rojo | `#ea0918` |
| Infinito «conectado» del wordmark | verde | `#158941` |
| Infinito de la bandeja sin conexión | rojo | `#f71224` |
| Infinito de la bandeja conectada | verde lima | `#58c006` |
| Infinito de la app (APK, `.exe`, favicon, icono del móvil) | naranja | `#ff813f` |
| Color de la interfaz (botones, títulos) | naranja de marca | `#e07a3d` |
| Letras «LaZ» y primera «o» | blanco sobre fondo negro | `#ffffff` / `#000000` |

- Letras, anillos e infinitos: contornos trazados (potrace) de las imágenes de `static/img/original/`, guardados en `diseno/trazos.json`; no se usa ninguna tipografía. Colores medidos en esas imágenes.
- Archivos: `static/img/` (SVG y PNG finales), `static/img/original/` (imágenes originales), `static/lazoo.ico` (naranja, `.exe`), `static/lazoo-rojo.ico` y `static/lazoo-verde.ico` (bandeja, de 16 a 256 px), `android/res/` (mipmaps, icono adaptable e icono de notificación).
- Animación: `static/logo.js`, sin librerías. Para regenerarlo todo: `python diseno/logos.py` (necesita Pillow); para volver a trazar los originales: `python diseno/logos.py --trazar` (además numpy y potracer). Solo para desarrollo, no se empaqueta.
