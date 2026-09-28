"""Putting an account under review, without naming who does it."""

import uuid
from abc import ABC, abstractmethod


class AccountReview(ABC):
    """The account and its sessions belong to users-api, so this service can
    only ask for the review, not apply it. How the request travels is decided
    in ADR-011 and lives under `infrastructure/`."""

    @abstractmethod
    async def put_under_review(self, user_id: uuid.UUID) -> None:
        """Ask for the account to be put under review and its sessions revoked.

        Never raises: the report that triggered it is already stored, and the
        next report aimed at the same account asks again.
        """
