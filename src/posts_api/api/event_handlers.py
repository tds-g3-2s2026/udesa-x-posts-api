"""Where the events the service consumes get the services that act on them.

The same seam as `deps.py`, for what arrives from the queue instead of from a
request: the consumer under `infrastructure/` only knows it hands bytes to a
function, and this builds that function.
"""

import logging
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from posts_api.app.errors import ProblemError
from posts_api.app.events import (
    InvalidEventError,
    InvitationAccepted,
    Outcome,
    PreferencesChanged,
    parse_event,
)
from posts_api.app.models.follow import Account, ProfileVisibility
from posts_api.app.repositories.blocks import BlockRepository
from posts_api.app.repositories.feed_language import FeedLanguageRepository
from posts_api.app.repositories.follow_requests import FollowRequestRepository
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.mutes import MuteRepository
from posts_api.app.repositories.user_deletion import UserDeletionRepository
from posts_api.app.services.follows import FollowService
from posts_api.app.services.user_deletion import UserDeletionService
from posts_api.config.settings import get_settings
from posts_api.infrastructure.database.outbox_repository import SqlAlchemyOutboxRepository
from posts_api.infrastructure.redis.rate_limiter import RedisRateLimiter

logger = logging.getLogger(__name__)

FEED_LANGUAGES = frozenset({"es", "en", "all"})
VISIBILITIES = frozenset(visibility.value for visibility in ProfileVisibility)


def build_event_handler(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> Callable[[bytes], Awaitable[Outcome]]:
    async def handle(body: bytes) -> Outcome:
        try:
            event = parse_event(body)
        except InvalidEventError as error:
            logger.warning("Rejected an event that cannot be read: %s", error)
            return "reject"
        if isinstance(event, PreferencesChanged):
            return await _apply_preferences(event)
        if isinstance(event, InvitationAccepted):
            return await _follow_inviter(event)
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

    async def _follow_inviter(event: InvitationAccepted) -> Outcome:
        # Acked and not rejected, as with the feed language: a value this
        # version does not know is a compatible change of the contract.
        if event.inviter_visibility not in VISIBILITIES:
            logger.warning(
                "Event %s: ignored the unknown visibility %s",
                event.event_id,
                event.inviter_visibility,
            )
            return "ack"
        invitee = Account(
            id=event.invitee_id,
            handle=event.invitee_handle,
            profile_visibility=ProfileVisibility.PUBLIC,
        )
        inviter = Account(
            id=event.inviter_id,
            handle=event.inviter_handle,
            profile_visibility=ProfileVisibility(event.inviter_visibility),
        )
        settings = get_settings()
        try:
            # One transaction: the profiles, the follow, its counters and its
            # event land together or not at all.
            async with session_factory() as session, session.begin():
                # The inviter may never have used this service, and a follow
                # needs the account to exist. The event is fresher than the
                # stored copy, which only learns a change of visibility from a
                # token: writing it back keeps a protected account from being
                # followed straight away.
                await FollowRepository(session).ensure_profile(inviter)
                await FollowService(
                    FollowRepository(session),
                    FollowRequestRepository(session),
                    BlockRepository(session),
                    RedisRateLimiter(redis),
                    SqlAlchemyOutboxRepository(session),
                    MuteRepository(session),
                    follow_limit=settings.follow_rate_limit,
                    window_seconds=settings.follow_rate_window_seconds,
                ).follow(invitee, inviter.id)
        except ProblemError as error:
            # The inviter blocked the invitee, closed the account, or the
            # follow limit is spent: retrying would not change any of that.
            logger.info(
                "Event %s: %s does not follow %s (%s)",
                event.event_id,
                event.invitee_id,
                event.inviter_id,
                error.code,
            )
            return "ack"
        logger.info(
            "Event %s: %s follows the account that invited it", event.event_id, event.invitee_id
        )
        return "ack"

    return handle
