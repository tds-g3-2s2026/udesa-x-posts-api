"""Reading an account's details from users-api, over its internal route.

The same route family as `account_review.py`: outside `/api`, so the gateway
never reaches it, and guarded by the shared token the client already carries.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass

import httpx
from pydantic import TypeAdapter

from posts_api.app.models.profile import AccountDetails
from posts_api.app.repositories.user_directory import UserDirectory, UserDirectoryUnavailableError

logger = logging.getLogger(__name__)

# One retry, as "Comunicación entre servicios" asks of every synchronous call.
# Kept short on purpose: somebody is waiting for the profile to open.
ATTEMPTS = 2
BACKOFF_SECONDS = 0.2
ACCOUNT_DETAILS_ADAPTER = TypeAdapter(AccountDetails)


def is_missing_account(response: httpx.Response) -> bool:
    """A 404 that users-api itself wrote, and not one for a route it lacks.

    An older users-api without the route also answers 404. Read as "the
    account does not exist", that would hide every profile during a rollout,
    so only the problem type it raises for a missing account counts.
    """
    if response.status_code != httpx.codes.NOT_FOUND:
        return False
    try:
        body = response.json()
    except (TypeError, ValueError):
        return False
    return (
        isinstance(body, dict)
        and isinstance(body.get("type"), str)
        and body["type"].endswith("/account-not-found")
    )


@dataclass
class HttpUserDirectory(UserDirectory):
    # The client opened once in the lifespan, shared with the account review:
    # the base URL, the timeout and the token are already set.
    client: httpx.AsyncClient

    async def details_of(self, user_id: uuid.UUID) -> AccountDetails | None:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                response = await self.client.get(f"/internal/users/{user_id}/profile")
                if is_missing_account(response):
                    return None
                response.raise_for_status()
                details = ACCOUNT_DETAILS_ADAPTER.validate_json(response.content, strict=True)
                if not details.handle:
                    raise ValueError("Expected a non-empty account handle")
                return details
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                # The last attempt always ends here or in the return above, so
                # the loop never falls through.
                if attempt == ATTEMPTS:
                    logger.warning("users-api did not return the details of %s: %r", user_id, exc)
                    raise UserDirectoryUnavailableError from exc
                await asyncio.sleep(BACKOFF_SECONDS * attempt)
