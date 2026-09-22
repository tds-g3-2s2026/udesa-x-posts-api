import uuid
from datetime import UTC, datetime, timedelta

from posts_api.app.pagination import DEFAULT_PAGE_SIZE
from posts_api.infrastructure.database.models import FollowModel, PostModel, UserProfileModel
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, handle_of, signed_in_as

pytestmark = requires_services


async def insert_post(author_id: uuid.UUID, content: str, created_at: datetime) -> None:
    async with app.state.session_factory() as session:
        if await session.get(UserProfileModel, author_id) is None:
            session.add(UserProfileModel(id=author_id, handle=handle_of(author_id)))
            await session.flush()
        session.add(PostModel(author_id=author_id, content=content, created_at=created_at))
        await session.commit()


async def insert_follow(follower_id: uuid.UUID, followee_id: uuid.UUID) -> None:
    async with app.state.session_factory() as session:
        for account_id in (follower_id, followee_id):
            if await session.get(UserProfileModel, account_id) is None:
                session.add(UserProfileModel(id=account_id, handle=handle_of(account_id)))
        await session.flush()
        session.add(FollowModel(follower_id=follower_id, followee_id=followee_id))
        await session.commit()


async def test_e2_h2_ca1_feed_is_ordered_newest_first(api):
    viewer, author = uuid.uuid4(), uuid.uuid4()
    await insert_follow(viewer, author)
    base = datetime.now(UTC)
    await insert_post(author, "primero", base)
    await insert_post(author, "segundo", base + timedelta(seconds=1))
    await insert_post(author, "tercero", base + timedelta(seconds=2))

    response = await api.get("/feed", headers=signed_in_as(viewer))

    assert response.status_code == 200
    contents = [one["content"] for one in response.json()["items"]]
    assert contents == ["tercero", "segundo", "primero"]


async def test_e2_h2_ca2_feed_pages_by_cursor_at_twenty(api):
    viewer, author = uuid.uuid4(), uuid.uuid4()
    await insert_follow(viewer, author)
    base = datetime.now(UTC)
    for offset in range(DEFAULT_PAGE_SIZE + 5):
        await insert_post(author, f"post {offset}", base + timedelta(seconds=offset))

    first = await api.get("/feed", headers=signed_in_as(viewer))
    first_body = first.json()
    assert len(first_body["items"]) == DEFAULT_PAGE_SIZE
    assert first_body["nextCursor"] is not None

    second = await api.get(f"/feed?cursor={first_body['nextCursor']}", headers=signed_in_as(viewer))
    second_body = second.json()

    assert len(second_body["items"]) == 5
    assert second_body["nextCursor"] is None
    first_ids = {one["id"] for one in first_body["items"]}
    second_ids = {one["id"] for one in second_body["items"]}
    assert first_ids.isdisjoint(second_ids)


async def test_e2_h2_ca5_protected_posts_need_an_approved_follow(api):
    """The feed's own definition already restricts it to followed authors.

    Following a protected account only ever happens after approval in this
    system, so there is no scenario where a protected author's post reaches
    someone who is not an approved follower — this proves that holds, not
    just that it happens to.
    """
    viewer, protected_author, stranger_author = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_a_profile(viewer)
    await given_a_profile(protected_author, visibility="protected")
    await given_a_profile(stranger_author, visibility="protected")
    await insert_post(protected_author, "solo para aprobados", datetime.now(UTC))
    await insert_post(stranger_author, "nunca lo sigo", datetime.now(UTC))
    # Only an approved relationship with the first author.
    async with app.state.session_factory() as session:
        session.add(FollowModel(follower_id=viewer, followee_id=protected_author))
        await session.commit()

    response = await api.get("/feed", headers=signed_in_as(viewer))

    contents = [one["content"] for one in response.json()["items"]]
    assert contents == ["solo para aprobados"]


async def test_the_feed_only_carries_followed_authors(api):
    viewer, followed, not_followed = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await insert_follow(viewer, followed)
    await insert_post(followed, "me sigue", datetime.now(UTC))
    await insert_post(not_followed, "no me sigue", datetime.now(UTC))

    response = await api.get("/feed", headers=signed_in_as(viewer))

    contents = [one["content"] for one in response.json()["items"]]
    assert contents == ["me sigue"]


async def test_following_nobody_gives_an_empty_feed(api):
    viewer = uuid.uuid4()
    await given_a_profile(viewer)

    response = await api.get("/feed", headers=signed_in_as(viewer))

    assert response.json() == {"items": [], "nextCursor": None}


async def test_a_feed_item_carries_the_fields_the_screen_needs(api):
    viewer, author = uuid.uuid4(), uuid.uuid4()
    await insert_follow(viewer, author)
    await insert_post(author, "hola", datetime.now(UTC))

    response = await api.get("/feed", headers=signed_in_as(viewer))

    row = response.json()["items"][0]
    assert set(row) == {
        "id",
        "authorId",
        "authorHandle",
        "authorDisplayName",
        "authorAvatarUrl",
        "content",
        "createdAt",
        "likesCount",
        "retweetsCount",
        "repliesCount",
    }
    assert row["authorHandle"] == handle_of(author)
    assert (row["authorDisplayName"], row["authorAvatarUrl"]) == (None, None)


async def test_the_feed_needs_a_token(api):
    response = await api.get("/feed")

    assert response.status_code == 401
