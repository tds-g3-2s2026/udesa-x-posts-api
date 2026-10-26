import uuid

import httpx
import pytest

from posts_api.app.repositories.administrator_directory import (
    AdministratorDirectoryUnavailableError,
)
from posts_api.infrastructure.users_api.administrator_directory import HttpAdministratorDirectory


@pytest.mark.parametrize("email", ["admin@udesa.edu.ar", "josé@udesa.edu.ar"])
async def test_identity_request_retries_then_returns_the_actor_email(email):
    actor = uuid.uuid4()
    requests = []

    def answer(request):
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, json={"id": str(actor), "email": email})

    async with httpx.AsyncClient(
        base_url="http://users-api",
        headers={"X-Internal-Token": "test"},
        transport=httpx.MockTransport(answer),
    ) as client:
        assert await HttpAdministratorDirectory(client).email_of(actor) == email
    assert len(requests) == 2
    assert all(r.url.path == f"/internal/administrators/{actor}/identity" for r in requests)
    assert all(r.headers["X-Internal-Token"] == "test" for r in requests)


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b"null",
        b'{"id": 42}',
        b'{"id":"00000000-0000-0000-0000-000000000000","email":"a@b"}',
    ],
)
async def test_malformed_identity_cannot_be_used_for_audit(body):
    async with httpx.AsyncClient(
        base_url="http://users-api",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body)),
    ) as client:
        with pytest.raises(AdministratorDirectoryUnavailableError):
            await HttpAdministratorDirectory(client).email_of(uuid.uuid4())
