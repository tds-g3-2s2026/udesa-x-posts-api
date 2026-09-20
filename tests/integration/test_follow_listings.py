import uuid
from datetime import UTC, datetime, timedelta

from posts_api.app.pagination import DEFAULT_PAGE_SIZE
from posts_api.infrastructure.database.models import FollowModel, UserProfileModel
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, handle_of, signed_in_as

pytestmark = requires_services


async def insert_follow(
    follower_id: uuid.UUID, followee_id: uuid.UUID, created_at: datetime
) -> None:
    """A follow relationship with a `created_at` set by hand, for control over ordering.

    Both ends need a profile for the foreign keys, and either one may already
    have been created by an earlier call in the same test: checked here,
    inside the one session that also writes the relationship, instead of a
    second call to `given_a_profile` that would collide with the existing row.

    The new profiles are flushed before the relationship is added, not left
    for the final commit: nothing here declares an ORM `relationship()`
    between the two tables, so the session has no way to know the insert
    order that satisfies the foreign key on its own.
    """
    async with app.state.session_factory() as session:
        for account_id in (follower_id, followee_id):
            if await session.get(UserProfileModel, account_id) is None:
                session.add(UserProfileModel(id=account_id, handle=handle_of(account_id)))
        await session.flush()
        session.add(
            FollowModel(follower_id=follower_id, followee_id=followee_id, created_at=created_at)
        )
        await session.commit()


async def make_protected(user_id: uuid.UUID) -> None:
    async with app.state.session_factory() as session:
        profile = await session.get(UserProfileModel, user_id)
        profile.visibility = "protected"
        await session.commit()


async def test_e3_h3_ca1_listings_carry_the_fields_the_screen_needs(api):
    target, a, b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target)
    base = datetime.now(UTC)
    await insert_follow(a, target, base)
    await insert_follow(b, target, base + timedelta(seconds=1))

    response = await api.get(f"/users/{target}/followers", headers=signed_in_as(target))

    assert response.status_code == 200
    body = response.json()
    # Most recent relationship first.
    assert [one["handle"] for one in body["items"]] == [handle_of(b), handle_of(a)]
    row = body["items"][0]
    assert set(row) == {"id", "handle", "displayName", "avatarUrl", "following", "createdAt"}
    # displayName and avatarUrl live in users-api and nothing copies them here
    # yet: present and null, not missing, so the screen can read the final
    # shape today and get the real value later without a contract change.
    assert (row["displayName"], row["avatarUrl"]) == (None, None)
    assert row["following"] is False
    assert body["nextCursor"] is None


async def test_following_lists_who_the_account_follows(api):
    origin, a, b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_a_profile(origin)
    base = datetime.now(UTC)
    await insert_follow(origin, a, base)
    await insert_follow(origin, b, base + timedelta(seconds=1))

    response = await api.get(f"/users/{origin}/following", headers=signed_in_as(origin))

    assert response.status_code == 200
    assert [one["handle"] for one in response.json()["items"]] == [handle_of(b), handle_of(a)]


async def test_following_flag_reflects_the_viewer_not_the_listed_account(api):
    """The button state is about the caller, not about who follows whom in the row."""
    target, follower = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target)
    await insert_follow(follower, target, datetime.now(UTC))
    # The caller (target) does not follow `follower` back.

    response = await api.get(f"/users/{target}/followers", headers=signed_in_as(target))

    assert response.json()["items"][0]["following"] is False

    await insert_follow(target, follower, datetime.now(UTC))
    response = await api.get(f"/users/{target}/followers", headers=signed_in_as(target))

    assert response.json()["items"][0]["following"] is True


async def test_an_account_with_nobody_gets_an_empty_list(api):
    lonely = uuid.uuid4()
    await given_a_profile(lonely)

    response = await api.get(f"/users/{lonely}/followers", headers=signed_in_as(lonely))

    assert response.json() == {"items": [], "nextCursor": None}


async def test_e3_h3_ca2_listings_page_by_cursor_at_twenty(api):
    target = uuid.uuid4()
    await given_a_profile(target)
    base = datetime.now(UTC)
    followers = [uuid.uuid4() for _ in range(DEFAULT_PAGE_SIZE + 5)]
    for offset, follower in enumerate(followers):
        await insert_follow(follower, target, base + timedelta(seconds=offset))

    first = await api.get(f"/users/{target}/followers", headers=signed_in_as(target))
    first_body = first.json()
    assert len(first_body["items"]) == DEFAULT_PAGE_SIZE
    assert first_body["nextCursor"] is not None

    second = await api.get(
        f"/users/{target}/followers?cursor={first_body['nextCursor']}",
        headers=signed_in_as(target),
    )
    second_body = second.json()

    assert len(second_body["items"]) == 5
    assert second_body["nextCursor"] is None
    first_ids = {one["id"] for one in first_body["items"]}
    second_ids = {one["id"] for one in second_body["items"]}
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | second_ids == {str(follower) for follower in followers}


async def test_a_protected_accounts_lists_are_refused_to_a_stranger(api):
    target, stranger = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target)
    await make_protected(target)

    response = await api.get(f"/users/{target}/followers", headers=signed_in_as(stranger))

    assert response.status_code == 403
    assert response.json()["type"].endswith("/follow-list-not-visible")


async def test_a_protected_accounts_lists_are_visible_to_an_approved_follower(api):
    target, follower = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target)
    await make_protected(target)
    await insert_follow(follower, target, datetime.now(UTC))

    response = await api.get(f"/users/{target}/followers", headers=signed_in_as(follower))

    assert response.status_code == 200


async def test_a_protected_account_can_read_its_own_lists(api):
    owner = uuid.uuid4()
    await given_a_profile(owner)
    await make_protected(owner)

    followers = await api.get(f"/users/{owner}/followers", headers=signed_in_as(owner))
    following = await api.get(f"/users/{owner}/following", headers=signed_in_as(owner))

    assert (followers.status_code, following.status_code) == (200, 200)


async def test_a_public_accounts_lists_are_visible_to_anyone(api):
    target, stranger = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target)

    response = await api.get(f"/users/{target}/followers", headers=signed_in_as(stranger))

    assert response.status_code == 200


async def test_an_unknown_account_is_a_404(api):
    response = await api.get(f"/users/{uuid.uuid4()}/followers", headers=signed_in_as(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["type"].endswith("/user-not-found")


async def test_the_listings_need_a_token(api):
    target = uuid.uuid4()
    await given_a_profile(target)

    followers = await api.get(f"/users/{target}/followers")
    following = await api.get(f"/users/{target}/following")

    assert (followers.status_code, following.status_code) == (401, 401)


async def test_reading_either_listing_puts_the_caller_on_the_graph(api):
    target, newcomer = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target)

    await api.get(f"/users/{target}/followers", headers=signed_in_as(newcomer))

    async with app.state.session_factory() as session:
        profile = await session.get(UserProfileModel, newcomer)
        assert profile is not None
        assert profile.handle == handle_of(newcomer)
