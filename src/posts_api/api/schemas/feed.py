"""What one row of the feed looks like on the wire.

Also what `GET /posts/{id}` and `GET /posts/{id}/replies` answer with: the same
shape, since all of them are a post plus the little the screen needs about who
wrote it.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from posts_api.api.schemas.images import PostImageSummary
from posts_api.app.models.post import PostWithAuthor


class FeedPostSummary(BaseModel):
    id: uuid.UUID
    author_id: uuid.UUID = Field(serialization_alias="authorId")
    author_handle: str | None = Field(serialization_alias="authorHandle")
    # The display name does not live in posts-api: it needs a copy this service
    # does not have. Present and null, not missing, so the screen reads one shape.
    author_display_name: str | None = Field(default=None, serialization_alias="authorDisplayName")
    # The author's photo, signed like the images; null without one, and the
    # app draws the default avatar. On a retweet, the original author's.
    author_avatar_url: str | None = Field(default=None, serialization_alias="authorAvatarUrl")
    # The account that wrote it was closed. The handle, the name and the avatar
    # are then null and `authorId` stays, but opening it answers 404: the screen
    # shows "[Usuario eliminado]" and does not navigate to the profile.
    author_deleted: bool = Field(default=False, serialization_alias="authorDeleted")
    content: str | None
    deleted: bool
    created_at: datetime = Field(serialization_alias="createdAt")
    likes_count: int = Field(serialization_alias="likesCount")
    retweets_count: int = Field(serialization_alias="retweetsCount")
    replies_count: int = Field(serialization_alias="repliesCount")
    # The post this one answers, `null` for one that answers nothing.
    parent_id: uuid.UUID | None = Field(default=None, serialization_alias="parentId")
    liked_by_me: bool = Field(default=False, serialization_alias="likedByMe")

    retweeted_by_me: bool = Field(default=False, serialization_alias="retweetedByMe")
    retweeted_by: str | None = Field(default=None, serialization_alias="retweetedBy")
    entry_id: str = Field(serialization_alias="entryId")
    activity_at: datetime = Field(serialization_alias="activityAt")
    # Ordered by position; empty for a post with no images and for a deleted one.
    # A retweet carries the images of the post it shares.
    images: list[PostImageSummary] = []

    @classmethod
    def of(cls, post: PostWithAuthor) -> "FeedPostSummary":
        return cls(
            entry_id=(
                f"retweet:{post.retweeter_id}:{post.id}" if post.retweeter_id else f"post:{post.id}"
            ),
            activity_at=post.activity_at or post.created_at,
            retweeted_by=post.retweeted_by,
            retweeted_by_me=post.retweeted_by_me,
            id=post.id,
            author_id=post.author_id,
            author_handle=post.author_handle,
            author_avatar_url=post.author_avatar_url,
            author_deleted=post.author_deleted,
            content=post.content,
            deleted=post.deleted,
            created_at=post.created_at,
            likes_count=post.likes_count,
            retweets_count=post.retweets_count,
            replies_count=post.replies_count,
            parent_id=post.parent_id,
            liked_by_me=post.liked_by_me,
            images=[PostImageSummary.of(one) for one in post.images],
        )
