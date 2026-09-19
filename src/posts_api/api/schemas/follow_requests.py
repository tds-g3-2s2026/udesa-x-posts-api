"""What a follow request looks like on the wire.

The names are not the ones the rest of the code uses: the app was written
against this shape first, so the contract is fixed and the service adapts to it
instead of the other way around.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from posts_api.app.models.follow import PendingFollowRequest


class FollowRequestSummary(BaseModel):
    """One line of the pending requests screen."""

    id: uuid.UUID
    # `serialization_alias` keeps Python naming inside and the agreed name
    # outside: FastAPI serialises responses by alias.
    requester_handle: str | None = Field(serialization_alias="requesterHandle")
    created_at: datetime = Field(serialization_alias="createdAt")

    @classmethod
    def of(cls, pending: PendingFollowRequest) -> "FollowRequestSummary":
        return cls(
            id=pending.id,
            requester_handle=pending.requester_handle,
            created_at=pending.created_at,
        )
