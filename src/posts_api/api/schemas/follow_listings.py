"""What one row of the followers or following screens looks like on the wire."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from posts_api.app.models.follow import FollowListItem, UserProfile


class FollowListItemSummary(BaseModel):
    """One row. `id` travels even though nothing in the copy asks for it,
    because the follow button on the row needs it to know who to follow."""

    id: uuid.UUID
    handle: str | None
    # Neither field is resolved yet: both live in another service, and
    # nothing copies them here. Always null for now, present so the screen
    # can already read the final shape and swap the placeholder in later.
    display_name: str | None = Field(default=None, serialization_alias="displayName")
    avatar_url: str | None = Field(default=None, serialization_alias="avatarUrl")
    # Whether whoever is asking already follows this account, not whether this
    # account follows them: that is what lets the row's button read "Seguir"
    # or "Siguiendo" without a second call.
    following: bool
    created_at: datetime = Field(serialization_alias="createdAt")

    @classmethod
    def of(cls, item: FollowListItem) -> "FollowListItemSummary":
        return cls(
            id=item.id,
            handle=item.handle,
            following=item.followed_by_viewer,
            created_at=item.created_at,
        )


class SuggestedAccountSummary(BaseModel):
    """One row of the "who to follow" empty state."""

    id: uuid.UUID
    handle: str | None
    display_name: str | None = Field(default=None, serialization_alias="displayName")
    avatar_url: str | None = Field(default=None, serialization_alias="avatarUrl")
    followers_count: int = Field(serialization_alias="followersCount")

    @classmethod
    def of(cls, profile: UserProfile) -> "SuggestedAccountSummary":
        return cls(id=profile.id, handle=profile.handle, followers_count=profile.followers_count)
