---
name: explicar-implementacion
description: Redacta la descripción de un Pull Request como una explicación breve y en texto corrido, y sirve para preparar la defensa ante el tutor. Usar antes de abrir un PR, antes de mergear, al preparar la defensa de una historia o cuando alguien pida explicar qué hace un cambio o por qué se hizo así.
---

# Explicar implementación

Redacta la descripción del PR a partir del diff: una explicación corta, como la que el autor le daría en persona a alguien del equipo que no estuvo en esa parte. La escribe y la revisa el autor: si al leerla no puede defender cada decisión, todavía no entendió el cambio.

## Entradas requeridas

1. **Diff completo**: `git diff main...HEAD`
2. **Issue y Criterios de Aceptación (CA)**: objetivo de la historia y requerimientos.
3. **Contexto del repo**: `AGENTS.md`, la arquitectura asociada y los ADR que toque el cambio.

## Qué tiene que contar

Texto corrido en español, sin títulos, checkboxes, tablas ni listas largas. Tiene que quedar claro:

- **El problema**: qué pasaba o qué faltaba, y por qué hacía falta tocarlo.
- **La solución**: cómo se resolvió y por qué de esa forma. Si la decisión sale de un CA, de una regla de `AGENTS.md` o de un ADR, nombrarlo. Si no sale de ninguno, decir que es una decisión propia del cambio.
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
- La justificación de una decisión es meramente "porque así funciona".

## Ejemplo de salida

> Hasta ahora un usuario podía darle me gusta dos veces al mismo post si tocaba el botón rápido: llegaban dos requests casi juntos, los dos veían que no había like y los dos lo guardaban. El CA.3 pide un solo like por usuario y por post.
>
> Lo resolví en la base y no en el código: la tabla `post_likes` ahora tiene como clave el par usuario y post, así que el segundo insert falla solo y lo devolvemos como si ya existiera. Chequear antes de insertar no alcanzaba, porque entre el chequeo y el insert puede entrar el otro request.
>
> Lo que más me costó fue el contador de likes del post. Lo actualizo en la misma transacción que el insert, para que no quede desfasado si algo se corta a mitad de camino. Es lo que conviene mirar: el contador es un dato copiado, y si alguien inserta likes por fuera del servicio deja de coincidir. Lo elegí para que el feed no tenga que contar likes en cada lectura.
>
> Closes #42
