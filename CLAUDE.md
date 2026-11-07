# CLAUDE.md — LaZoo

@AGENTS.md

Lo técnico de LaZoo está en `AGENTS.md` (importado arriba). Lo común a todos los agentes está en el ACUERDO: tablero crosswalk `guerrillaagents`, archivo `files/ACUERDO.md`. Una decisión posterior del dueño manda sobre los dos. Este archivo solo añade lo que Claude (Claude Code o claude.ai) necesita para trabajar aquí sin que se lo repitan en cada sesión.

## Antes de empezar

- `git fetch` y mira el tablero `guerrillaagents` (sección `lazo`). Si otro agente tiene una tarea abierta en la misma zona, no la toques.
- Una tarea, un objetivo, una rama.

## Tu papel

- En cada tarea, o implementas o revisas: nunca las dos cosas en la misma tarea.
- El dueño técnico del repo es el bot LaZoo. Él integra tu rama en `beta`, numera la versión, hace el zip y pone la etiqueta.

## Ramas y commits

- Rama `claude/<tarea>` creada desde `beta`. Nunca push a `beta` ni a `main`, nunca `force-push`, no borres ramas ni etiquetas.
- Autor, antes del primer commit:

  ```
  git config user.name "GUERRILLA"
  git config user.email "guerrilla@users.noreply.github.com"
  ```

- No subas `.github/workflows`: edita `ci/` y avisa al dueño.
- Nunca claves, keystores, contraseñas ni secretos. Tampoco abras `.lazo-pin`, `clipboard-history.json` ni `nube/`. Sin nombre real ni email personal.
- Todo en español: commits, notas e interfaz.

## Pruebas

- Una `test_vXYZ.py` nueva para lo que cambies, y pasa también las anteriores. En Linux fallan las de `pynput`: dilo en el traspaso.
- Nunca pruebes contra el LaZoo del dueño en el puerto 8787: usa una copia temporal.
- Lo que solo se comprueba en Windows o en el móvil (`.exe`, APK en Xiaomi y GrapheneOS) es una tarea para el dueño o para Copilot, con los pasos exactos.

## Al terminar

Traspaso en el tablero con el formato del ACUERDO (§3): Qué, Rama @ commit, Probado, Archivos, Riesgos / pendiente, Prueba manual para el dueño, Revisa.

`.claude/settings.json` bloquea el push a `main` y `beta`, el `force-push`, borrar ramas o etiquetas, editar `.github/workflows` y leer claves. Es una red de seguridad: no sustituye a estas reglas.
