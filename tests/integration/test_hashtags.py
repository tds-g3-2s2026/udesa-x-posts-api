import uuid

from sqlalchemy import select

from posts_api.infrastructure.database.models import BlockModel, PostHashtagModel
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, signed_in_as

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


async def search(api, viewer: uuid.UUID, query: str, **params):
    return await api.get(
        "/search/posts", params={"q": query, **params}, headers=signed_in_as(viewer)
    )


async def test_e2_h8_ca3_searching_a_hashtag_returns_its_posts(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    tagged = (await publish(api, author, "Primer día #UdeSA")).json()["id"]
    reply = await api.post(
        f"/posts/{tagged}/replies", json={"content": "otra #udesa"}, headers=signed_in_as(author)
    )
    await publish(api, author, "otro tema #tds")

    response = await search(api, viewer, "#UDESA")

    assert response.status_code == 200
    assert {item["id"] for item in response.json()["items"]} == {tagged, reply.json()["id"]}


async def test_a_hashtag_search_does_not_match_plain_words_or_longer_hashtags(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    exact = (await publish(api, author, "con #udesa")).json()["id"]
    await publish(api, author, "estudio en udesa sin hashtag")
    await publish(api, author, "con #udesabc más largo")

    response = await search(api, viewer, "#udesa")

    assert [item["id"] for item in response.json()["items"]] == [exact]


async def test_a_hashtag_search_highlights_the_hashtag_in_the_snippet(api):
    author = uuid.uuid4()
    await publish(api, author, "hoy #TDS y mañana")

    response = await search(api, author, "#tds")

    snippet = response.json()["items"][0]["snippet"]
    assert "".join(part["text"] for part in snippet if part["highlighted"]) == "#TDS"


async def test_a_query_with_a_hashtag_and_words_is_a_text_search(api):
    author = uuid.uuid4()
    await publish(api, author, "hola #udesa")
    await publish(api, author, "chau #udesa")

    response = await search(api, author, "hola #udesa")

    assert len(response.json()["items"]) == 1


async def test_a_hashtag_search_pages_twenty_results_at_a_time(api):
    author = uuid.uuid4()
    for number in range(21):
        await publish(api, author, f"post {number} #masivo")

    first = (await search(api, author, "#masivo")).json()
    second = (await search(api, author, "#masivo", cursor=first["nextCursor"])).json()

    assert (len(first["items"]), len(second["items"]), second["nextCursor"]) == (20, 1, None)


async def test_a_hashtag_search_skips_deleted_protected_and_blocked_authors(api):
    viewer, deleter, private, blocked = [uuid.uuid4() for _ in range(4)]
    await given_a_profile(viewer)
    await given_a_profile(private, visibility="protected")
    await given_a_profile(blocked)
    visible = (await publish(api, viewer, "propio #tema")).json()["id"]
    deleted = (await publish(api, deleter, "borrado #tema")).json()["id"]
    await api.delete(f"/posts/{deleted}", headers=signed_in_as(deleter))
    await api.post(
        "/posts",
        json={"content": "privado #tema"},
        headers=signed_in_as(private, profile_visibility="protected"),
    )
    await publish(api, blocked, "bloqueado #tema")
    async with app.state.session_factory() as session:
        session.add(BlockModel(blocker_id=viewer, blocked_id=blocked))
        await session.commit()

    response = await search(api, viewer, "#tema")

    assert [item["id"] for item in response.json()["items"]] == [visible]


async def test_a_hashtag_search_needs_at_least_three_characters_counting_the_hash(api):
    author = uuid.uuid4()
    await publish(api, author, "corto #ab")

    too_short = await search(api, author, "#a")
    enough = await search(api, author, "#ab")

    assert too_short.status_code == 422
    assert len(enough.json()["items"]) == 1
