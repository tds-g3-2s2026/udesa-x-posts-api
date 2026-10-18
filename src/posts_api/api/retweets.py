import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from posts_api.api.deps import CurrentUserDep, SessionDep
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.posts import PostRepository
from posts_api.app.repositories.retweets import RetweetRepository
from posts_api.app.services.retweets import RetweetService

router = APIRouter(prefix="/posts", tags=["retweets"])


def get_retweet_service(session: SessionDep) -> RetweetService:
    return RetweetService(
        RetweetRepository(session), PostRepository(session), FollowRepository(session)
    )


ServiceDep = Annotated[RetweetService, Depends(get_retweet_service)]


@router.post(
    "/{post_id}/retweet", status_code=201, responses={204: {"description": "Already shared"}}
)
async def retweet(
    post_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep
) -> Response:
    created = await service.retweet(current_user, post_id)
    return Response(status_code=201 if created else 204)


@router.delete("/{post_id}/retweet", status_code=204)
async def undo_retweet(
    post_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep
) -> None:
    await service.unretweet(current_user, post_id)
