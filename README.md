# UdeSA-X Posts API

Microservicio backend responsable de la lógica core de la red social: creación de publicaciones, retweets, likes, respuestas y la generación del feed cronológico.

## Cómo correrlo

Todo con Docker, que es como corre en el CI y como se despliega:

```bash
docker compose -f docker/docker-compose.dev.yml up --build
```

El servicio queda en `http://localhost:8001`, con la documentación interactiva en `/docs`.
Las rutas públicas cuelgan bajo el prefijo `/api` (por ejemplo `/api/users/{user_id}/follow`).
Los endpoints de verificación `/healthcheck` y `/livez` quedan fuera del prefijo `/api`, sin autenticación.
PostgreSQL y Redis usan los puertos 5433 y 6380 para no chocar con `udesa-x-users-api`.
En compose, las migraciones se aplican automáticamente (`alembic upgrade head`) antes de iniciar la API.

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

## Kubernetes

Los cuatro manifiestos de `k8s/` usan el namespace `tds-group-3`, según
[ADR-008](https://github.com/tds-g3-2s2026/udesa-x-platform/blob/main/docs/adr/ADR-008-plataforma-de-despliegue.md).
El Service es interno (`ClusterIP`) y escucha en el puerto `80` hacia el `targetPort` nombrado
`http` (puerto `8000`), coincidiendo con el `containerPort`, el `EXPOSE` y el comando de
Uvicorn en `docker/Dockerfile`.
Las sondas de Kubernetes consultan el puerto nombrado `http`:
- `readinessProbe` consulta `/healthcheck`: comprueba PostgreSQL y Redis; un fallo saca
  al pod de rotación sin reiniciarlo.
- `livenessProbe` consulta `/livez`: comprueba únicamente la vitalidad del proceso Python/FastAPI
  sin tocar dependencias externas, evitando reinicios en cascada por caídas transitorias de BD o Redis.
Ambos endpoints quedan fuera del prefijo `/api` y sin autenticación.

Una réplica pide `100m` de CPU y `128Mi` de memoria, con límites `500m` y `512Mi`,
dentro del LimitRange de plataforma. El rollout usa `maxSurge: 1` y
`maxUnavailable: 0` para mantener el pod anterior hasta que el nuevo esté listo,
reservando un slot temporal en la cuota (no promete alta disponibilidad).

Cada push a `main` que pasa el CI despliega solo, con el job `deploy` de
`.github/workflows/ci.yml`, que llama a `deploy.yml` de `udesa-x-platform`. Ese pipeline
publica la imagen en ECR, reemplaza `${ECR_IMAGE}` por su referencia por digest y corre
`alembic upgrade head` como Job con la misma imagen antes del rollout. Si la migración falla,
el despliegue se corta con los pods anteriores sirviendo. La aplicación no realiza
migraciones al arrancar. Qué hace paso por paso está en el README de `udesa-x-platform`,
sección "Despliegue continuo".

`configmap.yaml` define `LOG_LEVEL`, `FOLLOW_RATE_LIMIT`, `FOLLOW_RATE_WINDOW_SECONDS`
y `JWT_ISSUER` (`users-api`). La API valida estrictamente el issuer al verificar tokens
recibidos. Copiar `secret.template.yaml` a `secret.yaml`,
ignorado por git, y completar `DATABASE_URL` (con esquema `postgresql+asyncpg://`),
`REDIS_URL` y `JWT_PUBLIC_KEY` (clave pública Ed25519 en PEM). En el despliegue, el pipeline
arma el Secret con esos tres GitHub Secrets del repositorio. No aplicar la plantilla vacía ni
usar `kubectl apply -f k8s/` en un despliegue: incluiría esa plantilla.
`envFrom` se lee al crear el contenedor: el pipeline pone el hash del ConfigMap y del Secret
en el pod template, así que un cambio solo de configuración también reemplaza los pods. La
pública corresponde a la privada estable de users; los tokens antiguos sin `iss` se rechazan.

Validación sin escribir recursos:

```bash
kubectl apply --dry-run=client \
  -f k8s/deployment.yaml \
  -f k8s/service.yaml \
  -f k8s/configmap.yaml \
  -f k8s/secret.template.yaml
```

El dry-run no necesita permisos de escritura, pero `kubectl` consulta discovery
y esquemas del API server: requiere un kubeconfig y acceso de lectura al cluster.
No comprueba la existencia de la imagen, los valores secretos ni la cuota libre.
El PR requiere aprobación del tutor.

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

## Migraciones

El esquema se gestiona con Alembic (`alembic.ini` y `migrations/`).

```bash
uv run alembic upgrade head          # aplicar
```

| Migración | Qué crea |
|---|---|
| `0001_esquema_actual` | `user_profiles`, `follows`, `follow_requests` y `posts` |
| `0002_bloqueos` | `blocks` |

**Una migración ya aplicada no se edita**: una base que ya la corrió no la vuelve a correr, así
que el cambio nunca llegaría. Todo cambio de esquema va en una migración nueva.

**Transición de base de datos:** el primer despliegue productivo arranca sobre una base vacía y
aplica la migración inicial. No debe stampearse a ciegas (`alembic stamp`) contra bases existentes
sin verificar exhaustivamente el estado de tablas e índices preexistentes. A partir de ese primer
despliegue productivo, todos los cambios de esquema serán migraciones incrementales.

En desarrollo local con Docker, el compose ejecuta automáticamente las migraciones antes de
arrancar el servidor ASGI.
## Code Guidelines (Reglas del Equipo)
Para mantener la calidad y consistencia del código, todos los miembros deben seguir estas reglas:
* **Ramas:** Obligatorio usar la convención `feature-[nombre-de-la-funcionalidad]` o `fix-[fix-a-realizar]`. Toda rama se integra a `main`.
* **Issues:** Todas las ramas deben tener un issue asociado con la información necesaria para implementar la tarea.
* **Etiquetas (Labels):** Los issues deben clasificarse usando `feature`, `tech debt`, `spike`, o `bug`.
* **Pull Requests (PR):** Las descripciones de los PR deben redactarse en **español**.
* **Idioma del código:** En inglés todo lo que vive dentro de un archivo de código (variables, funciones, clases, tablas, comentarios y docstrings) y los nombres de los archivos y carpetas de código. En español la documentación, los mensajes de commit y las descripciones de PR.
* **Commits (Opcional):** Recomendamos usar la convención de [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).
