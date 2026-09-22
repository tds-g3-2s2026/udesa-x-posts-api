"""Where the rule "can this viewer read this author's posts?" lives.

Centralized here so every query that reads posts shares one filter: the feed,
the single-post view, and whatever a later story adds on top of it (blocking,
muting). A post that slips past this filter is a privacy leak, not a display
bug, so it gets written once and reused, never a second `WHERE` that has to
stay in sync with this one by hand.
"""

import uuid

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import InstrumentedAttribute, aliased

from posts_api.infrastructure.database.models import FollowModel


def visible_to(
    viewer_id: uuid.UUID,
    *,
    author_id: InstrumentedAttribute,
    author_visibility: InstrumentedAttribute,
) -> ColumnElement[bool]:
    """Whether the author behind these two columns lets `viewer_id` read their posts.

    Public authors are visible to anyone. A protected author is visible to
    themselves and to whoever they already approved as a follower — the same
    `follows` row `FollowRepository.is_following` checks elsewhere, read here
    with its own `EXISTS` so the caller's query stays a single statement.

    The `EXISTS` uses its own alias of `follows` and not the bare model: a
    caller whose own query already joins `follows` for another reason (the
    feed does, to pick the followed authors in the first place) would
    otherwise give SQLAlchemy two references to the same table and no way to
    tell which one this `EXISTS` means.
    """
    approved_follow = aliased(FollowModel)
    return or_(
        author_visibility != "protected",
        author_id == viewer_id,
        select(approved_follow.follower_id)
        .where(approved_follow.follower_id == viewer_id, approved_follow.followee_id == author_id)
        .exists(),
    )
