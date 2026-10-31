"""The image files, in a private S3 bucket.

Reads never go through this service: `url_for` signs a temporary URL and the
client downloads straight from S3.
"""

from contextlib import AsyncExitStack
from typing import BinaryIO

import aioboto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from posts_api.app.repositories.image_storage import ImageStorage, ImageStorageError
from posts_api.config.settings import Settings


class S3ImageStorage(ImageStorage):
    def __init__(
        self, *, bucket: str, region: str, endpoint_url: str | None, url_expiry_seconds: int
    ) -> None:
        self._bucket = bucket
        self._region = region
        self._endpoint_url = endpoint_url
        self._url_expiry_seconds = url_expiry_seconds
        self._stack = AsyncExitStack()
        self._client = None

    async def start(self) -> None:
        """Open the client once, like the other connections of the lifespan."""
        self._client = await self._stack.enter_async_context(
            aioboto3.Session().client(
                "s3",
                region_name=self._region,
                endpoint_url=self._endpoint_url,
                config=Config(
                    # Signature V4 is what a presigned URL needs outside us-east-1.
                    signature_version="s3v4",
                    # A request waiting on a bucket is a user waiting on a post:
                    # fail in seconds instead of the SDK's default minute.
                    connect_timeout=3,
                    read_timeout=10,
                    retries={"max_attempts": 2, "mode": "standard"},
                    # Without this the SDK signs the URL for the global host
                    # (bucket.s3.amazonaws.com), which redirects for any bucket
                    # outside us-east-1 and breaks the signature on the way. A
                    # custom endpoint keeps the default addressing.
                    s3=None if self._endpoint_url else {"addressing_style": "virtual"},
                ),
            )
        )

    async def aclose(self) -> None:
        await self._stack.aclose()

    async def put(self, key: str, body: BinaryIO, *, content_type: str) -> None:
        try:
            # The file and not its bytes: the SDK reads it in chunks
            # of at most 1 MiB to sign it and to send it, so a 10 MB cover never
            # sits whole in memory. It has to be seekable, for the retries.
            await self._client.put_object(
                Bucket=self._bucket, Key=key, Body=body, ContentType=content_type
            )
        except (BotoCoreError, ClientError) as exc:
            raise ImageStorageError(f"Could not store {key}") from exc

    async def delete(self, key: str) -> None:
        try:
            await self._client.delete_object(Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise ImageStorageError(f"Could not delete {key}") from exc

    async def url_for(self, key: str) -> str:
        try:
            return await self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=self._url_expiry_seconds,
            )
        except (BotoCoreError, ClientError) as exc:
            raise ImageStorageError(f"Could not sign {key}") from exc


class UnconfiguredImageStorage(ImageStorage):
    """What the service uses while no bucket is configured."""

    async def start(self) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def put(self, key: str, body: BinaryIO, *, content_type: str) -> None:
        raise ImageStorageError("No S3 bucket is configured")

    async def delete(self, key: str) -> None:
        raise ImageStorageError("No S3 bucket is configured")

    async def url_for(self, key: str) -> str:
        raise ImageStorageError("No S3 bucket is configured")


def build_image_storage(settings: Settings) -> S3ImageStorage | UnconfiguredImageStorage:
    if not settings.s3_bucket:
        return UnconfiguredImageStorage()
    return S3ImageStorage(
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        endpoint_url=settings.s3_endpoint_url,
        url_expiry_seconds=settings.image_url_expiry_seconds,
    )
