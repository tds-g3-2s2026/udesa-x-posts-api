"""What the social graph is, in plain Python.

No SQLAlchemy here on purpose. These classes carry the rules that answer
questions about following someone, and those rules do not change if the data
moves to another engine. The tables that store them live in
`infrastructure/database/models.py`.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ProfileVisibility(StrEnum):
    """Public accounts are followed right away, protected ones need approval."""

    PUBLIC = "public"
    PROTECTED = "protected"


class FollowRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True)
class Account:
    """Who is behind a request, as the token describes them.

    Not the same as `UserProfile`: that one is what this service stores about a
    user, and this one is what arrives signed on every call. The handle can be
    missing, because a token issued before users-api started sending it is still
    valid until it expires.
    """

    id: uuid.UUID
    handle: str | None = None


@dataclass
class UserProfile:
    """What this service knows about a user: a local copy, not the source of truth.

    users-api owns the account. posts-api keeps only the few fields the graph
    needs, so following someone does not require calling another service on
    every request.
    """

    id: uuid.UUID
    handle: str | None = None
    visibility: ProfileVisibility = ProfileVisibility.PUBLIC
    followers_count: int = 0
    following_count: int = 0

    @property
    def needs_approval(self) -> bool:
        """A protected account turns a follow into a pending request."""
        return self.visibility is ProfileVisibility.PROTECTED


@dataclass
class Follow:
    """An established relationship: the follower follows the followee."""

    follower_id: uuid.UUID
    followee_id: uuid.UUID
    created_at: datetime | None = None


@dataclass
class FollowRequest:
    """A pending ask to follow a protected account."""

    requester_id: uuid.UUID
    target_id: uuid.UUID
    id: uuid.UUID | None = None
    status: FollowRequestStatus = FollowRequestStatus.PENDING
    created_at: datetime | None = None

    @property
    def is_pending(self) -> bool:
        """Only a pending request can be approved or rejected."""
        return self.status is FollowRequestStatus.PENDING
