# UdeSA-X Posts API

Microservicio backend responsable de la lógica core de la red social: creación de publicaciones, retweets, likes, respuestas y la generación del feed cronológico.

## Cómo correrlo

Todo con Docker, que es como corre en el CI y como se despliega:

```bash
docker compose -f docker/docker-compose.dev.yml up --build
```

El servicio queda en `http://localhost:8001`, con la documentación interactiva en `/docs`.
PostgreSQL y Redis usan los puertos 5433 y 6380 para no chocar con `udesa-x-users-api`.

Los tests, dentro de la misma imagen que se despliega:

```bash
docker compose -f docker/docker-compose.dev.yml run --rm --build tests
```

El `--build` no es opcional: sin él compose reusa la imagen anterior y corre código viejo.

Sin Docker, solo los unitarios. Los de integración se saltean si no hay base:

```bash
uv sync
uv run pytest
```

## Integración continua

El pipeline vive una sola vez, en `udesa-x-platform`, y este repo lo consume en cuatro líneas
desde `.github/workflows/ci.yml`. En cada PR:

| Job | Qué hace |
|---|---|
| `Lint y formato` | Ruff sobre el runner |
| `Tests y cobertura` | Construye la etapa `test` de la imagen, corre la suite **adentro del contenedor**, saca los reportes y sube la cobertura a Codecov |

**El gate de cobertura está en 85% y bloquea.** Un PR por debajo queda en rojo y no se puede
mergear. Los dos checks son obligatorios en `main`.

Además del test, el pipeline construye la imagen de producción y verifica que levante y
responda 200 en `/healthcheck`: que compile no prueba que sirva.

## Estructura

Por capas, según el `ADR-007` de `udesa-x-platform`:

```text
src/posts_api/
├── api/              rutas, esquemas y el wiring en deps.py
├── app/              el negocio: modelos de dominio, interfaces y casos de uso
├── config/           configuración por variables de entorno
└── infrastructure/   las implementaciones, agrupadas por tecnología
```

La regla: las dependencias apuntan hacia adentro. `api/` e `infrastructure/` conocen a `app/`;
`app/` no conoce a ninguno de los dos y nunca importa SQLAlchemy.

**Sin Alembic todavía.** Las tablas se crean desde los modelos al arrancar: no hay base
desplegada, así que no hay datos vivos que una migración deba proteger.

## Code Guidelines (Reglas del Equipo)
Para mantener la calidad y consistencia del código, todos los miembros deben seguir estas reglas:
* **Ramas:** Obligatorio usar la convención `feature-[nombre-de-la-funcionalidad]` o `fix-[fix-a-realizar]`. Toda rama se integra a `main`.
* **Issues:** Todas las ramas deben tener un issue asociado con la información necesaria para implementar la tarea.
* **Etiquetas (Labels):** Los issues deben clasificarse usando `feature`, `tech debt`, `spike`, o `bug`.
* **Pull Requests (PR):** Las descripciones de los PR deben redactarse en **español**.
* **Idioma del código:** En inglés todo lo que vive dentro de un archivo de código (variables, funciones, clases, tablas, comentarios y docstrings) y los nombres de los archivos y carpetas de código. En español la documentación, los mensajes de commit y las descripciones de PR.
* **Commits (Opcional):** Recomendamos usar la convención de [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).
