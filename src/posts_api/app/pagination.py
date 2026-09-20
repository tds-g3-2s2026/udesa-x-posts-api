"""Cursor pagination, shared by every listing that pages through more than one screen.

`OFFSET` breaks the moment a row is inserted or removed while the caller is
still scrolling, because the offset counts positions and a change upstream
shifts every position after it. A cursor does not count positions: it
remembers the exact row the last page ended on and asks for what comes after
it, so an insertion elsewhere never repeats or skips anything.

The cursor is opaque to whoever holds it. It is encoded and decoded only here,
so the column a listing orders by can change later without breaking a client
that does nothing but echo the value back.
"""

import base64
import binascii
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, Select, tuple_

from posts_api.app.errors import ProblemError

# Every cursor-paginated listing in the service pages at the same size.
DEFAULT_PAGE_SIZE = 20


@dataclass(frozen=True)
class Cursor:
    """The tiebreak a page ends on: the ordering column plus an id.

    The ordering column alone is not enough, because two rows can share the
    same instant. Adding the id as a second key is what makes the order total:
    without it, a tie could come back twice or not at all depending on how the
    database happens to lay the rows out.
    """

    at: datetime
    tiebreak: uuid.UUID

    def encode(self) -> str:
        raw = f"{self.at.isoformat()}|{self.tiebreak}"
        return base64.urlsafe_b64encode(raw.encode()).decode()

    @classmethod
    def decode(cls, value: str) -> "Cursor":
        try:
            raw = base64.urlsafe_b64decode(value.encode()).decode()
            at_raw, tiebreak_raw = raw.split("|")
            return cls(at=datetime.fromisoformat(at_raw), tiebreak=uuid.UUID(tiebreak_raw))
        except (ValueError, binascii.Error) as error:
            # A client is never expected to build one of these by hand, but a
            # stale cursor from a previous deploy or a tampered query string
            # should not turn into a 500.
            raise ProblemError(
                status=400,
                code="invalid-cursor",
                title="Cursor inválido",
                detail="El cursor no tiene un formato reconocible",
            ) from error


def apply_cursor(
    statement: Select,
    *,
    order_by: ColumnElement,
    tiebreak_by: ColumnElement,
    cursor: Cursor | None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> Select:
    """Add the keyset `WHERE`, the stable `ORDER BY` and the `LIMIT` a page needs.

    One row past the page is asked for on purpose: getting `limit + 1` rows
    back is what tells `page_of` whether there is a next page, without a
    second round trip just to check.
    """
    if cursor is not None:
        # A row-value comparison, not two conditions stitched with OR: it reads
        # the same way the composite index does, so the planner can walk it
        # instead of falling back to a filter.
        statement = statement.where(
            tuple_(order_by, tiebreak_by) < tuple_(cursor.at, cursor.tiebreak)
        )
    return statement.order_by(order_by.desc(), tiebreak_by.desc()).limit(limit + 1)


def page_of[T](
    rows: list[T],
    *,
    limit: int,
    at: callable,
    tiebreak: callable,
) -> tuple[list[T], str | None]:
    """Split what `apply_cursor` fetched into the page and the cursor for the next one.

    `at` and `tiebreak` read the ordering column and the id off of one row,
    however the caller's row is shaped: a repository has no single row type
    every listing shares.
    """
    has_more = len(rows) > limit
    page = rows[:limit]
    if not has_more:
        return page, None
    last = page[-1]
    return page, Cursor(at=at(last), tiebreak=tiebreak(last)).encode()
