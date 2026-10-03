import logging
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from posts_api.api.blocks import router as blocks_router
from posts_api.api.errors import problem_error_handler, validation_error_handler
from posts_api.api.feed import router as feed_router
from posts_api.api.follow_requests import router as follow_requests_router
from posts_api.api.follows import router as follows_router
from posts_api.api.health import router as health_router
from posts_api.api.posts import router as posts_router
from posts_api.api.reports import router as reports_router
from posts_api.app.errors import ProblemError
from posts_api.app.security import load_public_key
from posts_api.config.settings import API_PREFIX, get_settings
from posts_api.infrastructure.database.session import build_session_factory
from posts_api.infrastructure.telemetry import export, instrument
from posts_api.infrastructure.users_api.account_review import build_users_api_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Uvicorn configures only its own loggers and leaves the root at WARNING,
    # so without this every logger.info in the service is dropped.
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        force=True,
    )
    if settings.otel_exporter_otlp_endpoint:
        export(tracer_provider, OTLPSpanExporter(), OTLPLogExporter())

    # Connections are opened once and shared. Creating an engine per request
    # exhausts the PostgreSQL pool as soon as there is any load.
    app.state.settings = settings
    app.state.engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    app.state.session_factory = build_session_factory(app.state.engine)
    app.state.redis = Redis.from_url(settings.redis_url)
    app.state.auth_redis = Redis.from_url(settings.auth_redis_url)
    app.state.jwt_public_key = load_public_key(settings.jwt_public_key)
    app.state.users_api = build_users_api_client(
        settings.users_api_url, settings.internal_api_token
    )
    # Its calls carry the request's trace, so users-api joins it.
    HTTPXClientInstrumentor.instrument_client(app.state.users_api, tracer_provider=tracer_provider)

    yield

    await app.state.engine.dispose()
    await app.state.redis.aclose()
    await app.state.auth_redis.aclose()
    await app.state.users_api.aclose()


app = FastAPI(title="UdeSA-X Posts API", version=version("posts-api"), lifespan=lifespan)

tracer_provider = instrument(app)

app.add_exception_handler(ProblemError, problem_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)

# The healthcheck stays out of the prefix: the Kubernetes probes reach the pod
# directly and never pass through the Ingress.
app.include_router(health_router)
app.include_router(follows_router, prefix=API_PREFIX)
app.include_router(follow_requests_router, prefix=API_PREFIX)
app.include_router(posts_router, prefix=API_PREFIX)
app.include_router(feed_router, prefix=API_PREFIX)
app.include_router(blocks_router, prefix=API_PREFIX)
app.include_router(reports_router, prefix=API_PREFIX)
