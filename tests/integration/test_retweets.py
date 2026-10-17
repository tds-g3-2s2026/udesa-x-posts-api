import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from posts_api.infrastructure.database.models import PostModel, RetweetModel
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, handle_of, signed_in_as
from tests.integration.test_likes import approve_follow, block, publish, read

pytestmark = requires_services


async def share(api, viewer, post):
    return await api.post(f"/posts/{post}/retweet", headers=signed_in_as(viewer))


async def undo(api, viewer, post):
    return await api.delete(f"/posts/{post}/retweet", headers=signed_in_as(viewer))


async def feed(api, viewer, cursor=None):
    return await api.get(
        "/feed", headers=signed_in_as(viewer), params={"cursor": cursor} if cursor else {}
    )


async def test_e2_h5_ca2_retweeting_twice_leaves_one_row(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    first = await share(api, fan, post)
    async with app.state.session_factory() as session:
        at = (await session.get(RetweetModel, (fan, uuid.UUID(post)))).created_at
    second = await share(api, fan, post)
    assert (first.status_code, second.status_code) == (201, 204)
    assert first.content == second.content == b""
    assert (await read(api, fan, post))["retweetsCount"] == 1
    assert (await read(api, fan, post))["retweetedByMe"] is True
    assert (await read(api, author, post))["retweetedByMe"] is False
    async with app.state.session_factory() as session:
        assert (await session.get(RetweetModel, (fan, uuid.UUID(post)))).created_at == at


async def test_e2_h5_ca2_first_concurrent_retweets_bootstrap_one_profile_and_count_once(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    responses = await asyncio.gather(*(share(api, fan, post) for _ in range(5)))
    assert sorted(r.status_code for r in responses) == [201, 204, 204, 204, 204]
    assert (await read(api, author, post))["retweetsCount"] == 1


async def test_e2_h5_ca3_undo_takes_the_row_and_the_counter_down(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    await share(api, fan, post)
    responses = await asyncio.gather(*(undo(api, fan, post) for _ in range(5)))
    assert [r.status_code for r in responses] == [204] * 5
    assert (await read(api, fan, post))["retweetsCount"] == 0
    assert (await read(api, fan, post))["retweetedByMe"] is False
    async with app.state.session_factory() as session:
        assert await session.get(RetweetModel, (fan, uuid.UUID(post))) is None


async def test_e2_h5_ca3_undo_never_goes_below_zero(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    for _ in range(2):
        assert (await undo(api, fan, post)).status_code == 204
    assert (await read(api, author, post))["retweetsCount"] == 0


async def test_e2_h5_ca4_a_protected_post_cannot_be_retweeted_without_follow(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author, visibility="protected")
    created = await api.post(
        "/posts",
        json={"content": "privado"},
        headers=signed_in_as(author, profile_visibility="protected"),
    )
    post = created.json()["id"]
    assert (await share(api, fan, post)).status_code == 404
    await approve_follow(fan, author)
    assert (await share(api, fan, post)).status_code == 201


async def test_blocks_and_missing_posts_refuse_both_operations_with_the_same_error(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    await share(api, fan, post)
    await block(fan, author)
    for operation in (share, undo):
        missing = await operation(api, fan, uuid.uuid4())
        refused = await operation(api, fan, post)
        assert missing.status_code == refused.status_code == 404
        for field in ("type", "title", "detail", "status"):
            assert missing.json()[field] == refused.json()[field]
    assert (await read(api, author, post))["retweetsCount"] == 1


async def test_e2_h5_ca1_a_followed_retweet_shows_who_shared_it(api):
    author, fan, viewer = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    await approve_follow(viewer, fan)
    await share(api, fan, post)
    rows = (await feed(api, viewer)).json()["items"]
    assert len(rows) == 1
    assert rows[0]["id"] == post
    assert rows[0]["entryId"] == f"retweet:{fan}:{post}"
    assert rows[0]["retweetedBy"] == handle_of(fan)
    assert rows[0]["activityAt"] >= rows[0]["createdAt"]
    assert rows[0]["retweetedByMe"] is False
    await undo(api, fan, post)
    assert (await feed(api, viewer)).json()["items"] == []


async def test_retweets_never_grant_access_to_a_protected_original(api):
    author, fan, viewer = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author, visibility="protected")
    post = (
        await api.post(
            "/posts",
            json={"content": "privado"},
            headers=signed_in_as(author, profile_visibility="protected"),
        )
    ).json()["id"]
    await approve_follow(fan, author)
    await approve_follow(viewer, fan)
    await share(api, fan, post)
    assert (await feed(api, viewer)).json()["items"] == []
    await approve_follow(viewer, author)
    assert len((await feed(api, viewer)).json()["items"]) == 2
    await block(author, viewer)
    assert (await feed(api, viewer)).json()["items"] == []


async def test_a_blocked_sharer_disappears_even_when_the_original_is_public(api):
    author, fan, viewer = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    await approve_follow(viewer, fan)
    await share(api, fan, post)
    await block(viewer, fan)
    assert (await feed(api, viewer)).json()["items"] == []


async def test_own_posts_and_replies_can_be_shared_and_carry_reader_state(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    reply = (
        await api.post(
            f"/posts/{post}/replies", json={"content": "respuesta"}, headers=signed_in_as(author)
        )
    ).json()["id"]
    assert (await share(api, author, post)).status_code == 201
    assert (await share(api, author, reply)).status_code == 201
    replies = await api.get(f"/posts/{post}/replies", headers=signed_in_as(author))
    assert replies.json()["items"][0]["retweetedByMe"] is True
    await approve_follow(viewer, author)
    rows = (await feed(api, viewer)).json()["items"]
    assert len(rows) == 3
    assert len({r["entryId"] for r in rows}) == 3
    assert [r["id"] for r in rows].count(reply) == 1
    assert (await feed(api, author)).json()["items"] == []


async def test_activity_cursor_pages_repeated_posts_and_timestamp_ties_without_loss(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    fans = [uuid.uuid4() for _ in range(23)]
    await approve_follow(viewer, author)
    for fan in fans:
        await approve_follow(viewer, fan)
    responses = await asyncio.gather(*(share(api, fan, post) for fan in fans))
    assert all(r.status_code == 201 for r in responses)
    at = datetime.now(UTC)
    async with app.state.session_factory() as session:
        await session.execute(update(RetweetModel).values(created_at=at))
        await session.execute(update(PostModel).values(created_at=at))
        await session.commit()
    first = (await feed(api, viewer)).json()
    assert len(first["items"]) == 20
    await undo(api, fans[0], post)
    second = (await feed(api, viewer, first["nextCursor"])).json()
    ids = [r["entryId"] for r in first["items"] + second["items"]]
    assert len(ids) == len(set(ids))
    expected = {f"retweet:{fan}:{post}" for fan in fans} | {f"post:{post}"}
    assert expected - set(ids) <= {f"retweet:{fans[0]}:{post}"}
    assert second["nextCursor"] is None
    for row in first["items"]:
        assert row["retweetsCount"] == 23


async def test_recreating_a_retweet_gets_a_new_activity_date(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    await share(api, fan, post)
    old = datetime.now(UTC) - timedelta(days=10)
    async with app.state.session_factory() as session:
        await session.execute(update(RetweetModel).values(created_at=old))
        await session.commit()
    await undo(api, fan, post)
    await share(api, fan, post)
    async with app.state.session_factory() as session:
        assert (await session.scalar(select(RetweetModel))).created_at > old


async def test_retweets_require_authentication_and_a_valid_feed_cursor(api):
    post = uuid.uuid4()
    assert (await api.post(f"/posts/{post}/retweet")).status_code == 401
    assert (await api.delete(f"/posts/{post}/retweet")).status_code == 401
    assert (await feed(api, uuid.uuid4(), "invalid")).status_code == 400


async def test_a_retweet_of_old_content_is_ordered_by_the_share_date(api):
    author, fan, viewer = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    old_post = await publish(api, author, "old")
    async with app.state.session_factory() as session:
        await session.execute(
            update(PostModel).values(created_at=datetime.now(UTC) - timedelta(days=10))
        )
        await session.commit()
    new_post = await publish(api, author, "new")
    await approve_follow(viewer, author)
    await approve_follow(viewer, fan)
    await share(api, fan, old_post)
    rows = (await feed(api, viewer)).json()["items"]
    assert [r["id"] for r in rows] == [old_post, new_post, old_post]
    assert rows[0]["activityAt"] > rows[0]["createdAt"]
    assert rows[0]["createdAt"] == rows[2]["createdAt"]
