# Plan de betas de «Controlar otro PC» (PC a PC)

Propuesta de la revisión de la 0.70–0.77 (15 nov 2026). Releases pequeñas, cada una con lo que entra, lo que queda fuera, cómo se decide pasar a la siguiente, qué tiene que probar el dueño y cómo contarlo. Los pasos largos, con todo el detalle, siguen en `docs/PRUEBAS-PC-A-PC.md` (aquí se citan como «PRUEBAS A.5», etc.).

`main` es la estable (0.31) y **no se toca** hasta que el dueño lo pida sobre un SHA exacto. Todas las betas salen de `beta` (o de `lazoo/pc-a-pc` mientras no esté integrada), con su versión, su zip y su etiqueta.

## Cómo va cada beta

1. LaZoo (el bot) publica la beta: `.exe`, APK (dice si cambió) y `LaZoo-X.Y-linux.tar.gz`, con sus enlaces.
2. El dueño hace la **lista corta** de esa beta (15–25 minutos) y contesta en el tablón con la **plantilla de feedback**, una por fallo. Lo que va bien basta con «paso N: bien».
3. Cada fallo se clasifica: **crítico** (se arregla en X.Y.1 con una prueba que lo reproduce, antes de seguir), **uso extremo** (se arregla o se apunta para la beta que toque) o **menor**.
4. Se pasa a la siguiente beta cuando se cumple el **criterio de salida**.

Crítico es: pérdida de datos, que controle el PC alguien no aprobado, datos fuera de la red local, teclas o botones que se quedan pulsados sin salida, LaZoo que no arranca o que deja el PC sin ratón o teclado.

## Beta 1 (0.78) · Windows ↔ Windows y Windows → Linux Xorg

**Entra**
- Controlar otro PC con el ratón y el teclado: tecla rápida (Ctrl+Alt+L), emergencia (Ctrl+Alt+Esc), añadir con PIN y aceptar en el otro PC, «Permitir que otro PC me controle» apagado de serie.
- Emisor Windows; receptor Windows o Linux con Xorg (XTest, sin permisos).
- Texto del portapapeles al cambiar de PC (hasta 1 MB).
- Nombres comunes y **notas compartidas entre PCs** — ver «Decisión del dueño» más abajo.
- Los arreglos de la 0.78: respuestas de sincronización solo selladas; nada fechado en el futuro; sin rondas en bucle; volver nunca se cuelga; dos emisores sin pisarse; con un PC antiguo, «actualízalo».

**Queda fuera** (funciona o no, pero no cuenta para pasar)
- Linux con Wayland (Beta 2). Emisor Linux (Beta 2; en Xorg ya va en pruebas automáticas con dos Xvfb, falta un PC de verdad).
- Imágenes del portapapeles (Beta 3): el código está desde la 0.76; si falla, se apunta, no bloquea.
- Varios PC y móviles, cambiar la dirección de un PC guardado, la regla para dos PC que se controlan a la vez.

**Criterio de salida** (todo a la vez)
- La lista corta completa en Windows ↔ Windows y en Windows → Ubuntu (sesión «Ubuntu en Xorg»), sin ningún fallo crítico.
- El móvil sigue yendo igual con la 0.78 en el PC: APK en Xiaomi y en GrapheneOS (ratón, teclado, una nota).
- Tres días de uso normal sin que se quede una tecla pulsada ni se pierda una nota.
- Cada fallo contado con la plantilla tiene su clasificación y, si es crítico, su arreglo con prueba.

**Lista corta para el dueño** (A = el PC cuyo teclado usas, B = el controlado)
1. Instala la 0.78 en A y en B. En el Panel pone 0.78. En B: «Permitir que otro PC me controle».
2. Con el móvil (APK, Xiaomi y GrapheneOS): entra en A, mueve el ratón, escribe una nota. Tiene que ir como siempre.
3. En A: Añadir otro PC con la IP y el PIN de B; en B, acepta mirando que la huella es la misma. (PRUEBAS A.2–A.3)
4. Ctrl+Alt+L: mueve, clic, arrastra, rueda; escribe en B `ñ`, `á`, `@` (AltGr) y pulsa Win. Ctrl+Alt+L para volver. (PRUEBAS A.4–A.6)
5. Teclas pegadas: controlando B, mantén Shift y pulsa Ctrl+Alt+Esc. En B las letras no salen en mayúscula. (PRUEBAS A.7)
6. Red caída: controlando B, apaga la Wi-Fi de B o tira del cable. A vuelve solo en menos de 5 s.
7. Red caída con algo grande: copia en A un texto muy largo (medio libro), Ctrl+Alt+L y, en ese instante, apaga la Wi-Fi de B. A vuelve y **Ctrl+Alt+L sigue contestando** después (antes se quedaba colgada).
8. En B: apaga «Permitir…» (o expulsa a A) mientras A lo controla. A vuelve solo y lo dice.
9. Portapapeles: copia en A, pasa, pega en B; copia en B, vuelve, pega en A. (PRUEBAS E.1–E.2)
10. Notas: escribe una nota en A → sale en B. Bórrala en B → desaparece en A. «Borrar todo» en A → se vacía B. Copia algo nuevo en B → **se queda** (no desaparece a los pocos segundos).
11. VPN: enciende ProtonVPN en A. El QR sigue con la IP de la Wi-Fi o el cable. Ctrl+Alt+L sigue controlando B (si no, activa en la VPN «permitir red local» y dilo).
12. Ctrl+Alt+Supr: controlando B, pulsa Ctrl+Alt+Supr en A, sal con Esc y escribe `hola` en B. ¿Sale `hola` o hace cosas raras (como si Ctrl o Alt siguieran pulsados)? Lo mismo con Win+L (bloquear A, desbloquear, escribir en B).
13. En B, abre algo que pida permiso de administrador (UAC). Lo esperado: desde A no se puede pulsar ahí. Di qué ves.
14. Velocidad del puntero: ¿en B va más rápido o más lento que con su propio ratón? Apunta la escala de pantalla (100 %, 125 %, 150 %) de A y de B, y cuántos monitores tiene cada uno.
15. Con B en Ubuntu (Xorg): repite 4, 5, 6 y 9.

## Beta 2 (la siguiente, 0.79 si no hay otra por medio) · Linux con Wayland y Linux como emisor

**Entra**
- Receptor en Wayland: ratón y teclado virtuales (`/dev/uinput`); ydotool 1.x como respaldo; con ydotool 0.1 (Ubuntu, Debian) el Panel dice que solo hay mover y clic.
- Emisor Linux: Xorg sin permisos; Wayland leyendo `/dev/input` (grupo «input», con el aviso de la 0.78 antes de darlo).
- La tecla rápida en Linux: Ctrl+Alt+L **bloquea la pantalla** en KDE, XFCE, Cinnamon y MATE. Otra tecla de serie en Linux o un aviso en el Panel.
- Regla para dos PC que se controlan a la vez (hoy, en dos Linux con Xorg, los dos se quedan sin ratón hasta pulsar Ctrl+Alt+Esc en cada uno).
- Cambiar la dirección de un PC guardado sin volver a emparejar (hoy, si el router le cambia la IP, hay que añadirlo otra vez).
- Lo que salga de los pasos 12–14 de la Beta 1 (Ctrl+Alt+Supr, UAC, velocidad del puntero).

**Queda fuera:** imágenes, varios PC y móviles.

**Criterio de salida**
- Lista corta completa en Ubuntu Wayland (receptor y emisor) contra Windows, sin fallos críticos.
- `python3 linux_kvm.py --diagnostico` dice el método que se usa de verdad en cada PC probado.
- Ningún permiso se concede sin que el Panel lo explique antes.

**Lista corta para el dueño**
1. Ubuntu en Wayland como B: el Panel dice qué falta; «Arreglar» pide la contraseña y **no** pide el grupo «input» (solo `/dev/uinput`). Cierra sesión y entra.
2. Desde Windows: pasos 4, 5, 6 y 9 de la Beta 1 sobre ese Ubuntu.
3. Ubuntu en Wayland como A (emisor): «Arreglar» enseña el aviso del teclado; acepta, cierra sesión y entra. Pasos 4, 5 y 6 contra el Windows.
4. Ubuntu en Xorg como A: lo mismo, sin permisos.
5. La tecla rápida no bloquea la pantalla ni choca con el escritorio.
6. Dos PC con el otro añadido en cada uno: pulsa la tecla rápida en los dos. Los dos tienen que poder volver.
7. Cambia la IP de B (reinicia el router o ponle otra a mano): se arregla desde el Panel sin volver a emparejar.

## Beta 3 (después, 0.80 o la que toque) · Imágenes y varios PC y móviles

**Entra**
- Imágenes del portapapeles al cambiar de PC (capturas), en los dos sentidos, con aviso si pasa de 20 MB o si el texto pasa de 1 MB (hoy no se pasa y no se dice).
- Que poner una imagen grande no frene el ratón (hoy una captura 4K son unos 4 s de cálculo en el PC que la recibe).
- Varios PC: elegir a cuál pasar con la tecla rápida cuando hay más de uno; hoja de ruta «varios PC y móviles» (tarea `t8apno`).
- La decisión sobre las notas compartidas, ya con el uso de las betas 1 y 2.

**Criterio de salida**
- Captura de pantalla de A pegada en B y al revés, en Windows ↔ Windows y Windows ↔ Linux.
- Tres PC a la vez (dos Windows y un Linux) y dos móviles una tarde sin fallos críticos.

**Lista corta para el dueño**
1. Impr Pant en A, Ctrl+Alt+L, pegar en Paint de B. Y al revés.
2. Una captura de un monitor 4K: ¿se nota el ratón parado al pegar?
3. Con tres PC: pasa de A a B y de A a C; el aviso dice a cuál vas.
4. Dos móviles y un PC controlando el mismo PC: nadie se queda con una tecla pulsada.

## Estable

Solo con el **ok explícito del dueño al SHA exacto**. Hasta entonces `main` no se toca.

Condiciones: las tres betas con su criterio de salida cumplido; `.exe`, APK (Xiaomi y GrapheneOS) y paquete Linux del mismo SHA probados por el dueño; ningún crítico abierto; la etiqueta de la beta anterior se conserva para poder volver.

## Decisión del dueño (antes de publicar la Beta 1)

**Notas compartidas entre PCs, ¿encendidas o apagadas de serie?** Hoy vienen encendidas: en cuanto dos PC se emparejan, el historial del portapapeles (también las contraseñas que copies) se copia solo al otro PC. Va cifrado y solo entre tus PC aprobados, pero es un dato que antes no salía del PC. Opciones: dejarlo encendido (como está) o apagado hasta que lo marques en cada PC.

## Plantilla de feedback

Una por fallo, como respuesta en el tablón bajo la tarea de la beta:

```
Beta: 1 (0.78)            Paso de la lista: 6
Equipo A (el que manda): sobremesa, Windows 11, LaZoo 0.78, por cable, escala 125 %, 2 monitores
Equipo B (el controlado): portátil, Ubuntu 24.04 Xorg, LaZoo 0.78, Wi-Fi
VPN u otros: ProtonVPN encendida en A
Qué hice: …
Qué esperaba: …
Qué pasó: …
¿Se repite?: siempre / a veces / una vez
Salida: ¿volvió el control con Ctrl+Alt+Esc? ¿hubo que cerrar LaZoo?
Adjunto: captura, o en Linux la salida de  python3 linux_kvm.py --diagnostico
```

## Límites conocidos (no son fallos)

- Ctrl+Alt+Supr, la pantalla de bloqueo y las ventanas de administrador (UAC) de Windows no se pueden capturar ni manejar desde otro PC: Windows no deja.
- Con los relojes de los dos PC a más de 60 s, no conectan y lo dicen («ponlos en hora»).
- Un PC con LaZoo 0.70–0.75 se puede controlar, pero no comparte notas ni nombres; uno con 0.67 o anterior no tiene «Controlar otro PC».
- Solo red local. Con una VPN que no deja ver la red local, el otro PC no se encuentra.
