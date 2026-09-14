import uuid

import httpx
import pytest
from sqlalchemy import delete

from posts_api.infrastructure.database.models import FollowModel, UserProfileModel
from posts_api.main import app
from tests.conftest import issue_token, requires_services

pytestmark = requires_services


@pytest.fixture
async def api():
    """The application running, on an empty graph.

    The tables are emptied before each test instead of after: if one fails, its
    rows stay in the database to be looked at.
    """
    async with app.router.lifespan_context(app):
        async with app.state.session_factory() as session:
            await session.execute(delete(FollowModel))
            await session.execute(delete(UserProfileModel))
            await session.commit()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def given_a_profile(user_id: uuid.UUID, *, visibility: str = "public") -> None:
    """Put an account on the graph, the way the copy from users-api will."""
    async with app.state.session_factory() as session:
        session.add(UserProfileModel(id=user_id, visibility=visibility))
        await session.commit()


async def is_following(follower_id: uuid.UUID, followee_id: uuid.UUID) -> bool:
    async with app.state.session_factory() as session:
        return await session.get(FollowModel, (follower_id, followee_id)) is not None


def signed_in_as(user_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(user_id)}"}


async def test_e3_h1_ca1_following_a_public_account_is_immediate(api):
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)

    response = await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))

    assert response.status_code == 204
    assert await is_following(follower, followee)


async def test_e3_h1_ca3_cannot_follow_yourself(api):
    user = uuid.uuid4()
    await given_a_profile(user)

    response = await api.post(f"/users/{user}/follow", headers=signed_in_as(user))

    assert response.status_code == 409
    assert response.json()["type"].endswith("/cannot-follow-yourself")
    assert not await is_following(user, user)


async def test_following_twice_leaves_a_single_relationship(api):
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)

    first = await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))
    second = await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))

    assert (first.status_code, second.status_code) == (204, 204)
    assert await is_following(follower, followee)


async def test_unfollowing_removes_the_relationship(api):
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)
    await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))

    response = await api.delete(f"/users/{followee}/follow", headers=signed_in_as(follower))

    assert response.status_code == 204
    assert not await is_following(follower, followee)


async def test_unfollowing_an_account_that_was_not_followed_is_not_an_error(api):
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)

    response = await api.delete(f"/users/{followee}/follow", headers=signed_in_as(follower))

    assert response.status_code == 204


async def test_following_an_unknown_account_is_rejected(api):
    response = await api.post(f"/users/{uuid.uuid4()}/follow", headers=signed_in_as(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["type"].endswith("/user-not-found")


async def test_following_a_protected_account_is_not_available_yet(api):
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee, visibility="protected")

    response = await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))

    assert response.status_code == 409
    assert response.json()["type"].endswith("/follow-needs-approval")


async def test_following_without_a_token_is_rejected(api):
    followee = uuid.uuid4()
    await given_a_profile(followee)

    response = await api.post(f"/users/{followee}/follow")

    assert response.status_code == 401


async def test_the_first_request_puts_the_signed_in_user_on_the_graph(api):
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)

    await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))

    async with app.state.session_factory() as session:
        assert await session.get(UserProfileModel, follower) is not None
