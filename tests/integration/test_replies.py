import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from posts_api.app.pagination import DEFAULT_PAGE_SIZE
from posts_api.infrastructure.database.models import (
    BlockModel,
    FollowModel,
    PostModel,
    UserProfileModel,
)
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, handle_of, signed_in_as

pytestmark = requires_services


async def publish(api, author: uuid.UUID, content: str = "original") -> str:
    created = await api.post("/posts", json={"content": content}, headers=signed_in_as(author))
    return created.json()["id"]


async def reply(api, author: uuid.UUID, post_id: str, content: str = "respuesta"):
    return await api.post(
        f"/posts/{post_id}/replies", json={"content": content}, headers=signed_in_as(author)
    )


async def insert_reply(author_id: uuid.UUID, parent_id: str, content: str, created_at: datetime):
    """A reply with a `created_at` set by hand: the order is what these tests read."""
    async with app.state.session_factory() as session:
        session.add(
            PostModel(
                author_id=author_id,
                parent_id=uuid.UUID(parent_id),
                content=content,
                created_at=created_at,
            )
        )
        await session.commit()


async def _ensure_profiles(*user_ids: uuid.UUID) -> None:
    """Profiles for the foreign keys, only for the ones the test has not made yet.

    Flushed before whatever is written next: nothing declares an ORM
    relationship between these tables, so the session cannot order the inserts
    by itself.
    """
    async with app.state.session_factory() as session:
        for user_id in user_ids:
            if await session.get(UserProfileModel, user_id) is None:
                session.add(UserProfileModel(id=user_id, handle=handle_of(user_id)))
        await session.commit()


async def block(blocker: uuid.UUID, blocked: uuid.UUID) -> None:
    await _ensure_profiles(blocker, blocked)
    async with app.state.session_factory() as session:
        session.add(BlockModel(blocker_id=blocker, blocked_id=blocked))
        await session.commit()


async def approve_follow(follower: uuid.UUID, followee: uuid.UUID) -> None:
    await _ensure_profiles(follower, followee)
    async with app.state.session_factory() as session:
        session.add(FollowModel(follower_id=follower, followee_id=followee))
        await session.commit()


async def contents_of_replies(api, viewer: uuid.UUID, post_id: str) -> list[str]:
    response = await api.get(f"/posts/{post_id}/replies", headers=signed_in_as(viewer))
    return [one["content"] for one in response.json()["items"]]


async def test_e2_h4_ca1_a_reply_points_to_the_original(api):
    author, replier = uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)

    created = await reply(api, replier, original)

    assert created.status_code == 201
    assert created.json()["parentId"] == original
    fetched = await api.get(f"/posts/{created.json()['id']}", headers=signed_in_as(author))
    assert fetched.json()["parentId"] == original
    # A post that answers nothing says so, instead of leaving the field out.
    untouched = await api.get(f"/posts/{original}", headers=signed_in_as(author))
    assert untouched.json()["parentId"] is None


async def test_e2_h4_ca2_a_reply_gets_the_same_checks_as_a_post(api):
    author, replier = uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)

    too_long = await reply(api, replier, original, "a" * 281)
    blank = await reply(api, replier, original, "   ")
    sanitized = await reply(api, replier, original, "hola <script>alert(1)</script>")

    assert too_long.status_code == 422
    assert too_long.json()["type"].endswith("/post-too-long")
    assert blank.status_code == 422
    assert blank.json()["type"].endswith("/post-is-blank")
    assert sanitized.status_code == 201
    assert "<script>" not in sanitized.json()["content"]

    # Posts and replies draw from the same hourly quota: the counter is the
    # one `POST /posts` charges, so a full one stops the reply too.
    await app.state.redis.set(f"post:rate:{replier}", 30, ex=3600)
    limited = await reply(api, replier, original)
    assert limited.status_code == 429
    assert limited.json()["type"].endswith("/too-many-posts")
    assert int(limited.headers["Retry-After"]) > 0


async def test_e2_h4_ca3_a_blocked_author_gets_the_generic_404(api):
    author, replier = uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)
    missing = await reply(api, replier, str(uuid.uuid4()))

    await block(author, replier)
    refused = await reply(api, replier, original)

    assert refused.status_code == 404
    assert refused.json()["type"].endswith("/post-not-found")
    # Same answer as for a post that was never there, so the status cannot be
    # read as confirmation that the block exists.
    for field in ("type", "title", "detail", "status"):
        assert refused.json()[field] == missing.json()[field]


async def test_e2_h4_ca3_a_block_in_the_other_direction_gets_it_too(api):
    author, replier = uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)

    await block(replier, author)
    refused = await reply(api, replier, original)

    assert refused.status_code == 404
    assert refused.json()["type"].endswith("/post-not-found")


async def test_a_protected_authors_post_cannot_be_answered_without_an_approved_follow(api):
    author, stranger, follower = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author, visibility="protected")
    created = await api.post(
        "/posts",
        json={"content": "solo aprobados"},
        headers=signed_in_as(author, profile_visibility="protected"),
    )
    original = created.json()["id"]
    await approve_follow(follower, author)

    refused = await reply(api, stranger, original)
    allowed = await reply(api, follower, original)

    assert refused.status_code == 404
    assert allowed.status_code == 201


async def test_a_refused_reply_leaves_the_counter_where_it_was(api):
    author, replier = uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)
    await block(author, replier)

    await reply(api, replier, original)

    fetched = await api.get(f"/posts/{original}", headers=signed_in_as(author))
    assert fetched.json()["repliesCount"] == 0


async def test_a_reply_counts_on_the_post_it_answers(api):
    author, first, second = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)

    await reply(api, first, original)
    await reply(api, second, original)

    fetched = await api.get(f"/posts/{original}", headers=signed_in_as(author))
    assert fetched.json()["repliesCount"] == 2


async def test_replies_that_land_together_are_all_counted(api):
    """Summed in SQL, so the five that arrive at once do not overwrite each other."""
    author = uuid.uuid4()
    original = await publish(api, author)
    repliers = [uuid.uuid4() for _ in range(5)]

    responses = await asyncio.gather(*(reply(api, one, original) for one in repliers))

    assert [one.status_code for one in responses] == [201] * 5
    fetched = await api.get(f"/posts/{original}", headers=signed_in_as(author))
    assert fetched.json()["repliesCount"] == 5


async def test_a_reply_can_be_answered_too(api):
    author, first, second = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)
    first_reply = (await reply(api, first, original)).json()["id"]

    nested = await reply(api, second, first_reply, "respuesta a la respuesta")

    assert nested.status_code == 201
    assert nested.json()["parentId"] == first_reply
    # Only the post that was answered counts it, not the whole thread above.
    parent = await api.get(f"/posts/{first_reply}", headers=signed_in_as(author))
    root = await api.get(f"/posts/{original}", headers=signed_in_as(author))
    assert parent.json()["repliesCount"] == 1
    assert root.json()["repliesCount"] == 1


async def test_a_reply_does_not_show_up_in_the_feed(api):
    author, replier = uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author, "el original")
    await approve_follow(replier, author)
    await approve_follow(author, replier)
    await reply(api, replier, original, "la respuesta")

    # The author follows the replier, so the reply would be right there if the
    # feed read it; the replier follows the author and still sees only the post.
    from_the_author = await api.get("/feed", headers=signed_in_as(author))
    from_the_replier = await api.get("/feed", headers=signed_in_as(replier))

    assert [one["content"] for one in from_the_author.json()["items"]] == []
    assert [one["content"] for one in from_the_replier.json()["items"]] == ["el original"]


async def test_e2_h4_ca4_replies_are_oldest_first_and_pages_at_twenty(api):
    author, replier, viewer = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)
    await given_a_profile(replier)
    base = datetime.now(UTC)
    # Inserted newest first on purpose: the order has to come from the query.
    for offset in reversed(range(DEFAULT_PAGE_SIZE + 5)):
        await insert_reply(replier, original, f"r{offset:02d}", base + timedelta(seconds=offset))

    first = await api.get(f"/posts/{original}/replies", headers=signed_in_as(viewer))
    first_body = first.json()
    assert first.status_code == 200
    assert [one["content"] for one in first_body["items"]] == [
        f"r{offset:02d}" for offset in range(DEFAULT_PAGE_SIZE)
    ]
    assert first_body["nextCursor"] is not None

    second = await api.get(
        f"/posts/{original}/replies?cursor={first_body['nextCursor']}",
        headers=signed_in_as(viewer),
    )
    second_body = second.json()

    assert [one["content"] for one in second_body["items"]] == [
        f"r{offset:02d}" for offset in range(DEFAULT_PAGE_SIZE, DEFAULT_PAGE_SIZE + 5)
    ]
    assert second_body["nextCursor"] is None


async def test_a_page_of_exactly_twenty_replies_has_no_next_page(api):
    author, replier = uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)
    await given_a_profile(replier)
    base = datetime.now(UTC)
    for offset in range(DEFAULT_PAGE_SIZE):
        await insert_reply(replier, original, f"r{offset}", base + timedelta(seconds=offset))

    response = await api.get(f"/posts/{original}/replies", headers=signed_in_as(author))

    assert len(response.json()["items"]) == DEFAULT_PAGE_SIZE
    assert response.json()["nextCursor"] is None


async def test_a_reply_listed_carries_the_shape_of_a_feed_row(api):
    author, replier = uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)
    await reply(api, replier, original)

    response = await api.get(f"/posts/{original}/replies", headers=signed_in_as(author))

    row = response.json()["items"][0]
    assert set(row) == {
        "id",
        "authorId",
        "authorHandle",
        "authorDisplayName",
        "authorAvatarUrl",
        "content",
        "deleted",
        "createdAt",
        "likesCount",
        "retweetsCount",
        "repliesCount",
        "parentId",
        "likedByMe",
        "retweetedByMe",
        "retweetedBy",
        "entryId",
        "activityAt",
        "images",
    }
    assert row["authorHandle"] == handle_of(replier)
    assert row["parentId"] == original


async def test_a_post_without_replies_lists_an_empty_page(api):
    author = uuid.uuid4()
    original = await publish(api, author)

    response = await api.get(f"/posts/{original}/replies", headers=signed_in_as(author))

    assert response.json() == {"items": [], "nextCursor": None}


async def test_the_replies_of_a_missing_or_unreadable_post_are_the_generic_404(api):
    author, stranger = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author, visibility="protected")
    created = await api.post(
        "/posts",
        json={"content": "solo aprobados"},
        headers=signed_in_as(author, profile_visibility="protected"),
    )
    hidden = created.json()["id"]
    await given_a_profile(stranger)

    missing = await api.get(f"/posts/{uuid.uuid4()}/replies", headers=signed_in_as(stranger))
    refused = await api.get(f"/posts/{hidden}/replies", headers=signed_in_as(stranger))

    assert (missing.status_code, refused.status_code) == (404, 404)
    assert refused.json()["type"].endswith("/post-not-found")
    for field in ("type", "title", "detail", "status"):
        assert refused.json()[field] == missing.json()[field]


async def test_a_blocked_account_cannot_list_the_replies_of_the_one_that_blocked_it(api):
    author, blocked = uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)
    await block(author, blocked)

    response = await api.get(f"/posts/{original}/replies", headers=signed_in_as(blocked))

    assert response.status_code == 404


async def test_replies_from_an_account_the_viewer_blocked_are_left_out(api):
    author, viewer, blocked, other = (uuid.uuid4() for _ in range(4))
    original = await publish(api, author)
    await reply(api, blocked, original, "del bloqueado")
    await reply(api, other, original, "de otro")
    await block(viewer, blocked)

    assert await contents_of_replies(api, viewer, original) == ["de otro"]
    # The other direction, too: the blocked account no longer reads the reply
    # of whoever blocked them, so the filter is not one-sided. Their own reply
    # stays readable to them.
    await reply(api, viewer, original, "del que bloquea")
    assert await contents_of_replies(api, blocked, original) == ["del bloqueado", "de otro"]


async def test_replies_from_a_protected_account_need_an_approved_follow(api):
    author, replier, stranger, follower = (uuid.uuid4() for _ in range(4))
    original = await publish(api, author)
    await given_a_profile(replier, visibility="protected")
    await api.post(
        f"/posts/{original}/replies",
        json={"content": "protegida"},
        headers=signed_in_as(replier, profile_visibility="protected"),
    )
    await reply(api, stranger, original, "pública")
    await approve_follow(follower, replier)

    assert await contents_of_replies(api, author, original) == ["pública"]
    assert sorted(await contents_of_replies(api, follower, original)) == ["protegida", "pública"]


async def test_replying_and_listing_need_a_token(api):
    original = uuid.uuid4()

    created = await api.post(f"/posts/{original}/replies", json={"content": "hola"})
    listed = await api.get(f"/posts/{original}/replies")

    assert (created.status_code, listed.status_code) == (401, 401)


async def test_a_garbled_cursor_on_the_replies_is_a_400(api):
    author = uuid.uuid4()
    original = await publish(api, author)

    response = await api.get(
        f"/posts/{original}/replies?cursor=not-a-real-cursor", headers=signed_in_as(author)
    )

    assert response.status_code == 400
    assert response.json()["type"].endswith("/invalid-cursor")


async def test_the_replies_query_can_be_answered_with_an_index(api):
    """The table is empty here, so PostgreSQL would pick a sequential scan whatever
    indexes exist; turning it off shows whether the partial index matches the
    query's columns, which is what this is after."""
    async with app.state.session_factory() as session:
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = await session.execute(
            text(
                "EXPLAIN SELECT * FROM posts WHERE parent_id = :parent "
                "ORDER BY created_at, id LIMIT :limit"
            ),
            {"parent": str(uuid.uuid4()), "limit": DEFAULT_PAGE_SIZE + 1},
        )
        plan_text = "\n".join(row[0] for row in plan)

    assert "ix_posts_parent_created" in plan_text
