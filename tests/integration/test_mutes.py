import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from posts_api.app.pagination import DEFAULT_PAGE_SIZE
from posts_api.infrastructure.database.models import FollowModel, MuteModel, OutboxModel
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, handle_of, signed_in_as
from tests.integration.test_user_deleted import close_account

pytestmark = requires_services


async def is_muted(muter_id: uuid.UUID, muted_id: uuid.UUID) -> bool:
    async with app.state.session_factory() as session:
        return await session.get(MuteModel, (muter_id, muted_id)) is not None


async def is_following(follower_id: uuid.UUID, followee_id: uuid.UUID) -> bool:
    async with app.state.session_factory() as session:
        return await session.get(FollowModel, (follower_id, followee_id)) is not None


async def outbox_size() -> int:
    async with app.state.session_factory() as session:
        return await session.scalar(select(func.count()).select_from(OutboxModel))


async def test_e3_h10_ca1_muting_writes_no_event(api):
    muter, muted = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(muter)
    await given_a_profile(muted)
    before = await outbox_size()

    response = await api.post(f"/users/{muted}/mute", headers=signed_in_as(muter))

    assert response.status_code == 204
    assert await is_muted(muter, muted)
    # No event means nothing can reach the muted account, not even a push.
    assert await outbox_size() == before


async def test_e3_h10_ca2_muting_keeps_the_follow(api):
    muter, muted = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(muter)
    await given_a_profile(muted)
    followed = await api.post(f"/users/{muted}/follow", headers=signed_in_as(muter))
    assert followed.status_code == 204

    await api.post(f"/users/{muted}/mute", headers=signed_in_as(muter))

    assert await is_following(muter, muted)
    profile = await api.get(f"/users/{muted}", headers=signed_in_as(muter))
    assert profile.json()["followersCount"] == 1


async def test_e3_h10_ca3_lists_muted_accounts_newest_first(api):
    owner, first, second = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for account in (owner, first, second):
        await given_a_profile(account)
    await api.post(f"/users/{first}/mute", headers=signed_in_as(owner))
    await api.post(f"/users/{second}/mute", headers=signed_in_as(owner))

    listed = await api.get("/mutes", headers=signed_in_as(owner))

    assert listed.status_code == 200
    body = listed.json()
    assert [one["handle"] for one in body["items"]] == [handle_of(second), handle_of(first)]
    assert set(body["items"][0]) == {"id", "handle", "createdAt"}
    assert body["nextCursor"] is None

    await api.delete(f"/users/{first}/mute", headers=signed_in_as(owner))
    after = await api.get("/mutes", headers=signed_in_as(owner))

    assert [one["id"] for one in after.json()["items"]] == [str(second)]


async def test_the_list_only_shows_who_the_caller_muted(api):
    owner, someone_else, muted = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for account in (owner, someone_else, muted):
        await given_a_profile(account)
    await api.post(f"/users/{muted}/mute", headers=signed_in_as(someone_else))

    listed = await api.get("/mutes", headers=signed_in_as(owner))

    assert listed.json() == {"items": [], "nextCursor": None}


async def test_the_list_pages_by_cursor_at_twenty(api):
    owner = uuid.uuid4()
    muted = [uuid.uuid4() for _ in range(DEFAULT_PAGE_SIZE + 5)]
    for account in (owner, *muted):
        await given_a_profile(account)
    base = datetime.now(UTC)
    async with app.state.session_factory() as session:
        for offset, account in enumerate(muted):
            at = base + timedelta(seconds=offset)
            session.add(MuteModel(muter_id=owner, muted_id=account, created_at=at))
        await session.commit()

    first = (await api.get("/mutes", headers=signed_in_as(owner))).json()
    second = (
        await api.get(f"/mutes?cursor={first['nextCursor']}", headers=signed_in_as(owner))
    ).json()

    assert len(first["items"]) == DEFAULT_PAGE_SIZE
    assert second["nextCursor"] is None
    listed = [one["id"] for one in first["items"] + second["items"]]
    assert listed == [str(account) for account in reversed(muted)]


async def test_muting_twice_is_not_an_error(api):
    muter, muted = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(muter)
    await given_a_profile(muted)

    first = await api.post(f"/users/{muted}/mute", headers=signed_in_as(muter))
    second = await api.post(f"/users/{muted}/mute", headers=signed_in_as(muter))

    assert (first.status_code, second.status_code) == (204, 204)
    assert await is_muted(muter, muted)


async def test_unmuting_lifts_the_mute(api):
    muter, muted = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(muter)
    await given_a_profile(muted)
    await api.post(f"/users/{muted}/mute", headers=signed_in_as(muter))

    response = await api.delete(f"/users/{muted}/mute", headers=signed_in_as(muter))

    assert response.status_code == 204
    assert not await is_muted(muter, muted)


async def test_unmuting_an_account_that_was_not_muted_changes_nothing(api):
    muter, other = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(muter)
    await given_a_profile(other)

    response = await api.delete(f"/users/{other}/mute", headers=signed_in_as(muter))

    assert response.status_code == 204


async def test_muting_is_one_way(api):
    one, other = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(one)
    await given_a_profile(other)

    await api.post(f"/users/{other}/mute", headers=signed_in_as(one))

    assert await is_muted(one, other)
    assert not await is_muted(other, one)


async def test_muting_oneself_is_rejected(api):
    user = uuid.uuid4()
    await given_a_profile(user)

    response = await api.post(f"/users/{user}/mute", headers=signed_in_as(user))

    assert response.status_code == 409
    assert response.json()["type"].endswith("/cannot-mute-yourself")


async def test_muting_an_unknown_account_is_rejected(api):
    response = await api.post(f"/users/{uuid.uuid4()}/mute", headers=signed_in_as(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["type"].endswith("/user-not-found")


async def test_muting_needs_a_token(api):
    response = await api.post(f"/users/{uuid.uuid4()}/mute")

    assert response.status_code == 401


async def test_closing_an_account_takes_its_mutes_in_both_directions(api):
    leaving, muted_by_it, muting_it = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for account in (leaving, muted_by_it, muting_it):
        await given_a_profile(account)
    await api.post(f"/users/{muted_by_it}/mute", headers=signed_in_as(leaving))
    await api.post(f"/users/{leaving}/mute", headers=signed_in_as(muting_it))

    assert await close_account(leaving) == "ack"

    assert not await is_muted(leaving, muted_by_it)
    assert not await is_muted(muting_it, leaving)
    listed = await api.get("/mutes", headers=signed_in_as(muting_it))
    assert listed.json()["items"] == []
