"""What one row of the feed looks like on the wire.

Also what `GET /posts/{id}` answers with: the same shape, since both are a
post plus the little the screen needs about who wrote it.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from posts_api.app.models.post import PostWithAuthor


class FeedPostSummary(BaseModel):
    id: uuid.UUID
    author_id: uuid.UUID = Field(serialization_alias="authorId")
    author_handle: str | None = Field(serialization_alias="authorHandle")
    # Neither lives in posts-api yet: the display name needs a copy this
    # service does not have, and the avatar is not built. Present and null,
    # not missing, so the screen can read the final shape today.
    author_display_name: str | None = Field(default=None, serialization_alias="authorDisplayName")
    author_avatar_url: str | None = Field(default=None, serialization_alias="authorAvatarUrl")
    content: str
    created_at: datetime = Field(serialization_alias="createdAt")
    likes_count: int = Field(serialization_alias="likesCount")
    retweets_count: int = Field(serialization_alias="retweetsCount")
    replies_count: int = Field(serialization_alias="repliesCount")

    @classmethod
    def of(cls, post: PostWithAuthor) -> "FeedPostSummary":
        return cls(
            id=post.id,
            author_id=post.author_id,
            author_handle=post.author_handle,
            content=post.content,
            created_at=post.created_at,
            likes_count=post.likes_count,
            retweets_count=post.retweets_count,
            replies_count=post.replies_count,
        )
