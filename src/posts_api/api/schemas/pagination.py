"""The one response shape every cursor-paginated listing uses.

A single documented shape so mobile and the backoffice consume the same
thing on every listing, instead of each endpoint inventing its own.
Documented in `ARQUITECTURA.md`.
"""

from pydantic import BaseModel, Field


class CursorPage[ItemT](BaseModel):
    items: list[ItemT]
    # `null` and not an empty string: an empty string reads as "cursor of
    # length zero" instead of "there is nothing after this page".
    next_cursor: str | None = Field(default=None, serialization_alias="nextCursor")
