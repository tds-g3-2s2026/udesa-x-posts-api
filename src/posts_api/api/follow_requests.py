from typing import Annotated

from fastapi import APIRouter, Depends

from posts_api.api.deps import CurrentUserDep, SessionDep
from posts_api.api.schemas.follow_requests import FollowRequestSummary
from posts_api.app.repositories.follow_requests import FollowRequestRepository
from posts_api.app.services.follow_requests import FollowRequestService

router = APIRouter(prefix="/follow-requests", tags=["follow-requests"])


def get_follow_request_service(session: SessionDep) -> FollowRequestService:
    return FollowRequestService(FollowRequestRepository(session))


ServiceDep = Annotated[FollowRequestService, Depends(get_follow_request_service)]


@router.get("")
async def list_pending(
    current_user: CurrentUserDep, service: ServiceDep
) -> list[FollowRequestSummary]:
    """The requests aimed at whoever is asking. There is no way to ask for another account's."""
    pending = await service.pending_for(current_user)
    return [FollowRequestSummary.of(one) for one in pending]
