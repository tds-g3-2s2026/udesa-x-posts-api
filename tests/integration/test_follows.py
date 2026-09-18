import asyncio
import uuid

from posts_api.infrastructure.database.models import FollowModel, UserProfileModel
from posts_api.main import app
from tests.conftest import issue_token, requires_services
from tests.integration.conftest import given_a_profile, handle_of, signed_in_as

pytestmark = requires_services


async def is_following(follower_id: uuid.UUID, followee_id: uuid.UUID) -> bool:
    async with app.state.session_factory() as session:
        return await session.get(FollowModel, (follower_id, followee_id)) is not None


async def counters_of(user_id: uuid.UUID) -> tuple[int, int]:
    """Followers and following, read straight from the table."""
    async with app.state.session_factory() as session:
        profile = await session.get(UserProfileModel, user_id)
        return profile.followers_count, profile.following_count


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


async def test_e3_h1_ca4_counters_stay_consistent_under_concurrent_follows(api):
    """Ten accounts following the same target at the same time.

    Run one after the other this passes even with the sum done in Python, which
    is the mistake the criterion exists to catch: every request would read the
    same value and the increments would overwrite each other.
    """
    followee = uuid.uuid4()
    await given_a_profile(followee)
    followers = [uuid.uuid4() for _ in range(10)]

    responses = await asyncio.gather(
        *(api.post(f"/users/{followee}/follow", headers=signed_in_as(f)) for f in followers)
    )

    assert [r.status_code for r in responses] == [204] * 10
    followers_count, _ = await counters_of(followee)
    assert followers_count == 10
    for follower in followers:
        assert await counters_of(follower) == (0, 1)


async def test_counters_go_back_down_when_the_follow_is_undone(api):
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)
    await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))

    await api.delete(f"/users/{followee}/follow", headers=signed_in_as(follower))

    assert await counters_of(followee) == (0, 0)
    assert await counters_of(follower) == (0, 0)


async def test_unfollowing_twice_does_not_push_the_counters_below_zero(api):
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)
    await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))

    await api.delete(f"/users/{followee}/follow", headers=signed_in_as(follower))
    await api.delete(f"/users/{followee}/follow", headers=signed_in_as(follower))

    assert await counters_of(followee) == (0, 0)


async def test_following_the_same_account_twice_counts_once(api):
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)

    await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))
    await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))

    assert await counters_of(followee) == (1, 0)


async def test_e3_h1_ca5_limits_follow_requests_to_fifty_per_hour(api):
    """The window is already full, so the next attempt is refused."""
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)
    await app.state.redis.set(f"follow:rate:{follower}", 50, ex=3600)

    response = await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))

    assert response.status_code == 429
    assert response.json()["type"].endswith("/too-many-follows")
    assert int(response.headers["Retry-After"]) > 0
    assert not await is_following(follower, followee)


async def test_the_attempt_below_the_limit_still_goes_through(api):
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)
    await app.state.redis.set(f"follow:rate:{follower}", 49, ex=3600)

    response = await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))

    assert response.status_code == 204
    assert await is_following(follower, followee)


async def test_the_limit_is_counted_per_account(api):
    """One account reaching the limit does not block anybody else."""
    blocked, free, followee = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)
    await app.state.redis.set(f"follow:rate:{blocked}", 50, ex=3600)

    refused = await api.post(f"/users/{followee}/follow", headers=signed_in_as(blocked))
    allowed = await api.post(f"/users/{followee}/follow", headers=signed_in_as(free))

    assert (refused.status_code, allowed.status_code) == (429, 204)


async def test_the_window_does_not_move_forward_with_each_attempt(api):
    """The expiry is set once, so retrying does not extend the block."""
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)

    await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))
    first_ttl = await app.state.redis.ttl(f"follow:rate:{follower}")
    await api.post(f"/users/{uuid.uuid4()}/follow", headers=signed_in_as(follower))
    second_ttl = await app.state.redis.ttl(f"follow:rate:{follower}")

    assert second_ttl <= first_ttl


async def test_the_handle_from_the_token_lands_on_the_profile(api):
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)

    await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))

    async with app.state.session_factory() as session:
        profile = await session.get(UserProfileModel, follower)
        assert profile.handle == handle_of(follower)


async def test_a_profile_without_a_handle_gets_it_on_the_next_request(api):
    """The rows created before users-api sent the handle get filled in."""
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)
    async with app.state.session_factory() as session:
        session.add(UserProfileModel(id=follower))
        await session.commit()

    await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))

    async with app.state.session_factory() as session:
        profile = await session.get(UserProfileModel, follower)
        assert profile.handle == handle_of(follower)


async def test_a_token_without_a_handle_leaves_the_profile_alone(api):
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)

    headers = {"Authorization": f"Bearer {issue_token(follower, handle=None)}"}
    response = await api.post(f"/users/{followee}/follow", headers=headers)

    assert response.status_code == 204
    async with app.state.session_factory() as session:
        assert (await session.get(UserProfileModel, follower)).handle is None
