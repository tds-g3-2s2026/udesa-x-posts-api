import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from posts_api.api.health import router as health_router
from posts_api.config.settings import get_settings
from posts_api.infrastructure.database.session import build_session_factory


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

    # Connections are opened once and shared. Creating an engine per request
    # exhausts the PostgreSQL pool as soon as there is any load.
    app.state.settings = settings
    app.state.engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    app.state.session_factory = build_session_factory(app.state.engine)
    app.state.redis = Redis.from_url(settings.redis_url)

    yield

    await app.state.engine.dispose()
    await app.state.redis.aclose()


app = FastAPI(title="UdeSA-X Posts API", version="0.1.0", lifespan=lifespan)

app.include_router(health_router)
