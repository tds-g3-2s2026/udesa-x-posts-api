"""Where events wait until they are published."""

from abc import ABC, abstractmethod

from posts_api.app.events import Event


class OutboxRepository(ABC):
    @abstractmethod
    async def add(self, event: Event) -> None:
        """Queue the event inside the transaction of the request.

        It commits or rolls back together with the state change that caused it,
        so an event never describes something that did not happen and a change
        never goes without its event. Publishing is a separate step, done later
        by the publisher.
        """
