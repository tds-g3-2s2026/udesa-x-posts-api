import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from posts_api.api.deps import CurrentUserDep, SessionDep
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.likes import LikeRepository
from posts_api.app.repositories.posts import PostRepository
from posts_api.app.services.likes import LikeService

router = APIRouter(prefix="/posts", tags=["likes"])


def get_like_service(session: SessionDep) -> LikeService:
    return LikeService(LikeRepository(session), PostRepository(session), FollowRepository(session))


ServiceDep = Annotated[LikeService, Depends(get_like_service)]


@router.put("/{post_id}/like", status_code=status.HTTP_204_NO_CONTENT)
async def like_post(post_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep) -> None:
    """Like a post. Idempotent: `204` whether the like was new or already there."""
    await service.like(current_user, post_id)


@router.delete("/{post_id}/like", status_code=status.HTTP_204_NO_CONTENT)
async def unlike_post(
    post_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep
) -> None:
    """Take the like back. Idempotent: `204` whether there was one or not."""
    await service.unlike(current_user, post_id)
