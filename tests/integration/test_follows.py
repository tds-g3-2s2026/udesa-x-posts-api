import asyncio
import uuid

from sqlalchemy import select

from posts_api.infrastructure.database.models import (
    FollowModel,
    FollowRequestModel,
    UserProfileModel,
)
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


async def test_e3_h2_ca1_unfollow_takes_effect_immediately(api):
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


async def test_e3_h2_ca2_counters_drop_on_unfollow(api):
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


async def following_set(follower_id: uuid.UUID) -> set[uuid.UUID]:
    """The accounts this one follows: what the feed will read to build itself."""
    async with app.state.session_factory() as session:
        found = await session.execute(
            select(FollowModel.followee_id).where(FollowModel.follower_id == follower_id)
        )
        return set(found.scalars())


async def test_e3_h2_ca3_unfollowed_user_leaves_the_following_set(api):
    """The half of CA.3 that exists today.

    The criterion asks that the posts stop appearing in the feed, and the feed
    is E2-H2, still to come. What can be checked now is that the account leaves
    the set the feed will read. The end to end test belongs with the feed.
    """
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)
    await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))
    assert followee in await following_set(follower)

    await api.delete(f"/users/{followee}/follow", headers=signed_in_as(follower))

    assert followee not in await following_set(follower)


async def status_of_request(requester_id: uuid.UUID, target_id: uuid.UUID) -> str | None:
    async with app.state.session_factory() as session:
        found = await session.execute(
            select(FollowRequestModel.status).where(
                FollowRequestModel.requester_id == requester_id,
                FollowRequestModel.target_id == target_id,
            )
        )
        return found.scalar_one_or_none()


async def test_unfollowing_withdraws_a_request_nobody_answered(api):
    requester, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")
    asked = await api.post(f"/users/{target}/follow", headers=signed_in_as(requester))
    assert asked.status_code == 202

    response = await api.delete(f"/users/{target}/follow", headers=signed_in_as(requester))

    assert response.status_code == 204
    # Cancelled and not rejected: rejected is the owner's answer, and the owner
    # never answered.
    assert await status_of_request(requester, target) == "cancelled"


async def test_withdrawing_leaves_the_counters_where_they_were(api):
    """A pending request never moved them, so undoing it must not either."""
    requester, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")
    await api.post(f"/users/{target}/follow", headers=signed_in_as(requester))

    await api.delete(f"/users/{target}/follow", headers=signed_in_as(requester))

    assert await counters_of(target) == (0, 0)
    assert await counters_of(requester) == (0, 0)


async def test_a_withdrawn_request_leaves_the_owners_pending_list(api):
    requester, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")
    await api.post(f"/users/{target}/follow", headers=signed_in_as(requester))

    await api.delete(f"/users/{target}/follow", headers=signed_in_as(requester))

    listed = await api.get("/follow-requests", headers=signed_in_as(target))
    assert listed.json() == []


async def test_asking_again_after_withdrawing_opens_a_new_request(api):
    """The unique index only covers open requests, so a cancelled one does not block."""
    requester, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")
    await api.post(f"/users/{target}/follow", headers=signed_in_as(requester))
    await api.delete(f"/users/{target}/follow", headers=signed_in_as(requester))

    again = await api.post(f"/users/{target}/follow", headers=signed_in_as(requester))

    assert again.status_code == 202
    listed = await api.get("/follow-requests", headers=signed_in_as(target))
    assert len(listed.json()) == 1


async def test_a_request_the_owner_already_answered_is_not_rewritten(api):
    """Rejected is the owner's word: whoever asked cannot overwrite it."""
    requester, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")
    await api.post(f"/users/{target}/follow", headers=signed_in_as(requester))
    listed = await api.get("/follow-requests", headers=signed_in_as(target))
    request_id = listed.json()[0]["id"]
    await api.post(f"/follow-requests/{request_id}/reject", headers=signed_in_as(target))

    await api.delete(f"/users/{target}/follow", headers=signed_in_as(requester))

    assert await status_of_request(requester, target) == "rejected"
