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
RabbitMQ queda en el 5672, con su pantalla de administración en `http://localhost:15672`
(usuario y clave `posts`): ahí se ve la cola `posts-api` y su `posts-api.dlq`.
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

`configmap.yaml` define `LOG_LEVEL`, `FOLLOW_RATE_LIMIT`, `FOLLOW_RATE_WINDOW_SECONDS`,
`JWT_ISSUER` (`users-api`), `S3_BUCKET` y `S3_REGION` (el bucket de las imágenes) y `USERS_API_URL`, la dirección interna de `users-api` a la que se
avisa que una cuenta pasa a revisión por denuncias (ADR-011). La API valida estrictamente el
issuer al verificar tokens recibidos. Copiar `secret.template.yaml` a `secret.yaml`,
ignorado por git, y completar `DATABASE_URL` (con esquema `postgresql+asyncpg://`),
`REDIS_URL`, `RABBITMQ_URL` (el RabbitMQ de los eventos, ver "Baja de cuentas" y "Eventos
que publica"),
`AUTH_REDIS_URL` (el Redis donde `users-api` escribe las revocaciones, ver
"Revocación de sesiones"; en el cluster, `redis://redis:6379/0`), `JWT_PUBLIC_KEY` (clave
pública Ed25519 en PEM) e `INTERNAL_API_TOKEN`, el secreto compartido con `users-api` para sus
rutas internas, con el mismo valor en los dos servicios. En el despliegue, el pipeline arma el
Secret con esos GitHub Secrets del repositorio. No aplicar la plantilla vacía ni usar `kubectl apply -f k8s/` en un despliegue:
incluiría esa plantilla.
Las imágenes de los posts van a un bucket privado de S3. Se configuran con `S3_BUCKET`,
`S3_REGION` (por defecto `us-east-1`) e `IMAGE_URL_EXPIRY_SECONDS` (por defecto `3600`, lo que
dura la URL firmada de lectura). Las credenciales no son variables del servicio: el SDK las toma
del entorno. En el cluster llegan por el Secret (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` y
`AWS_SESSION_TOKEN`, de un usuario de IAM con acceso al bucket) y son temporales: al vencer, subir
imágenes falla con `503 images-unavailable` y las URLs de lectura dejan de abrir, hasta cargar
otras credenciales y volver a desplegar. Lo
recomendable a futuro es un rol de IAM asociado al pod, sin claves. Sin `S3_BUCKET` el servicio arranca y atiende todo lo demás, pero
publicar un post con imágenes responde `503 images-unavailable`. `S3_ENDPOINT_URL` solo sirve
para apuntar a un servidor compatible con S3 en desarrollo.
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

## Revocación de sesiones

Un token firmado y vigente no alcanza: `users-api` puede haberlo revocado antes de que venza
(cierre de sesión, cambio de contraseña, cuenta puesta en revisión por denuncias). Como
`posts-api` no tiene su propia lista, en cada request autenticado lee las marcas que
`users-api` escribe en su Redis (base `/0`), solo lectura, con una única consulta (ADR-014):

| Clave | Valor | Revoca |
|---|---|---|
| `revoked:jti:<jti>` | `"1"` | ese token |
| `revoked:user:<uuid>` | segundos Unix | los tokens de la cuenta con `iat <= valor` |

Un token revocado recibe `401` con `code: session-revoked`, igual que en `users-api`. Si ese
Redis no responde, el request se rechaza con `503` (`auth-unavailable`): sin poder verificar,
no pasa. Las claves y la regla son un contrato que mantiene `users-api`; cambiar una obliga a
cambiar la otra. En desarrollo, el `docker-compose` no incluye a `users-api`, así que nadie
escribe marcas y no se revoca nada. En los tests, `AUTH_REDIS_URL` apunta a otra base que
`REDIS_URL` (`/2`), porque los tests vacían esta última antes de cada caso.

## Baja de cuentas

Cuando `users-api` cierra una cuenta publica `user.deleted.v1` (contrato en
`contracts/events/`). `posts-api` lo consume de la cola `posts-api`, ligada al exchange
`udesa-x.events` por ese tipo, con la misma topología que `notifications-api`: cola `quorum` con
`x-dead-letter-exchange: udesa-x.events.dlx`, `posts-api.dlq` como DLQ, ack manual y `prefetch`
10. Un mensaje que no se puede leer va a la DLQ; un fallo de la base lo devuelve a la cola. El
cliente es `aio-pika` (ADR-019) y, como `AUTH_REDIS_URL`, `RABBITMQ_URL` no tiene valor por
omisión. Si el broker no está, el servicio arranca igual y vuelve a intentar cada 5 segundos.

El manejador corre en una sola transacción y se puede repetir sin efecto: la cuenta queda con
`user_profiles.deleted_at` (el `time` del evento) y

- se borran sus seguimientos y solicitudes en los dos sentidos, y se corrigen los contadores de
  seguidores y seguidos de las cuentas que tocaban;
- se borran sus bloqueos, sus likes y sus retweets, con los contadores de los posts;
- sus posts no se borran: salen de la vista. `visible_to` oculta a los autores con `deleted_at`,
  así que el feed, el perfil y `GET /posts/{id}` no los devuelven. La excepción son las
  respuestas, que se quedan para no romper los hilos y salen con `authorDeleted: true`, sin
  handle, nombre ni avatar (`authorId` se mantiene);
- la cuenta queda pública, para que la protección de una cuenta sin seguidores no esconda sus
  respuestas;
- `GET /users/{id}`, sus posts, sus seguidores y a quién sigue, y seguirla responden `404
  user-not-found`, como una cuenta que no existe;
- las imágenes de sus posts siguen en el bucket: borrarlas queda como mejora.

El filtro está en la consulta y no depende de cuándo llegue el evento a una réplica: desde que
el manejador commitea, nada la muestra. Antes del evento, lo que sí es inmediato es que sus
tokens mueren por ADR-014.

## Denuncias y bandeja del backoffice

Una cuenta pasa a revisión cuando junta denuncias pendientes de 6 cuentas distintas: `posts-api` se
lo pide a `users-api` por `POST /internal/users/{id}/review` (ADR-011). Cada denuncia está
pendiente, descartada o resuelta, y solo las pendientes cuentan para ese umbral
([ADR-020](https://github.com/tds-g3-2s2026/udesa-x-platform/blob/main/docs/adr/ADR-020-cierre-de-casos-de-denuncias.md)).

El backoffice las ve agrupadas en casos, uno por cuenta (E5-H7), todo bajo `/api/admin/posts`
porque el gateway ya manda ese prefijo acá:

| Ruta | Qué hace |
|---|---|
| `GET /admin/posts/reports/cases?cursor=` | Cuentas con denuncias pendientes, primero la que denunció más gente distinta, después la denunciada más recientemente. Veinte por página, con `nextCursor` |
| `POST /admin/posts/reports/cases/{id}/dismiss` | Descarta las pendientes de la cuenta |
| `POST /admin/posts/reports/cases/{id}/resolve` | Las resuelve. "Suspender" en el backoffice bloquea la cuenta en `users-api` y después resuelve |

Descartar y Resolver guardan quién y cuándo, y le piden a `users-api` que levante la revisión
con `DELETE /internal/users/{id}/review`: una cuenta en revisión vuelve a entrar, y una
suspendida no cambia. Ese pedido sale antes de confirmar el cambio: si `users-api` no responde
después de un reintento, la acción responde `503` (`users-api-unavailable`) y las denuncias
siguen pendientes para volver a intentarlo. Un caso sin pendientes responde `204` y no hace
nada. Solo un token de `moderator` o `superadmin` llega a estas rutas.

Cada cierre efectivo guarda `admin.action_recorded.v1` en el outbox de la misma
transacción que cambia las denuncias. Conserva el email del administrador leído
desde users-api antes de modificar el caso; si esa identidad no se puede obtener,
responde 503 sin cerrar denuncias ni levantar la revisión. Un caso sin pendientes
responde 204 sin consultar users-api ni producir otro evento.

El publicador existente entrega la auditoría por RabbitMQ. users-api conserva el
historial y deduplica por ID del evento; la consulta refleja estas decisiones con
consistencia eventual. No se transportan auditorías por HTTP. La llamada HTTP para
levantar la revisión mantiene su comportamiento y sus límites de consistencia.

## Eventos que publica

Cuando una cuenta empieza a seguir a otra, `posts-api` publica `follow.created.v1` (contrato en
`contracts/events/`). Es el mismo evento para un follow directo a una cuenta pública y para una
solicitud aprobada por una cuenta protegida; una solicitud pendiente o rechazada no publica nada.
`notifications-api` lo consume para mandar el push al seguido.

Se usa un outbox transaccional, igual que en `users-api`:

1. El request escribe el evento en la tabla `outbox`, en la misma transacción que el follow y los
   contadores. Si una de las escrituras falla, no queda ninguna: no hay follow sin evento ni
   evento sin follow.
2. Un trigger hace `pg_notify('outbox', ...)` al insertar. El aviso llega cuando la transacción
   commitea.
3. El publicador corre como tarea dentro del proceso de la API. Se despierta con el aviso, o cada
   `OUTBOX_POLL_SECONDS` (5 por omisión) si se perdió la conexión que escucha. Toma hasta 100 filas
   con `FOR UPDATE SKIP LOCKED`, así dos réplicas no publican la misma, y las publica en el exchange
   `udesa-x.events` con el `type` como routing key, con confirmación del broker y `mandatory`.
4. Cada fila confirmada se borra. Una que el broker devuelve porque ninguna cola está ligada a ese
   tipo queda en la tabla y se reintenta en la pasada siguiente, sin frenar a las demás.

La entrega es al menos una vez: si el proceso cae entre la confirmación y el borrado, el evento sale
de nuevo, y el consumidor lo descarta por el `id`. Si RabbitMQ no está, la API responde igual y los
eventos esperan en la tabla.

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
| `0002b_tabla_de_posts` | `posts`, solo si falta: la base de producción aplicó la `0001` antes de que se le sumara esa tabla |
| `0003_denuncias` | `reports` |
| `0010_outbox` | `outbox`, con el trigger que avisa por `pg_notify` en cada inserción |

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
