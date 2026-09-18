"""The rules of the requests that a protected account receives."""

from posts_api.app.models.follow import Account, PendingFollowRequest
from posts_api.app.repositories.follow_requests import FollowRequestRepository


class FollowRequestService:
    def __init__(self, requests: FollowRequestRepository) -> None:
        self._requests = requests

    async def pending_for(self, owner: Account) -> list[PendingFollowRequest]:
        """The requests aimed at whoever is asking, never anyone else's.

        The owner comes from the token and not from the URL, so there is no
        identifier a caller could change to read somebody else's list.
        """
        return await self._requests.pending_for(owner.id)
