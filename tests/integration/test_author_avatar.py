"""The photo and cover on the profile header, and the photo of the author on each post."""

import uuid

from sqlalchemy import func, update

from posts_api.infrastructure.database.models import UserProfileModel
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, signed_in_as
from tests.integration.test_feed import insert_follow
from tests.integration.test_post_media import PNG
from tests.integration.test_profile import users_api  # noqa: F401  (fixture)
from tests.integration.test_profile_images import image, key_in, put_avatar

pytestmark = requires_services


async def test_your_own_profile_shows_your_photo_and_cover_even_if_protected(
    api,
    users_api,  # noqa: F811
):
    owner = uuid.uuid4()
    await given_a_profile(owner, visibility="protected")
    users_api.has(owner, visibility="protected")
    # The token carries the visibility, and every request writes it back.
    as_owner = signed_in_as(owner, profile_visibility="protected")
    avatar = (await api.put("/users/me/avatar", files=image(PNG), headers=as_owner)).json()[
        "avatarUrl"
    ]
    cover = (await api.put("/users/me/cover", files=image(PNG), headers=as_owner)).json()[
        "coverUrl"
    ]

    response = await api.get(f"/users/{owner}", headers=as_owner)

    assert response.status_code == 200
    body = response.json()
    assert (key_in(body["avatarUrl"]), key_in(body["coverUrl"])) == (key_in(avatar), key_in(cover))
    assert (body["isPrivate"], body["isFollowedByMe"]) == (True, False)


async def test_the_photo_of_the_author_travels_with_each_post(api, users_api):  # noqa: F811
    reader, author = uuid.uuid4(), uuid.uuid4()
    users_api.has(author)
    await insert_follow(reader, author)
    avatar = key_in((await put_avatar(api, author)).json()["avatarUrl"])
    post = (await api.post("/posts", json={"content": "hola"}, headers=signed_in_as(author))).json()
    await api.post(
        f"/posts/{post['id']}/replies", json={"content": "yo"}, headers=signed_in_as(author)
    )

    feed = await api.get("/feed", headers=signed_in_as(reader))
    single = await api.get(f"/posts/{post['id']}", headers=signed_in_as(reader))
    replies = await api.get(f"/posts/{post['id']}/replies", headers=signed_in_as(reader))
    on_profile = await api.get(f"/users/{author}/posts", headers=signed_in_as(reader))

    rows = [
        feed.json()["items"][0],
        single.json(),
        replies.json()["items"][0],
        on_profile.json()["items"][0],
    ]
    assert [key_in(row["authorAvatarUrl"]) for row in rows] == [avatar] * 4


async def test_a_retweet_row_carries_the_photo_of_the_original_author(api):
    reader, author, sharer = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await insert_follow(reader, sharer)
    author_photo = key_in((await put_avatar(api, author)).json()["avatarUrl"])
    await put_avatar(api, sharer)
    post = (await api.post("/posts", json={"content": "hola"}, headers=signed_in_as(author))).json()
    await api.post(f"/posts/{post['id']}/retweet", headers=signed_in_as(sharer))

    feed = await api.get("/feed", headers=signed_in_as(reader))

    row = feed.json()["items"][0]
    assert row["retweetedBy"] is not None
    assert key_in(row["authorAvatarUrl"]) == author_photo


async def test_e1_h8_ca5_without_a_photo_the_posts_carry_none(api):
    reader, author = uuid.uuid4(), uuid.uuid4()
    await insert_follow(reader, author)
    await api.post("/posts", json={"content": "hola"}, headers=signed_in_as(author))

    feed = await api.get("/feed", headers=signed_in_as(reader))

    assert feed.json()["items"][0]["authorAvatarUrl"] is None


async def test_a_closed_account_shows_no_photo_on_what_it_left(api):
    reader, author = uuid.uuid4(), uuid.uuid4()
    await put_avatar(api, author)
    post = (await api.post("/posts", json={"content": "hola"}, headers=signed_in_as(reader))).json()
    await api.post(
        f"/posts/{post['id']}/replies", json={"content": "chau"}, headers=signed_in_as(author)
    )
    async with app.state.session_factory() as session:
        await session.execute(
            update(UserProfileModel)
            .where(UserProfileModel.id == author)
            .values(deleted_at=func.now())
        )
        await session.commit()

    replies = await api.get(f"/posts/{post['id']}/replies", headers=signed_in_as(reader))

    reply = replies.json()["items"][0]
    assert reply["authorDeleted"] is True
    assert reply["authorAvatarUrl"] is None


async def test_a_photo_that_cannot_be_signed_goes_out_as_the_default(api, users_api):  # noqa: F811
    owner = uuid.uuid4()
    users_api.has(owner)
    await put_avatar(api, owner)
    post = (await api.post("/posts", json={"content": "hola"}, headers=signed_in_as(owner))).json()
    app.state.image_storage.fail_on_url = True

    profile = await api.get(f"/users/{owner}", headers=signed_in_as(uuid.uuid4()))
    single = await api.get(f"/posts/{post['id']}", headers=signed_in_as(uuid.uuid4()))

    assert profile.status_code == 200
    assert profile.json()["avatarUrl"] is None
    assert single.status_code == 200
    assert single.json()["authorAvatarUrl"] is None
