# Publicar LaZoo (construir el .exe y la APK en GitHub)

GitHub puede construir `LaZoo.exe` y `LaZoo.apk` por ti, en sus ordenadores, sin usar el tuyo. Lo hace el archivo `.github/workflows/construir.yml`.

## Con un clic

1. Entra en el repositorio en GitHub y abre la pestaña **Actions**.
2. A la izquierda, elige **Construir LaZoo**.
3. Pulsa **Run workflow**, elige la rama (por ejemplo `beta`) y vuelve a pulsar **Run workflow**.
4. Espera unos minutos a que salgan las dos marcas verdes.
5. Abre la ejecución y, abajo, en **Artifacts**, descarga:
   - `LaZoo-windows`: la carpeta con `LaZoo.exe`. Copia la carpeta entera, el .exe solo no arranca.
   - `LaZoo-android-pruebas`: `LaZoo.apk`.

Los archivos se guardan 30 días.

## Con una etiqueta

Si subes una etiqueta que empiece por `v` (por ejemplo `v0.48.0`), se construye solo:

```
git tag v0.48.0
git push origin v0.48.0
```

Subir commits normales a `beta` NO lo lanza.

## Avisos

- La APK va firmada con una clave de **pruebas** nueva en cada construcción. Android pedirá «instalar apps desconocidas» y, si ya tenías otra LaZoo instalada con otra clave, tendrás que desinstalarla antes. Para una firma fija hace falta guardar una clave en los secretos del repositorio (todavía no se hace).
- El `.exe` no está firmado: Windows mostrará «Windows protegió su PC» (Más información → Ejecutar de todas formas).
- No usa contraseñas ni secretos. Las versiones de las herramientas están fijadas (Python 3.12, PyInstaller 6.22.3, Java 17, Android 34).
