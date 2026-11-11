# Pruebas de LaZoo en Linux (0.68)

Lista para pasar en un PC con Linux antes de llevar la versión Linux a `beta`, y otra vez antes de `main`.
PC de referencia: Ubuntu con GNOME en Wayland (Vaio del dueño). Marca cada casilla con **va** o **falla** y,
si falla, copia lo que salga en la terminal.

## 0. Antes de empezar

```sh
lsb_release -d; echo $XDG_SESSION_TYPE; echo $XDG_CURRENT_DESKTOP
snap list firefox 2>/dev/null | tail -1; which ydotool ydotoold wmctrl playerctl wl-copy
```

## 1. Instalar

- [ ] Descomprimir `LaZoo-0.68-linux.tar.gz` y `sh instalar-linux.sh`. Pregunta antes de usar `sudo`.
- [ ] En Wayland pregunta por ydotool. Decir que sí, **cerrar sesión y volver a entrar**.
- [ ] Tras volver a entrar: `systemctl --user status lazoo-ydotoold` dice *active (running)*.
- [ ] «LaZoo» aparece en el menú de aplicaciones.

## 2. Bandeja y emparejar

- [ ] Abrir LaZoo desde el menú: sale el icono rojo en la barra de arriba y se abre el Panel.
- [ ] Escanear el QR con la App 2: sale el cuadro «nuevo dispositivo» en el PC. Aceptar.
- [ ] El icono se pone verde. Menú del icono: Abrir el Panel, Pastillas, Dispositivos, Salir funcionan.
- [ ] «Iniciar con el sistema»: reiniciar y LaZoo arranca solo (sin abrir el Panel).
- [ ] Cerrar la app del móvil 10 minutos con la pantalla apagada, volver: reconecta sin QR.

## 3. Ratón y teclado (Wayland + ydotool)

- [ ] El trackpad del móvil mueve el cursor de verdad (en todas las ventanas, no solo en algunas).
- [ ] Clic, clic derecho, doble clic y arrastrar una ventana.
- [ ] Rueda (dos dedos) en una página larga.
- [ ] Escribir «hola 123» en un editor: llega bien.
- [ ] Escribir «año, acción, ¿qué?» : llega bien (va pegado) y lo que había en el portapapeles sigue ahí.
- [ ] La pestaña **Ventanas** no aparece en el móvil (decisión del dueño para Linux).

## 4. YouTube (Firefox de Ubuntu; repetir con Brave o Chrome si los usas)

```sh
python3 linux_yt.py --diagnostico   # con YouTube abierto
```

- [ ] El diagnóstico dice que ve la página (`"pagina": true`) y la barra (`"barra": true`).
  Brave/Chrome: antes `gsettings set org.gnome.desktop.interface toolkit-accessibility true` y reabrirlo.
- [ ] Pestaña YouTube del móvil: título, play/pausa, ±10 s, siguiente, anterior.
- [ ] Barra de progreso: arrastrar, ver «Ir a m:ss», soltar y que salte justo ahí.
- [ ] Volumen: mover la barra del móvil y que cambie la del reproductor (número sin «≈»).
- [ ] Silencio, subtítulos, modo cine y pantalla completa.
- [ ] Velocidad y tamaño de subtítulos: en Wayland avisan de que aún no van (es lo esperado).
- [ ] «Seguir viendo en el móvil»: el PC se pausa y Brave del móvil abre el mismo minuto.
- [ ] Con «Saltar anuncios» encendido, un anuncio saltable se salta solo y sale en el historial del Panel.
- [ ] «¿Sigues ahí?»: dejar una lista de reproducción horas (o esperar a que salga) y que siga.
- [ ] Patrocinios (encendido en el Panel): un vídeo con patrocinio marcado en SponsorBlock lo salta.

## 5. Resto

- [ ] No se bloquea: con el móvil en uso, dejar el PC 15 min sin tocar: no se apaga la pantalla.
  Sin usar el móvil, se bloquea como siempre.
- [ ] Cursor grande y enorme, y vuelta a normal.
- [ ] Volumen del sistema y bloquear el PC (Sistema).
- [ ] Brillo (Sistema): si no cambia, apuntarlo (puede faltar permiso).
- [ ] Pasar por wifi: una nota del móvil al PC con «Al PC» y Ctrl+V en el PC; un archivo del móvil al PC.

## 6. Para pasar a beta / main

- **beta**: todo lo de arriba va o tiene una razón apuntada, y el `.exe` de Windows sigue igual en la prueba
  de siempre.
- **main**: unos días de uso real en beta con los dos PC y el móvil, y el visto bueno del dueño.
