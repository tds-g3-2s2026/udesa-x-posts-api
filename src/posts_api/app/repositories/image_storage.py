"""Where the image files live, without naming the service that keeps them."""

import logging
from abc import ABC, abstractmethod
from typing import BinaryIO

logger = logging.getLogger(__name__)


class ImageStorageError(Exception):
    """The storage could not do what it was asked, or is not configured."""


class ImageStorage(ABC):
    @abstractmethod
    async def put(self, key: str, body: BinaryIO, *, content_type: str) -> None:
        """Store the file under `key`, reading it from where it is without loading it whole."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove the file under `key`. Removing one that is not there is not an error."""

    @abstractmethod
    async def url_for(self, key: str) -> str:
        """A temporary URL that reads the file, without credentials."""


async def signed_url_or_none(storage: ImageStorage, key: str | None) -> str | None:
    """The URL of a profile photo or cover, or `None` when there is none or it cannot be signed.

    Unlike the images of a post, a failure here does not fail the page: `None`
    is what an account without a photo has, and the app draws the default avatar.
    """
    if key is None:
        return None
    try:
        return await storage.url_for(key)
    except ImageStorageError:
        logger.warning("Could not sign %s; it goes out as no image", key)
        return None
