"""A change of visibility reaches the reads through the event, not the owner's next request."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from posts_api.api.event_handlers import build_event_handler
from posts_api.app.models.follow import ProfileVisibility
from posts_api.app.repositories.follows import FollowRepository
from posts_api.infrastructure.database.models import (
    FeedPreferenceModel,
    FollowModel,
    UserProfileModel,
)
from posts_api.main import app
from tests.conftest import requires_services
from tests.events import body_of, preferences_changed, user_deleted
from tests.integration.conftest import given_a_profile, handle_of, signed_in_as
from tests.integration.test_feed import insert_follow
from tests.integration.test_likes import publish
from tests.integration.test_profile import users_api  # noqa: F401

pytestmark = requires_services


async def announce(
    user_id: uuid.UUID,
    visibility: str,
    *,
    at: datetime | None = None,
    language: str = "all",
) -> str:
    """What the consumer does with the event, without the broker in between."""
    handler = build_event_handler(app.state.session_factory, app.state.redis)
    return await handler(
        body_of(preferences_changed(user_id, language, visibility=visibility, at=at))
    )


async def profile_of(user_id: uuid.UUID) -> UserProfileModel | None:
    async with app.state.session_factory() as session:
        return await session.get(UserProfileModel, user_id)


async def post_status(api, viewer: uuid.UUID, post_id: str) -> int:
    return (await api.get(f"/posts/{post_id}", headers=signed_in_as(viewer))).status_code


async def test_e2_h2_ca5_a_stranger_loses_the_post_when_the_author_turns_protected(api):
    ana, bruno = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, ana)
    assert await post_status(api, bruno, post) == 200

    assert await announce(ana, "protected") == "ack"

    assert await post_status(api, bruno, post) == 404


async def test_e2_h14_ca3_a_stranger_loses_the_profile_posts_when_the_account_turns_protected(
    api,
):
    ana, bruno = uuid.uuid4(), uuid.uuid4()
    await publish(api, ana)
    assert (await api.get(f"/users/{ana}/posts", headers=signed_in_as(bruno))).status_code == 200

    await announce(ana, "protected")

    assert (await api.get(f"/users/{ana}/posts", headers=signed_in_as(bruno))).status_code == 403


async def test_an_approved_follower_keeps_reading_after_the_account_turns_protected(api):
    ana, carla = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, ana)
    await insert_follow(carla, ana)

    await announce(ana, "protected")

    assert await post_status(api, carla, post) == 200


async def test_an_account_that_turns_public_again_opens_its_posts(api):
    ana, bruno = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, ana)
    now = datetime.now(UTC)
    await announce(ana, "protected", at=now - timedelta(seconds=10))
    assert await post_status(api, bruno, post) == 404

    await announce(ana, "public", at=now)

    assert await post_status(api, bruno, post) == 200


async def test_an_older_event_arriving_late_does_not_undo_a_newer_one(api):
    ana = uuid.uuid4()
    await given_a_profile(ana)
    now = datetime.now(UTC)

    await announce(ana, "protected", at=now)
    assert await announce(ana, "public", at=now - timedelta(seconds=5)) == "ack"

    assert (await profile_of(ana)).visibility == "protected"


async def test_the_same_event_delivered_twice_changes_nothing(api):
    ana = uuid.uuid4()
    handler = build_event_handler(app.state.session_factory, app.state.redis)
    event = body_of(preferences_changed(ana, "all", visibility="protected"))

    assert await handler(event) == "ack"
    assert await handler(event) == "ack"

    assert (await profile_of(ana)).visibility == "protected"


async def test_the_event_of_an_account_that_never_reached_this_service_is_kept(api):
    ana = uuid.uuid4()

    await announce(ana, "protected")
    profile = await profile_of(ana)
    assert profile.visibility == "protected"
    assert profile.handle is None

    # The first request of its owner carries a token minted before the change.
    await api.get("/follow-requests", headers=signed_in_as(ana, profile_visibility="public"))

    profile = await profile_of(ana)
    assert profile.visibility == "protected"
    assert profile.handle is not None


async def test_a_token_cannot_undo_what_an_event_set(api):
    ana = uuid.uuid4()
    await given_a_profile(ana)
    await announce(ana, "protected")

    await api.get("/follow-requests", headers=signed_in_as(ana, profile_visibility="public"))

    assert (await profile_of(ana)).visibility == "protected"


async def test_a_closed_account_stays_public(api):
    ana = uuid.uuid4()
    handler = build_event_handler(app.state.session_factory, app.state.redis)
    await handler(body_of(user_deleted(ana)))

    await announce(ana, "protected", at=datetime.now(UTC) + timedelta(seconds=5))

    assert (await profile_of(ana)).visibility == "public"


async def test_the_same_event_applied_twice_is_ignored_the_second_time(api):
    ana = uuid.uuid4()
    at = datetime.now(UTC)

    async with app.state.session_factory() as session, session.begin():
        follows = FollowRepository(session)
        assert await follows.apply_visibility(ana, ProfileVisibility.PROTECTED, at) is True
        assert await follows.apply_visibility(ana, ProfileVisibility.PROTECTED, at) is False


async def test_a_failure_applying_the_visibility_leaves_the_language_unapplied(api, monkeypatch):
    ana = uuid.uuid4()

    async def failing(self, user_id, visibility, at):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(FollowRepository, "apply_visibility", failing)
    handler = build_event_handler(app.state.session_factory, app.state.redis)

    with pytest.raises(RuntimeError):
        await handler(body_of(preferences_changed(ana, "es", visibility="protected")))

    async with app.state.session_factory() as session:
        assert await session.get(FeedPreferenceModel, ana) is None


async def test_turning_public_again_does_not_touch_who_follows_the_account(api):
    ana, carla = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(ana, visibility="protected")
    await insert_follow(carla, ana)

    await announce(ana, "public")

    async with app.state.session_factory() as session:
        assert await session.get(FollowModel, (carla, ana)) is not None


async def test_a_profile_made_by_an_event_gets_its_handle_when_somebody_opens_it(api, users_api):  # noqa: F811
    ana, bruno = uuid.uuid4(), uuid.uuid4()
    users_api.has(ana, visibility="public")
    await announce(ana, "protected")
    assert (await profile_of(ana)).handle is None

    response = await api.get(f"/users/{ana}", headers=signed_in_as(bruno))

    assert response.status_code == 200
    assert response.json()["handle"] == handle_of(ana)
    profile = await profile_of(ana)
    assert profile.handle == handle_of(ana)
    # The lookup completes the handle and nothing else: the event owns the visibility.
    assert profile.visibility == "protected"


async def test_a_profile_made_by_an_event_is_still_shown_when_users_api_is_down(api, users_api):  # noqa: F811
    ana, bruno = uuid.uuid4(), uuid.uuid4()
    await announce(ana, "protected")
    users_api.down = True

    response = await api.get(f"/users/{ana}", headers=signed_in_as(bruno))

    assert response.status_code == 200
    assert response.json()["handle"] is None
    assert response.json()["isPrivate"] is True


async def test_an_event_without_visibility_leaves_the_stored_one_alone(api):
    ana = uuid.uuid4()
    await given_a_profile(ana, visibility="protected")
    handler = build_event_handler(app.state.session_factory, app.state.redis)

    assert await handler(body_of(preferences_changed(ana, "es"))) == "ack"

    assert (await profile_of(ana)).visibility == "protected"


async def test_an_event_without_visibility_does_not_make_up_a_profile(api):
    """Following on a row made from it would let anybody follow a protected account unasked."""
    newcomer = uuid.uuid4()
    handler = build_event_handler(app.state.session_factory, app.state.redis)

    await handler(body_of(preferences_changed(newcomer, "es")))

    assert await profile_of(newcomer) is None


async def test_a_visibility_this_version_does_not_know_is_ignored_without_retrying(api):
    ana = uuid.uuid4()
    await given_a_profile(ana, visibility="protected")
    event = preferences_changed(ana, "es", visibility="protected")
    event["data"]["profile_visibility"] = "friends"

    outcome = await build_event_handler(app.state.session_factory, app.state.redis)(body_of(event))

    assert outcome == "ack"
    assert (await profile_of(ana)).visibility == "protected"


async def test_a_language_this_version_does_not_know_does_not_keep_the_visibility_out(api):
    ana = uuid.uuid4()
    await given_a_profile(ana)
    event = preferences_changed(ana, "es", visibility="protected")
    event["data"]["feed_language"] = "pt"

    outcome = await build_event_handler(app.state.session_factory, app.state.redis)(body_of(event))

    assert outcome == "ack"
    assert (await profile_of(ana)).visibility == "protected"
