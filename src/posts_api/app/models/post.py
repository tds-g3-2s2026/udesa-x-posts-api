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
    parent_id: uuid.UUID | None = None


@dataclass(frozen=True)
class PostWithAuthor:
    """A post plus the handle of whoever wrote it, the way a reading screen needs it.

    Not the same as `Post`: that one is the row, and this one is the row plus
    a field that lives on the author's profile. The feed and the single-post
    view both read this shape, resolving the handle in the same query instead
    of one round trip per row.
    """

    id: uuid.UUID
    author_id: uuid.UUID
    author_handle: str | None
    content: str | None
    created_at: datetime
    likes_count: int
    retweets_count: int
    replies_count: int
    deleted: bool = False
    parent_id: uuid.UUID | None = None
    # Whether whoever is reading already liked it: a fact about the reader, not
    # about the post, so it is filled in by the query that reads it.
    liked_by_me: bool = False
    retweeted_by_me: bool = False
    retweeted_by: str | None = None
    retweeter_id: uuid.UUID | None = None
    activity_at: datetime | None = None
