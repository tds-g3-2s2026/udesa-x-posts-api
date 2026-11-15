import uuid

from sqlalchemy import func, select, update

from posts_api.app.repositories.posts import PostRepository
from posts_api.infrastructure.database.models import (
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
