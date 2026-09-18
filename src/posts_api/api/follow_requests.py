import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from posts_api.api.deps import CurrentUserDep, SessionDep
from posts_api.api.schemas.follow_requests import FollowRequestSummary
from posts_api.app.repositories.follow_requests import FollowRequestRepository
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.services.follow_requests import FollowRequestService

router = APIRouter(prefix="/follow-requests", tags=["follow-requests"])


def get_follow_request_service(session: SessionDep) -> FollowRequestService:
    # Both repositories share the session of the request, so approving writes
    # the answer, the relationship and the counters in one transaction.
    return FollowRequestService(FollowRequestRepository(session), FollowRepository(session))


ServiceDep = Annotated[FollowRequestService, Depends(get_follow_request_service)]


@router.get("")
async def list_pending(
    current_user: CurrentUserDep, service: ServiceDep
) -> list[FollowRequestSummary]:
    """The requests aimed at whoever is asking. There is no way to ask for another account's."""
    pending = await service.pending_for(current_user)
    return [FollowRequestSummary.of(one) for one in pending]


@router.post("/{request_id}/approve", status_code=status.HTTP_204_NO_CONTENT)
async def approve(request_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep) -> None:
    """Accept a request. Only the account it was aimed at can answer it."""
    await service.approve(current_user, request_id)


@router.post("/{request_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
async def reject(request_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep) -> None:
    await service.reject(current_user, request_id)
