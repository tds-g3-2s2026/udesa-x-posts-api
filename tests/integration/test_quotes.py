import uuid

from posts_api.infrastructure.database.models import BlockModel, PostModel, UserProfileModel
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import handle_of, signed_in_as

pytestmark = requires_services


async def publish(api, author: uuid.UUID, content: str = "original") -> str:
    created = await api.post("/posts", json={"content": content}, headers=signed_in_as(author))
    return created.json()["id"]


async def quote(api, author: uuid.UUID, post_id: str, content: str = "Mirá esto"):
    return await api.post(
        f"/posts/{post_id}/quotes", json={"content": content}, headers=signed_in_as(author)
    )


async def quotes_count_of(post_id: str) -> int:
    async with app.state.session_factory() as session:
        return (await session.get(PostModel, uuid.UUID(post_id))).quotes_count


async def block(blocker: uuid.UUID, blocked: uuid.UUID) -> None:
    async with app.state.session_factory() as session:
        for user_id in (blocker, blocked):
            if await session.get(UserProfileModel, user_id) is None:
                session.add(UserProfileModel(id=user_id, handle=handle_of(user_id)))
        await session.flush()
        session.add(BlockModel(blocker_id=blocker, blocked_id=blocked))
        await session.commit()


async def test_e2_h13_ca2_an_empty_comment_is_rejected(api):
    author, quoter = uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)

    response = await quote(api, quoter, original, "   ")

    assert response.status_code == 422
    assert response.json()["type"].endswith("/post-is-blank")
    assert await quotes_count_of(original) == 0


async def test_e2_h13_ca2_a_comment_over_280_characters_is_rejected(api):
    author, quoter = uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)

    response = await quote(api, quoter, original, "x" * 281)

    assert response.status_code == 422
    assert response.json()["type"].endswith("/post-too-long")
    assert await quotes_count_of(original) == 0


async def test_e2_h13_ca3_quoting_increments_the_quotes_count(api):
    author, first, second = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)

    created = await quote(api, first, original, "Totalmente de acuerdo #taller")
    await quote(api, second, original)

    assert created.status_code == 201
    body = created.json()
    assert body["quotedPostId"] == original
    assert body["content"] == "Totalmente de acuerdo #taller"
    # The quote is a post of its own, with its own counter.
    assert (body["authorId"], body["quotesCount"]) == (str(first), 0)
    assert await quotes_count_of(original) == 2


async def test_a_post_that_quotes_nothing_says_so(api):
    created = await api.post(
        "/posts", json={"content": "sin cita"}, headers=signed_in_as(uuid.uuid4())
    )

    assert created.json()["quotedPostId"] is None
    assert created.json()["quotesCount"] == 0


async def test_deleting_a_quote_takes_it_off_the_count(api):
    author, quoter = uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)
    created = await quote(api, quoter, original)

    deleted = await api.delete(f"/posts/{created.json()['id']}", headers=signed_in_as(quoter))

    assert deleted.status_code == 204
    assert await quotes_count_of(original) == 0
    # Deleting it again changes nothing, the counter included.
    await api.delete(f"/posts/{created.json()['id']}", headers=signed_in_as(quoter))
    assert await quotes_count_of(original) == 0


async def test_a_quote_can_be_quoted_and_counts_only_for_what_it_quotes(api):
    author, first, second = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)
    first_quote = (await quote(api, first, original)).json()["id"]

    second_quote = await quote(api, second, first_quote)

    assert second_quote.status_code == 201
    assert await quotes_count_of(first_quote) == 1
    assert await quotes_count_of(original) == 1


async def test_a_post_the_author_cannot_see_cannot_be_quoted(api):
    author, quoter = uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)
    await block(author, quoter)

    response = await quote(api, quoter, original)

    assert response.status_code == 404
    assert await quotes_count_of(original) == 0


async def test_a_post_that_does_not_exist_cannot_be_quoted(api):
    response = await quote(api, uuid.uuid4(), str(uuid.uuid4()))

    assert response.status_code == 404


async def test_a_deleted_post_cannot_be_quoted(api):
    author, quoter = uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)
    await api.delete(f"/posts/{original}", headers=signed_in_as(author))

    response = await quote(api, quoter, original)

    assert response.status_code == 409
    assert response.json()["type"].endswith("/post-deleted")


async def test_quoting_needs_a_session(api):
    original = await publish(api, uuid.uuid4())

    response = await api.post(f"/posts/{original}/quotes", json={"content": "hola"})

    assert response.status_code == 401
