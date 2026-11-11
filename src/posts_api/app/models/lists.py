"""What a list of accounts is, in plain Python.

The tables are `lists` and `list_members` in `infrastructure/database/models.py`;
these are what the rules about lists are written against.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AccountList:
    """A list as its owner sees it on the lists screen."""

    id: uuid.UUID
    name: str
    members_count: int
    created_at: datetime


@dataclass(frozen=True)
class ListMember:
    """An account inside a list. The handle is empty until users-api sends it."""

    id: uuid.UUID
    handle: str | None
    added_at: datetime
