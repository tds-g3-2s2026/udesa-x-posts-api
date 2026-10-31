"""Another user's profile (E2-H14).

Under `/users`, like the followers and following lists the profile opens.
Included after `follows.py` in `main.py`, so `/users/suggested` is matched
before `/users/{user_id}` gets the chance to read "suggested" as an id.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from posts_api.api.deps import (
    CurrentUserDep,
    PostImagesDep,
    ProfileImagesDep,
    SessionDep,
    UsersApiDep,
)
from posts_api.api.schemas.feed import FeedPostSummary
from posts_api.api.schemas.pagination import CursorPage
from posts_api.api.schemas.profiles import ProfileSummary
from posts_api.app.repositories.blocks import BlockRepository
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.mutes import MuteRepository
from posts_api.app.repositories.profile_posts import ProfilePostRepository
from posts_api.app.repositories.user_directory import UserDirectory
from posts_api.app.services.profiles import ProfileService
from posts_api.infrastructure.users_api.user_directory import HttpUserDirectory

router = APIRouter(prefix="/users", tags=["profiles"])


def get_user_directory(users_api: UsersApiDep) -> UserDirectory:
    return HttpUserDirectory(users_api)


def get_profile_service(
    session: SessionDep,
    directory: Annotated[UserDirectory, Depends(get_user_directory)],
    images: PostImagesDep,
    profile_images: ProfileImagesDep,
) -> ProfileService:
    return ProfileService(
        FollowRepository(session),
        BlockRepository(session),
        directory,
        ProfilePostRepository(session),
        images,
        MuteRepository(session),
        profile_images,
    )


ServiceDep = Annotated[ProfileService, Depends(get_profile_service)]


@router.get("/{user_id}")
async def profile(
    user_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep
) -> ProfileSummary:
    """The header of a profile: name, biography, registration date and counters."""
    return ProfileSummary.of(await service.profile_of(user_id, current_user))


@router.get("/{user_id}/posts")
async def profile_posts(
    user_id: uuid.UUID,
    current_user: CurrentUserDep,
    service: ServiceDep,
    cursor: Annotated[str | None, Query()] = None,
) -> CursorPage[FeedPostSummary]:
    """The author's posts, newest first, twenty per page.

    The same item shape as the feed, so the screen paints them with the card
    it already has.
    """
    posts, next_cursor = await service.posts_of(user_id, current_user, cursor=cursor)
    return CursorPage(items=[FeedPostSummary.of(one) for one in posts], next_cursor=next_cursor)
