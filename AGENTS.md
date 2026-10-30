# Encargo para quien siga LaZoo

Léelo antes de tocar código. No reescribas la app. El usuario ya usa la 0.31 en un PC Windows y un móvil por Wi-Fi.

Repositorio: https://github.com/Guerrillabitcoin/lazo
Arranque: `iniciar.bat` (Windows) o `./iniciar.sh`. Python 3.10+. Puerto 8787. Página del PC: `http://127.0.0.1:8787/conectar`. Pruebas: `python test_mouse.py`.

## Qué es

Mando local del PC desde el navegador del móvil. No es una web suelta ni una cuenta en la nube. El programa corre en el PC. El móvil entra por la Wi-Fi de casa. Nada debe salir a internet. No abras el 8787 en el router.

Nombre de cara al público: **LaZoo**. En el logo se escribe **LaZo**: la segunda o se separa y se pone verde al conectar, y se junta en rojo al cortarse. Misma animación en el móvil y en la pantalla del QR del PC. Debajo del logo va el número de versión.

## Decisiones ya cerradas

- HTTP en la red local. No pongas un certificado: el usuario lo vio como aviso de sitio malicioso. Si el navegador dice «conexión no segura», es la dirección de casa. Explícalo, no lo «arregles» con TLS.
- El QR y el PIN se ven solo cuando no hay móvil. Al conectar desaparecen y el logo pasa a verde. Si el móvil se va, vuelven al momento (`/api/bye` y una ventana de unos 5 s).
- El QR ya trae el PIN. En el móvil, el campo de PIN se oculta al entrar y solo vuelve si se corta, con el PIN escrito.
- El teclado del móvil es el del sistema, cuando el foco del PC está en un texto. El teclado de la app es opcional y se pliega con el mismo botón.
- La pastilla Ratón va fija al principio del dock. El resto se desliza en horizontal y se reordena agarrando el asa, no el botón entero.
- YouTube y Spotify se controlan con atajos de la app de verdad, no inyectando JavaScript ni abriendo la consola. No reescales su ventana al pulsar un botón. Play y pausa son el mismo botón y cambia el icono. El volumen es un slider.
- Las notas no se duplican, la última queda arriba, y copiar está a la derecha. No guardes el portapapeles que ya había al arrancar.
- El puente Wi-Fi es local: texto, archivos y fotos. Un observador de la Wi-Fi debe ver tráfico cifrado (sello `LZ2`, HMAC-SHA256), no el texto.
- La interfaz va en español, oscura, con acento naranja `#e07a3d`. El trackpad es oscuro y deja una huella naranja.
- Cada cambio que el usuario pueda instalar sube de versión, entra en una carpeta `LaZoo-X.Y` dentro del zip, con `VERSION.txt`, y se publica en GitHub Releases. El número tiene que coincidir con el logo, `iniciar.bat` y el README.

## No lo rompas

Ratón (WebSocket binario), cursor normal/grande/enorme, ventanas, YouTube, Spotify, volumen del PC, notas, puente, logo de conexión y la pantalla del QR. Las pruebas (atajos, captura, brillo, batería, dormir, abrir una web, me gusta y cola de Spotify) viven solo en la pestaña Pruebas. No las mezcles con las pastillas estables.

## Qué falta, sin hacerlo todo de golpe

Un solo encargo por vez, con prueba antes de publicar:

1. Fluidez del ratón en el teléfono real del usuario (sigue notando retardo).
2. Barra de subida del puente: progreso, pendientes y velocidad.
3. Que ignore adaptadores virtuales `172.*` al elegir la IP del QR.
4. Servicio en segundo plano en Windows, sin ventana negra, y más adelante un `.exe`. El móvil sigue en el navegador hasta que exista una APK. No conviertas esto en un rewrite.
5. Carpeta de fotos del móvil hacia el PC, al estilo de una copia local, no una nube pública.

## Cómo trabajar

Diff corto. No renombres el producto ni cambies el puerto. Si una función de Windows no existe en Linux o macOS, degrada con un error corto. No añadas dependencias si `requirements.txt` y la biblioteca estándar bastan. Cuando publiques, el zip se llama `LaZoo-X.Y.zip`.
