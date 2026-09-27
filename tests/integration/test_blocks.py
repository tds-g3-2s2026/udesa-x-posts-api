import uuid

from sqlalchemy import select

from posts_api.infrastructure.database.models import (
    BlockModel,
    FollowModel,
    FollowRequestModel,
    UserProfileModel,
)
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, handle_of, signed_in_as

pytestmark = requires_services


async def is_following(follower_id: uuid.UUID, followee_id: uuid.UUID) -> bool:
    async with app.state.session_factory() as session:
        return await session.get(FollowModel, (follower_id, followee_id)) is not None


async def counters_of(user_id: uuid.UUID) -> tuple[int, int]:
    async with app.state.session_factory() as session:
        profile = await session.get(UserProfileModel, user_id)
        return profile.followers_count, profile.following_count


async def follow_each_other(api, one: uuid.UUID, other: uuid.UUID) -> None:
    await given_a_profile(one)
    await given_a_profile(other)
    for follower, followee in ((one, other), (other, one)):
        response = await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))
        assert response.status_code == 204


async def feed_contents(api, viewer: uuid.UUID) -> list[str]:
    response = await api.get("/feed", headers=signed_in_as(viewer))
    assert response.status_code == 200
    return [one["content"] for one in response.json()["items"]]


async def test_e3_h4_ca3_blocking_removes_follows_both_ways(api):
    blocker, blocked = uuid.uuid4(), uuid.uuid4()
    await follow_each_other(api, blocker, blocked)

    response = await api.post(f"/users/{blocked}/block", headers=signed_in_as(blocker))

    assert response.status_code == 204
    assert not await is_following(blocker, blocked)
    assert not await is_following(blocked, blocker)
    assert await counters_of(blocker) == (0, 0)
    assert await counters_of(blocked) == (0, 0)


async def test_blocking_withdraws_a_pending_request_from_the_blocked_account(api):
    blocker, blocked = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(blocker, visibility="protected")
    await given_a_profile(blocked)
    asked = await api.post(f"/users/{blocker}/follow", headers=signed_in_as(blocked))
    assert asked.status_code == 202

    await api.post(f"/users/{blocked}/block", headers=signed_in_as(blocker))

    pending = await api.get("/follow-requests", headers=signed_in_as(blocker))
    assert pending.json()["items"] == []
    async with app.state.session_factory() as session:
        found = await session.execute(
            select(FollowRequestModel.status).where(FollowRequestModel.requester_id == blocked)
        )
        assert found.scalars().all() == ["cancelled"]


async def test_e3_h4_ca4_blocked_user_gets_404_on_the_profile(api):
    blocker, blocked = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(blocker)
    await given_a_profile(blocked)
    await api.post(f"/users/{blocked}/block", headers=signed_in_as(blocker))

    for screen in ("followers", "following"):
        response = await api.get(f"/users/{blocker}/{screen}", headers=signed_in_as(blocked))

        assert response.status_code == 404
        # The same answer an account that does not exist gets, word for word.
        missing = await api.get(f"/users/{uuid.uuid4()}/{screen}", headers=signed_in_as(blocked))
        assert response.json()["type"] == missing.json()["type"]
        assert response.json()["detail"] == missing.json()["detail"]


async def test_the_blocker_still_sees_the_lists_of_who_they_blocked(api):
    blocker, blocked = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(blocker)
    await given_a_profile(blocked)
    await api.post(f"/users/{blocked}/block", headers=signed_in_as(blocker))

    response = await api.get(f"/users/{blocked}/followers", headers=signed_in_as(blocker))

    assert response.status_code == 200


async def test_the_blocked_account_cannot_follow_the_blocker(api):
    blocker, blocked = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(blocker)
    await given_a_profile(blocked)
    await api.post(f"/users/{blocked}/block", headers=signed_in_as(blocker))

    response = await api.post(f"/users/{blocker}/follow", headers=signed_in_as(blocked))

    assert response.status_code == 404
    assert response.json()["type"].endswith("/user-not-found")
    assert not await is_following(blocked, blocker)


async def test_the_blocker_has_to_unblock_before_following_again(api):
    blocker, blocked = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(blocker)
    await given_a_profile(blocked)
    await api.post(f"/users/{blocked}/block", headers=signed_in_as(blocker))

    refused = await api.post(f"/users/{blocked}/follow", headers=signed_in_as(blocker))
    await api.delete(f"/users/{blocked}/block", headers=signed_in_as(blocker))
    accepted = await api.post(f"/users/{blocked}/follow", headers=signed_in_as(blocker))

    assert refused.status_code == 409
    assert refused.json()["type"].endswith("/account-blocked")
    assert accepted.status_code == 204


async def test_e3_h4_ca5_blocked_posts_leave_the_feed_both_ways(api):
    blocker, blocked = uuid.uuid4(), uuid.uuid4()
    await follow_each_other(api, blocker, blocked)
    await api.post("/posts", json={"content": "del que bloquea"}, headers=signed_in_as(blocker))
    await api.post("/posts", json={"content": "del bloqueado"}, headers=signed_in_as(blocked))
    assert await feed_contents(api, blocker) == ["del bloqueado"]
    assert await feed_contents(api, blocked) == ["del que bloquea"]

    await api.post(f"/users/{blocked}/block", headers=signed_in_as(blocker))

    assert await feed_contents(api, blocker) == []
    assert await feed_contents(api, blocked) == []


async def test_the_filter_hides_the_posts_even_if_a_follow_survived(api):
    """Blocking already removes the follows, so the test above would pass
    without the filter. Here the follow is put back by hand next to the block,
    which is what proves the filter itself holds."""
    blocker, blocked = uuid.uuid4(), uuid.uuid4()
    await follow_each_other(api, blocker, blocked)
    await api.post("/posts", json={"content": "del que bloquea"}, headers=signed_in_as(blocker))
    await api.post("/posts", json={"content": "del bloqueado"}, headers=signed_in_as(blocked))
    async with app.state.session_factory() as session:
        session.add(BlockModel(blocker_id=blocker, blocked_id=blocked))
        await session.commit()

    assert await is_following(blocker, blocked)
    assert await feed_contents(api, blocker) == []
    assert await feed_contents(api, blocked) == []


async def test_e3_h4_ca2_blocked_accounts_are_listed_and_can_be_unblocked(api):
    owner, first, second = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for account in (owner, first, second):
        await given_a_profile(account)
    await api.post(f"/users/{first}/block", headers=signed_in_as(owner))
    await api.post(f"/users/{second}/block", headers=signed_in_as(owner))

    listed = await api.get("/blocks", headers=signed_in_as(owner))

    assert listed.status_code == 200
    body = listed.json()
    assert [one["handle"] for one in body["items"]] == [handle_of(second), handle_of(first)]
    assert set(body["items"][0]) == {"id", "handle", "createdAt"}
    assert body["nextCursor"] is None

    unblocked = await api.delete(f"/users/{first}/block", headers=signed_in_as(owner))
    after = await api.get("/blocks", headers=signed_in_as(owner))

    assert unblocked.status_code == 204
    assert [one["id"] for one in after.json()["items"]] == [str(second)]


async def test_the_list_only_shows_who_the_caller_blocked(api):
    owner, someone_else, blocked = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for account in (owner, someone_else, blocked):
        await given_a_profile(account)
    await api.post(f"/users/{blocked}/block", headers=signed_in_as(someone_else))

    listed = await api.get("/blocks", headers=signed_in_as(owner))

    assert listed.json()["items"] == []


async def test_unblocking_does_not_bring_the_follows_back(api):
    blocker, blocked = uuid.uuid4(), uuid.uuid4()
    await follow_each_other(api, blocker, blocked)
    await api.post(f"/users/{blocked}/block", headers=signed_in_as(blocker))

    await api.delete(f"/users/{blocked}/block", headers=signed_in_as(blocker))

    assert not await is_following(blocker, blocked)
    assert not await is_following(blocked, blocker)


async def test_blocking_twice_moves_the_counters_once(api):
    blocker, blocked = uuid.uuid4(), uuid.uuid4()
    await follow_each_other(api, blocker, blocked)

    first = await api.post(f"/users/{blocked}/block", headers=signed_in_as(blocker))
    second = await api.post(f"/users/{blocked}/block", headers=signed_in_as(blocker))

    assert (first.status_code, second.status_code) == (204, 204)
    assert await counters_of(blocker) == (0, 0)


async def test_cannot_block_yourself(api):
    user = uuid.uuid4()
    await given_a_profile(user)

    response = await api.post(f"/users/{user}/block", headers=signed_in_as(user))

    assert response.status_code == 409
    assert response.json()["type"].endswith("/cannot-block-yourself")


async def test_blocking_an_unknown_account_is_rejected(api):
    response = await api.post(f"/users/{uuid.uuid4()}/block", headers=signed_in_as(uuid.uuid4()))

    assert response.status_code == 404


async def test_blocking_needs_a_token(api):
    response = await api.post(f"/users/{uuid.uuid4()}/block")

    assert response.status_code == 401
