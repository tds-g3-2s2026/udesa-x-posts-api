import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from posts_api.app.models.follow import ProfileVisibility
from posts_api.app.repositories.user_directory import UserDirectoryUnavailableError
from posts_api.infrastructure.users_api.user_directory import HttpUserDirectory, is_missing_account


def profile_response(**overrides):
    body = {
        "handle": "@student",
        "profile_visibility": "public",
        "display_name": None,
        "bio": None,
        "created_at": "2026-10-25T12:00:00+00:00",
    }
    body.update(overrides)
    return body


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        profile_response(handle=None),
        profile_response(handle=42),
        profile_response(profile_visibility=None),
        profile_response(profile_visibility=42),
        profile_response(display_name=[]),
        profile_response(bio=42),
        profile_response(created_at=None),
        profile_response(created_at=42),
    ],
)
async def test_e2_h10_ca6_malformed_identity_profiles_are_unavailable(body):
    def respond(request):
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(
        base_url="http://users-api", transport=httpx.MockTransport(respond)
    ) as client:
        directory = HttpUserDirectory(client)
        with (
            patch(
                "posts_api.infrastructure.users_api.user_directory.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            pytest.raises(UserDirectoryUnavailableError),
        ):
            await directory.details_of(uuid.uuid4())


async def test_e2_h10_ca6_valid_identity_profile_keeps_account_fields():
    def respond(request):
        return httpx.Response(200, json=profile_response(profile_visibility="protected"))

    async with httpx.AsyncClient(
        base_url="http://users-api", transport=httpx.MockTransport(respond)
    ) as client:
        details = await HttpUserDirectory(client).details_of(uuid.uuid4())

    assert details is not None
    assert details.handle == "@student"
    assert details.profile_visibility is ProfileVisibility.PROTECTED


@pytest.mark.parametrize("body", [None, [], {"type": None}, {"type": 42}, {"type": []}])
def test_e2_h10_ca6_malformed_not_found_body_is_not_an_account_miss(body):
    response = httpx.Response(404, json=body)

    assert is_missing_account(response) is False


def test_e2_h10_ca6_account_not_found_problem_is_an_account_miss():
    response = httpx.Response(404, json={"type": "https://udesa-x.dev/errors/account-not-found"})

    assert is_missing_account(response) is True
