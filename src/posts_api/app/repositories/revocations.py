"""Asking whether a session was closed, without naming who closed it."""

import uuid
from abc import ABC, abstractmethod


class RevocationStore(ABC):
    """The revocation marks that users-api writes. posts-api only reads them."""

    @abstractmethod
    async def is_revoked(self, jti: str, user_id: uuid.UUID, issued_at: float) -> bool:
        """Whether the token with that `jti`, issued at that instant, was revoked.

        It is revoked if its own session was closed, or if every session of the
        account was closed at or after the moment the token was issued.
        """
