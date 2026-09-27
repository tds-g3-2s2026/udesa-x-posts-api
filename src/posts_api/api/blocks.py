import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from posts_api.api.deps import CurrentUserDep, SessionDep
from posts_api.api.schemas.blocks import BlockedAccountSummary
from posts_api.api.schemas.pagination import CursorPage
from posts_api.app.repositories.blocks import BlockRepository
from posts_api.app.repositories.follow_requests import FollowRequestRepository
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.services.blocks import BlockService

router = APIRouter(tags=["blocks"])


def get_block_service(session: SessionDep) -> BlockService:
    return BlockService(
        BlockRepository(session), FollowRepository(session), FollowRequestRepository(session)
    )


ServiceDep = Annotated[BlockService, Depends(get_block_service)]


@router.post("/users/{user_id}/block", status_code=status.HTTP_204_NO_CONTENT)
async def block(user_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep) -> None:
    """Block an account. Who is blocking comes from the token, never from the body."""
    await service.block(current_user, user_id)


@router.delete("/users/{user_id}/block", status_code=status.HTTP_204_NO_CONTENT)
async def unblock(user_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep) -> None:
    await service.unblock(current_user, user_id)


@router.get("/blocks")
async def blocked_accounts(
    current_user: CurrentUserDep,
    service: ServiceDep,
    cursor: Annotated[str | None, Query()] = None,
) -> CursorPage[BlockedAccountSummary]:
    """The accounts the caller blocked, most recent first."""
    items, next_cursor = await service.blocked_by(current_user, cursor=cursor)
    return CursorPage(
        items=[BlockedAccountSummary.of(one) for one in items], next_cursor=next_cursor
    )
