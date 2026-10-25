"""The rules of the requests that a protected account receives."""

import uuid
from datetime import UTC, datetime

from posts_api.app import events
from posts_api.app.errors import ProblemError
from posts_api.app.models.follow import Account, FollowRequestStatus, PendingFollowRequest
from posts_api.app.pagination import DEFAULT_PAGE_SIZE, Cursor
from posts_api.app.repositories.follow_requests import FollowRequestRepository
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.outbox import OutboxRepository


class FollowRequestService:
    def __init__(
        self,
        requests: FollowRequestRepository,
        follows: FollowRepository,
        outbox: OutboxRepository,
    ) -> None:
        self._requests = requests
        self._follows = follows
        self._outbox = outbox

    async def pending_for(
        self, owner: Account, *, cursor: str | None = None
    ) -> tuple[list[PendingFollowRequest], str | None]:
        """The requests aimed at whoever is asking, never anyone else's, one page at a time.

        The owner comes from the token and not from the URL, so there is no
        identifier a caller could change to read somebody else's list.

        Reading the list also puts the caller on the graph. It is not a detail:
        a profile is only created by a request that succeeds, because a failed
        one rolls its transaction back, and the only other place that creates
        one is following somebody. An account nobody has on the graph answers
        `404` when somebody tries to follow it, so without this nobody could
        ever be followed for the first time.
        """
        await self._follows.ensure_profile(owner)
        decoded = Cursor.decode(cursor) if cursor is not None else None
        return await self._requests.pending_for(owner.id, cursor=decoded, limit=DEFAULT_PAGE_SIZE)

    async def approve(self, owner: Account, request_id: uuid.UUID) -> None:
        """Answer yes: the relationship is established and the counters move.

        The writes and the event share the session of the request, so they are
        one transaction. A failure halfway cannot leave a request marked as
        approved with nobody following, which is the kind of lie nothing would
        detect afterwards, nor announce a follow that never happened.
        """
        request = await self._required(owner, request_id)
        await self._requests.resolve(request_id, FollowRequestStatus.APPROVED)
        await self._follows.add_follow(request.requester_id, owner.id)
        await self._follows.move_counters(request.requester_id, owner.id, by=1)
        # The same event as a direct follow: for whoever is followed, a request
        # they approved is a new follower like any other.
        requester = await self._follows.find_profile(request.requester_id)
        await self._outbox.add(
            events.follow_created(
                request.requester_id,
                owner.id,
                follower_handle=requester.handle if requester is not None else None,
                now=datetime.now(UTC),
            )
        )

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
