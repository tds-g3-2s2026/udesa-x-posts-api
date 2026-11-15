import uuid

from sqlalchemy import func, select, update

from posts_api.app.repositories.posts import PostRepository
from posts_api.infrastructure.database.models import (
    FollowModel,
    PostMentionModel,
    PostModel,
    UserProfileModel,
)
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, handle_of, signed_in_as

pytestmark = requires_services


async def publish(api, author: uuid.UUID, content: str):
    return await api.post("/posts", json={"content": content}, headers=signed_in_as(author))


async def stored_mentions(post_id: str) -> list[uuid.UUID]:
    async with app.state.session_factory() as session:
        rows = await session.scalars(
            select(PostMentionModel.user_id).where(PostMentionModel.post_id == uuid.UUID(post_id))
        )
        return sorted(rows)


async def test_a_post_stores_the_accounts_it_mentions(api):
    author, ana, beto = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_a_profile(ana)
    await given_a_profile(beto)

    response = await publish(api, author, f"Con {handle_of(ana)} y {handle_of(beto)} en la UdeSA")

    assert response.status_code == 201
    assert await stored_mentions(response.json()["id"]) == sorted([ana, beto])


async def test_a_reply_stores_its_mentions(api):
    author, ana = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(ana)
    parent = (await publish(api, author, "post")).json()["id"]

    reply = await api.post(
        f"/posts/{parent}/replies",
        json={"content": f"respuesta para {handle_of(ana)}"},
        headers=signed_in_as(author),
    )

    assert reply.status_code == 201
    assert await stored_mentions(reply.json()["id"]) == [ana]


async def test_a_handle_nobody_has_is_not_stored(api):
    author, ana = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(ana)

    response = await publish(api, author, f"{handle_of(ana)} y @nadie_aca")

    assert response.status_code == 201
    assert await stored_mentions(response.json()["id"]) == [ana]


async def test_a_handle_is_matched_without_regard_to_case(api):
    author, ana = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(ana)

    response = await publish(api, author, f"Hola {handle_of(ana).upper()}")

    assert response.status_code == 201
    assert await stored_mentions(response.json()["id"]) == [ana]


async def test_a_closed_account_is_not_stored(api):
    author, ana = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(ana)
    async with app.state.session_factory() as session:
        await session.execute(
            update(UserProfileModel).where(UserProfileModel.id == ana).values(deleted_at=func.now())
        )
        await session.commit()

    response = await publish(api, author, f"Hola {handle_of(ana)}")

    assert response.status_code == 201
    assert await stored_mentions(response.json()["id"]) == []


async def test_an_author_can_mention_themselves(api):
    author = uuid.uuid4()

    response = await publish(api, author, f"Soy {handle_of(author)}")

    assert response.status_code == 201
    assert await stored_mentions(response.json()["id"]) == [author]


async def test_a_deleted_post_keeps_no_mentions(api):
    author, ana = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(ana)
    post = (await publish(api, author, f"Hola {handle_of(ana)}")).json()["id"]

    response = await api.delete(f"/posts/{post}", headers=signed_in_as(author))

    assert response.status_code == 204
    assert await stored_mentions(post) == []


async def test_replacing_the_content_of_a_post_drops_its_mentions(api):
    author, ana = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(ana)
    post = (await publish(api, author, f"Hola {handle_of(ana)}")).json()["id"]

    async with app.state.session_factory() as session:
        await PostRepository(session).replace_content(uuid.UUID(post), "[removed]")
        await session.commit()

    assert await stored_mentions(post) == []


async def test_ten_distinct_mentions_are_accepted(api):
    content = " ".join(f"@user{n:04d}" for n in range(10))

    response = await publish(api, uuid.uuid4(), content)

    assert response.status_code == 201


async def test_eleven_mentions_are_rejected(api):
    content = " ".join(f"@user{n:04d}" for n in range(11))

    response = await publish(api, uuid.uuid4(), content)

    assert response.status_code == 422
    assert response.json()["type"].endswith("/too-many-mentions")
    async with app.state.session_factory() as session:
        assert await session.scalar(select(PostModel.id).limit(1)) is None


async def test_a_repeated_mention_counts_once(api):
    content = " ".join(["@igual_00"] * 11)

    response = await publish(api, uuid.uuid4(), content)

    assert response.status_code == 201


def listed(handle: str) -> str:
    """The handle the way the app compares it: lower-case and without the `@`."""
    return handle.removeprefix("@").lower()


async def detail_of(api, reader: uuid.UUID, post_id: str) -> dict:
    response = await api.get(f"/posts/{post_id}", headers=signed_in_as(reader))
    assert response.status_code == 200
    return response.json()


async def test_e2_h9_ca1_a_post_returns_the_accounts_it_mentions(api):
    author, ana, beto = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_a_profile(ana)
    await given_a_profile(beto)
    post = (await publish(api, author, f"Con {handle_of(ana)} y {handle_of(beto)}")).json()["id"]

    detail = await detail_of(api, author, post)

    # Ordered by handle, which the test cannot know in advance: compare as a set.
    assert {(one["id"], one["handle"]) for one in detail["mentions"]} == {
        (str(ana), listed(handle_of(ana))),
        (str(beto), listed(handle_of(beto))),
    }
    assert len(detail["mentions"]) == 2


async def test_e2_h9_ca2_an_unknown_handle_is_not_a_mention(api):
    author, ana = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(ana)
    post = (await publish(api, author, f"{handle_of(ana)} y @nadie_aca")).json()["id"]
    nobody = (await publish(api, author, "Hola @nadie_aca")).json()["id"]

    assert (await detail_of(api, author, post))["mentions"] == [
        {"id": str(ana), "handle": listed(handle_of(ana))}
    ]
    assert (await detail_of(api, author, nobody))["mentions"] == []


async def test_the_feed_the_profile_and_the_replies_carry_the_mentions(api):
    author, reader, ana = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for account in (author, reader, ana):
        await given_a_profile(account)
    async with app.state.session_factory() as session:
        session.add(FollowModel(follower_id=reader, followee_id=author))
        await session.commit()
    mention = {"id": str(ana), "handle": listed(handle_of(ana))}
    post = (await publish(api, author, f"Hola {handle_of(ana)}")).json()["id"]
    reply = await api.post(
        f"/posts/{post}/replies",
        json={"content": f"Otra vez {handle_of(ana)}"},
        headers=signed_in_as(author),
    )
    assert reply.status_code == 201

    feed = await api.get("/feed", headers=signed_in_as(reader))
    profile = await api.get(f"/users/{author}/posts", headers=signed_in_as(reader))
    replies = await api.get(f"/posts/{post}/replies", headers=signed_in_as(reader))

    assert [one["mentions"] for one in feed.json()["items"]] == [[mention]]
    assert [one["mentions"] for one in profile.json()["items"]] == [[mention]]
    assert [one["mentions"] for one in replies.json()["items"]] == [[mention]]


async def test_a_post_without_mentions_returns_an_empty_list(api):
    author = uuid.uuid4()
    post = (await publish(api, author, "Sin nadie")).json()["id"]

    assert (await detail_of(api, author, post))["mentions"] == []


async def test_an_account_closed_after_the_post_is_not_a_mention_any_more(api):
    author, ana = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(ana)
    post = (await publish(api, author, f"Hola {handle_of(ana)}")).json()["id"]
    async with app.state.session_factory() as session:
        await session.execute(
            update(UserProfileModel).where(UserProfileModel.id == ana).values(deleted_at=func.now())
        )
        await session.commit()

    assert (await detail_of(api, author, post))["mentions"] == []


async def test_a_deleted_post_returns_no_mentions(api):
    author, ana = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(ana)
    post = (await publish(api, author, f"Hola {handle_of(ana)}")).json()["id"]
    await api.delete(f"/posts/{post}", headers=signed_in_as(author))

    detail = await detail_of(api, author, post)

    assert detail["deleted"] is True
    assert detail["mentions"] == []
