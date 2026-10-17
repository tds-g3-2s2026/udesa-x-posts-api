---
name: revisar-pr
description: Realiza una revisión técnica exhaustiva de un Pull Request contra los criterios de aceptación, reglas de arquitectura, cobertura, tests y seguridad OWASP. Usar al revisar un PR, al evaluar si un cambio está listo para mergear o durante el rol semanal de revisor primario.
---

# Revisar Pull Request

Genera un informe técnico de revisión para que un integrante del equipo decida si aprueba o solicita cambios en un PR.

## Entradas requeridas

1. **Diff completo**: `git diff main...HEAD`
2. **Issue asociada**: Criterios de Aceptación (CA) y alcance.
3. **Descripción del PR**: Debe incluir la sección **"Explicación de la implementación"**.
4. **Reglas del repo**: `AGENTS.md` y guías en `docs/`.

> **Comprobación inicial obligatoria**: Si la sección *"Explicación de la implementación"* no existe o está vacía, rechazar el PR inmediatamente indicando que es obligatoria para iniciar la revisión.

## Checklist de revisión

### 1. Criterios de Aceptación y Trazabilidad
- Verificar que cada CA de la issue tenga código que lo implemente y al menos un test asociado nombrado con el formato `E<épica>-H<historia>.CA<número>` (ej. `E1-H1.CA3`).
- Marcar explícitamente cualquier CA no cubierto o sin test trazable.

### 2. Calidad de Tests
- Validar aserciones reales (`assert` concretos sobre comportamiento, no solo ejecución para inflar cobertura).
- Verificar cobertura de caminos de error y validaciones (no solo camino feliz).
- Confirmar tests de integración contra contenedores si toca base de datos, colas o contratos externos.

### 3. Cobertura de Código
- Confirmar que la cobertura se mantenga sobre el umbral requerido (mínimo 85% para backend).
- Si la cobertura disminuye, identificar los archivos específicos afectados.

### 4. Seguridad (OWASP)
- **Autorización**: Validación de permisos y propiedad sobre el recurso (no solo estar autenticado).
- **Validación de entrada**: Esquemas de request validados y sanitización de texto libre.
- **Fuga de información**: Manejo seguro de errores sin exponer stack traces ni enumeración de usuarios.
- **Inyección y secretos**: Consultas parametrizadas (vía ORM) y cero credenciales hardcodeadas.

### 5. Reglas de Arquitectura y Equipo
- Respeto de capas: rutas HTTP en `routes/`, lógica en `services/`, persistencia en `repositories/`.
- Sin dependencias externas ni patrones nuevos sin ADR aprobado en `docs/adr/`.
- Nombres de ramas (`feature-<nombre>`, `fix-<nombre>`, `chore-<nombre>`) e issue vinculada.
- Código e identificadores en inglés; documentación, commits y PR en español.

### 6. Comprensibilidad y Simplicidad
- Sin abstracciones prematuras ni capas de indirección innecesarias.
- Código legible y mantenible por cualquier miembro del equipo.

## Formato del informe

```markdown
## Revisión de PR #<número> - <título>

**Veredicto:** [Listo para aprobar | Cambios necesarios | Falta explicación obligatoria]

### Bloqueantes
- [Archivo:Línea] Descripción del problema y por qué bloquea el merge. (O "Ninguno")

### A corregir
- [Archivo:Línea] Corrección necesaria sin bloqueo inmediato.

### Sugerencias
- [Archivo:Línea] Oportunidad de mejora opcional.

### Matriz de Criterios de Aceptación

| Criterio | Implementado | Test Asociado |
|---|---|---|
| CA.1 | Sí | `tests/unit/test_users.py::E1-H1.CA1` |
| CA.2 | No | Falta test / implementación |
```

## Reglas para los hallazgos

- Cada observación debe indicar **archivo, línea, impacto concreto y justificación**.
- Separar defectos objetivos de preferencias personales de estilo.
- Si el PR cumple todos los puntos, emitir veredicto favorable sin inventar observaciones artificiales.
