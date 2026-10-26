"""Batch graph lookups authenticated independently of public sessions."""

import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field

from posts_api.api.deps import SessionDep
from posts_api.app.errors import ProblemError
from posts_api.app.repositories.blocks import BlockRepository


async def require_internal_token(
    request: Request, token: Annotated[str | None, Header(alias="X-Internal-Token")] = None
) -> None:
    if token is None or not hmac.compare_digest(
        token.encode(), request.app.state.settings.internal_api_token.encode()
    ):
        raise ProblemError(
            status=401,
            code="invalid-internal-token",
            title="No se pudo autenticar la solicitud",
            detail="Falta el token interno o no es válido",
        )


router = APIRouter(
    prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal_token)]
)


class BlockCheckRequest(BaseModel):
    viewer_id: UUID
    user_ids: list[UUID] = Field(max_length=50)


class BlockCheckResponse(BaseModel):
    excluded_ids: list[UUID]


@router.post("/blocks/check")
async def check_blocks(body: BlockCheckRequest, session: SessionDep) -> BlockCheckResponse:
    return BlockCheckResponse(
        excluded_ids=await BlockRepository(session).excluded_ids(body.viewer_id, body.user_ids)
    )
