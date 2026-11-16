import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import event

from posts_api.infrastructure.database.models import (
    FollowModel,
    PostHashtagModel,
    PostModel,
    UserProfileModel,
)
from posts_api.infrastructure.redis.trending_cache import KEY
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, handle_of, signed_in_as

pytestmark = requires_services


async def insert_post(
    author: uuid.UUID,
    tags: list[str],
    *,
    created_at: datetime | None = None,
    parent: uuid.UUID | None = None,
    deleted: bool = False,
) -> uuid.UUID:
    async with app.state.session_factory() as session:
        post = PostModel(
            author_id=author,
            content=" ".join(f"#{tag}" for tag in tags) or "sin hashtags",
            created_at=created_at or datetime.now(UTC),
            parent_id=parent,
            deleted_at=datetime.now(UTC) if deleted else None,
        )
        session.add(post)
        await session.flush()
        session.add_all([PostHashtagModel(post_id=post.id, tag=tag) for tag in tags])
        await session.commit()
        return post.id


async def close_profile(user_id: uuid.UUID) -> None:
    async with app.state.session_factory() as session:
        session.add(
            UserProfileModel(
                id=user_id,
                handle=handle_of(user_id),
                deleted_at=datetime.now(UTC),
            )
        )
        await session.commit()


async def trending(api, viewer: uuid.UUID):
    return await api.get("/trending", headers=signed_in_as(viewer))


async def trending_tags(api, viewer: uuid.UUID) -> list[str]:
    return [item["tag"] for item in (await trending(api, viewer)).json()]


async def test_e2_h11_ca1_a_post_from_the_last_24_hours_counts(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    await insert_post(author, ["udesa"], created_at=datetime.now(UTC) - timedelta(hours=23))

    response = await trending(api, viewer)

    assert response.json() == [{"tag": "udesa", "count": 1}]


async def test_e2_h11_ca1_a_post_older_than_24_hours_does_not_count(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    await insert_post(author, ["viejo"], created_at=datetime.now(UTC) - timedelta(hours=25))
    await insert_post(author, ["nuevo"])

    assert await trending_tags(api, viewer) == ["nuevo"]


async def test_e2_h11_ca1_replies_count(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    parent = await insert_post(author, ["tds"])
    await insert_post(author, ["tds"], parent=parent)

    response = await trending(api, viewer)

    assert response.json() == [{"tag": "tds", "count": 2}]


async def test_e2_h11_ca1_deleted_posts_do_not_count(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    await insert_post(author, ["borrado"], deleted=True)

    assert await trending_tags(api, viewer) == []


async def test_e2_h11_ca1_posts_of_protected_authors_do_not_count(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author, visibility="protected")
    await insert_post(author, ["privado"])

    assert await trending_tags(api, viewer) == []


async def test_e2_h11_ca1_a_protected_author_does_not_count_even_for_a_follower(api):
    author, follower = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author, visibility="protected")
    await given_a_profile(follower)
    async with app.state.session_factory() as session:
        session.add(FollowModel(follower_id=follower, followee_id=author))
        await session.commit()
    await insert_post(author, ["privado"])

    assert await trending_tags(api, follower) == []
    assert await trending_tags(api, uuid.uuid4()) == []


async def test_e2_h11_ca1_posts_of_deleted_authors_do_not_count(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    await close_profile(author)
    await insert_post(author, ["cerrada"])

    assert await trending_tags(api, viewer) == []


async def test_e2_h11_ca1_a_tag_repeated_in_one_post_counts_once(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    await api.post("/posts", json={"content": "#udesa #UDESA"}, headers=signed_in_as(author))

    response = await trending(api, viewer)

    assert response.json() == [{"tag": "udesa", "count": 1}]


async def test_e2_h11_ca2_the_ten_most_used_topics_are_kept_whatever_their_name(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    for number in range(11):
        await insert_post(author, [f"a{number:02d}"])
    for _ in range(3):
        await insert_post(author, ["zzz"])

    topics = (await trending(api, viewer)).json()

    assert len(topics) == 10
    assert topics[0] == {"tag": "zzz", "count": 3}


async def test_e2_h11_ca2_topics_are_ordered_by_count_then_tag(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    for tags in (["beta"], ["beta"], ["beta"], ["gama"], ["gama"], ["alfa"], ["alfa"], ["zeta"]):
        await insert_post(author, tags)

    response = await trending(api, viewer)

    assert response.json() == [
        {"tag": "beta", "count": 3},
        {"tag": "alfa", "count": 2},
        {"tag": "gama", "count": 2},
        {"tag": "zeta", "count": 1},
    ]


async def test_e2_h11_ca2_without_posts_the_ranking_is_empty(api):
    assert (await trending(api, uuid.uuid4())).json() == []


async def test_e2_h11_ca2_the_endpoint_requires_a_token(api):
    assert (await api.get("/trending")).status_code == 401


async def test_e2_h11_ca3_the_second_call_is_served_without_querying_the_database(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    await insert_post(author, ["udesa"])
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "post_hashtags" in statement:
            statements.append(statement)

    event.listen(app.state.engine.sync_engine, "before_cursor_execute", record)
    try:
        first = await trending(api, viewer)
        asked_by_first_call = len(statements)
        second = await trending(api, viewer)
    finally:
        event.remove(app.state.engine.sync_engine, "before_cursor_execute", record)

    assert asked_by_first_call == 1
    assert len(statements) == asked_by_first_call
    assert second.json() == first.json()


async def test_e2_h11_ca3_the_entry_is_written_with_a_ttl_of_900_seconds(api):
    await trending(api, uuid.uuid4())

    ttl = await app.state.redis.ttl(KEY)

    assert 890 <= ttl <= 900


async def test_e2_h11_ca3_once_the_entry_expires_the_ranking_is_computed_again(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    await insert_post(author, ["udesa"])
    assert await trending_tags(api, viewer) == ["udesa"]
    await insert_post(author, ["tds"])
    assert await trending_tags(api, viewer) == ["udesa"]

    await app.state.redis.delete(KEY)

    assert await trending_tags(api, viewer) == ["tds", "udesa"]
