import asyncio
import uuid
from dataclasses import dataclass
from email.utils import getaddresses

import httpx

from posts_api.app.repositories.administrator_directory import (
    AdministratorDirectory,
    AdministratorDirectoryUnavailableError,
)

ATTEMPTS = 2
BACKOFF_SECONDS = 0.2


@dataclass
class HttpAdministratorDirectory(AdministratorDirectory):
    client: httpx.AsyncClient

    async def email_of(self, actor_id: uuid.UUID) -> str:
        for attempt in range(ATTEMPTS):
            try:
                response = await self.client.get(f"/internal/administrators/{actor_id}/identity")
                response.raise_for_status()
                body = response.json()
                identity_id = body["id"]
                if not isinstance(identity_id, str) or uuid.UUID(identity_id) != actor_id:
                    raise ValueError("Administrator identity does not match")
                email = body["email"]
                if not isinstance(email, str):
                    raise ValueError("Administrator email is not text")
                if getaddresses([email], strict=True) != [("", email)]:
                    raise ValueError("Administrator email is malformed")
                local, _, domain = email.rpartition("@")
                if not local or not domain:
                    raise ValueError("Administrator email is incomplete")
                return email
            except (httpx.HTTPError, ValueError, TypeError, KeyError) as error:
                if attempt == ATTEMPTS - 1:
                    raise AdministratorDirectoryUnavailableError from error
                await asyncio.sleep(BACKOFF_SECONDS)
