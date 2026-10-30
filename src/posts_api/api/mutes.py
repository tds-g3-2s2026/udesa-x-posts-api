import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from posts_api.api.deps import CurrentUserDep, SessionDep
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.mutes import MuteRepository
from posts_api.app.services.mutes import MuteService

router = APIRouter(tags=["mutes"])


def get_mute_service(session: SessionDep) -> MuteService:
    return MuteService(MuteRepository(session), FollowRepository(session))


ServiceDep = Annotated[MuteService, Depends(get_mute_service)]


@router.post("/users/{user_id}/mute", status_code=status.HTTP_204_NO_CONTENT)
async def mute(user_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep) -> None:
    """Mute an account. Who is muting comes from the token, never from the body."""
    await service.mute(current_user, user_id)


@router.delete("/users/{user_id}/mute", status_code=status.HTTP_204_NO_CONTENT)
async def unmute(user_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep) -> None:
    await service.unmute(current_user, user_id)
