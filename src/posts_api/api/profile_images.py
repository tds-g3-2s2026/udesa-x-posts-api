"""The profile photo and the cover of whoever is signed in.

Under `/users/me`: the gateway sends `/api/users` here, and `/api/me` belongs
to users-api. Nothing under `/users/{user_id}` takes these methods and paths,
so the order in `main.py` does not matter for them.

Each route commits by hand before deleting the file it replaced: deleting it
first would leave the profile pointing at nothing if the commit then failed.
"""

from fastapi import APIRouter, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.api.deps import CurrentUserDep, ProfileImagesDep, SessionDep
from posts_api.api.multipart import read_profile_image
from posts_api.api.schemas.profile_images import AvatarSummary, CoverSummary
from posts_api.app.image_rules import AVATAR, COVER, ProfileImageKind
from posts_api.app.models.follow import Account
from posts_api.app.services.profile_images import ProfileImages

router = APIRouter(prefix="/users/me", tags=["profiles"])


async def _replace(
    request: Request,
    kind: ProfileImageKind,
    owner: Account,
    images: ProfileImages,
    session: AsyncSession,
) -> str:
    image = await read_profile_image(request, kind)
    try:
        change = await images.replace(owner, kind, image)
    finally:
        image.close()
    await session.commit()
    await images.discard(change.previous_key)
    return change.url


async def _remove(
    kind: ProfileImageKind, owner: Account, images: ProfileImages, session: AsyncSession
) -> Response:
    previous = await images.remove(owner, kind)
    await session.commit()
    await images.discard(previous)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/avatar")
async def replace_avatar(
    request: Request, current_user: CurrentUserDep, images: ProfileImagesDep, session: SessionDep
) -> AvatarSummary:
    """Upload or replace the profile photo: one JPG or PNG `image` part, up to 5 MB."""
    return AvatarSummary(avatar_url=await _replace(request, AVATAR, current_user, images, session))


@router.delete("/avatar", status_code=status.HTTP_204_NO_CONTENT)
async def remove_avatar(
    current_user: CurrentUserDep, images: ProfileImagesDep, session: SessionDep
) -> Response:
    """Go back to the default avatar. Answers the same when there was no photo."""
    return await _remove(AVATAR, current_user, images, session)


@router.put("/cover")
async def replace_cover(
    request: Request, current_user: CurrentUserDep, images: ProfileImagesDep, session: SessionDep
) -> CoverSummary:
    """Upload or replace the cover: one JPG or PNG `image` part, up to 10 MB."""
    return CoverSummary(cover_url=await _replace(request, COVER, current_user, images, session))


@router.delete("/cover", status_code=status.HTTP_204_NO_CONTENT)
async def remove_cover(
    current_user: CurrentUserDep, images: ProfileImagesDep, session: SessionDep
) -> Response:
    """Go back to no cover. Answers the same when there was none."""
    return await _remove(COVER, current_user, images, session)
