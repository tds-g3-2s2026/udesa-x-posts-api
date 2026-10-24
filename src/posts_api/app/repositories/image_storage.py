"""Where the image files live, without naming the service that keeps them."""

from abc import ABC, abstractmethod
from typing import BinaryIO


class ImageStorageError(Exception):
    """The storage could not do what it was asked, or is not configured."""


class ImageStorage(ABC):
    @abstractmethod
    async def put(self, key: str, body: BinaryIO, *, content_type: str) -> None:
        """Store the file under `key`."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove the file under `key`. Removing one that is not there is not an error."""

    @abstractmethod
    async def url_for(self, key: str) -> str:
        """A temporary URL that reads the file, without credentials."""
