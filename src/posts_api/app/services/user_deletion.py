"""Closing an account here after users-api closed it."""

import uuid
from datetime import datetime

from posts_api.app.repositories.user_deletion import UserDeletionRepository


class UserDeletionService:
    def __init__(self, deletions: UserDeletionRepository) -> None:
        self._deletions = deletions

    async def apply(self, user_id: uuid.UUID, at: datetime) -> bool:
        """Close the account, returning False when it already was.

        Meant to run in one transaction. An event delivered twice finds the
        account closed and changes nothing, so the counters are not corrected a
        second time.
        """
        if not await self._deletions.close(user_id, at):
            return False
        await self._deletions.release_follows(user_id)
        await self._deletions.release_blocks(user_id)
        await self._deletions.release_likes(user_id)
        await self._deletions.release_retweets(user_id)
        return True
