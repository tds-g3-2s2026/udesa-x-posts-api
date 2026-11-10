"""What the service does when users-api says an invited account verified its address."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update

from posts_api.api.event_handlers import build_event_handler
from posts_api.infrastructure.database.models import (
    BlockModel,
    FollowModel,
    FollowRequestModel,
    OutboxModel,
    UserProfileModel,
)
from posts_api.main import app
from tests.conftest import requires_services
from tests.events import FOLLOW_CREATED, body_of, invitation_accepted
from tests.integration.conftest import given_a_profile

pytestmark = requires_services


async def deliver(event: dict) -> str:
    """The event through the handler, without the broker in between."""
    handler = build_event_handler(app.state.session_factory, app.state.redis)
    return await handler(body_of(event))


async def follows(follower: uuid.UUID, followee: uuid.UUID) -> bool:
    async with app.state.session_factory() as session:
        return await session.get(FollowModel, (follower, followee)) is not None


async def count(model) -> int:
    async with app.state.session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def profile(user_id: uuid.UUID) -> UserProfileModel | None:
    async with app.state.session_factory() as session:
        return await session.get(UserProfileModel, user_id)


async def test_e3_h9_ca2_the_invitee_follows_the_inviter(api):
    invitee, inviter = uuid.uuid4(), uuid.uuid4()

    outcome = await deliver(invitation_accepted(invitee, inviter))

    assert outcome == "ack"
    assert await follows(invitee, inviter)
    assert (await profile(inviter)).followers_count == 1
    assert (await profile(invitee)).following_count == 1


async def test_neither_account_needs_to_be_known_beforehand(api):
    invitee, inviter = uuid.uuid4(), uuid.uuid4()
    assert await profile(inviter) is None and await profile(invitee) is None

    await deliver(invitation_accepted(invitee, inviter))

    assert (await profile(inviter)).handle == f"@v{str(inviter)[:8]}"
    assert (await profile(invitee)).handle == f"@i{str(invitee)[:8]}"


async def test_the_inviter_is_told_about_the_new_follower(api):
    invitee, inviter = uuid.uuid4(), uuid.uuid4()

    await deliver(invitation_accepted(invitee, inviter))

    async with app.state.session_factory() as session:
        [payload] = list(await session.scalars(select(OutboxModel.payload)))
    FOLLOW_CREATED.validate(payload)
    assert payload["data"]["followee_id"] == str(inviter)
    assert payload["data"]["follower_id"] == str(invitee)


async def test_a_protected_inviter_gets_a_request_and_not_a_follow(api):
    invitee, inviter = uuid.uuid4(), uuid.uuid4()

    outcome = await deliver(invitation_accepted(invitee, inviter, inviter_visibility="protected"))

    assert outcome == "ack"
    assert not await follows(invitee, inviter)
    assert await count(FollowRequestModel) == 1
    assert await count(OutboxModel) == 0


async def test_an_inviter_who_turned_protected_since_the_stored_copy_gets_a_request(api):
    invitee, inviter = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(inviter, visibility="public")

    await deliver(invitation_accepted(invitee, inviter, inviter_visibility="protected"))

    assert not await follows(invitee, inviter)
    assert await count(FollowRequestModel) == 1
    assert (await profile(inviter)).visibility == "protected"


async def test_the_same_event_twice_leaves_one_follow(api):
    invitee, inviter = uuid.uuid4(), uuid.uuid4()
    event = invitation_accepted(invitee, inviter)

    await deliver(event)
    await deliver(event)

    assert await count(FollowModel) == 1
    assert await count(OutboxModel) == 1
    assert (await profile(inviter)).followers_count == 1


async def test_an_inviter_who_blocked_the_invitee_is_not_followed(api):
    invitee, inviter = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(invitee)
    await given_a_profile(inviter)
    async with app.state.session_factory() as session:
        session.add(BlockModel(blocker_id=inviter, blocked_id=invitee))
        await session.commit()

    outcome = await deliver(invitation_accepted(invitee, inviter))

    # Acked: retrying would find the same block.
    assert outcome == "ack"
    assert not await follows(invitee, inviter)


async def test_a_closed_inviter_is_not_followed(api):
    invitee, inviter = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(inviter)
    async with app.state.session_factory() as session:
        await session.execute(
            update(UserProfileModel)
            .where(UserProfileModel.id == inviter)
            .values(deleted_at=datetime.now(UTC))
        )
        await session.commit()

    outcome = await deliver(invitation_accepted(invitee, inviter))

    assert outcome == "ack"
    assert not await follows(invitee, inviter)


async def test_a_visibility_this_version_does_not_know_is_acked_without_a_follow(api):
    invitee, inviter = uuid.uuid4(), uuid.uuid4()
    event = invitation_accepted(invitee, inviter)
    event["data"]["inviter_visibility"] = "friends-only"

    outcome = await build_event_handler(app.state.session_factory, app.state.redis)(body_of(event))

    assert outcome == "ack"
    assert await count(FollowModel) == 0


async def test_an_event_missing_a_field_is_rejected(api):
    event = invitation_accepted(uuid.uuid4(), uuid.uuid4())
    del event["data"]["inviter_id"]

    outcome = await build_event_handler(app.state.session_factory, app.state.redis)(body_of(event))

    assert outcome == "reject"
