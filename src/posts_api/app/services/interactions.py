"""Telling somebody that an account liked, shared, answered or mentioned them.

The reasons to stay quiet are written once, here: a copy per service would let them
drift apart.
"""

import uuid
from datetime import UTC, datetime

from posts_api.app import events
from posts_api.app.repositories.mutes import MuteRepository
from posts_api.app.repositories.outbox import OutboxRepository


async def _is_not_news(
    mutes: MuteRepository, *, actor_id: uuid.UUID, recipient_id: uuid.UUID
) -> bool:
    """Whether what `actor_id` did is not worth telling `recipient_id` about."""
    # Answering, liking or naming yourself is not news to anyone.
    if actor_id == recipient_id:
        return True
    # A muted account still acts, the recipient just does not get the notice:
    # the same rule a follow from a muted account follows.
    return await mutes.is_muted(recipient_id, actor_id)


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
    if await _is_not_news(mutes, actor_id=actor_id, recipient_id=post_author_id):
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


async def queue_mention(
    outbox: OutboxRepository,
    mutes: MuteRepository,
    *,
    author_id: uuid.UUID,
    author_handle: str | None,
    mentioned_id: uuid.UUID,
    post_id: uuid.UUID,
    root_post_id: uuid.UUID,
    content: str,
) -> None:
    """Write `mention.created.v1` in the caller's transaction, unless nobody should hear of it.

    The mention itself is already saved by the caller either way: this only decides
    whether the mentioned account is told. Whether it can read the post at all is
    for the caller to settle first, with the rule every read of posts shares.
    """
    if await _is_not_news(mutes, actor_id=author_id, recipient_id=mentioned_id):
        return
    await outbox.add(
        events.mention_created(
            author_id,
            mentioned_id,
            post_id,
            root_post_id,
            author_handle=author_handle,
            content=content,
            now=datetime.now(UTC),
        )
    )
