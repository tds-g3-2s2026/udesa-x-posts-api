"""What a report is, in plain Python.

No SQLAlchemy here, same reasoning as `app/models/follow.py`: the table that
stores this lives in `infrastructure/database/models.py`.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ReportReason(StrEnum):
    """The closed list of E3-H5 CA.1. Anything else is refused before it is stored,
    so the reports can be counted and filtered by reason without guessing what
    somebody meant by free text."""

    SPAM = "spam"
    HARASSMENT = "harassment"
    INAPPROPRIATE_CONTENT = "inappropriate_content"
    IMPERSONATION = "impersonation"


@dataclass(frozen=True)
class Report:
    """One account reporting another.

    Always aimed at an account. `post_id` says which post it was reported from,
    when it was: the threshold of CA.2 counts per account either way.
    """

    id: uuid.UUID
    reporter_id: uuid.UUID
    target_id: uuid.UUID
    post_id: uuid.UUID | None
    reason: ReportReason
    created_at: datetime
