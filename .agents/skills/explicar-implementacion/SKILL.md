---
name: explicar-implementacion
description: Genera la explicación estructurada de un cambio de código para la sección obligatoria del Pull Request y la defensa ante el tutor. Usar antes de abrir un PR, antes de mergear, al preparar la defensa de una historia o cuando alguien pida explicar qué hace un cambio o por qué se hizo así.
---

# Explicar implementación

Genera la explicación técnica y justificación de diseño de un diff para que cualquier integrante del equipo pueda entenderlo, revisarlo y defenderlo ante el tutor.

## Entradas requeridas

1. **Diff completo**: `git diff main...HEAD`
2. **Issue y Criterios de Aceptación (CA)**: objetivo de la historia y requerimientos.
3. **Contexto del repo**: `AGENTS.md` y arquitectura asociada.

## Estructura de salida

Completar exactamente estas cuatro secciones en español:

### 1. Qué cambió
- Describir los cambios concretos en lenguaje llano, mencionando archivos y módulos principales.
- Explicar la solución como una unidad conceptual ordenada por relevancia, no como un listado línea por línea del diff.

### 2. Por qué
- Justificar cada decisión técnica anclándola en un Criterio de Aceptación (CA), una regla de `AGENTS.md` o un ADR en `docs/adr/`.
- Si una decisión no responde a ninguna de estas fuentes, declararla explícitamente como decisión de diseño local.

### 3. Ventajas y desventajas
- **Ventajas**: qué resuelve, qué simplifica o qué garantías otorga.
- **Desventajas y costos**: compromisos asumidos (ej. consulta extra a base de datos, desnormalización, acoplamiento, casos borde omitidos). Identificarlos sin omitir costos.

### 4. Mejoras posibles
- Diferenciar lo que **quedó afuera a propósito** (historias futuras, alcance acotado) de lo que **no se llegó a implementar** por tiempo o complejidad.

## Criterios de calidad

- **Claridad didáctica**: Explicar la ruta que sigue el dato (entrada -> servicio -> persistencia/evento).
- **Cero jerga sin definir**: Si se usan términos técnicos (ej. *outbox*, *idempotencia*, *cursor pagination*), definir en una frase qué implica en este código.
- **Sin adornos**: Si el cambio es simple, la explicación debe ser concisa.

## Señales de bloqueo (Red Flags)

Frenar y alertar al desarrollador antes de redactar el PR si:
- Hay archivos modificados en el diff cuyo motivo no se puede justificar.
- Se introdujo una librería o patrón nuevo sin un ADR previo.
- Un Criterio de Aceptación de la issue no tiene código ni tests que lo respalden.
- La justificación de una decisión es meramente "porque así funciona".

## Ejemplo de salida

> **Qué cambió**
> Se implementó el endpoint `POST /posts/{id}/likes` en `routes/likes.py` y su servicio en `services/likes.py`. Se agregó la tabla `post_likes` con clave primaria compuesta `(user_id, post_id)` en la migración `0007_post_likes.py`. El contador `likes_count` de la tabla `posts` se actualiza en la misma transacción que el insert.
>
> **Por qué**
> La clave compuesta garantiza a nivel de base de datos el CA.3 (un like por usuario por post), evitando condiciones de carrera en requests concurrentes sin consultas previas. La actualización transaccional de `likes_count` evita desincronizaciones ante caídas intermedias.
>
> **Ventajas y desventajas**
> - *Ventaja*: La integridad la asegura la base de datos de forma atómica.
> - *Desventaja*: El contador es dato desnormalizado; si se insertara en `post_likes` por fuera del servicio, el contador podría desfasarse. Se priorizó velocidad de lectura del feed sobre cálculo en vivo (`COUNT(*)`).
>
> **Mejoras posibles**
> - *Fuera de alcance*: Notificación al autor del post (cubierto en historia E4-H2). El endpoint ya emite el evento `interaction.created`.
> - *Mejora futura*: Tarea periódica de reconciliación de contadores ante desfasajes.
