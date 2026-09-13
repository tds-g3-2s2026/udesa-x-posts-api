from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    is_healthy: bool
    detail: str | None = None


async def check_postgres(engine: AsyncEngine) -> DependencyStatus:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as error:
        return DependencyStatus("postgres", False, str(error))
    return DependencyStatus("postgres", True)


async def check_redis(client: Redis) -> DependencyStatus:
    try:
        await client.ping()
    except Exception as error:
        return DependencyStatus("redis", False, str(error))
    return DependencyStatus("redis", True)


def build_report(statuses: list[DependencyStatus]) -> tuple[dict, int]:
    """Build the response body and its HTTP status code.

    Returns 503 when any dependency is down, so the readiness probe pulls the pod
    out of rotation instead of sending it traffic that is going to fail.
    """
    is_healthy = all(status.is_healthy for status in statuses)
    body = {
        "status": "ok" if is_healthy else "degraded",
        "dependencies": {
            status.name: "ok" if status.is_healthy else status.detail for status in statuses
        },
    }
    return body, 200 if is_healthy else 503
