"""What the reads say about quotes: the reference to the original and the visible counter.

The original travels as an id, and the app reads it with `GET /posts/{id}`: the
same visibility rule and the same deleted marker as opening it by hand.
"""

import uuid

from tests.conftest import requires_services
from tests.integration.conftest import signed_in_as
from tests.integration.test_likes import approve_follow, block
from tests.integration.test_quotes import publish, quote, quotes_count_of
from tests.integration.test_user_deleted import close_account

pytestmark = requires_services


async def test_e2_h13_ca1_a_quote_points_to_the_original_in_every_read(api):
    author, quoter, reader = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author, "El deploy salió verde")
    created = (await quote(api, quoter, original, "Por fin")).json()["id"]
    await approve_follow(reader, quoter)

    detail = await api.get(f"/posts/{created}", headers=signed_in_as(reader))
    feed = await api.get("/feed", headers=signed_in_as(reader))
    profile = await api.get(f"/users/{quoter}/posts", headers=signed_in_as(reader))
    embedded = await api.get(f"/posts/{original}", headers=signed_in_as(reader))

    assert detail.json()["quotedPostId"] == original
    assert [one["quotedPostId"] for one in feed.json()["items"]] == [original]
    assert [one["quotedPostId"] for one in profile.json()["items"]] == [original]
    # What the app draws inside the quote is the original as anyone opens it.
    assert embedded.json()["content"] == "El deploy salió verde"


async def test_e2_h13_ca3_the_quotes_count_is_visible(api):
    author, first, second = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)
    await quote(api, first, original)
    await quote(api, second, original)

    detail = await api.get(f"/posts/{original}", headers=signed_in_as(author))
    profile = await api.get(f"/users/{author}/posts", headers=signed_in_as(author))

    assert detail.json()["quotesCount"] == 2
    assert profile.json()["items"][0]["quotesCount"] == 2


async def test_e2_h13_ca4_a_deleted_original_keeps_the_quote(api):
    author, quoter = uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)
    created = (await quote(api, quoter, original, "Guardo esto")).json()["id"]

    await api.delete(f"/posts/{original}", headers=signed_in_as(author))

    kept = await api.get(f"/posts/{created}", headers=signed_in_as(quoter))
    gone = await api.get(f"/posts/{original}", headers=signed_in_as(quoter))
    assert kept.status_code == 200
    assert (kept.json()["content"], kept.json()["quotedPostId"]) == ("Guardo esto", original)
    # The app reads this and shows [Post original eliminado].
    assert (gone.json()["deleted"], gone.json()["content"]) == (True, None)


async def test_who_cannot_read_the_original_gets_the_quote_without_it(api):
    author, quoter, reader = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)
    created = (await quote(api, quoter, original)).json()["id"]
    await block(author, reader)

    kept = await api.get(f"/posts/{created}", headers=signed_in_as(reader))
    hidden = await api.get(f"/posts/{original}", headers=signed_in_as(reader))

    assert kept.status_code == 200
    # Same answer as a post that does not exist: the app shows "Post no disponible".
    assert hidden.status_code == 404


async def test_a_closed_account_takes_its_quotes_off_the_count(api):
    author, quoter = uuid.uuid4(), uuid.uuid4()
    original = await publish(api, author)
    await quote(api, quoter, original)
    await quote(api, quoter, original, "Otra vez")
    await quote(api, uuid.uuid4(), original)

    await close_account(quoter)

    assert await quotes_count_of(original) == 1
