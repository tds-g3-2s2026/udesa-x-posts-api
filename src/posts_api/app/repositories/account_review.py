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


class ReviewReleaseUnavailableError(Exception):
    """users-api could not be reached to lift a review."""


class ReviewRelease(ABC):
    """Lifting the review of an account once the backoffice closed its case (ADR-020).

    Apart from `AccountReview` because it fails the other way around: a review
    that does not reach users-api waits for the next report, but a case must
    not close while its account stays blocked, so this one raises.
    """

    @abstractmethod
    async def lift_review(self, user_id: uuid.UUID) -> None:
        """Ask users-api to release the account from review.

        An account users-api no longer has counts as released. Raises
        `ReviewReleaseUnavailableError` when users-api cannot be reached.
        """
