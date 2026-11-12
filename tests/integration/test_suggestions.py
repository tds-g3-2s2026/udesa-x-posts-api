"""The accounts suggested to follow, for the empty feed and the onboarding."""

import uuid

from posts_api.app.services.follow_listings import SUGGESTED_ACCOUNTS_LIMIT
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, signed_in_as
from tests.integration.test_follow_listings import given_a_profile_with_followers

pytestmark = requires_services


async def suggested_to(api, viewer: uuid.UUID) -> list[str]:
    response = await api.get("/users/suggested", headers=signed_in_as(viewer))
    assert response.status_code == 200
    return [one["id"] for one in response.json()]


async def test_e1_h14_ca3_suggests_the_five_most_followed_accounts(api):
    viewer = uuid.uuid4()
    await given_a_profile(viewer)
    accounts = [uuid.uuid4() for _ in range(6)]
    for followers, account in zip((60, 50, 40, 30, 20, 10), accounts, strict=True):
        await given_a_profile_with_followers(account, followers)

    suggested = await suggested_to(api, viewer)

    assert suggested[:5] == [str(one) for one in accounts[:5]]


async def test_an_account_the_viewer_blocked_is_not_suggested(api):
    viewer, blocked, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_a_profile(viewer)
    await given_a_profile_with_followers(blocked, 100)
    await given_a_profile_with_followers(other, 1)
    await api.post(f"/users/{blocked}/block", headers=signed_in_as(viewer))

    assert await suggested_to(api, viewer) == [str(other)]


async def test_an_account_that_blocked_the_viewer_is_not_suggested(api):
    viewer, blocker, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_a_profile(viewer)
    await given_a_profile_with_followers(blocker, 100)
    await given_a_profile_with_followers(other, 1)
    await api.post(f"/users/{viewer}/block", headers=signed_in_as(blocker))

    assert await suggested_to(api, viewer) == [str(other)]


async def test_an_account_the_viewer_muted_is_not_suggested(api):
    viewer, muted, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_a_profile(viewer)
    await given_a_profile_with_followers(muted, 100)
    await given_a_profile_with_followers(other, 1)
    await api.post(f"/users/{muted}/mute", headers=signed_in_as(viewer))

    assert await suggested_to(api, viewer) == [str(other)]


async def test_muting_only_hides_the_account_from_whoever_muted(api):
    viewer, muter, muted = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_a_profile(viewer)
    await given_a_profile_with_followers(muted, 100)
    await api.post(f"/users/{muted}/mute", headers=signed_in_as(muter))

    assert str(muted) in await suggested_to(api, viewer)


async def test_the_limit_counts_what_is_left_after_the_filters(api):
    viewer = uuid.uuid4()
    await given_a_profile(viewer)
    accounts = [uuid.uuid4() for _ in range(SUGGESTED_ACCOUNTS_LIMIT + 2)]
    for position, account in enumerate(accounts):
        await given_a_profile_with_followers(account, 1000 - position)
    # The two most followed are out: one blocked, one muted.
    await api.post(f"/users/{accounts[0]}/block", headers=signed_in_as(viewer))
    await api.post(f"/users/{accounts[1]}/mute", headers=signed_in_as(viewer))

    suggested = await suggested_to(api, viewer)

    assert suggested == [str(one) for one in accounts[2:]]
