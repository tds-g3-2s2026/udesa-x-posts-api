"""What a user's profile header looks like on the wire."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from posts_api.app.models.profile import Profile


class ProfileSummary(BaseModel):
    """The header of the profile screen, in one call.

    `display_name`, `bio` and `created_at` come from users-api and travel as
    null when it could not answer, so the screen still opens.
    """

    id: uuid.UUID
    handle: str | None
    display_name: str | None = Field(serialization_alias="displayName")
    bio: str | None
    # Signed URLs that expire in an hour, null for an account without one. A
    # null photo is drawn as the default avatar.
    avatar_url: str | None = Field(default=None, serialization_alias="avatarUrl")
    cover_url: str | None = Field(default=None, serialization_alias="coverUrl")
    created_at: datetime | None = Field(serialization_alias="createdAt")
    followers_count: int = Field(serialization_alias="followersCount")
    following_count: int = Field(serialization_alias="followingCount")
    # Whether the account is protected, not whether the caller may read it:
    # with `isFollowedByMe` the screen knows both.
    is_private: bool = Field(serialization_alias="isPrivate")
    is_followed_by_me: bool = Field(serialization_alias="isFollowedByMe")
    # Only the caller learns it: the muted account sees the same header as before.
    is_muted_by_me: bool = Field(serialization_alias="isMutedByMe")

    @classmethod
    def of(cls, profile: Profile) -> "ProfileSummary":
        details = profile.details
        return cls(
            id=profile.id,
            handle=profile.handle,
            display_name=details.display_name if details else None,
            bio=details.bio if details else None,
            created_at=details.created_at if details else None,
            followers_count=profile.followers_count,
            following_count=profile.following_count,
            is_private=profile.is_private,
            is_followed_by_me=profile.followed_by_viewer,
            is_muted_by_me=profile.muted_by_viewer,
            avatar_url=profile.avatar_url,
            cover_url=profile.cover_url,
        )
