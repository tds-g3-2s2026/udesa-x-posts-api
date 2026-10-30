"""Another user's profile header (E2-H14).

users-api is answered at the HTTP level and not swapped for a fake service, so
the client that reads it is the one that runs in production.
"""

import uuid
from datetime import UTC, datetime

import httpx
import pytest

from posts_api.api.deps import get_users_api
from posts_api.infrastructure.users_api.account_review import build_users_api_client
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, handle_of, signed_in_as

pytestmark = requires_services

INTERNAL_TOKEN = "test-internal-token"


class FakeUsersApi:
    """Answers the internal profile route the way users-api does."""

    def __init__(self) -> None:
        self.accounts: dict[uuid.UUID, dict] = {}
        self.tokens: list[str | None] = []
        self.down = False
        self.without_the_route = False
        self.behind_a_proxy = False
        self.malformed_profile = False

    def has(self, user_id: uuid.UUID, *, display_name=None, bio=None, visibility="public") -> None:
        self.accounts[user_id] = {
            "id": str(user_id),
            "handle": handle_of(user_id),
            "profile_visibility": visibility,
            "display_name": display_name,
            "bio": bio,
            "created_at": "2026-09-01T12:00:00Z",
        }

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.tokens.append(request.headers.get("X-Internal-Token"))
        if self.down:
            return httpx.Response(503)
        if self.without_the_route:
            # What FastAPI answers for a path it does not know.
            return httpx.Response(404, json={"detail": "Not Found"})
        if self.behind_a_proxy:
            # A 404 written by something in front of users-api, not as JSON.
            return httpx.Response(404, text="<html>Not Found</html>")
        user_id = uuid.UUID(request.url.path.split("/")[3])
        if user_id not in self.accounts:
            return httpx.Response(
                404, json={"type": "https://udesa-x.dev/errors/account-not-found", "status": 404}
            )
        if self.malformed_profile:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=self.accounts[user_id])


@pytest.fixture
async def users_api():
    fake = FakeUsersApi()
    client = build_users_api_client(
        "http://users-api", INTERNAL_TOKEN, transport=httpx.MockTransport(fake.answer)
    )
    app.dependency_overrides[get_users_api] = lambda: client
    yield fake
    app.dependency_overrides.pop(get_users_api)
    await client.aclose()


async def test_e2_h14_ca1_the_profile_carries_what_the_screen_needs(api, users_api):
    viewer, owner = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(owner)
    users_api.has(owner, display_name="Ana Pérez", bio="Estudio en la UdeSA")
    await api.post(f"/users/{owner}/follow", headers=signed_in_as(viewer))

    response = await api.get(f"/users/{owner}", headers=signed_in_as(viewer))

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(owner)
    assert body["handle"] == handle_of(owner)
    assert body["displayName"] == "Ana Pérez"
    assert body["bio"] == "Estudio en la UdeSA"
    assert datetime.fromisoformat(body["createdAt"]) == datetime(2026, 9, 1, 12, tzinfo=UTC)
    assert body["followersCount"] == 1
    assert body["followingCount"] == 0
    assert body["isPrivate"] is False
    assert body["isFollowedByMe"] is True
    # E1-H8 is not built: the screen falls back to the default avatar.
    assert body["avatarUrl"] is None


async def test_e2_h14_ca3_a_protected_account_shows_its_header_and_says_it_is_private(
    api, users_api
):
    viewer, owner = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(owner, visibility="protected")
    users_api.has(owner, display_name="Cuenta protegida")

    response = await api.get(f"/users/{owner}", headers=signed_in_as(viewer))

    assert response.status_code == 200
    body = response.json()
    assert body["displayName"] == "Cuenta protegida"
    assert body["isPrivate"] is True
    assert body["isFollowedByMe"] is False


async def test_e2_h14_ca3_a_blocker_is_404(api, users_api):
    viewer, owner = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(viewer)
    users_api.has(owner)
    await api.post(f"/users/{viewer}/block", headers=signed_in_as(owner))

    response = await api.get(f"/users/{owner}", headers=signed_in_as(viewer))

    assert response.status_code == 404
    assert response.json()["type"].endswith("/user-not-found")


async def test_an_account_the_viewer_blocked_is_404_too(api, users_api):
    viewer, owner = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(owner)
    users_api.has(owner)
    await api.post(f"/users/{owner}/block", headers=signed_in_as(viewer))

    response = await api.get(f"/users/{owner}", headers=signed_in_as(viewer))

    assert response.status_code == 404
    assert response.json()["type"].endswith("/user-not-found")


async def test_an_unknown_account_is_checked_in_users_api(api, users_api):
    response = await api.get(f"/users/{uuid.uuid4()}", headers=signed_in_as(uuid.uuid4()))

    assert response.status_code == 404
    assert users_api.tokens == [INTERNAL_TOKEN]


async def test_an_account_users_api_no_longer_has_is_404(api, users_api):
    owner = uuid.uuid4()
    await given_a_profile(owner)

    response = await api.get(f"/users/{owner}", headers=signed_in_as(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["type"].endswith("/user-not-found")


async def test_the_profile_still_opens_when_users_api_does_not_answer(api, users_api):
    owner = uuid.uuid4()
    await given_a_profile(owner)
    users_api.down = True

    response = await api.get(f"/users/{owner}", headers=signed_in_as(uuid.uuid4()))

    assert response.status_code == 200
    body = response.json()
    assert body["handle"] == handle_of(owner)
    assert body["displayName"] is None
    assert body["bio"] is None
    assert body["createdAt"] is None
    # Asked twice: one retry, as every synchronous call between services.
    assert len(users_api.tokens) == 2


async def test_a_users_api_without_the_route_does_not_hide_the_profile(api, users_api):
    owner = uuid.uuid4()
    await given_a_profile(owner)
    users_api.without_the_route = True

    response = await api.get(f"/users/{owner}", headers=signed_in_as(uuid.uuid4()))

    assert response.status_code == 200
    assert response.json()["displayName"] is None


async def test_a_404_that_is_not_json_does_not_hide_the_profile(api, users_api):
    owner = uuid.uuid4()
    await given_a_profile(owner)
    users_api.behind_a_proxy = True

    response = await api.get(f"/users/{owner}", headers=signed_in_as(uuid.uuid4()))

    assert response.status_code == 200
    assert response.json()["displayName"] is None


async def test_users_api_is_asked_with_the_internal_token(api, users_api):
    owner = uuid.uuid4()
    await given_a_profile(owner)
    users_api.has(owner)

    await api.get(f"/users/{owner}", headers=signed_in_as(uuid.uuid4()))

    assert users_api.tokens == [INTERNAL_TOKEN]


async def test_suggested_accounts_are_not_read_as_a_profile(api, users_api):
    response = await api.get("/users/suggested", headers=signed_in_as(uuid.uuid4()))

    assert response.status_code == 200


@pytest.mark.parametrize("visibility", ["public", "protected"])
async def test_e2_h10_ca6_opens_a_new_account_from_both_profile_endpoints(
    api, users_api, visibility
):
    import asyncio

    viewer, owner = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(viewer)
    users_api.has(owner, visibility=visibility)
    header, posts = await asyncio.gather(
        api.get(f"/users/{owner}", headers=signed_in_as(viewer)),
        api.get(f"/users/{owner}/posts", headers=signed_in_as(viewer)),
    )
    assert header.status_code == 200
    assert header.json()["handle"] == handle_of(owner)
    assert header.json()["followersCount"] == 0
    assert header.json()["isPrivate"] == (visibility == "protected")
    assert posts.status_code == (403 if visibility == "protected" else 200)
    if visibility == "public":
        assert posts.json()["items"] == []


async def test_e2_h10_ca6_missing_profile_dependency_failure_is_503(api, users_api):
    users_api.down = True
    response = await api.get(f"/users/{uuid.uuid4()}", headers=signed_in_as(uuid.uuid4()))
    assert response.status_code == 503


async def test_e2_h10_ca6_malformed_identity_profile_is_503_without_creating_copy(api, users_api):
    from posts_api.infrastructure.database.models import UserProfileModel

    viewer, owner = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(viewer)
    users_api.has(owner)
    users_api.malformed_profile = True

    response = await api.get(f"/users/{owner}", headers=signed_in_as(viewer))

    assert response.status_code == 503
    assert response.json()["type"].endswith("/profile-unavailable")
    async with app.state.session_factory() as session:
        assert await session.get(UserProfileModel, owner) is None


async def test_e2_h10_ca6_deleted_profile_is_not_recreated(api, users_api):
    from sqlalchemy import update

    from posts_api.infrastructure.database.models import UserProfileModel

    owner = uuid.uuid4()
    await given_a_profile(owner)
    users_api.has(owner)
    async with app.state.session_factory() as session:
        await session.execute(
            update(UserProfileModel)
            .where(UserProfileModel.id == owner)
            .values(deleted_at=datetime.now(UTC))
        )
        await session.commit()
    response = await api.get(f"/users/{owner}", headers=signed_in_as(uuid.uuid4()))
    assert response.status_code == 404
    assert users_api.tokens == []


async def test_e2_h10_ca6_existing_profile_counters_and_visibility_are_preserved(api, users_api):
    from sqlalchemy import update

    from posts_api.infrastructure.database.models import UserProfileModel

    owner = uuid.uuid4()
    await given_a_profile(owner, visibility="protected")
    users_api.has(owner, visibility="public")
    async with app.state.session_factory() as session:
        await session.execute(
            update(UserProfileModel).where(UserProfileModel.id == owner).values(followers_count=7)
        )
        await session.commit()
    response = await api.get(f"/users/{owner}", headers=signed_in_as(uuid.uuid4()))
    assert response.json()["followersCount"] == 7
    assert response.json()["isPrivate"] is True
