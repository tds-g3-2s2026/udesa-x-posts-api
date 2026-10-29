import uuid
from abc import ABC, abstractmethod


class AdministratorDirectoryUnavailableError(Exception):
    """The administrator identity could not be obtained from users-api."""


class AdministratorDirectory(ABC):
    @abstractmethod
    async def email_of(self, actor_id: uuid.UUID) -> str: ...
