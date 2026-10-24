"""Stand-ins for the services the tests cannot reach."""

from typing import BinaryIO

from posts_api.app.repositories.image_storage import ImageStorage, ImageStorageError


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

    async def put(self, key: str, body: BinaryIO, *, content_type: str) -> None:
        self.puts += 1
        if self.fail_on_put == self.puts:
            raise ImageStorageError("simulated failure")
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
