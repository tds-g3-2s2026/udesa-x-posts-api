"""The feed filtered by the language its reader chose in users-api."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from posts_api.api.event_handlers import build_event_handler
from posts_api.infrastructure.database.models import (
    FeedPreferenceModel,
    PostModel,
    UserProfileModel,
)
from posts_api.main import app
from tests.conftest import requires_services
from tests.events import body_of, preferences_changed
from tests.integration.conftest import signed_in_as
from tests.integration.test_feed import insert_follow
from tests.integration.test_likes import publish
from tests.integration.test_retweets import share

pytestmark = requires_services

SPANISH = "Hoy fui a la universidad y la clase de ingeniería estuvo muy buena"
ENGLISH = "I went to the university today and the engineering class was really good"
FRENCH = "Bonjour tout le monde, comment allez-vous aujourd'hui"


async def choose(user_id: uuid.UUID, language: str, *, at: datetime | None = None) -> str:
    """What the consumer does with the event, without the broker in between."""
    handler = build_event_handler(app.state.session_factory, app.state.redis)
    return await handler(body_of(preferences_changed(user_id, language, at=at)))


async def feed_of(api, viewer: uuid.UUID) -> list[str]:
    response = await api.get("/feed", headers=signed_in_as(viewer))
    assert response.status_code == 200
    return [row["content"] for row in response.json()["items"]]


async def language_of(post_id: str) -> str | None:
    async with app.state.session_factory() as session:
        return await session.scalar(
            select(PostModel.language).where(PostModel.id == uuid.UUID(post_id))
        )


async def chosen_by(user_id: uuid.UUID) -> str:
    async with app.state.session_factory() as session:
        return (await session.get(FeedPreferenceModel, user_id)).language


async def test_e1_h7_ca2_a_spanish_feed_hides_english_posts(api):
    viewer, author = uuid.uuid4(), uuid.uuid4()
    await insert_follow(viewer, author)
    await publish(api, author, SPANISH)
    await publish(api, author, ENGLISH)

    await choose(viewer, "es")

    assert await feed_of(api, viewer) == [SPANISH]


async def test_an_english_feed_hides_spanish_posts(api):
    viewer, author = uuid.uuid4(), uuid.uuid4()
    await insert_follow(viewer, author)
    await publish(api, author, SPANISH)
    await publish(api, author, ENGLISH)

    await choose(viewer, "en")

    assert await feed_of(api, viewer) == [ENGLISH]


async def test_e1_h7_ca2_all_shows_every_language(api):
    viewer, author = uuid.uuid4(), uuid.uuid4()
    await insert_follow(viewer, author)
    await publish(api, author, SPANISH)
    await publish(api, author, ENGLISH)
    await choose(viewer, "es", at=datetime.now(UTC) - timedelta(minutes=1))
    assert await feed_of(api, viewer) == [SPANISH]

    await choose(viewer, "all")

    assert await feed_of(api, viewer) == [ENGLISH, SPANISH]


async def test_an_account_that_never_chose_sees_every_language(api):
    viewer, author = uuid.uuid4(), uuid.uuid4()
    await insert_follow(viewer, author)
    await publish(api, author, SPANISH)
    await publish(api, author, ENGLISH)

    assert await feed_of(api, viewer) == [ENGLISH, SPANISH]


async def test_what_could_not_be_classified_is_always_shown(api):
    viewer, author = uuid.uuid4(), uuid.uuid4()
    await insert_follow(viewer, author)
    await publish(api, author, FRENCH)
    await publish(api, author, "ok")

    await choose(viewer, "es")

    assert await feed_of(api, viewer) == ["ok", FRENCH]


async def test_a_post_older_than_the_detection_is_always_shown(api):
    viewer, author = uuid.uuid4(), uuid.uuid4()
    await insert_follow(viewer, author)
    async with app.state.session_factory() as session:
        session.add(PostModel(author_id=author, content=ENGLISH, language=None))
        await session.commit()

    await choose(viewer, "es")

    assert await feed_of(api, viewer) == [ENGLISH]


async def test_a_retweet_goes_by_the_language_of_what_it_shares(api):
    viewer, sharer, author = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await insert_follow(viewer, sharer)
    await share(api, sharer, await publish(api, author, ENGLISH))
    await share(api, sharer, await publish(api, author, SPANISH))

    await choose(viewer, "es")

    assert await feed_of(api, viewer) == [SPANISH]


async def test_the_filter_runs_before_paging(api):
    """Twenty newer posts in the other language do not leave the page empty."""
    viewer, author = uuid.uuid4(), uuid.uuid4()
    await insert_follow(viewer, author)
    await publish(api, author, SPANISH)
    async with app.state.session_factory() as session:
        session.add_all(
            PostModel(
                author_id=author,
                content=f"{ENGLISH} {n}",
                language="en",
                created_at=datetime.now(UTC) + timedelta(seconds=n + 1),
            )
            for n in range(25)
        )
        await session.commit()

    await choose(viewer, "es")

    response = await api.get("/feed", headers=signed_in_as(viewer))
    body = response.json()
    assert [row["content"] for row in body["items"]] == [SPANISH]
    assert body["nextCursor"] is None


async def test_only_the_feed_is_filtered(api):
    viewer, author = uuid.uuid4(), uuid.uuid4()
    await insert_follow(viewer, author)
    post = await publish(api, author, ENGLISH)
    await choose(viewer, "es")

    single = await api.get(f"/posts/{post}", headers=signed_in_as(viewer))
    on_profile = await api.get(f"/users/{author}/posts", headers=signed_in_as(viewer))

    assert single.status_code == 200
    assert [row["content"] for row in on_profile.json()["items"]] == [ENGLISH]


async def test_publishing_stores_the_language_of_the_post_and_of_a_reply(api):
    author = uuid.uuid4()

    spanish = await publish(api, author, SPANISH)
    english = await publish(api, author, ENGLISH)
    short = await publish(api, author, "ok")
    reply = await api.post(
        f"/posts/{english}/replies", json={"content": SPANISH}, headers=signed_in_as(author)
    )

    assert await language_of(spanish) == "es"
    assert await language_of(english) == "en"
    assert await language_of(short) == "other"
    assert await language_of(reply.json()["id"]) == "es"


async def test_a_post_with_only_images_stays_unclassified(api):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

    created = await api.post(
        "/posts",
        files=[("images", ("a.png", png, "image/png"))],
        headers=signed_in_as(uuid.uuid4()),
    )

    assert created.status_code == 201
    assert await language_of(created.json()["id"]) == "other"


async def test_the_language_is_kept_for_an_account_that_never_reached_this_service(api):
    newcomer = uuid.uuid4()

    assert await choose(newcomer, "en") == "ack"

    assert await chosen_by(newcomer) == "en"


async def test_an_event_does_not_make_up_a_profile(api):
    """The event knows neither the handle nor the visibility: following on a row made
    from it would let anybody follow a protected account without asking."""
    newcomer, follower = uuid.uuid4(), uuid.uuid4()

    await choose(newcomer, "es")

    async with app.state.session_factory() as session:
        assert await session.get(UserProfileModel, newcomer) is None
    follow = await api.post(f"/users/{newcomer}/follow", headers=signed_in_as(follower))
    assert follow.status_code == 404


async def test_the_first_request_of_an_account_keeps_what_it_chose_before(api):
    reader, author = uuid.uuid4(), uuid.uuid4()
    await choose(reader, "es")
    await insert_follow(reader, author)
    await publish(api, author, SPANISH)
    await publish(api, author, ENGLISH)

    assert await feed_of(api, reader) == [SPANISH]


async def test_an_older_event_arriving_late_does_not_undo_a_newer_one(api):
    viewer = uuid.uuid4()
    now = datetime.now(UTC)

    await choose(viewer, "es", at=now)
    assert await choose(viewer, "en", at=now - timedelta(seconds=5)) == "ack"

    assert await chosen_by(viewer) == "es"


async def test_the_same_event_delivered_twice_changes_nothing(api):
    viewer = uuid.uuid4()
    handler = build_event_handler(app.state.session_factory, app.state.redis)
    event = body_of(preferences_changed(viewer, "es"))

    assert await handler(event) == "ack"
    assert await handler(event) == "ack"

    assert await chosen_by(viewer) == "es"


async def test_a_language_this_version_does_not_know_is_ignored_without_retrying(api):
    viewer = uuid.uuid4()
    await choose(viewer, "es", at=datetime.now(UTC) - timedelta(minutes=1))
    event = preferences_changed(viewer, "es")
    event["data"]["feed_language"] = "pt"

    outcome = await build_event_handler(app.state.session_factory, app.state.redis)(body_of(event))

    assert outcome == "ack"
    assert await chosen_by(viewer) == "es"
