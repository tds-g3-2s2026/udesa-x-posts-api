"""Telling the author of a post that somebody liked, shared or answered it.

One function for the three services, so the two reasons to stay quiet are
written once: a copy per service would let them drift apart.
"""

import uuid
from datetime import UTC, datetime

from posts_api.app import events
from posts_api.app.repositories.mutes import MuteRepository
from posts_api.app.repositories.outbox import OutboxRepository


async def queue_interaction(
    outbox: OutboxRepository,
    mutes: MuteRepository,
    kind: events.InteractionKind,
    *,
    actor_id: uuid.UUID,
    actor_handle: str | None,
    post_id: uuid.UUID,
    post_author_id: uuid.UUID,
    reply_id: uuid.UUID | None = None,
) -> None:
    """Write `interaction.created.v1` in the caller's transaction, unless nobody should hear of it.

    The interaction itself is already saved by the caller either way: this only
    decides whether the author is told.
    """
    # Answering or liking your own post is not news to anyone.
    if actor_id == post_author_id:
        return
    # A muted account still interacts, the author just does not get the notice:
    # the same rule a follow from a muted account follows.
    if await mutes.is_muted(post_author_id, actor_id):
        return
    await outbox.add(
        events.interaction_created(
            kind,
            actor_id,
            post_id,
            post_author_id,
            actor_handle=actor_handle,
            reply_id=reply_id,
            now=datetime.now(UTC),
        )
    )
