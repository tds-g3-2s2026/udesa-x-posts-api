"""The revocation marks of users-api, read from its Redis.

ADR-014: users-api owns these keys and posts-api never writes them. The formats
below are a contract between the two services, so they mirror
`users_api/infrastructure/redis/session_store.py` and change only together.
"""

import uuid
from dataclasses import dataclass

from redis.asyncio import Redis

from posts_api.app.repositories.revocations import RevocationStore
from posts_api.app.security import is_session_revoked


def revoked_token_key(jti: str) -> str:
    return f"revoked:jti:{jti}"


def revoked_sessions_key(user_id: uuid.UUID) -> str:
    return f"revoked:user:{user_id}"


@dataclass
class RedisRevocationStore(RevocationStore):
    """Reads from the database where users-api writes, not from the one of this service."""

    redis: Redis

    async def is_revoked(self, jti: str, user_id: uuid.UUID, issued_at: float) -> bool:
        # One round trip for both marks: this runs on every authenticated request.
        token_mark, cutoff = await self.redis.mget(
            revoked_token_key(jti), revoked_sessions_key(user_id)
        )
        return is_session_revoked(
            token_marked=token_mark is not None,
            # A Unix timestamp in whole seconds, as users-api writes it.
            cutoff=None if cutoff is None else int(cutoff),
            issued_at=issued_at,
        )
