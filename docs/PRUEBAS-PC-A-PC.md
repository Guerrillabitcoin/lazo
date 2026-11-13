# Prueba de «Controlar otro PC» (0.70)

El ratón y el teclado de un PC (el **emisor**) manejan otro PC de tu red (el **receptor**), como Mouse Without Borders. Se pasa de uno a otro con una **tecla rápida** (Ctrl+Alt+L de serie), no por el borde de la pantalla.

- Emisor: **Windows** (en Linux aún no se puede mandar; en Wayland ningún programa puede capturar el teclado y el ratón de todo el escritorio).
- Receptor: **Windows** o **Linux** (Xorg con XTest; Wayland con ydotool, como en la 0.68).
- Solo red local. Firmado y cifrado (LZ2) como el móvil. El receptor tiene que aceptar al emisor con el aviso de siempre.

Teclas: **Ctrl+Alt+L** (se cambia en el Panel) pasa al otro PC y vuelve. **Ctrl+Alt+Esc** suelta siempre (emergencia). Win y Alt+Tab se mandan. **Ctrl+Alt+Supr**, la pantalla de bloqueo y las ventanas de administrador (UAC) no se pueden capturar ni inyectar.

## A. De Windows a Windows

Necesitas dos PC con Windows en la misma Wi-Fi o red, los dos con LaZoo 0.70 abierto (icono en la bandeja). Llamaremos **A** al que tiene el ratón y el teclado que vas a usar, y **B** al que vas a controlar.

1. En **B**: abre el Panel de LaZoo (doble clic en el icono). En **Configuración → Otro PC**, marca **«Permitir que otro PC me controle»**. Debajo sale una línea «Para el otro PC: 192.168.x.y:8787 · PIN 123456». Apúntala.
   - Comprueba que de serie estaba **desmarcada**.
2. En **A**: clic derecho en el icono → **Controlar otro PC → Añadir otro PC…** Se abre el Panel en «Controlar otro PC». Escribe la IP:puerto y el PIN de B y pulsa **Añadir**.
   - En A sale «Acepta «PC · NOMBRE-DE-A» en el otro PC (huella XXXX-…)».
3. En **B**: sale el aviso de Windows de siempre «Nuevo dispositivo **PC · NOMBRE-DE-A** … quiere entrar». Comprueba que la huella es la misma que en A y pulsa **Sí**.
   - En A, a los pocos segundos: «Añadido «NOMBRE-DE-B». Pulsa Ctrl+Alt+L para controlarlo.» y B aparece en la lista.
4. En **A**: pulsa **Ctrl+Alt+L**.
   - Sale un aviso «Controlando «B»…» y el icono de A se pone naranja; el tooltip dice «controlando «B» · Ctrl+Alt+L para volver».
   - El puntero de A se queda quieto en el centro de su pantalla. En B sale el aviso ««A» está usando el ratón y el teclado de este PC».
5. Mueve el ratón de A: se mueve el puntero de **B**. Prueba:
   - clic izquierdo, derecho y central; arrastrar una ventana; doble clic;
   - rueda arriba y abajo, y la rueda horizontal si tu ratón la tiene; botones de atrás y adelante del ratón en el navegador;
   - escribir en el Bloc de notas de B: letras, **ñ**, acentos (´ + a), mayúsculas, **AltGr** (@, #, €), números, F-teclas, flechas, Inicio/Fin;
   - **Win** abre el menú Inicio de **B** (no el de A); **Alt+Tab** cambia de ventana en **B**;
   - nada de lo que escribes ni de los clics llega a A.
6. Pulsa **Ctrl+Alt+L** otra vez: vuelves a A. El puntero de A vuelve a donde estaba antes del paso 4. Aviso «De vuelta en este PC», icono como antes.
7. **Teclas que no se quedan pegadas:** en A pulsa Ctrl+Alt+L, mantén **Shift** pulsado y, sin soltarlo, pulsa **Ctrl+Alt+Esc**. Ya estás en A. Escribe en B con su propio teclado (o vuelve con Ctrl+Alt+L): las letras **no** salen en mayúscula (B soltó Shift).
8. **Se cae la red:** controla B y desenchufa el cable o apaga la Wi-Fi de B. En unos 3 s, A vuelve solo (aviso «El otro PC no responde» o «Se cortó la conexión»). En B, nada queda pulsado.
9. **Expulsar:** en B, clic derecho en el icono → Dispositivos conectados → «PC · A» → Expulsar. Si A estaba controlando, vuelve solo; al pulsar Ctrl+Alt+L sale «El otro PC ya no reconoce a este…».
10. **Apagar el permiso:** en B desmarca «Permitir que otro PC me controle». En A, Ctrl+Alt+L dice «El otro PC no deja que lo controlen…».
11. **Cambiar la tecla:** en A, Panel → Configuración → Tecla rápida: «Ctrl+Alt+K» → Guardar tecla. Ahora Ctrl+Alt+K alterna y Ctrl+Alt+L ya no hace nada.
12. **Desde la bandeja:** en A, clic derecho → Controlar otro PC → elige B (empieza a controlar) y luego «Dejar de controlar» no se puede pulsar con el ratón de A mientras controlas (está en B): usa la tecla. Con el menú, sí puedes empezar.
13. **Salir:** con A controlando B, cierra LaZoo de A con la tecla de emergencia y luego Salir: el teclado y el ratón de A funcionan siempre.

## B. De Windows a Linux

Igual que A, con **B en Linux** (instalado con `instalar-linux.sh`).

1. En B (Linux): Panel de LaZoo → Configuración → marca «Permitir que otro PC me controle» y apunta IP:puerto y PIN.
2. En A (Windows): Añadir otro PC… con esos datos. En B sale el **cuadro de GTK** de 60 s «nuevo dispositivo PC · A»: **Sí**.
3. Ctrl+Alt+L en A y repite el paso 5 de arriba en un editor de texto de B.
   - **Xorg:** va por XTest. **Wayland (Ubuntu de serie):** va por ydotool (tiene que estar preparado por `instalar-linux.sh` y haber cerrado sesión una vez); el movimiento puede ir algo menos fino.
   - Las teclas van por su **posición física**: con la misma distribución (español) en los dos PCs, ñ, acentos y AltGr salen igual.
   - La tecla Win abre el menú de actividades/aplicaciones de Linux.
4. Repite los pasos 6 a 10.
5. En el menú de la bandeja de Linux también está «Controlar otro PC», pero desde Linux aún no se puede mandar: al elegir un PC sale el aviso que lo explica. «Permitir que otro PC controle este» sí funciona ahí.

## Qué mirar si algo falla

- «No llego al otro PC»: los dos en la misma red, LaZoo abierto en B, el cortafuegos de B deja el puerto (el mismo que usa el móvil).
- «El reloj de los dos PC no coincide»: pon la hora automática en los dos (la firma vale 60 s).
- Ctrl+Alt+L no hace nada y el Panel avisa «otro programa usa Ctrl+Alt+L»: cambia la tecla.
- Ventanas de administrador en B (Administrador de tareas, instaladores): Windows no deja que un programa normal les mande teclas o clics (UIPI). Ábrelas con el ratón y el teclado de B, o arranca LaZoo de B como administrador.
