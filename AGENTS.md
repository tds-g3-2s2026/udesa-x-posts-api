# AGENTS.md - udesa-x-posts-api

<!-- INICIO BLOQUE PROPIO - completado en cada servicio -->

Contenido, grafo social, feed cronológico y denuncias de UdeSA-X: posts, likes, retweets,
seguir/dejar de seguir, solicitudes de seguimiento, bloqueos y moderación. Cubre E2-H1 a H5,
E3-H1 a H10 y E3-H5.

## Stack y herramientas

- Lenguaje y runtime: Python 3.13 / FastAPI, Uvicorn
- Gestor de paquetes: uv
- Persistencia y migraciones: PostgreSQL (SQLAlchemy 2 async con asyncpg) / Alembic
- Imágenes de los posts: bucket privado de S3 vía `aioboto3`, detrás de la interfaz
  `ImageStorage`; el multipart se lee a mano con `python-multipart` (ADR-018)
- Mensajería: RabbitMQ con `aio-pika` (ADR-019). Consume `user.deleted.v1` en la cola
  `posts-api` (`infrastructure/rabbitmq/`), con su DLQ `posts-api.dlq`
- Cache y estado efímero: Redis `/1` (rate limit de follows y posts). Lee además, en solo
  lectura, el Redis `/0` de `users-api` para las revocaciones de sesión (ADR-014)

## Checks y comandos

No hay `scripts/lint.sh` ni `scripts/test.sh` en este repo todavía: los comandos son los que
corre el CI (`.github/workflows/ci.yml` vía el reusable `ci-python.yml` de platform).

```bash
uv run ruff check .                                    # Lint
uv run ruff format --check .                           # Formato
uv run pytest tests/unit --cov=src --cov-report=term   # Tests unitarios con cobertura
uv run pytest --cov=src --cov-report=term              # + tests/integration, requiere DATABASE_URL,
                                                        # REDIS_URL y AUTH_REDIS_URL
```

**Gate de cobertura del 85%: bloqueante en este repo** (`bloquear-por-cobertura: true` en
`ci.yml`).

## Arquitectura y particularidades locales

- El código se organiza por capa, según el ADR-007 de `udesa-x-platform`: `api/` expone las
  rutas, sus esquemas y el wiring; `app/` tiene el negocio (`models/`, `repositories/`,
  `services/`); `config/` la configuración; `infrastructure/` las implementaciones agrupadas
  por tecnología.
- **Deuda conocida:** a diferencia de `users-api`, los repositorios de PostgreSQL
  (`app/repositories/follows.py`, `blocks.py`, `posts.py`, `feed.py`, etc.) son clases
  concretas con SQLAlchemy adentro, sin una interfaz intermedia en `app/`. Sí devuelven
  dataclasses del dominio, nunca filas de SQLAlchemy, y los servicios no importan SQLAlchemy.
  Redis y el cliente HTTP a `users-api` sí tienen interfaz en `app/` e implementación en
  `infrastructure/`. No dupliques el patrón plano al agregar un repositorio nuevo sin
  acordarlo antes: el objetivo es llegar a la misma forma que `users-api`.
- El grafo social (`follows`, `follow_requests`, `blocks`) vive en este servicio y no en uno
  propio, por el ADR-005: el feed necesita el grafo en la misma consulta que los posts.
- La regla de visibilidad de posts (bloqueos y cuentas protegidas) está centralizada en
  `app/repositories/post_visibility.py` (`visible_to`). Cualquier consulta nueva que lea
  posts tiene que reusar esa función, nunca escribir su propio filtro.
- `api/deps.py` arma las dependencias de cada request, pero no es el único lugar: algunas
  rutas (`api/follows.py`, `api/posts.py`, `api/reports.py`) importan implementaciones de
  `infrastructure/` directamente. Es la misma deuda del punto anterior.
- Migraciones: de `0001_esquema_actual` a `0010_outbox`, con `0002b_tabla_de_posts` en el
  medio. **Una migración ya aplicada en producción no se edita**, se agrega una nueva (es la
  lección detrás de la `0002b`).
- Los eventos que publica el servicio van por el outbox transaccional, como en `users-api`:
  el servicio llama a `OutboxRepository.add` con la sesión del request, en la misma
  transacción que el cambio, y `infrastructure/rabbitmq/outbox_publisher.py` los publica.
  Nunca publicar directo al broker desde un request.
- `AUTH_REDIS_URL` es obligatoria: el servicio no arranca sin ella (ADR-014). Es de solo
  lectura; nunca escribir ni borrar claves ahí.
- Tests en `tests/unit/` y `tests/integration/`. Identificadores de historia
  (`E3-H1.CA2`, etc.) solo en el nombre de la función de test, nunca en `src/` ni en
  comentarios, como pide "Trazabilidad de criterios de aceptación" en `CONVENCIONES.md`.
- `contracts/events/` es una copia de `udesa-x-platform/docs/eventos/` con los eventos que
  este servicio publica o consume (ADR-017 de platform). No se edita acá: se cambia en
  platform y se trae con su `scripts/sync-contracts.sh`. El job `Contratos de eventos al dia`
  del CI falla si la copia difiere. Los tests validan contra estos esquemas los mensajes.
- Documentación general del sistema: consultar `../udesa-x-platform/docs/`
  (`ARQUITECTURA.md`, `CONVENCIONES.md`, `PLANIFICACION.md`) y los ADR 005, 009, 011 y 014.

<!-- FIN BLOQUE PROPIO -->

<!-- INICIO BLOQUE COMUN - sincronizado desde udesa-x-platform, no editar la copia local -->

## Reglas del equipo

- **Ramas e issues**: Rama base `main`. Ramas de trabajo `feature-<nombre>` (funcionalidad), `fix-<nombre>` (defecto) o `chore-<nombre>` (mantenimiento y tooling, etiqueta `tech debt`), siempre asociadas a un issue en el mismo repositorio.
- **Idiomas**:
  - Código (`src/`, `tests/`), nombres de archivos, identificadores y comentarios en código: **inglés**.
  - Documentación (`docs/`, `README.md`), mensajes de commit y Pull Requests: **español**.
- **Commits**: Formato Conventional Commits (`feat:`, `fix:`, `docs:`, etc.) con descripción en español.
- **Simplicidad**: Soluciones mínimas y directas para el criterio de aceptación. No introducir librerías, patrones ni abstracciones nuevas sin un ADR aprobado en `docs/adr/`.

## Límites y flujo de trabajo del agente

- El agente inspecciona el repositorio (`git status`, `git diff`), edita archivos en el working tree, ejecuta checks locales y redacta propuestas de commit y PR.
- **El agente nunca commitea, pushea ni abre/aprueba/mergea Pull Requests.** La revisión y confirmación en Git la realiza siempre un integrante del equipo.
- **Sin firmas**: Nunca agregar `Co-Authored-By`, firmas o menciones del agente en commits, PRs ni código.

## Modo de planificación

- Planes extremadamente concisos: priorizar brevedad y concreción por sobre prosa formal.
- Al final de cada plan, incluir la lista de preguntas o dudas pendientes a resolver (si las hay).

## Skills (.agents/skills/)

- `explicar-implementacion`: Le pregunta al autor por qué tomó sus decisiones y con eso redacta la descripción del PR, una explicación breve en texto corrido para alguien sin el contexto de la pieza.
- `revisar-pr`: Guía paso a paso para la revisión técnica de Pull Requests.

<!-- FIN BLOQUE COMUN -->
