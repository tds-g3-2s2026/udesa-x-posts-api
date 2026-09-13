from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from posts_api.infrastructure.health import build_report, check_postgres, check_redis

router = APIRouter(tags=["health"])


@router.get("/healthcheck")
async def healthcheck(request: Request) -> JSONResponse:
    """Check PostgreSQL and Redis before reporting the service as healthy."""
    state = request.app.state
    statuses = [
        await check_postgres(state.engine),
        await check_redis(state.redis),
    ]
    body, status_code = build_report(statuses)
    return JSONResponse(body, status_code=status_code)
