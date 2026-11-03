# Pruebas del ratón · LaZoo 0.53

Guía corta para probar el **ajuste fino del ratón** y pasarnos datos e impresiones.
Tardas unos 15-20 minutos. No hace falta hacerlo todo de una vez.

---

## 1. Antes de empezar

1. Abre **LaZoo 0.53** en el PC y conecta el móvil (si usas la APK, actualízala a la 0.53).
2. En el móvil, ve a la pastilla **Ratón**.
3. Debajo del touchpad, activa **«Ajuste fino / stats»** (antes se llamaba «Modo stats»).
4. Aparecen los números de fondo en el touchpad y, debajo, el bloque **«Ajuste fino»** con los presets y las opciones.
5. Elige **10 s** en el selector y activa **«Congelar al soltar el dedo»**.

Apunta qué red usas en cada prueba: **PC por Wi-Fi o por cable**, banda del móvil (**2,4 o 5 GHz**) y si estás **cerca o lejos del router**.

---

## 2. Presets (botones de arriba)

| Preset | Para qué sirve | Lo que cambia |
|---|---|---|
| **Equilibrado** (por defecto) | Uso normal | Corrección suave 3 pasos, mezcla 30 ms, interpolación sí, colchón adaptativo 15-40 ms, 200 Hz, sub-píxel sí, envíos 60/s |
| **Máxima fluidez** | Que se vea lo más suave posible | Corrección 4 pasos, mezcla 50 ms, colchón 25-60 ms, 250 Hz, cola 200 ms. Algo más de retraso |
| **Mínimo retraso** | Que responda lo antes posible | Corrección 2 pasos, sin mezcla ni interpolación, colchón 10-20 ms, 500 Hz, predicción corta, «reciente primero», envíos 90/s. Puede verse más a saltos |
| **Como 0.50** | Comparar con lo antiguo | Igual que la 0.50: sin predicción, sin ajustes nuevos |

**«Restablecer valores»** vuelve a «Equilibrado». Si tocas cualquier opción suelta, el preset pasa a «Personalizado».
La predicción y la inercia siguen arriba («Predicción de movimiento», «Inercia al soltar»); los presets ponen la predicción en sí (y «Como 0.50» la quita junto con la inercia).

## 3. Qué hace cada opción (por si quieres tocar a mano)

| Opción | Qué hace | Por defecto |
|---|---|---|
| Corrección suave | Si el PC predijo de más, vuelve atrás en 2-4 pasos cortos en vez de un salto | 3 pasos |
| Mezcla al llegar datos | Tras predecir, lo que falta entra repartido en ese tiempo | 30 ms |
| Interpolación tras huecos | Solo tras un hueco de red: reparte en pasos iguales de 5 ms | sí |
| Colchón | Adaptativo (sube con huecos, baja si va estable) o fijo | adaptativo |
| Colchón mín. / máx. | Rango del adaptativo | 15 / 40 ms |
| Colchón fijo | Margen si eliges «fijo» | 30 ms |
| Pasos del PC | Veces por segundo que se mueve el cursor | 200 Hz |
| Predicción máx. | Cuánto sigue el gesto el PC sin datos | 150 ms |
| Frenado de la predicción | Lo rápido que frena lo predicho | 90 ms |
| Sub-píxeles y redondeo estable | Pasos iguales, sin 1-2-1-3 | sí |
| Límite de cola | Más retraso que esto se vacía deprisa | 150 ms |
| Reciente primero | Si la cola pasa el límite, salta a la posición actual | no |
| Temporizador de alta resolución | Pasos exactos en Windows | sí |
| Envíos del móvil | Mensajes por segundo como máximo | 60/s |

---

## 4. Combinaciones recomendadas

Prueba en este orden. Con cada una haz al menos el escenario A (círculos lentos).

1. **Equilibrado** tal cual.
2. **Máxima fluidez**.
3. **Mínimo retraso**.
4. **Como 0.50** (para comparar).
5. **Equilibrado + Inercia al soltar «media»**.
6. **Equilibrado con «Corrección suave: no»** (para ver si la corrección se nota).
7. **Equilibrado con colchón fijo 30 ms** (frente al adaptativo).
8. **Equilibrado con pasos del PC a 500 Hz** (y otra a 125 Hz).
9. **Equilibrado con envíos del móvil a 90/s** (si la red va bien).

---

## 5. Escenarios

- **A. Círculos lentos:** dibuja círculos grandes y lentos con el dedo, sin parar, unos 10 s.
- **B. Círculos rápidos:** círculos más pequeños y rápidos, 10 s.
- **C. Soltar y retocar:** mueve, suelta, vuelve a tocar y haz movimientos cortos de precisión (como apuntar a un botón pequeño). Repite unas 5 veces.
- **D. Red buena:** móvil y PC cerca del router (o PC por cable).
- **E. Red mala:** aléjate del router (otra habitación) o pon una descarga grande / un vídeo en 4K en otro aparato mientras pruebas.

## 6. Qué mirar

- **Fluidez en la pantalla del PC:** ¿el cursor se desliza seguido o va a trompicones?
- **Sensación en el dedo:** ¿el cursor va «pegado» al dedo o con retraso? ¿Se pasa y vuelve atrás?
- **Al parar el dedo:** ¿hay un pequeño rebote hacia atrás? ¿Molesta?
- **Deriva** (en las stats): debe ser **~0 px**. Si sube y se queda alta, avísanos.
- **Error de predicción** (en las stats): cuánto se pasó la predicción. Menos es mejor; con «Como 0.50» sale 0 porque no predice.

## 7. Cómo copiar las stats

1. Con el preset elegido, haz el escenario unos 10 s sin parar.
2. Suelta el dedo. Al segundo se congelan solas (no hace falta darse prisa).
3. Pulsa **«Copiar stats»**.
4. Pega el texto en el chat junto con la plantilla de abajo.
5. Pulsa **«Seguir»** para descongelar antes de la siguiente prueba.

Las stats no se paran solas ni al hacer clic: solo con «Congelar» o al soltar el dedo (si está activado). Guardan los últimos 15 s.

## 8. Plantilla para pegar (una por prueba)

```
Prueba nº:
Preset / cambios: (p. ej. Equilibrado + inercia media)
Escenario: (A círculos lentos / B rápidos / C soltar y retocar)
Red: PC por Wi-Fi o cable · banda 2,4/5 GHz · cerca/lejos del router · descarga en marcha sí/no
Móvil: (Xiaomi / GrapheneOS) · navegador o APK
Fluidez visual en el PC (1-5):
Sensación en el dedo (1-5):
Rebote al parar: no / poco / molesta
Notas:
[pega aquí «Copiar stats»]
```

## 9. Tabla rápida (opcional)

| Nº | Preset / cambios | Escenario | Red | Fluidez PC (1-5) | Dedo (1-5) | Deriva (px) | Error pred. medio (px) | Notas |
|---|---|---|---|---|---|---|---|---|
| 1 | Equilibrado | A | | | | | | |
| 2 | Máxima fluidez | A | | | | | | |
| 3 | Mínimo retraso | A | | | | | | |
| 4 | Como 0.50 | A | | | | | | |
| 5 | Equilibrado + inercia media | C | | | | | | |
| 6 | Equilibrado, corrección no | B | | | | | | |
| 7 | Equilibrado, colchón fijo 30 | E | | | | | | |
| 8 | Equilibrado, 500 Hz | B | | | | | | |
| 9 | Equilibrado, envíos 90/s | D | | | | | | |

Con 4-5 pruebas bien hechas (presets 1-4 en escenario A y alguna en red mala) ya podemos decidir los valores finales.
