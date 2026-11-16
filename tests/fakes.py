"""Stand-ins for the services the tests cannot reach."""

from datetime import datetime
from typing import BinaryIO

from posts_api.app.models.trending import TrendingTopic
from posts_api.app.repositories.image_storage import ImageStorage, ImageStorageError
from posts_api.app.repositories.trending_cache import TrendingCache


class FakeImageStorage(ImageStorage):
    """An in-memory bucket, which signs URLs that point nowhere."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}
        # The upload number (counting from 1) that fails, if any.
        self.fail_on_put: int | None = None
        self.puts = 0
        self.fail_on_url = False
        self.fail_on_delete = False
        # Whether each file arrived as a temporary file already on disk, not as
        # bytes in memory. `_rolled` is private, but it is the only way to ask.
        self.from_disk: dict[str, bool] = {}

    async def put(self, key: str, body: BinaryIO, *, content_type: str) -> None:
        self.puts += 1
        if self.fail_on_put == self.puts:
            raise ImageStorageError("simulated failure")
        self.from_disk[key] = getattr(body, "_rolled", False)
        self.files[key] = body.read()
        self.content_types[key] = content_type

    async def delete(self, key: str) -> None:
        if self.fail_on_delete:
            raise ImageStorageError("simulated failure")
        self.files.pop(key, None)

    async def url_for(self, key: str) -> str:
        if self.fail_on_url:
            raise ImageStorageError("simulated failure")
        return f"https://bucket.test/{key}?signature=fake"


class FakeTrendingCache(TrendingCache):
    """A cache in memory, which records the TTL it was given. `expire` drops the entry."""

    def __init__(self) -> None:
        self.topics: list[TrendingTopic] | None = None
        self.ttl_seconds: int | None = None

    async def get(self) -> list[TrendingTopic] | None:
        return self.topics

    async def set(self, topics: list[TrendingTopic], ttl_seconds: int) -> None:
        self.topics = list(topics)
        self.ttl_seconds = ttl_seconds

    def expire(self) -> None:
        self.topics = None


class FakeTrendingRepository:
    """Answers with a fixed ranking and remembers how it was asked."""

    def __init__(self, topics: list[TrendingTopic]) -> None:
        self.topics = topics
        self.calls = 0
        self.since: datetime | None = None
        self.limit: int | None = None

    async def top(self, *, since: datetime, limit: int) -> list[TrendingTopic]:
        self.calls += 1
        self.since = since
        self.limit = limit
        return self.topics[:limit]
