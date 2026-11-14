import uuid

import pytest

from posts_api.app.services.interactions import queue_interaction
from tests.events import INTERACTION_CREATED


class InMemoryOutbox:
    def __init__(self) -> None:
        self.events = []

    async def add(self, event) -> None:
        self.events.append(event)


class Mutes:
    def __init__(self, *muted: tuple[uuid.UUID, uuid.UUID]) -> None:
        self._muted = set(muted)

    async def is_muted(self, muter_id: uuid.UUID, muted_id: uuid.UUID) -> bool:
        return (muter_id, muted_id) in self._muted


async def queue(outbox, mutes, *, actor, author, kind="like", reply_id=None):
    await queue_interaction(
        outbox,
        mutes,
        kind,
        actor_id=actor,
        actor_handle="@ana",
        post_id=uuid.uuid4(),
        post_author_id=author,
        reply_id=reply_id,
    )


async def test_the_author_is_told_when_somebody_else_interacts():
    outbox = InMemoryOutbox()

    await queue(outbox, Mutes(), actor=uuid.uuid4(), author=uuid.uuid4())

    [event] = outbox.events
    INTERACTION_CREATED.validate(event.envelope)


async def test_interacting_with_your_own_post_tells_nobody():
    outbox = InMemoryOutbox()
    me = uuid.uuid4()

    await queue(outbox, Mutes(), actor=me, author=me)

    assert outbox.events == []


@pytest.mark.parametrize("kind", ["like", "retweet"])
async def test_the_author_who_muted_the_actor_is_not_told(kind):
    outbox = InMemoryOutbox()
    actor, author = uuid.uuid4(), uuid.uuid4()

    await queue(outbox, Mutes((author, actor)), actor=actor, author=author, kind=kind)

    assert outbox.events == []


async def test_a_mute_in_the_other_direction_does_not_silence_the_actor():
    outbox = InMemoryOutbox()
    actor, author = uuid.uuid4(), uuid.uuid4()

    await queue(outbox, Mutes((actor, author)), actor=actor, author=author)

    assert len(outbox.events) == 1
