"""The outbox, on PostgreSQL through SQLAlchemy."""

from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.events import Event
from posts_api.app.repositories.outbox import OutboxRepository
from posts_api.infrastructure.database.models import OutboxModel


class SqlAlchemyOutboxRepository(OutboxRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, event: Event) -> None:
        self.session.add(OutboxModel(id=event.id, type=event.type, payload=event.envelope))
