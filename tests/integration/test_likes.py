import asyncio
import uuid

from posts_api.infrastructure.database.models import BlockModel, FollowModel, UserProfileModel
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, handle_of, signed_in_as

pytestmark = requires_services


async def publish(api, author: uuid.UUID, content: str = "un post") -> str:
    created = await api.post("/posts", json={"content": content}, headers=signed_in_as(author))
    return created.json()["id"]


async def like(api, viewer: uuid.UUID, post_id: str):
    return await api.put(f"/posts/{post_id}/like", headers=signed_in_as(viewer))


async def unlike(api, viewer: uuid.UUID, post_id: str):
    return await api.delete(f"/posts/{post_id}/like", headers=signed_in_as(viewer))


async def read(api, viewer: uuid.UUID, post_id: str) -> dict:
    response = await api.get(f"/posts/{post_id}", headers=signed_in_as(viewer))
    return response.json()


async def ensure_profiles(*user_ids: uuid.UUID) -> None:
    async with app.state.session_factory() as session:
        for user_id in user_ids:
            if await session.get(UserProfileModel, user_id) is None:
                session.add(UserProfileModel(id=user_id, handle=handle_of(user_id)))
        await session.commit()


async def block(blocker: uuid.UUID, blocked: uuid.UUID) -> None:
    await ensure_profiles(blocker, blocked)
    async with app.state.session_factory() as session:
        session.add(BlockModel(blocker_id=blocker, blocked_id=blocked))
        await session.commit()


async def approve_follow(follower: uuid.UUID, followee: uuid.UUID) -> None:
    await ensure_profiles(follower, followee)
    async with app.state.session_factory() as session:
        session.add(FollowModel(follower_id=follower, followee_id=followee))
        await session.commit()


async def test_e2_h6_ca3_liking_twice_counts_once(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    post_id = await publish(api, author)

    first = await like(api, fan, post_id)
    second = await like(api, fan, post_id)

    # 204 both times: the client retrying a request it never saw answered gets
    # the same result as the first one.
    assert (first.status_code, second.status_code) == (204, 204)
    assert (await read(api, author, post_id))["likesCount"] == 1


async def test_e2_h6_ca3_concurrent_likes_count_once(api):
    """The same account liking five times at once: the database picks the winner.

    A read followed by an insert would let several of them see "no like yet".
    """
    author, fan = uuid.uuid4(), uuid.uuid4()
    post_id = await publish(api, author)
    # Already on the graph, so what races here is the like and nothing else.
    await given_a_profile(fan)

    responses = await asyncio.gather(*(like(api, fan, post_id) for _ in range(5)))

    assert [one.status_code for one in responses] == [204] * 5
    assert (await read(api, author, post_id))["likesCount"] == 1


async def test_likes_from_different_accounts_that_land_together_all_count(api):
    author = uuid.uuid4()
    post_id = await publish(api, author)
    fans = [uuid.uuid4() for _ in range(5)]

    responses = await asyncio.gather(*(like(api, fan, post_id) for fan in fans))

    assert [one.status_code for one in responses] == [204] * 5
    assert (await read(api, author, post_id))["likesCount"] == 5


async def test_e2_h6_ca1_a_post_the_viewer_cannot_read_cannot_be_liked(api):
    author, blocked, stranger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    post_id = await publish(api, author)
    missing = await like(api, stranger, str(uuid.uuid4()))
    await block(author, blocked)

    refused = await like(api, blocked, post_id)

    assert refused.status_code == 404
    assert refused.json()["type"].endswith("/post-not-found")
    # Same answer as for a post that was never there, so the status cannot be
    # read as confirmation that the block exists.
    for field in ("type", "title", "detail", "status"):
        assert refused.json()[field] == missing.json()[field]
    assert (await read(api, author, post_id))["likesCount"] == 0


async def test_a_protected_authors_post_needs_an_approved_follow_to_be_liked(api):
    author, follower, stranger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author, visibility="protected")
    created = await api.post(
        "/posts",
        json={"content": "solo aprobados"},
        headers=signed_in_as(author, profile_visibility="protected"),
    )
    post_id = created.json()["id"]
    await approve_follow(follower, author)

    refused = await like(api, stranger, post_id)
    allowed = await like(api, follower, post_id)

    assert (refused.status_code, allowed.status_code) == (404, 204)
    assert (await read(api, author, post_id))["likesCount"] == 1


async def test_a_block_in_the_other_direction_cannot_like_either(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    post_id = await publish(api, author)
    await block(fan, author)

    refused = await like(api, fan, post_id)

    assert refused.status_code == 404


async def test_e2_h6_ca1_put_then_delete_leaves_no_like(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    post_id = await publish(api, author)

    await like(api, fan, post_id)
    taken_back = await unlike(api, fan, post_id)

    assert taken_back.status_code == 204
    after = await read(api, fan, post_id)
    assert after["likesCount"] == 0
    assert after["likedByMe"] is False


async def test_taking_back_a_like_that_was_never_given_is_not_an_error(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    post_id = await publish(api, author)

    response = await unlike(api, fan, post_id)

    assert response.status_code == 204
    # Not pushed below zero by a delete that found nothing to delete.
    assert (await read(api, author, post_id))["likesCount"] == 0


async def test_taking_a_like_back_twice_counts_once(api):
    author, fan, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    post_id = await publish(api, author)
    await like(api, fan, post_id)
    await like(api, other, post_id)

    await unlike(api, fan, post_id)
    await unlike(api, fan, post_id)

    assert (await read(api, author, post_id))["likesCount"] == 1


async def test_a_missing_or_unreadable_post_cannot_be_unliked(api):
    author, blocked = uuid.uuid4(), uuid.uuid4()
    post_id = await publish(api, author)
    await block(author, blocked)

    missing = await unlike(api, blocked, str(uuid.uuid4()))
    refused = await unlike(api, blocked, post_id)

    assert (missing.status_code, refused.status_code) == (404, 404)
    assert refused.json()["type"].endswith("/post-not-found")


async def test_liked_by_me_is_about_the_reader_and_not_the_post(api):
    author, fan, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    post_id = await publish(api, author)

    await like(api, fan, post_id)

    assert (await read(api, fan, post_id))["likedByMe"] is True
    assert (await read(api, other, post_id))["likedByMe"] is False
    assert (await read(api, author, post_id))["likedByMe"] is False


async def test_liked_by_me_travels_in_the_feed_and_in_the_replies(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    post_id = await publish(api, author, "el original")
    await approve_follow(fan, author)
    reply = await api.post(
        f"/posts/{post_id}/replies", json={"content": "una respuesta"}, headers=signed_in_as(author)
    )
    await like(api, fan, post_id)
    await like(api, fan, reply.json()["id"])

    feed = await api.get("/feed", headers=signed_in_as(fan))
    replies = await api.get(f"/posts/{post_id}/replies", headers=signed_in_as(fan))
    not_the_fan = await api.get(f"/posts/{post_id}/replies", headers=signed_in_as(author))

    assert [one["likedByMe"] for one in feed.json()["items"]] == [True]
    assert [one["likedByMe"] for one in replies.json()["items"]] == [True]
    assert [one["likedByMe"] for one in not_the_fan.json()["items"]] == [False]


async def test_a_post_that_was_just_written_is_not_liked_by_its_author(api):
    author = uuid.uuid4()

    created = await api.post("/posts", json={"content": "nuevo"}, headers=signed_in_as(author))

    assert created.json()["likedByMe"] is False


async def test_an_account_can_like_its_own_post(api):
    author = uuid.uuid4()
    post_id = await publish(api, author)

    response = await like(api, author, post_id)

    assert response.status_code == 204
    assert (await read(api, author, post_id))["likedByMe"] is True


async def test_the_first_thing_an_account_does_can_be_a_like(api):
    """Liking puts the account on the graph, like every other first action: the
    like points at the profile, which would not exist yet otherwise."""
    author, newcomer = uuid.uuid4(), uuid.uuid4()
    post_id = await publish(api, author)

    response = await like(api, newcomer, post_id)

    assert response.status_code == 204
    async with app.state.session_factory() as session:
        assert await session.get(UserProfileModel, newcomer) is not None


async def test_liking_and_taking_back_need_a_token(api):
    post_id = uuid.uuid4()

    liked = await api.put(f"/posts/{post_id}/like")
    unliked = await api.delete(f"/posts/{post_id}/like")

    assert (liked.status_code, unliked.status_code) == (401, 401)
