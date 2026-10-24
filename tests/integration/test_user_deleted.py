import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from posts_api.api.event_handlers import build_event_handler
from posts_api.infrastructure.database.models import (
    BlockModel,
    FollowModel,
    FollowRequestModel,
    LikeModel,
    PostModel,
    RetweetModel,
    UserProfileModel,
)
from posts_api.main import app
from tests.conftest import requires_services
from tests.events import body_of, user_deleted
from tests.integration.conftest import given_a_profile, signed_in_as
from tests.integration.test_likes import approve_follow, block, publish, read
from tests.integration.test_replies import _ensure_profiles, reply
from tests.integration.test_retweets import share

pytestmark = requires_services

DELETED_AUTHOR_FIELDS = {"authorHandle": None, "authorDisplayName": None, "authorAvatarUrl": None}


async def close_account(user_id: uuid.UUID, *, at: datetime | None = None) -> str:
    """What the consumer does with the event, without the broker in between."""
    handler = build_event_handler(app.state.session_factory)
    return await handler(body_of(user_deleted(user_id, at=at)))


async def profile_of(user_id: uuid.UUID) -> UserProfileModel:
    async with app.state.session_factory() as session:
        return await session.get(UserProfileModel, user_id)


async def count(model, *where) -> int:
    async with app.state.session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model).where(*where))


async def follow(api, follower: uuid.UUID, followee: uuid.UUID) -> None:
    # Whoever is followed has to be on the graph already.
    await _ensure_profiles(follower, followee)
    response = await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))
    assert response.status_code in (200, 201, 204)


async def test_e1_h4_ca2_follows_removed_both_directions(api):
    leaving, fan, idol = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await follow(api, fan, leaving)
    await follow(api, leaving, idol)
    await follow(api, fan, idol)

    assert await close_account(leaving) == "ack"

    assert await count(FollowModel, FollowModel.follower_id == leaving) == 0
    assert await count(FollowModel, FollowModel.followee_id == leaving) == 0
    # What the others still have is what they had without the closed account.
    assert await count(FollowModel) == 1
    assert (await profile_of(fan)).following_count == 1
    assert (await profile_of(idol)).followers_count == 1
    followers = await api.get(f"/users/{idol}/followers", headers=signed_in_as(fan))
    assert [one["id"] for one in followers.json()["items"]] == [str(fan)]
    following = await api.get(f"/users/{fan}/following", headers=signed_in_as(fan))
    assert [one["id"] for one in following.json()["items"]] == [str(idol)]


async def test_the_follow_requests_of_the_account_go_too(api):
    leaving, other = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(leaving, visibility="protected")
    await given_a_profile(other, visibility="protected")
    async with app.state.session_factory() as session:
        session.add(FollowRequestModel(requester_id=other, target_id=leaving))
        session.add(FollowRequestModel(requester_id=leaving, target_id=other))
        await session.commit()

    await close_account(leaving)

    assert await count(FollowRequestModel) == 0
    pending = await api.get("/follow-requests", headers=signed_in_as(other))
    assert pending.json()["items"] == []


async def test_its_blocks_go_in_both_directions(api):
    leaving, blocked, blocker = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await block(leaving, blocked)
    await block(blocker, leaving)

    await close_account(leaving)

    assert await count(BlockModel) == 0


async def test_its_likes_and_retweets_are_taken_back_with_their_counters(api):
    author, leaving, staying = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    for fan in (leaving, staying):
        await api.put(f"/posts/{post}/like", headers=signed_in_as(fan))
        await share(api, fan, post)
    before = await read(api, author, post)
    assert (before["likesCount"], before["retweetsCount"]) == (2, 2)

    await close_account(leaving)

    after = await read(api, author, post)
    assert (after["likesCount"], after["retweetsCount"]) == (1, 1)
    assert await count(LikeModel, LikeModel.user_id == leaving) == 0
    assert await count(RetweetModel, RetweetModel.user_id == leaving) == 0


async def test_a_post_that_was_deleted_keeps_its_counters_at_zero(api):
    author, leaving = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    await api.put(f"/posts/{post}/like", headers=signed_in_as(leaving))
    await api.delete(f"/posts/{post}", headers=signed_in_as(author))

    await close_account(leaving)

    async with app.state.session_factory() as session:
        row = await session.get(PostModel, uuid.UUID(post))
    assert (row.likes_count, row.retweets_count) == (0, 0)


async def test_e1_h4_ca5_replies_and_retweets_show_deleted_user(api):
    author, leaving, viewer = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author, "original")
    answer = (await reply(api, leaving, post, "una respuesta")).json()["id"]
    await share(api, leaving, post)

    await close_account(leaving)

    listed = await api.get(f"/posts/{post}/replies", headers=signed_in_as(viewer))
    [one] = listed.json()["items"]
    assert one["id"] == answer
    assert one["authorDeleted"] is True
    assert {key: one[key] for key in DELETED_AUTHOR_FIELDS} == DELETED_AUTHOR_FIELDS
    assert one["authorId"] == str(leaving)
    assert one["content"] == "una respuesta"
    alone = await api.get(f"/posts/{answer}", headers=signed_in_as(viewer))
    assert alone.status_code == 200
    assert alone.json()["authorDeleted"] is True
    # The retweet is not shown anywhere any more: it is gone, and the count with it.
    assert (await read(api, author, post))["retweetsCount"] == 0
    assert await count(RetweetModel) == 0


async def test_a_post_by_a_live_author_says_the_author_is_not_deleted(api):
    author = uuid.uuid4()
    post = await publish(api, author)

    shown = await read(api, author, post)

    assert shown["authorDeleted"] is False
    assert shown["authorHandle"] is not None


async def test_the_root_posts_of_the_account_are_hidden(api):
    leaving, viewer = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, leaving)
    await approve_follow(viewer, leaving)

    await close_account(leaving)

    assert (await api.get(f"/posts/{post}", headers=signed_in_as(viewer))).status_code == 404
    assert (await api.get("/feed", headers=signed_in_as(viewer))).json()["items"] == []


async def test_a_reply_retweeted_by_somebody_followed_stays_in_the_feed_with_its_marker(api):
    author, leaving, sharer, viewer = (uuid.uuid4() for _ in range(4))
    post = await publish(api, author)
    answer = (await reply(api, leaving, post)).json()["id"]
    await share(api, sharer, answer)
    await follow(api, viewer, sharer)

    await close_account(leaving)

    [entry] = (await api.get("/feed", headers=signed_in_as(viewer))).json()["items"]
    assert entry["id"] == answer
    assert entry["authorDeleted"] is True
    assert entry["authorHandle"] is None


async def test_the_replies_of_a_protected_account_stay_readable_once_it_closes(api):
    author, leaving, stranger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_a_profile(leaving, visibility="protected")
    post = await publish(api, author)
    await reply(api, leaving, post, "desde una cuenta protegida")

    await close_account(leaving)

    listed = await api.get(f"/posts/{post}/replies", headers=signed_in_as(stranger))
    assert [one["content"] for one in listed.json()["items"]] == ["desde una cuenta protegida"]
    assert (await profile_of(leaving)).visibility == "public"


async def test_the_account_is_not_found_anywhere_any_more(api):
    leaving, viewer = uuid.uuid4(), uuid.uuid4()
    await publish(api, leaving)
    await close_account(leaving)

    for path in (
        f"/users/{leaving}",
        f"/users/{leaving}/posts",
        f"/users/{leaving}/followers",
        f"/users/{leaving}/following",
    ):
        response = await api.get(path, headers=signed_in_as(viewer))
        assert response.status_code == 404, path
        assert response.json()["type"] == "https://udesa-x.dev/errors/user-not-found", path
    assert (
        await api.post(f"/users/{leaving}/follow", headers=signed_in_as(viewer))
    ).status_code == 404
    suggested = await api.get("/users/suggested", headers=signed_in_as(viewer))
    assert str(leaving) not in [one["id"] for one in suggested.json()]


async def test_e1_h4_ca2_the_same_event_twice_corrects_the_counters_once(api):
    leaving, fan, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await follow(api, fan, leaving)
    await follow(api, fan, other)

    first = await close_account(leaving)
    second = await close_account(leaving)

    assert (first, second) == ("ack", "ack")
    assert (await profile_of(fan)).following_count == 1


async def test_the_closing_time_is_the_one_of_the_event(api):
    leaving = uuid.uuid4()
    at = datetime(2026, 10, 23, 15, 20, tzinfo=UTC)

    await close_account(leaving, at=at)
    await close_account(leaving, at=datetime(2030, 1, 1, tzinfo=UTC))

    assert (await profile_of(leaving)).deleted_at == at


async def test_an_account_the_service_never_saw_is_closed_before_it_shows_up(api):
    ghost = uuid.uuid4()

    await close_account(ghost)

    assert (await profile_of(ghost)).deleted_at is not None
    # Signing in afterwards, with a token that was still valid, does not reopen it.
    await api.get("/feed", headers=signed_in_as(ghost))
    assert (await profile_of(ghost)).deleted_at is not None


async def test_an_event_that_cannot_be_read_is_rejected_and_changes_nothing(api):
    leaving = uuid.uuid4()
    await given_a_profile(leaving)
    handler = build_event_handler(app.state.session_factory)

    outcome = await handler(b'{"type": "user.deleted.v1"}')

    assert outcome == "reject"
    assert (await profile_of(leaving)).deleted_at is None
