"""Another user's profile, as the profile screen reads it (E2-H14)."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from posts_api.app.models.follow import ProfileVisibility


@dataclass(frozen=True)
class AccountDetails:
    """What users-api keeps about an account and this service does not copy.

    The name and the biography change whenever their owner edits them, so a
    local copy would go stale between one request of theirs and the next.
    They are asked for when somebody opens the profile.
    """

    handle: str
    profile_visibility: ProfileVisibility
    display_name: str | None
    bio: str | None
    created_at: datetime


@dataclass(frozen=True)
class Profile:
    """The header of a profile: the local graph plus the details from users-api.

    `details` is None when users-api could not answer. The handle, the
    counters and the follow state are this service's own, so the screen still
    gets them and shows the rest empty.
    """

    id: uuid.UUID
    handle: str | None
    is_private: bool
    followers_count: int
    following_count: int
    followed_by_viewer: bool
    details: AccountDetails | None
