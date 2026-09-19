import uuid

from sqlalchemy import select

from posts_api.infrastructure.database.models import (
    FollowModel,
    FollowRequestModel,
    UserProfileModel,
)
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, handle_of, signed_in_as

pytestmark = requires_services


async def pending_rows(target_id: uuid.UUID) -> list[FollowRequestModel]:
    async with app.state.session_factory() as session:
        found = await session.execute(
            select(FollowRequestModel).where(FollowRequestModel.target_id == target_id)
        )
        return list(found.scalars())


async def test_e3_h1_ca2_following_a_protected_account_creates_a_pending_request(api):
    requester, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")

    response = await api.post(f"/users/{target}/follow", headers=signed_in_as(requester))

    # 202 and not 204: nothing was established, the ask was accepted.
    assert response.status_code == 202
    rows = await pending_rows(target)
    assert [(row.requester_id, row.status) for row in rows] == [(requester, "pending")]

    # And the relationship does not exist until somebody approves it.
    async with app.state.session_factory() as session:
        assert await session.get(FollowModel, (requester, target)) is None


async def test_the_listing_gives_the_screen_exactly_what_it_expects(api):
    requester, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")
    await api.post(f"/users/{target}/follow", headers=signed_in_as(requester))

    response = await api.get("/follow-requests", headers=signed_in_as(target))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    # The names are the ones the app was written against, not the Python ones.
    assert set(body[0]) == {"id", "requesterHandle", "createdAt"}
    assert body[0]["requesterHandle"] == handle_of(requester)
    assert uuid.UUID(body[0]["id"])


async def test_the_listing_only_returns_what_was_aimed_at_whoever_asks(api):
    requester, mine, somebody_else = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_a_profile(mine, visibility="protected")
    await given_a_profile(somebody_else, visibility="protected")
    await api.post(f"/users/{mine}/follow", headers=signed_in_as(requester))
    await api.post(f"/users/{somebody_else}/follow", headers=signed_in_as(requester))

    response = await api.get("/follow-requests", headers=signed_in_as(mine))

    assert [one["requesterHandle"] for one in response.json()] == [handle_of(requester)]
    assert len(await pending_rows(somebody_else)) == 1


async def test_an_account_with_nothing_pending_gets_an_empty_list(api):
    owner = uuid.uuid4()
    await given_a_profile(owner, visibility="protected")

    response = await api.get("/follow-requests", headers=signed_in_as(owner))

    assert response.status_code == 200
    assert response.json() == []


async def test_asking_twice_leaves_a_single_request(api):
    requester, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")

    first = await api.post(f"/users/{target}/follow", headers=signed_in_as(requester))
    second = await api.post(f"/users/{target}/follow", headers=signed_in_as(requester))

    assert (first.status_code, second.status_code) == (202, 202)
    assert len(await pending_rows(target)) == 1


async def test_a_protected_account_already_followed_gets_no_request(api):
    """Approved before the account turned protected: there is nothing left to ask."""
    follower, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target)
    await api.post(f"/users/{target}/follow", headers=signed_in_as(follower))
    async with app.state.session_factory() as session:
        profile = await session.get(UserProfileModel, target)
        profile.visibility = "protected"
        await session.commit()

    response = await api.post(f"/users/{target}/follow", headers=signed_in_as(follower))

    assert response.status_code == 204
    assert await pending_rows(target) == []


async def test_a_request_counts_against_the_limit_by_the_hour(api):
    """Asking is a follow attempt, so it is charged like one."""
    requester, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")
    await app.state.redis.set(f"follow:rate:{requester}", 50, ex=3600)

    response = await api.post(f"/users/{target}/follow", headers=signed_in_as(requester))

    assert response.status_code == 429
    assert await pending_rows(target) == []


async def test_asking_to_follow_yourself_is_still_refused(api):
    owner = uuid.uuid4()
    await given_a_profile(owner, visibility="protected")

    response = await api.post(f"/users/{owner}/follow", headers=signed_in_as(owner))

    assert response.status_code == 409
    assert await pending_rows(owner) == []


async def test_the_listing_needs_a_token(api):
    response = await api.get("/follow-requests")

    assert response.status_code == 401


async def a_request_from(api, requester: uuid.UUID, target: uuid.UUID) -> str:
    """Leave a pending request and give back its id, the way the screen gets it."""
    await api.post(f"/users/{target}/follow", headers=signed_in_as(requester))
    listed = await api.get("/follow-requests", headers=signed_in_as(target))
    return listed.json()[0]["id"]


async def counters_of(user_id: uuid.UUID) -> tuple[int, int]:
    async with app.state.session_factory() as session:
        profile = await session.get(UserProfileModel, user_id)
        return profile.followers_count, profile.following_count


async def status_of(request_id: str) -> str:
    async with app.state.session_factory() as session:
        return (await session.get(FollowRequestModel, uuid.UUID(request_id))).status


async def test_approving_establishes_the_relationship_and_moves_the_counters(api):
    requester, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")
    request_id = await a_request_from(api, requester, target)

    response = await api.post(
        f"/follow-requests/{request_id}/approve", headers=signed_in_as(target)
    )

    assert response.status_code == 204
    assert await status_of(request_id) == "approved"
    async with app.state.session_factory() as session:
        assert await session.get(FollowModel, (requester, target)) is not None
    assert await counters_of(target) == (1, 0)
    assert await counters_of(requester) == (0, 1)


async def test_rejecting_closes_the_request_and_changes_nothing_else(api):
    requester, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")
    request_id = await a_request_from(api, requester, target)

    response = await api.post(f"/follow-requests/{request_id}/reject", headers=signed_in_as(target))

    assert response.status_code == 204
    assert await status_of(request_id) == "rejected"
    async with app.state.session_factory() as session:
        assert await session.get(FollowModel, (requester, target)) is None
    assert await counters_of(target) == (0, 0)


async def test_somebody_else_cannot_answer_a_request(api):
    """404 and not 403: a 403 would confirm that the request exists."""
    requester, target, stranger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")
    await given_a_profile(stranger)
    request_id = await a_request_from(api, requester, target)

    response = await api.post(
        f"/follow-requests/{request_id}/approve", headers=signed_in_as(stranger)
    )

    assert response.status_code == 404
    assert await status_of(request_id) == "pending"


async def test_neither_can_the_one_who_asked(api):
    requester, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")
    request_id = await a_request_from(api, requester, target)

    response = await api.post(
        f"/follow-requests/{request_id}/approve", headers=signed_in_as(requester)
    )

    assert response.status_code == 404
    assert await status_of(request_id) == "pending"


async def test_approving_twice_does_not_count_two_followers(api):
    requester, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")
    request_id = await a_request_from(api, requester, target)
    await api.post(f"/follow-requests/{request_id}/approve", headers=signed_in_as(target))

    again = await api.post(f"/follow-requests/{request_id}/approve", headers=signed_in_as(target))

    assert again.status_code == 404
    assert await counters_of(target) == (1, 0)


async def test_a_rejected_request_cannot_be_approved_afterwards(api):
    requester, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")
    request_id = await a_request_from(api, requester, target)
    await api.post(f"/follow-requests/{request_id}/reject", headers=signed_in_as(target))

    response = await api.post(
        f"/follow-requests/{request_id}/approve", headers=signed_in_as(target)
    )

    assert response.status_code == 404
    assert await status_of(request_id) == "rejected"


async def test_an_answered_request_leaves_the_pending_list(api):
    requester, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")
    request_id = await a_request_from(api, requester, target)

    await api.post(f"/follow-requests/{request_id}/approve", headers=signed_in_as(target))

    listed = await api.get("/follow-requests", headers=signed_in_as(target))
    assert listed.json() == []


async def test_asking_again_after_unfollowing_can_be_approved_again(api):
    """A plain unique constraint over the three columns would break here.

    The second approval would collide with the first resolved row, so the
    uniqueness only applies while a request is open.
    """
    requester, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")
    first = await a_request_from(api, requester, target)
    await api.post(f"/follow-requests/{first}/approve", headers=signed_in_as(target))
    await api.delete(f"/users/{target}/follow", headers=signed_in_as(requester))

    second = await a_request_from(api, requester, target)
    response = await api.post(f"/follow-requests/{second}/approve", headers=signed_in_as(target))

    assert response.status_code == 204
    assert await counters_of(target) == (1, 0)


async def test_answering_a_request_that_does_not_exist_is_a_404(api):
    owner = uuid.uuid4()
    await given_a_profile(owner, visibility="protected")

    response = await api.post(
        f"/follow-requests/{uuid.uuid4()}/reject", headers=signed_in_as(owner)
    )

    assert response.status_code == 404


async def test_reading_the_list_puts_the_caller_on_the_graph(api):
    """Without this nobody could ever be followed for the first time.

    A profile is only written by a request that succeeds: a failed one rolls
    its transaction back, and following somebody who is not on the graph fails.
    """
    newcomer = uuid.uuid4()

    await api.get("/follow-requests", headers=signed_in_as(newcomer))

    async with app.state.session_factory() as session:
        profile = await session.get(UserProfileModel, newcomer)
        assert profile is not None
        assert profile.handle == handle_of(newcomer)


async def test_an_account_that_opened_the_app_can_be_followed(api):
    """The whole bootstrap, without seeding anything by hand."""
    follower, target = uuid.uuid4(), uuid.uuid4()
    # Neither exists on the graph. The target opens their requests screen.
    await api.get("/follow-requests", headers=signed_in_as(target))

    response = await api.post(f"/users/{target}/follow", headers=signed_in_as(follower))

    assert response.status_code == 204
