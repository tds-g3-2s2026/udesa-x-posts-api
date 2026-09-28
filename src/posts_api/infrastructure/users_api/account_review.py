"""Putting an account under review by calling users-api, as ADR-011 decides.

The route is internal: it hangs outside `/api`, so neither the Ingress nor the
gateway ever reach it, and it still asks for the shared secret in case a route
gets added there by mistake.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass

import httpx

from posts_api.app.repositories.account_review import AccountReview

logger = logging.getLogger(__name__)

INTERNAL_TOKEN_HEADER = "X-Internal-Token"

# One retry, as "Comunicación entre servicios" asks of every synchronous call.
# Kept short on purpose: the reporter is waiting for the response.
ATTEMPTS = 2
BACKOFF_SECONDS = 0.2


@dataclass
class HttpAccountReview(AccountReview):
    # Opened once in the lifespan with the base URL, the timeout and the
    # secret already set, the same as the Redis connection.
    client: httpx.AsyncClient

    async def put_under_review(self, user_id: uuid.UUID) -> None:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                response = await self.client.post(f"/internal/users/{user_id}/review")
                response.raise_for_status()
                return
            except httpx.HTTPError as exc:
                if attempt < ATTEMPTS:
                    await asyncio.sleep(BACKOFF_SECONDS * attempt)
                    continue
                # Logged and swallowed: the report is already stored, and the
                # next one aimed at this account asks again.
                logger.warning("users-api did not put account %s under review: %r", user_id, exc)


def build_users_api_client(
    base_url: str,
    internal_token: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """`transport` is there for the tests, which answer in place of users-api."""
    return httpx.AsyncClient(
        base_url=base_url,
        headers={INTERNAL_TOKEN_HEADER: internal_token},
        timeout=2.0,
        transport=transport,
    )
