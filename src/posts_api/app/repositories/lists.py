"""Everything lists read and write in PostgreSQL."""

import uuid

from sqlalchemy import ScalarSelect, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.models.lists import AccountList, ListMember
from posts_api.infrastructure.database.models import ListMemberModel, ListModel, UserProfileModel


def members_count() -> ScalarSelect[int]:
    """How many accounts the list in the outer query holds, counted when it is read."""
    return (
        select(func.count())
        .where(ListMemberModel.list_id == ListModel.id)
        .correlate(ListModel)
        .scalar_subquery()
    )


class ListRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_owner(self, owner_id: uuid.UUID) -> None:
        """Hold the owner's profile until the transaction ends.

        Two lists created at the same time would both count nineteen and both go
        in. With the row held, the second one waits and counts twenty.
        """
        await self._session.execute(
            select(UserProfileModel.id).where(UserProfileModel.id == owner_id).with_for_update()
        )

    async def count_owned(self, owner_id: uuid.UUID) -> int:
        return await self._session.scalar(
            select(func.count()).select_from(ListModel).where(ListModel.owner_id == owner_id)
        )

    async def create(self, owner_id: uuid.UUID, name: str) -> AccountList:
        created = await self._session.execute(
            insert(ListModel)
            .values(owner_id=owner_id, name=name)
            .returning(ListModel.id, ListModel.created_at)
        )
        list_id, created_at = created.one()
        return AccountList(id=list_id, name=name, members_count=0, created_at=created_at)

    async def owned_by(self, owner_id: uuid.UUID) -> list[AccountList]:
        """The owner's lists, oldest first."""
        found = await self._session.execute(
            select(ListModel.id, ListModel.name, members_count(), ListModel.created_at)
            .where(ListModel.owner_id == owner_id)
            .order_by(ListModel.created_at, ListModel.id)
        )
        return [
            AccountList(id=list_id, name=name, members_count=count, created_at=created_at)
            for list_id, name, count, created_at in found.all()
        ]

    async def find_owned(self, list_id: uuid.UUID, owner_id: uuid.UUID) -> AccountList | None:
        """The list, or None when it does not exist or belongs to someone else.

        Both look the same from outside: nobody gets to confirm that a list made
        by another account exists.
        """
        found = await self._session.execute(
            select(ListModel.id, ListModel.name, members_count(), ListModel.created_at).where(
                ListModel.id == list_id, ListModel.owner_id == owner_id
            )
        )
        row = found.one_or_none()
        if row is None:
            return None
        return AccountList(id=row[0], name=row[1], members_count=row[2], created_at=row[3])

    async def rename(self, list_id: uuid.UUID, name: str) -> None:
        await self._session.execute(
            update(ListModel).where(ListModel.id == list_id).values(name=name)
        )

    async def delete(self, list_id: uuid.UUID) -> None:
        """Delete the list. Its members go with it: `list_members` cascades."""
        await self._session.execute(delete(ListModel).where(ListModel.id == list_id))

    async def lock(self, list_id: uuid.UUID) -> None:
        """Hold the list until the transaction ends, for the same reason as `lock_owner`."""
        await self._session.execute(
            select(ListModel.id).where(ListModel.id == list_id).with_for_update()
        )

    async def is_member(self, list_id: uuid.UUID, member_id: uuid.UUID) -> bool:
        return await self._session.get(ListMemberModel, (list_id, member_id)) is not None

    async def count_members(self, list_id: uuid.UUID) -> int:
        return await self._session.scalar(
            select(func.count())
            .select_from(ListMemberModel)
            .where(ListMemberModel.list_id == list_id)
        )

    async def add_member(self, list_id: uuid.UUID, member_id: uuid.UUID) -> None:
        await self._session.execute(
            insert(ListMemberModel)
            .values(list_id=list_id, member_id=member_id)
            .on_conflict_do_nothing()
        )

    async def remove_member(self, list_id: uuid.UUID, member_id: uuid.UUID) -> None:
        await self._session.execute(
            delete(ListMemberModel).where(
                ListMemberModel.list_id == list_id, ListMemberModel.member_id == member_id
            )
        )

    async def members(self, list_id: uuid.UUID) -> list[ListMember]:
        """The accounts in the list, the most recently added first."""
        found = await self._session.execute(
            select(ListMemberModel.member_id, UserProfileModel.handle, ListMemberModel.added_at)
            .join(UserProfileModel, UserProfileModel.id == ListMemberModel.member_id)
            .where(ListMemberModel.list_id == list_id)
            .order_by(ListMemberModel.added_at.desc(), ListMemberModel.member_id)
        )
        return [
            ListMember(id=member_id, handle=handle, added_at=added_at)
            for member_id, handle, added_at in found.all()
        ]
