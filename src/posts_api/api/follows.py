import uuid

from fastapi import APIRouter, status

from posts_api.api.deps import CurrentUserDep, SessionDep
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.services.follows import FollowService

router = APIRouter(prefix="/users", tags=["follows"])


def _service(session: SessionDep) -> FollowService:
    return FollowService(FollowRepository(session))


@router.post("/{user_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
async def follow(user_id: uuid.UUID, current_user: CurrentUserDep, session: SessionDep) -> None:
    """Follow an account. Who is following comes from the token, never from the body."""
    await _service(session).follow(current_user, user_id)


@router.delete("/{user_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
async def unfollow(user_id: uuid.UUID, current_user: CurrentUserDep, session: SessionDep) -> None:
    await _service(session).unfollow(current_user, user_id)
