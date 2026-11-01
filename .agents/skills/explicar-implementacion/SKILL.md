---
name: explicar-implementacion
description: Redacta la descripción de un Pull Request como una explicación breve y en texto corrido, después de preguntarle al autor por qué tomó sus decisiones, y sirve para preparar la defensa ante el tutor. Usar antes de abrir un PR, antes de mergear, al preparar la defensa de una historia o cuando alguien pida explicar qué hace un cambio o por qué se hizo así.
---

# Explicar implementación

Redacta la descripción del PR con dos fuentes: el diff y lo que responde el autor. Sale una explicación corta, como la que el autor le daría en persona a alguien del equipo que no estuvo en esa parte. El diff muestra qué cambió, pero no por qué se eligió esa forma ni con qué se topó el autor: eso se le pregunta antes de redactar, no se deduce. Si el autor no puede responder, todavía no entendió el cambio.

## Entradas requeridas

1. **Diff completo**: `git diff main...HEAD`
2. **Issue y Criterios de Aceptación (CA)**: objetivo de la historia y requerimientos.
3. **Contexto del repo**: `AGENTS.md`, la arquitectura asociada y los ADR que toque el cambio.
4. **Respuestas del autor**: salen del paso siguiente.

## Preguntarle al autor antes de redactar

1. Leer el diff y el issue, y marcar las decisiones que más pesan: los lugares donde había más de una forma razonable de hacerlo.
2. Preguntarle al autor, en un solo mensaje, y esperar las respuestas antes de seguir. Las preguntas son sobre ese código, no genéricas: "¿por qué la unicidad quedó en la base y no en un chequeo antes del insert?", no "¿por qué hiciste este cambio?". Tienen que cubrir:
   - por qué eligió esa forma y qué alternativa descartó;
   - con qué se trabó en el camino;
   - qué dejó afuera a propósito.
3. Redactar con esas respuestas. Un porqué que el autor no dio no se completa con una suposición: se vuelve a preguntar o queda afuera.

Entre dos y cuatro preguntas. En un cambio chico, como un PR autoaprobado según el ADR-022, alcanza con una o ninguna.

## Qué tiene que contar

Texto corrido en español, sin títulos, checkboxes, tablas ni listas largas. Tiene que quedar claro:

- **El problema**: qué pasaba o qué faltaba, y por qué hacía falta tocarlo.
- **La solución**: cómo se resolvió y por qué de esa forma, según lo que respondió el autor. Si la decisión sale de un CA, de una regla de `AGENTS.md` o de un ADR, nombrarlo. Si no sale de ninguno, decir que es una decisión propia del cambio.
- **Lo que costó**: con qué se topó el autor en el camino, si hubo algo.
- **Lo que conviene mirar**: la decisión que más pesa, el costo que se aceptó o lo que quedó afuera a propósito.

Si el PR es autoaprobado según el ADR-022 de `udesa-x-platform`, una frase que diga por qué entra. Al final, la línea `Closes #<número>`.

## Criterios de calidad

- **Para alguien sin contexto**: que lo entienda un integrante que nunca abrió ese módulo. Contar el recorrido del dato (entrada -> servicio -> persistencia o evento) antes que los nombres de archivos.
- **Lenguaje plano**: frases cortas y palabras simples. Si aparece un término técnico propio de la pieza (ej. *outbox*, *idempotencia*, *cursor pagination*), decir en una frase qué implica en este código.
- **Proporción**: un cambio chico se explica en dos o tres frases. Si la explicación no entra en unos pocos párrafos, probablemente el PR hace más de una cosa y conviene partirlo.
- **La solución como una unidad**, no archivo por archivo ni línea por línea del diff.

## Señales de bloqueo (Red Flags)

Frenar y alertar al desarrollador antes de redactar el PR si:
- Hay archivos modificados en el diff cuyo motivo no se puede justificar.
- Se introdujo una librería o patrón nuevo sin un ADR previo.
- Un Criterio de Aceptación de la issue no tiene código ni tests que lo respalden.
- La justificación de una decisión es meramente "porque así funciona", o el autor no sabe responder por qué la tomó.

## Ejemplo

Preguntas al autor:

> 1. ¿Por qué la unicidad del like quedó en la base, con la clave usuario y post, y no en un chequeo antes del insert?
> 2. El contador de likes del post se actualiza en la misma transacción que el insert. ¿Lo comparaste contra contarlos en cada lectura?
> 3. ¿Hubo algo que te costó más de lo que esperabas?

Descripción redactada con las respuestas:

> Hasta ahora un usuario podía darle me gusta dos veces al mismo post si tocaba el botón rápido: llegaban dos requests casi juntos, los dos veían que no había like y los dos lo guardaban. El CA.3 pide un solo like por usuario y por post.
>
> Lo resolví en la base y no en el código: la tabla `post_likes` ahora tiene como clave el par usuario y post, así que el segundo insert falla solo y lo devolvemos como si ya existiera. Chequear antes de insertar no alcanzaba, porque entre el chequeo y el insert puede entrar el otro request.
>
> Lo que más me costó fue el contador de likes del post. Lo actualizo en la misma transacción que el insert, para que no quede desfasado si algo se corta a mitad de camino. Es lo que conviene mirar: el contador es un dato copiado, y si alguien inserta likes por fuera del servicio deja de coincidir. Lo elegí para que el feed no tenga que contar likes en cada lectura.
>
> Closes #42
