import uuid

from sqlalchemy import select

from posts_api.infrastructure.database.models import PostHashtagModel
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import signed_in_as

pytestmark = requires_services


async def publish(api, author: uuid.UUID, content: str):
    return await api.post("/posts", json={"content": content}, headers=signed_in_as(author))


async def stored_hashtags(post_id: str) -> list[str]:
    async with app.state.session_factory() as session:
        rows = await session.scalars(
            select(PostHashtagModel.tag)
            .where(PostHashtagModel.post_id == uuid.UUID(post_id))
            .order_by(PostHashtagModel.tag)
        )
        return list(rows)


async def test_e2_h8_ca1_a_post_stores_its_hashtags(api):
    response = await publish(api, uuid.uuid4(), "Primer día #UdeSA #tds")

    assert response.status_code == 201
    assert await stored_hashtags(response.json()["id"]) == ["tds", "udesa"]


async def test_e2_h8_ca1_a_reply_stores_its_hashtags(api):
    author = uuid.uuid4()
    parent = (await publish(api, author, "post")).json()["id"]

    reply = await api.post(
        f"/posts/{parent}/replies", json={"content": "respuesta #Tds"}, headers=signed_in_as(author)
    )

    assert reply.status_code == 201
    assert await stored_hashtags(reply.json()["id"]) == ["tds"]


async def test_a_post_without_hashtags_stores_none(api):
    response = await publish(api, uuid.uuid4(), "a#b y ##c no cuentan")

    assert response.status_code == 201
    assert await stored_hashtags(response.json()["id"]) == []


async def test_e2_h8_ca4_ten_distinct_hashtags_are_accepted(api):
    content = " ".join(f"#t{n}" for n in range(10))

    response = await publish(api, uuid.uuid4(), content)

    assert response.status_code == 201
    assert len(await stored_hashtags(response.json()["id"])) == 10


async def test_e2_h8_ca4_eleven_hashtags_are_rejected(api):
    author = uuid.uuid4()
    content = " ".join(f"#t{n}" for n in range(11))

    response = await publish(api, author, content)

    assert response.status_code == 422
    assert response.json()["type"].endswith("/too-many-hashtags")
    async with app.state.session_factory() as session:
        assert await session.scalar(select(PostHashtagModel.tag).limit(1)) is None


async def test_e2_h8_ca4_a_repeated_hashtag_counts_once(api):
    content = " ".join(["#igual"] * 11)

    response = await publish(api, uuid.uuid4(), content)

    assert response.status_code == 201
    assert await stored_hashtags(response.json()["id"]) == ["igual"]


async def test_e2_h8_ca5_upper_and_lower_case_are_the_same_hashtag(api):
    response = await publish(api, uuid.uuid4(), "#UdeSA #udesa #UDESA")

    assert response.status_code == 201
    assert await stored_hashtags(response.json()["id"]) == ["udesa"]


async def test_deleting_a_post_removes_its_hashtags(api):
    author = uuid.uuid4()
    post = (await publish(api, author, "adiós #tds")).json()["id"]

    response = await api.delete(f"/posts/{post}", headers=signed_in_as(author))

    assert response.status_code == 204
    assert await stored_hashtags(post) == []
