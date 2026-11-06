"""Where the events the service consumes get the services that act on them.

The same seam as `deps.py`, for what arrives from the queue instead of from a
request: the consumer under `infrastructure/` only knows it hands bytes to a
function, and this builds that function.
"""

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from posts_api.app.events import InvalidEventError, Outcome, PreferencesChanged, parse_event
from posts_api.app.repositories.feed_language import FeedLanguageRepository
from posts_api.app.repositories.user_deletion import UserDeletionRepository
from posts_api.app.services.user_deletion import UserDeletionService

logger = logging.getLogger(__name__)

FEED_LANGUAGES = frozenset({"es", "en", "all"})


def build_event_handler(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[bytes], Awaitable[Outcome]]:
    async def handle(body: bytes) -> Outcome:
        try:
            event = parse_event(body)
        except InvalidEventError as error:
            logger.warning("Rejected an event that cannot be read: %s", error)
            return "reject"
        if isinstance(event, PreferencesChanged):
            return await _apply_preferences(event)
        # One transaction for the whole account: it all lands or none of it does,
        # and the message goes back to the queue.
        async with session_factory() as session, session.begin():
            closed = await UserDeletionService(UserDeletionRepository(session)).apply(
                event.user_id, event.at
            )
        logger.info(
            "Event %s: account %s %s",
            event.event_id,
            event.user_id,
            "closed" if closed else "was already closed",
        )
        return "ack"

    async def _apply_preferences(event: PreferencesChanged) -> Outcome:
        # Acked and not rejected: a new value is a compatible change of the
        # contract (ADR-017), and retrying would not make this version know it.
        if event.feed_language not in FEED_LANGUAGES:
            logger.warning(
                "Event %s: ignored the unknown feed language %s",
                event.event_id,
                event.feed_language,
            )
            return "ack"
        async with session_factory() as session, session.begin():
            applied = await FeedLanguageRepository(session).apply(
                event.user_id, event.feed_language, event.at
            )
        logger.info(
            "Event %s: account %s feed language %s",
            event.event_id,
            event.user_id,
            event.feed_language if applied else "not changed, a newer one was already applied",
        )
        return "ack"

    return handle
