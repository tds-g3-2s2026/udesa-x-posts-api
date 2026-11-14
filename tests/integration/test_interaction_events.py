"""What liking, sharing and answering a post leave in the outbox.

The publisher is covered in `test_outbox_publisher.py`. Here the app points at a
broker nobody listens on (see `tests/conftest.py`), so the events stay in the
outbox for the tests to read.
"""

import uuid

import pytest

from posts_api.infrastructure.database.models import LikeModel, OutboxModel
from posts_api.infrastructure.database.outbox_repository import SqlAlchemyOutboxRepository
from tests.conftest import requires_services
from tests.events import INTERACTION_CREATED
from tests.integration.conftest import given_a_profile, handle_of
from tests.integration.test_likes import like, publish
from tests.integration.test_mutes import mute
from tests.integration.test_outbox_follow import count, outbox_events
from tests.integration.test_replies import reply
from tests.integration.test_retweets import share

pytestmark = requires_services


async def test_e4_h2_ca1_like_writes_interaction_created(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    post = await publish(api, author)

    response = await like(api, fan, post)

    assert response.status_code == 204
    [event] = await outbox_events()
    INTERACTION_CREATED.validate(event)
    assert event["data"] == {
        "kind": "like",
        "actor_id": str(fan),
        "actor_handle": handle_of(fan),
        "post_id": post,
        "post_author_id": str(author),
        "reply_id": None,
    }


async def test_e4_h2_ca1_retweet_writes_interaction_created(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    post = await publish(api, author)

    response = await share(api, fan, post)

    assert response.status_code == 201
    [event] = await outbox_events()
    INTERACTION_CREATED.validate(event)
    assert event["data"] == {
        "kind": "retweet",
        "actor_id": str(fan),
        "actor_handle": handle_of(fan),
        "post_id": post,
        "post_author_id": str(author),
        "reply_id": None,
    }


async def test_e4_h2_ca1_reply_writes_interaction_created(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    post = await publish(api, author)

    response = await reply(api, fan, post)

    assert response.status_code == 201
    [event] = await outbox_events()
    INTERACTION_CREATED.validate(event)
    assert event["data"] == {
        "kind": "reply",
        "actor_id": str(fan),
        "actor_handle": handle_of(fan),
        "post_id": post,
        "post_author_id": str(author),
        "reply_id": response.json()["id"],
    }


async def test_e4_h2_ca2_payload_carries_post_id(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    post = await publish(api, author)
    answered = (await reply(api, fan, post)).json()["id"]
    # Interacting with the reply is interacting with another post: the event
    # names that one, with the author of the reply as its recipient.
    await like(api, author, answered)
    await share(api, author, answered)

    events = [event["data"] for event in await outbox_events()]

    assert [(data["kind"], data["post_id"], data["post_author_id"]) for data in events] == [
        ("reply", post, str(author)),
        ("like", answered, str(fan)),
        ("retweet", answered, str(fan)),
    ]
    # Only a reply carries the post it created.
    assert [data["reply_id"] for data in events] == [answered, None, None]


async def test_e4_h2_ca1_like_writes_outbox_row_in_same_transaction(api, monkeypatch):
    author, fan = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    post = await publish(api, author)

    async def failing_add(self, event):
        # The like and the row reach the database inside the transaction
        # before the failure, so only a rollback can take both back.
        self.session.add(OutboxModel(id=event.id, type=event.type, payload=event.envelope))
        await self.session.flush()
        raise RuntimeError("the outbox write failed")

    monkeypatch.setattr(SqlAlchemyOutboxRepository, "add", failing_add)

    with pytest.raises(RuntimeError):
        await like(api, fan, post)

    assert await count(LikeModel) == 0
    assert await count(OutboxModel) == 0


async def test_liking_twice_queues_a_single_event(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    post = await publish(api, author)

    await like(api, fan, post)
    await like(api, fan, post)

    assert len(await outbox_events()) == 1


async def test_sharing_twice_queues_a_single_event(api):
    author, fan = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    post = await publish(api, author)

    assert (await share(api, fan, post)).status_code == 201
    assert (await share(api, fan, post)).status_code == 204

    assert len(await outbox_events()) == 1


async def test_a_muted_account_still_interacts_but_the_author_is_not_told(api):
    author, muted = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    await given_a_profile(muted)
    post = await publish(api, author)
    await mute(api, author, muted)

    assert (await like(api, muted, post)).status_code == 204
    assert (await share(api, muted, post)).status_code == 201
    answered = await reply(api, muted, post)

    assert answered.status_code == 201
    assert await count(LikeModel) == 1
    assert await outbox_events() == []


async def test_a_mute_only_silences_the_account_that_was_muted(api):
    author, muted, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for account in (author, muted, other):
        await given_a_profile(account)
    post = await publish(api, author)
    await mute(api, author, muted)

    await like(api, other, post)
    await like(api, muted, post)

    [event] = await outbox_events()
    assert event["data"]["actor_id"] == str(other)


async def test_interacting_with_your_own_post_queues_nothing(api):
    author = uuid.uuid4()
    await given_a_profile(author)
    post = await publish(api, author)

    assert (await like(api, author, post)).status_code == 204
    assert (await share(api, author, post)).status_code == 201
    assert (await reply(api, author, post)).status_code == 201

    assert await count(LikeModel) == 1
    assert await outbox_events() == []
