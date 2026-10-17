"""Reading the details users-api keeps about an account, without naming how."""

import uuid
from abc import ABC, abstractmethod

from posts_api.app.models.profile import AccountDetails


class UserDirectoryUnavailableError(Exception):
    """users-api did not answer in time, or answered with an error."""


class UserDirectory(ABC):
    """The account belongs to users-api. How the request travels lives under
    `infrastructure/`, the same as `AccountReview`."""

    @abstractmethod
    async def details_of(self, user_id: uuid.UUID) -> AccountDetails | None:
        """The account's details, or None if users-api says it does not exist.

        Raises `UserDirectoryUnavailableError` when users-api cannot answer, so the
        caller decides what a missing answer means for its own response.
        """
