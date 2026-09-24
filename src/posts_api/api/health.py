from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from posts_api.infrastructure.health import build_report, check_postgres, check_redis

router = APIRouter(tags=["health"])


@router.get("/healthcheck")
async def healthcheck(request: Request) -> JSONResponse:
    """Check PostgreSQL and Redis, and report the version that is running."""
    state = request.app.state
    statuses = [
        await check_postgres(state.engine),
        await check_redis(state.redis),
    ]
    body, status_code = build_report(statuses)
    return JSONResponse({**body, "version": request.app.version}, status_code=status_code)


@router.get("/livez", status_code=status.HTTP_200_OK)
async def livez() -> dict[str, str]:
    """Report that the process is running and accepting HTTP requests.

    Does not touch PostgreSQL or Redis: a liveness failure restarts the pod, and
    restarting a pod whose database is slow makes the outage worse, not better.
    """
    return {"status": "ok"}
