# LaZoo para Android

App mínima: al abrirla sale el escáner de QR. Lee el QR de la ventana de LaZoo del PC
(`http://IP:8787/#k=...`) y carga la web de LaZoo de ese PC en un WebView. El protocolo
(firma, sello `LZ2`, aprobación) es el mismo que en el navegador.

- Sin Google Play Services ni ML Kit: el QR lo lee `jsQR` (Apache-2.0) dentro de la app,
  servido desde `https://appassets.androidplatform.net/assets/` para que la cámara funcione.
  Vale en GrapheneOS.
- Solo abre IPs de red local (10/8, 172.16/12, 192.168/16, 169.254/16, 127/8, fc00::/7, fe80::/10).
- Guarda el último PC («Volver al último PC»). «Atrás» dentro de LaZoo vuelve al escáner.
- Permisos: cámara (solo para el escáner) e internet (red local). Elegir archivos para el puente
  usa el selector del sistema.

## Compilar

Sin Gradle. Hace falta JDK 17 y el Android SDK con `platforms;android-34` y `build-tools;34.0.0`:

```bash
sdkmanager "platforms;android-34" "build-tools;34.0.0"
ANDROID_SDK=~/android-sdk JAVA_HOME=~/jdk17 ./construir_apk.sh ../LaZoo-0.44.apk
```

La primera vez crea una clave de pruebas en `~/.lazoo/lazoo-pruebas.jks` (no se sube al repo).
Para instalar: copia el `.apk` al móvil y permite «instalar apps desconocidas».
Si cambias de clave, Android pide desinstalar la versión anterior.
