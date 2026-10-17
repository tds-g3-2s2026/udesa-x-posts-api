"""Another user's profile (E2-H14).

Under `/users`, like the followers and following lists the profile opens.
Included after `follows.py` in `main.py`, so `/users/suggested` is matched
before `/users/{user_id}` gets the chance to read "suggested" as an id.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from posts_api.api.deps import CurrentUserDep, SessionDep, UsersApiDep
from posts_api.api.schemas.profiles import ProfileSummary
from posts_api.app.repositories.blocks import BlockRepository
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.user_directory import UserDirectory
from posts_api.app.services.profiles import ProfileService
from posts_api.infrastructure.users_api.user_directory import HttpUserDirectory

router = APIRouter(prefix="/users", tags=["profiles"])


def get_user_directory(users_api: UsersApiDep) -> UserDirectory:
    return HttpUserDirectory(users_api)


def get_profile_service(
    session: SessionDep, directory: Annotated[UserDirectory, Depends(get_user_directory)]
) -> ProfileService:
    return ProfileService(FollowRepository(session), BlockRepository(session), directory)


ServiceDep = Annotated[ProfileService, Depends(get_profile_service)]


@router.get("/{user_id}")
async def profile(
    user_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep
) -> ProfileSummary:
    """The header of a profile: name, biography, registration date and counters."""
    return ProfileSummary.of(await service.profile_of(user_id, current_user))
