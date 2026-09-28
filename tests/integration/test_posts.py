import uuid

from posts_api.infrastructure.database.models import FollowModel, UserProfileModel
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, handle_of, signed_in_as

pytestmark = requires_services


async def approve_follow(follower_id: uuid.UUID, followee_id: uuid.UUID) -> None:
    async with app.state.session_factory() as session:
        if await session.get(UserProfileModel, follower_id) is None:
            session.add(UserProfileModel(id=follower_id, handle=handle_of(follower_id)))
            await session.flush()
        session.add(FollowModel(follower_id=follower_id, followee_id=followee_id))
        await session.commit()


async def test_e2_h1_ca4_creating_a_post_stores_the_author_content_and_counters_at_zero(api):
    author = uuid.uuid4()

    response = await api.post(
        "/posts", json={"content": "Hola UdeSA-X"}, headers=signed_in_as(author)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["authorId"] == str(author)
    assert body["content"] == "Hola UdeSA-X"
    assert (body["likesCount"], body["retweetsCount"], body["repliesCount"]) == (0, 0, 0)
    assert body["createdAt"]
    # Version 7 and not merely present: proves PostgreSQL generated it with
    # `uuidv7()`, the primary key this table uses.
    assert uuid.UUID(body["id"]).version == 7


async def test_posting_puts_the_author_on_the_graph(api):
    """The same bootstrap `/follow-requests` and the listings already do.

    Without this, an account whose first action is posting instead of
    following could never post at all: the row `posts.author_id` points at
    would not exist yet.
    """
    newcomer = uuid.uuid4()

    response = await api.post(
        "/posts", json={"content": "primer post"}, headers=signed_in_as(newcomer)
    )

    assert response.status_code == 201


async def test_creating_a_post_needs_a_token(api):
    response = await api.post("/posts", json={"content": "hola"})

    assert response.status_code == 401


async def test_e2_h1_ca1_rejects_text_over_280_characters(api):
    author = uuid.uuid4()

    response = await api.post("/posts", json={"content": "a" * 281}, headers=signed_in_as(author))

    assert response.status_code == 422
    assert response.json()["type"].endswith("/post-too-long")


async def test_exactly_280_characters_is_still_accepted(api):
    author = uuid.uuid4()

    response = await api.post("/posts", json={"content": "a" * 280}, headers=signed_in_as(author))

    assert response.status_code == 201


async def test_e2_h1_ca2_rejects_blank_content(api):
    author = uuid.uuid4()

    empty = await api.post("/posts", json={"content": ""}, headers=signed_in_as(author))
    only_spaces = await api.post("/posts", json={"content": "    "}, headers=signed_in_as(author))

    assert empty.status_code == 422
    assert empty.json()["type"].endswith("/post-is-blank")
    assert only_spaces.status_code == 422
    assert only_spaces.json()["type"].endswith("/post-is-blank")


async def test_content_that_is_only_a_tag_counts_as_blank(api):
    """Stripping the tag can leave nothing behind, and that is still CA.2's problem."""
    author = uuid.uuid4()

    response = await api.post(
        "/posts", json={"content": "<div></div>"}, headers=signed_in_as(author)
    )

    assert response.status_code == 422
    assert response.json()["type"].endswith("/post-is-blank")


async def test_e2_h1_ca3_strips_html_and_scripts(api):
    author = uuid.uuid4()
    payload = "Hello <script>alert('xss')</script> world <b>bold</b>"

    response = await api.post("/posts", json={"content": payload}, headers=signed_in_as(author))

    assert response.status_code == 201
    stored = response.json()["content"]
    assert "<script>" not in stored
    assert "<b>" not in stored
    # The tag is gone, the text that was inside it is not: stripping the
    # markup is not the same as deleting the post over it.
    assert "alert" in stored
    assert "bold" in stored


async def test_e2_h1_ca5_limits_to_thirty_posts_per_hour(api):
    author = uuid.uuid4()
    await app.state.redis.set(f"post:rate:{author}", 30, ex=3600)

    response = await api.post("/posts", json={"content": "uno más"}, headers=signed_in_as(author))

    assert response.status_code == 429
    assert response.json()["type"].endswith("/too-many-posts")
    assert int(response.headers["Retry-After"]) > 0


async def test_the_thirtieth_post_in_the_hour_still_goes_through(api):
    author = uuid.uuid4()
    await app.state.redis.set(f"post:rate:{author}", 29, ex=3600)

    response = await api.post(
        "/posts", json={"content": "todavía entra"}, headers=signed_in_as(author)
    )

    assert response.status_code == 201


async def test_the_limit_is_counted_per_account(api):
    blocked, free = uuid.uuid4(), uuid.uuid4()
    await app.state.redis.set(f"post:rate:{blocked}", 30, ex=3600)

    refused = await api.post("/posts", json={"content": "hola"}, headers=signed_in_as(blocked))
    allowed = await api.post("/posts", json={"content": "hola"}, headers=signed_in_as(free))

    assert (refused.status_code, allowed.status_code) == (429, 201)


async def test_a_rejected_attempt_still_counts_against_the_limit(api):
    """Trying to post spam is still an attempt, charged like any other.

    Started well under the limit and not at it: the point is to see the
    content check reject the post, not the rate limit beat it there.
    """
    author = uuid.uuid4()
    await app.state.redis.set(f"post:rate:{author}", 5, ex=3600)

    response = await api.post("/posts", json={"content": ""}, headers=signed_in_as(author))

    assert response.status_code == 422
    assert response.json()["type"].endswith("/post-is-blank")
    assert int(await app.state.redis.get(f"post:rate:{author}")) == 6


async def test_a_public_authors_post_can_be_read_by_anyone(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    created = await api.post("/posts", json={"content": "hola"}, headers=signed_in_as(author))
    post_id = created.json()["id"]

    response = await api.get(f"/posts/{post_id}", headers=signed_in_as(viewer))

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == post_id
    assert body["authorId"] == str(author)
    assert body["authorHandle"] == handle_of(author)
    assert body["content"] == "hola"
    assert (body["authorDisplayName"], body["authorAvatarUrl"]) == (None, None)


async def test_e2_h2_ca5_a_protected_authors_post_needs_an_approved_follow(api):
    author, follower, stranger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author, visibility="protected")
    created = await api.post(
        "/posts", json={"content": "solo aprobados"}, headers=signed_in_as(author)
    )
    post_id = created.json()["id"]
    await approve_follow(follower, author)
    await given_a_profile(stranger)

    approved = await api.get(f"/posts/{post_id}", headers=signed_in_as(follower))
    refused = await api.get(f"/posts/{post_id}", headers=signed_in_as(stranger))

    assert approved.status_code == 200
    assert refused.status_code == 404
    assert refused.json()["type"].endswith("/post-not-found")


async def test_an_author_can_always_read_their_own_protected_post(api):
    author = uuid.uuid4()
    await given_a_profile(author, visibility="protected")
    created = await api.post("/posts", json={"content": "mio"}, headers=signed_in_as(author))
    post_id = created.json()["id"]

    response = await api.get(f"/posts/{post_id}", headers=signed_in_as(author))

    assert response.status_code == 200


async def test_a_nonexistent_post_is_a_404(api):
    response = await api.get(f"/posts/{uuid.uuid4()}", headers=signed_in_as(uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["type"].endswith("/post-not-found")


async def test_reading_a_post_needs_a_token(api):
    response = await api.get(f"/posts/{uuid.uuid4()}")

    assert response.status_code == 401
