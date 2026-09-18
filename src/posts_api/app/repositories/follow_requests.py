"""Everything the follow requests need from PostgreSQL.

Shares the session of the request with `FollowRepository`, so a request opened
here and a counter moved there land in the same transaction.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from posts_api.app.models.follow import (
    FollowRequest,
    FollowRequestStatus,
    PendingFollowRequest,
)
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

    async def pending_for(self, target_id: uuid.UUID) -> list[PendingFollowRequest]:
        """The requests aimed at an account, newest first.

        The handle is read in the same query, joined against the requester's
        profile: asking for it row by row would be one round trip per line of
        the screen.
        """
        found = await self._session.execute(
            select(FollowRequestModel, UserProfileModel.handle)
            .join(UserProfileModel, UserProfileModel.id == FollowRequestModel.requester_id)
            .where(
                FollowRequestModel.target_id == target_id,
                FollowRequestModel.status == FollowRequestStatus.PENDING,
            )
            .order_by(FollowRequestModel.created_at.desc())
        )
        return [
            PendingFollowRequest(id=row.id, requester_handle=handle, created_at=row.created_at)
            for row, handle in found.all()
        ]
