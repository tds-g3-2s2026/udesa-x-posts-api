"""What an image of a post looks like on the wire."""

import uuid

from pydantic import BaseModel

from posts_api.app.models.post import PostImage


class PostImageSummary(BaseModel):
    id: uuid.UUID
    # Signed and temporary: it reads the file straight from the storage.
    url: str
    position: int

    @classmethod
    def of(cls, image: PostImage) -> "PostImageSummary":
        return cls(id=image.id, url=image.url, position=image.position)
