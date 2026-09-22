"""What a post is, in plain Python.

No SQLAlchemy here, same reasoning as `app/models/follow.py`: the table that
stores this lives in `infrastructure/database/models.py`, and this is what the
rules about creating and reading a post get written against.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Post:
    """A published post, with its counters at whatever they currently are.

    `id` and `created_at` are `None` before the row exists: both are assigned
    by PostgreSQL on insert, not chosen here.
    """

    author_id: uuid.UUID
    content: str
    id: uuid.UUID | None = None
    created_at: datetime | None = None
    likes_count: int = 0
    retweets_count: int = 0
    replies_count: int = 0
