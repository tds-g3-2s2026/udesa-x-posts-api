"""What one row of the blocked-accounts screen looks like on the wire."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from posts_api.app.models.follow import BlockedAccount


class BlockedAccountSummary(BaseModel):
    id: uuid.UUID
    handle: str | None
    created_at: datetime = Field(serialization_alias="createdAt")

    @classmethod
    def of(cls, account: BlockedAccount) -> "BlockedAccountSummary":
        return cls(id=account.id, handle=account.handle, created_at=account.created_at)
