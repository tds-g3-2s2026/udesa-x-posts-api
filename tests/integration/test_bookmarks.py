"""Bookmarks: each viewer keeps a private list of the posts they saved."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select

from posts_api.app.pagination import DEFAULT_PAGE_SIZE
from posts_api.infrastructure.database.models import BookmarkModel, OutboxModel
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, signed_in_as
from tests.integration.test_likes import approve_follow, block, publish, read
from tests.integration.test_profile_posts import insert_post
from tests.integration.test_user_deleted import close_account
from tests.integration.test_visibility_events import announce

pytestmark = requires_services


async def save(api, viewer: uuid.UUID, post_id) -> httpx.Response:
    return await api.put(f"/posts/{post_id}/bookmark", headers=signed_in_as(viewer))


async def unsave(api, viewer: uuid.UUID, post_id) -> httpx.Response:
    return await api.delete(f"/posts/{post_id}/bookmark", headers=signed_in_as(viewer))


async def listing(api, viewer: uuid.UUID, cursor: str | None = None) -> httpx.Response:
    return await api.get(
        "/bookmarks", headers=signed_in_as(viewer), params={"cursor": cursor} if cursor else {}
    )


async def count(model, *where) -> int:
    async with app.state.session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model).where(*where))


def listing_parameters() -> set[str]:
    paths = app.openapi()["paths"]
    [path] = [one for one in paths if one.endswith("/bookmarks")]
    return {param["name"] for param in paths[path]["get"].get("parameters", [])}


async def test_e2_h12_ca1_saving_and_removing_are_idempotent(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)

    first = await save(api, fan, post)
    second = await save(api, fan, post)

    assert (first.status_code, second.status_code) == (204, 204)
    assert await count(BookmarkModel) == 1
    assert [one["id"] for one in (await listing(api, fan)).json()["items"]] == [post]
    assert (await read(api, fan, post))["savedByMe"] is True

    taken_off = await unsave(api, fan, post)
    taken_off_again = await unsave(api, fan, post)

    assert (taken_off.status_code, taken_off_again.status_code) == (204, 204)
    assert (await listing(api, fan)).json()["items"] == []
    assert (await read(api, fan, post))["savedByMe"] is False


async def test_e2_h12_ca2_nobody_else_can_read_the_list(api):
    owner, nosy = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, owner)
    await save(api, owner, post)

    theirs = await listing(api, nosy)

    assert theirs.status_code == 200
    assert theirs.json()["items"] == []
    assert [one["id"] for one in (await listing(api, owner)).json()["items"]] == [post]
    # No route hands out somebody else's list: there is no user in the path or the query.
    assert (
        await api.get(f"/users/{owner}/bookmarks", headers=signed_in_as(nosy))
    ).status_code == 404
    # Pins the query parameters so a user id can never be accepted.
    assert listing_parameters() == {"cursor"}


async def test_e2_h12_ca2_saving_does_not_notify_the_author(api):
    author, fan, followee = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    # Positive control: following writes an outbox row, so the counter does see writes.
    await given_a_profile(followee)
    outbox_at_start = await count(OutboxModel)
    assert (
        await api.post(f"/users/{followee}/follow", headers=signed_in_as(fan))
    ).status_code == 204
    assert await count(OutboxModel) == outbox_at_start + 1
    outbox_before = await count(OutboxModel)

    assert (await save(api, fan, post)).status_code == 204

    assert await count(OutboxModel) == outbox_before


async def test_e2_h12_ca3_newest_saved_first_with_a_cursor(api):
    viewer, author = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    base = datetime.now(UTC)
    posts = [
        await insert_post(author, f"post {offset}", base + timedelta(minutes=offset))
        for offset in range(DEFAULT_PAGE_SIZE + 1)
    ]
    # Saved out of the posts' own order: the list follows the moment of saving.
    save_order = posts[::2] + posts[1::2]
    for post in save_order:
        assert (await save(api, viewer, post)).status_code == 204
    expected = [str(post) for post in reversed(save_order)]

    first = (await listing(api, viewer)).json()
    second = (await listing(api, viewer, cursor=first["nextCursor"])).json()

    assert len(first["items"]) == DEFAULT_PAGE_SIZE
    assert first["nextCursor"] is not None
    assert [one["id"] for one in first["items"]] == expected[:DEFAULT_PAGE_SIZE]
    assert [one["id"] for one in second["items"]] == expected[DEFAULT_PAGE_SIZE:]
    assert second["nextCursor"] is None


async def test_a_saved_post_hides_while_its_author_is_protected_and_returns_after_the_follow(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    await save(api, viewer, post)

    await announce(author, "protected")

    assert (await listing(api, viewer)).json()["items"] == []
    # The bookmark itself stays: only the visibility changed.
    assert await count(BookmarkModel, BookmarkModel.user_id == viewer) == 1

    await approve_follow(viewer, author)

    assert [one["id"] for one in (await listing(api, viewer)).json()["items"]] == [post]


async def test_a_deleted_post_leaves_the_list(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    await save(api, fan, post)

    await api.delete(f"/posts/{post}", headers=signed_in_as(author))

    assert (await listing(api, fan)).json()["items"] == []


async def test_removing_a_bookmark_of_a_post_that_is_no_longer_visible_still_answers_204(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    await save(api, fan, post)
    await announce(author, "protected")

    removed = await unsave(api, fan, post)

    assert removed.status_code == 204
    assert await count(BookmarkModel, BookmarkModel.user_id == fan) == 0


async def test_saving_a_post_the_viewer_cannot_read_answers_not_found(api):
    author, blocked, stranger, outsider = (uuid.uuid4() for _ in range(4))
    public = await publish(api, author)
    await block(author, blocked)
    await given_a_profile(stranger, visibility="protected")
    private_post = str(await insert_post(stranger, "solo para seguidores", datetime.now(UTC)))
    deleted = await publish(api, outsider)
    await api.delete(f"/posts/{deleted}", headers=signed_in_as(outsider))

    refused = [
        await save(api, blocked, public),
        await save(api, outsider, private_post),
        await save(api, outsider, deleted),
        await save(api, outsider, str(uuid.uuid4())),
    ]

    assert [one.status_code for one in refused] == [404] * 4
    assert refused[0].json()["type"].endswith("/post-not-found")
    assert await count(BookmarkModel) == 0


async def test_saving_again_keeps_the_original_position(api):
    viewer, author = uuid.uuid4(), uuid.uuid4()
    first_post = await publish(api, author, "primero")
    second_post = await publish(api, author, "segundo")
    await save(api, viewer, first_post)
    await save(api, viewer, second_post)

    assert (await save(api, viewer, first_post)).status_code == 204

    assert [one["id"] for one in (await listing(api, viewer)).json()["items"]] == [
        second_post,
        first_post,
    ]


async def test_saved_by_me_is_reported_on_feed_profile_posts_and_detail(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    saved = await publish(api, author, "guardado")
    not_saved = await publish(api, author, "no guardado")
    await approve_follow(viewer, author)
    await save(api, viewer, saved)

    feed = (await api.get("/feed", headers=signed_in_as(viewer))).json()["items"]
    profile = (await api.get(f"/users/{author}/posts", headers=signed_in_as(viewer))).json()[
        "items"
    ]
    detail = await read(api, viewer, saved)

    flags = {one["id"]: one["savedByMe"] for one in feed}
    assert flags == {saved: True, not_saved: False}
    assert {one["id"]: one["savedByMe"] for one in profile} == {saved: True, not_saved: False}
    assert detail["savedByMe"] is True
    assert (await read(api, author, saved))["savedByMe"] is False


async def test_deleting_the_post_removes_its_bookmarks(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    await save(api, fan, post)

    await api.delete(f"/posts/{post}", headers=signed_in_as(author))

    assert await count(BookmarkModel, BookmarkModel.post_id == uuid.UUID(post)) == 0


async def test_closing_the_account_removes_its_bookmarks(api):
    author, leaving, staying = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    await save(api, leaving, post)
    await save(api, staying, post)

    await close_account(leaving)

    assert await count(BookmarkModel, BookmarkModel.user_id == leaving) == 0
    assert await count(BookmarkModel, BookmarkModel.user_id == staying) == 1


async def test_a_saved_post_leaves_the_list_when_its_author_closes_the_account(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    await save(api, fan, post)

    await close_account(author)

    assert (await listing(api, fan)).json()["items"] == []


async def test_an_invalid_cursor_answers_bad_request(api):
    viewer = uuid.uuid4()

    response = await listing(api, viewer, cursor="no-es-un-cursor")

    assert response.status_code == 400
    assert response.json()["type"].endswith("/invalid-cursor")
