"""The S3 client against a local server that answers like a bucket would.

No bucket exists to test against, so this checks what can be checked without
one: the requests the client really sends, and the URLs it signs.
"""

import io
from urllib.parse import parse_qs, urlparse

import pytest
from aiohttp import web

from posts_api.app.repositories.image_storage import ImageStorageError
from posts_api.config.settings import Settings
from posts_api.infrastructure.s3.image_storage import (
    S3ImageStorage,
    UnconfiguredImageStorage,
    build_image_storage,
)


@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")


@pytest.fixture
async def bucket():
    """A server that keeps what it is sent, addressed path-style like any custom endpoint."""
    stored: dict[str, tuple[bytes, str]] = {}

    async def put(request: web.Request) -> web.Response:
        stored[request.match_info["key"]] = (
            await request.read(),
            request.headers.get("Content-Type", ""),
        )
        return web.Response(status=200)

    async def delete(request: web.Request) -> web.Response:
        stored.pop(request.match_info["key"], None)
        return web.Response(status=204)

    async def refuse(request: web.Request) -> web.Response:
        return web.Response(status=403, text="<Error><Code>AccessDenied</Code></Error>")

    app = web.Application()
    app.router.add_put("/images/{key:.+}", put)
    app.router.add_delete("/images/{key:.+}", delete)
    app.router.add_put("/locked/{key:.+}", refuse)
    app.router.add_delete("/locked/{key:.+}", refuse)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    yield stored, f"http://127.0.0.1:{port}"
    await runner.cleanup()


async def storage_for(endpoint: str, bucket: str = "images", expiry: int = 3600) -> S3ImageStorage:
    storage = S3ImageStorage(
        bucket=bucket, region="us-east-1", endpoint_url=endpoint, url_expiry_seconds=expiry
    )
    await storage.start()
    return storage


async def test_put_sends_the_bytes_and_the_content_type(bucket):
    stored, endpoint = bucket
    storage = await storage_for(endpoint)

    await storage.put("posts/1/a.png", io.BytesIO(b"png-bytes"), content_type="image/png")

    assert stored["posts/1/a.png"] == (b"png-bytes", "image/png")
    await storage.aclose()


async def test_delete_removes_the_file(bucket):
    stored, endpoint = bucket
    storage = await storage_for(endpoint)
    await storage.put("posts/1/a.png", io.BytesIO(b"x"), content_type="image/png")

    await storage.delete("posts/1/a.png")

    assert stored == {}
    await storage.aclose()


async def test_a_refusal_from_the_bucket_becomes_a_storage_error(bucket):
    _, endpoint = bucket
    storage = await storage_for(endpoint, bucket="locked")

    with pytest.raises(ImageStorageError):
        await storage.put("posts/1/a.png", io.BytesIO(b"x"), content_type="image/png")
    with pytest.raises(ImageStorageError):
        await storage.delete("posts/1/a.png")
    await storage.aclose()


async def test_an_unreachable_bucket_becomes_a_storage_error():
    storage = await storage_for("http://127.0.0.1:9")

    with pytest.raises(ImageStorageError):
        await storage.put("posts/1/a.png", io.BytesIO(b"x"), content_type="image/png")
    await storage.aclose()


async def test_the_signed_url_reads_that_key_and_expires_when_configured():
    storage = await storage_for("https://s3.us-east-1.amazonaws.com", bucket="udesa-x", expiry=900)

    url = await storage.url_for("posts/1/a.png")

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.path.endswith("/posts/1/a.png")
    assert "udesa-x" in url
    assert query["X-Amz-Expires"] == ["900"]
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    await storage.aclose()


async def test_the_signed_url_points_at_the_regional_host_of_the_bucket():
    """The global host redirects for a bucket outside us-east-1 and breaks the signature."""
    storage = S3ImageStorage(
        bucket="udesa-x", region="us-east-2", endpoint_url=None, url_expiry_seconds=60
    )
    await storage.start()

    url = await storage.url_for("posts/1/a.png")

    assert urlparse(url).hostname == "udesa-x.s3.us-east-2.amazonaws.com"
    await storage.aclose()


async def test_signing_without_credentials_is_a_storage_error(monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID")
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY")
    # Keeps the SDK from finding credentials in the machine running the test.
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/nonexistent")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    storage = await storage_for("https://s3.us-east-1.amazonaws.com")

    with pytest.raises(ImageStorageError):
        await storage.url_for("posts/1/a.png")
    await storage.aclose()


def settings_with(**overrides) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://x",
        redis_url="redis://x",
        auth_redis_url="redis://x",
        jwt_public_key="x",
        internal_api_token="x",
        _env_file=None,
        **overrides,
    )


def test_a_configured_bucket_builds_the_s3_storage():
    built = build_image_storage(settings_with(s3_bucket="udesa-x", image_url_expiry_seconds=60))

    assert isinstance(built, S3ImageStorage)


async def test_with_no_bucket_the_storage_refuses_every_operation():
    built = build_image_storage(settings_with())
    assert isinstance(built, UnconfiguredImageStorage)

    await built.start()
    with pytest.raises(ImageStorageError):
        await built.put("k", io.BytesIO(b""), content_type="image/png")
    with pytest.raises(ImageStorageError):
        await built.delete("k")
    with pytest.raises(ImageStorageError):
        await built.url_for("k")
    await built.aclose()
