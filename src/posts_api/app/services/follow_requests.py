"""The rules of the requests that a protected account receives."""

import uuid

from posts_api.app.errors import ProblemError
from posts_api.app.models.follow import Account, FollowRequestStatus, PendingFollowRequest
from posts_api.app.repositories.follow_requests import FollowRequestRepository
from posts_api.app.repositories.follows import FollowRepository


class FollowRequestService:
    def __init__(self, requests: FollowRequestRepository, follows: FollowRepository) -> None:
        self._requests = requests
        self._follows = follows

    async def pending_for(self, owner: Account) -> list[PendingFollowRequest]:
        """The requests aimed at whoever is asking, never anyone else's.

        The owner comes from the token and not from the URL, so there is no
        identifier a caller could change to read somebody else's list.
        """
        return await self._requests.pending_for(owner.id)

    async def approve(self, owner: Account, request_id: uuid.UUID) -> None:
        """Answer yes: the relationship is established and the counters move.

        The three writes share the session of the request, so they are one
        transaction. A failure halfway cannot leave a request marked as approved
        with nobody following, which is the kind of lie nothing would detect
        afterwards.
        """
        request = await self._required(owner, request_id)
        await self._requests.resolve(request_id, FollowRequestStatus.APPROVED)
        await self._follows.add_follow(request.requester_id, owner.id)
        await self._follows.move_counters(request.requester_id, owner.id, by=1)

    async def reject(self, owner: Account, request_id: uuid.UUID) -> None:
        """Answer no: the request is closed and nothing else changes."""
        await self._required(owner, request_id)
        await self._requests.resolve(request_id, FollowRequestStatus.REJECTED)

    async def _required(self, owner: Account, request_id: uuid.UUID):
        """The open request, if it is this account's to answer.

        A request that does not exist, that was aimed at somebody else, or that
        was already answered, all come back the same way: `404`. A `403` would
        confirm that the request exists, and that is already something a
        stranger should not learn.
        """
        request = await self._requests.find_pending_by_id(request_id, target_id=owner.id)
        if request is None:
            raise ProblemError(
                status=404,
                code="follow-request-not-found",
                title="No se pudo responder la solicitud",
                detail="La solicitud no existe o ya fue respondida",
            )
        return request
