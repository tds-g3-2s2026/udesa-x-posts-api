"""What a post looks like on the wire."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from posts_api.app.models.post import Post


class CreatePostRequest(BaseModel):
    content: str


class PostSummary(BaseModel):
    id: uuid.UUID
    author_id: uuid.UUID = Field(serialization_alias="authorId")
    content: str
    created_at: datetime = Field(serialization_alias="createdAt")
    likes_count: int = Field(serialization_alias="likesCount")
    retweets_count: int = Field(serialization_alias="retweetsCount")
    replies_count: int = Field(serialization_alias="repliesCount")

    @classmethod
    def of(cls, post: Post) -> "PostSummary":
        return cls(
            id=post.id,
            author_id=post.author_id,
            content=post.content,
            created_at=post.created_at,
            likes_count=post.likes_count,
            retweets_count=post.retweets_count,
            replies_count=post.replies_count,
        )
