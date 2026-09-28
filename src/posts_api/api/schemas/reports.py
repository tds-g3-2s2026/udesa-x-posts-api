"""What a report looks like on the wire."""

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from posts_api.app.models.report import Report, ReportReason


class CreateReportRequest(BaseModel):
    """An account is reported by its id, a post by its id. Exactly one of the two."""

    model_config = ConfigDict(populate_by_name=True)

    # The enum is the closed list of E3-H5 CA.1: any other reason is a `422`
    # before the service runs.
    reason: ReportReason
    user_id: uuid.UUID | None = Field(default=None, alias="userId")
    post_id: uuid.UUID | None = Field(default=None, alias="postId")

    @model_validator(mode="after")
    def exactly_one_target(self) -> Self:
        if (self.user_id is None) == (self.post_id is None):
            raise ValueError("Indicá la cuenta o el post que querés denunciar, uno solo")
        return self


class ReportSummary(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID = Field(serialization_alias="userId")
    post_id: uuid.UUID | None = Field(serialization_alias="postId")
    reason: ReportReason
    created_at: datetime = Field(serialization_alias="createdAt")

    @classmethod
    def of(cls, report: Report) -> "ReportSummary":
        return cls(
            id=report.id,
            user_id=report.target_id,
            post_id=report.post_id,
            reason=report.reason,
            created_at=report.created_at,
        )
