# Agente de LaZoo

Eres el agente que convierte LaZoo en un producto para varios sistemas. No reescribas la 0.31: el usuario ya la usa. Cada fase tiene que seguir arrancando con `iniciar.bat` hasta que el reemplazo haga lo mismo.

Repositorio: https://github.com/Guerrillabitcoin/lazo
Hoy: Python 3.10+, puerto 8787, página del PC en `http://127.0.0.1:8787/conectar`, móvil en el navegador. Pruebas: `python test_mouse.py`.

## Qué tiene que quedar

Un solo protocolo. Tres programas, no tres apps distintas.

| Pieza | Dónde | Forma |
| --- | --- | --- |
| Anfitrión | Windows, Linux y macOS | Icono en la bandeja. Sin ventana negra. Al pulsar, abre la pantalla del QR: primero la página local, y solo si hace falta una ventana propia. |
| Mando | Android y GrapheneOS | Una APK instalable, sin tienda y sin servicios de Google. La misma interfaz que ahora. |
| Mando | iOS | El navegador, hasta que exista cuenta de desarrollador de Apple. No bloquees el resto por iOS. |

El PC controlado puede ser Windows, Linux o Mac. El móvil puede ser Android, GrapheneOS o iOS. Cualquier mando habla con cualquier anfitrión.

Sigue siendo local. La misma Wi-Fi, nada sale a internet, no se abre el 8787 en el router. Nombre público **LaZoo**. En el logo, **LaZo**: la segunda o se abre en verde al conectar y se cierra en rojo al cortarse, en el móvil y en el PC.

## Decisiones cerradas

- HTTP en la red local. No instales un certificado: el usuario lo vio como aviso de sitio malicioso. Si el navegador dice «conexión no segura», explícalo.
- El QR y el PIN solo se ven sin móvil. Al conectar desaparecen. Si se corta, vuelven al momento.
- El QR ya lleva el PIN. En el móvil el campo se oculta al entrar.
- Teclado del sistema al pulsar un texto del PC. El teclado de la app es opcional.
- Ratón fijo en el dock. El resto se desliza y se reordena por el asa.
- YouTube y Spotify con atajos de la app real. No inyectes JavaScript ni reescales su ventana.
- Notas sin duplicar, la última arriba. No guardes el portapapeles que ya había al arrancar.
- El puente es local. Quien escuche la Wi-Fi ve el sello `LZ2`, no el texto.
- Interfaz en español, fondo oscuro, naranja `#e07a3d`, trackpad oscuro con huella naranja.
- Cada entrega instalable sube de versión: carpeta `LaZoo-X.Y`, `VERSION.txt`, GitHub Release, y el mismo número en el logo.

No rompas el ratón, el cursor, las ventanas, YouTube, Spotify, el volumen, las notas, el puente, el logo ni la pantalla del QR. Las pruebas (atajos, captura, brillo, batería, dormir, abrir una web, me gusta y cola de Spotify) se quedan en la pestaña Pruebas.

## Orden de trabajo

Una fase por encargo. No empieces la siguiente si la anterior no arranca.

1. **Protocolo.** Deja escrito, en un solo módulo, el emparejamiento, el WebSocket del ratón y el sello `LZ2`. Windows, Linux y Mac ya entran por `control.py`. No dupliques eso en cada plataforma.
2. **Bandeja en Windows.** El proceso queda en la bandeja, abre la pantalla del QR y se cierra desde el icono. `iniciar.bat` puede seguir existiendo como atajo. Nada de ventana negra obligatoria.
3. **El mismo anfitrión en Linux y macOS.** Misma bandeja o el equivalente, mismos fallos cortos si falta un permiso. En Wayland, di qué no puede hacer el ratón en vez de fingir que funciona.
4. **APK.** Un contenedor Android que cargue la interfaz actual, hable con el anfitrión y se instale a mano. Sin Google Play Services, para que sirva en GrapheneOS. El navegador del móvil sigue valiendo.
5. **iOS.** Documenta el límite: Safari ya entra. Una app propia solo cuando haya firma de Apple.

Después, y solo después: fluidez del ratón, barra de subida del puente, ignorar IPs `172.*` virtuales, y la copia local de fotos. No son el primer trabajo.

## Cómo trabajar

Diff corto. No cambies el puerto ni el nombre. No añadas una dependencia si la biblioteca estándar basta. Si publicas, el zip se llama `LaZoo-X.Y.zip` y la APK, cuando exista, `LaZoo-X.Y.apk`.
