"""Everything the follow requests need from PostgreSQL.

Shares the session of the request with `FollowRepository`, so a request opened
here and a counter moved there land in the same transaction.
"""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.models.follow import (
    FollowRequest,
    FollowRequestStatus,
    PendingFollowRequest,
)
from posts_api.app.pagination import DEFAULT_PAGE_SIZE, Cursor, apply_cursor, page_of
from posts_api.infrastructure.database.models import FollowRequestModel, UserProfileModel


def _to_request(row: FollowRequestModel) -> FollowRequest:
    return FollowRequest(
        id=row.id,
        requester_id=row.requester_id,
        target_id=row.target_id,
        status=FollowRequestStatus(row.status),
        created_at=row.created_at,
    )


class FollowRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_pending(
        self, requester_id: uuid.UUID, target_id: uuid.UUID
    ) -> FollowRequest | None:
        """The open request between two accounts, if there is one."""
        found = await self._session.execute(
            select(FollowRequestModel).where(
                FollowRequestModel.requester_id == requester_id,
                FollowRequestModel.target_id == target_id,
                FollowRequestModel.status == FollowRequestStatus.PENDING,
            )
        )
        row = found.scalar_one_or_none()
        return _to_request(row) if row is not None else None

    async def open(self, requester_id: uuid.UUID, target_id: uuid.UUID) -> FollowRequest:
        row = FollowRequestModel(requester_id=requester_id, target_id=target_id)
        self._session.add(row)
        # Flushed so the row gets its id and its timestamp from the database
        # before the answer is built, without closing the transaction.
        await self._session.flush()
        await self._session.refresh(row)
        return _to_request(row)

    async def find_pending_by_id(
        self, request_id: uuid.UUID, *, target_id: uuid.UUID
    ) -> FollowRequest | None:
        """An open request, but only if it was aimed at that account.

        The owner is part of the query and not a check afterwards: a request
        belonging to somebody else simply does not come back, so there is no
        branch that could forget to compare.
        """
        found = await self._session.execute(
            select(FollowRequestModel).where(
                FollowRequestModel.id == request_id,
                FollowRequestModel.target_id == target_id,
                FollowRequestModel.status == FollowRequestStatus.PENDING,
            )
        )
        row = found.scalar_one_or_none()
        return _to_request(row) if row is not None else None

    async def resolve(self, request_id: uuid.UUID, status: FollowRequestStatus) -> None:
        """Move an open request to its answer.

        The status is part of the condition, so a request already answered is
        not answered twice: the update reaches no rows.
        """
        await self._session.execute(
            update(FollowRequestModel)
            .where(
                FollowRequestModel.id == request_id,
                FollowRequestModel.status == FollowRequestStatus.PENDING,
            )
            .values(status=status)
        )

    async def cancel(self, requester_id: uuid.UUID, target_id: uuid.UUID) -> bool:
        """Withdraw an open request, and report whether there was one.

        The status is part of the condition, like in `resolve`: a request the
        owner already answered is theirs and does not get rewritten by the one
        who asked.
        """
        result = await self._session.execute(
            update(FollowRequestModel)
            .where(
                FollowRequestModel.requester_id == requester_id,
                FollowRequestModel.target_id == target_id,
                FollowRequestModel.status == FollowRequestStatus.PENDING,
            )
            .values(status=FollowRequestStatus.CANCELLED)
        )
        return result.rowcount > 0

    async def pending_for(
        self,
        target_id: uuid.UUID,
        *,
        cursor: Cursor | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[PendingFollowRequest], str | None]:
        """The requests aimed at an account, newest first, one page at a time.

        The handle is read in the same query, joined against the requester's
        profile: asking for it row by row would be one round trip per line of
        the screen.
        """
        base = (
            select(FollowRequestModel, UserProfileModel.handle)
            .join(UserProfileModel, UserProfileModel.id == FollowRequestModel.requester_id)
            .where(
                FollowRequestModel.target_id == target_id,
                FollowRequestModel.status == FollowRequestStatus.PENDING,
            )
        )
        statement = apply_cursor(
            base,
            order_by=FollowRequestModel.created_at,
            tiebreak_by=FollowRequestModel.id,
            cursor=cursor,
            limit=limit,
        )
        found = await self._session.execute(statement)
        rows = [
            PendingFollowRequest(id=row.id, requester_handle=handle, created_at=row.created_at)
            for row, handle in found.all()
        ]
        return page_of(
            rows, limit=limit, at=lambda one: one.created_at, tiebreak=lambda one: one.id
        )
