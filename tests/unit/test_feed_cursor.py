import base64
import uuid
from datetime import UTC, datetime

import pytest

from posts_api.app.errors import ProblemError
from posts_api.app.feed_pagination import FeedCursor


def test_activity_cursor_round_trip_preserves_every_tiebreak():
    cursor = FeedCursor(datetime.now(UTC), uuid.uuid4(), 1, uuid.uuid4())
    assert FeedCursor.decode(cursor.encode()) == cursor


@pytest.mark.parametrize(
    "raw",
    [
        "garbage",
        "2026-10-17T00:00:00|bad|0|bad",
        "2026-10-17T00:00:00|00000000-0000-0000-0000-000000000000|0|00000000-0000-0000-0000-000000000000",
        "2026-10-17T00:00:00+00:00|00000000-0000-0000-0000-000000000000|2|00000000-0000-0000-0000-000000000000",
    ],
)
def test_malformed_or_ambiguous_activity_cursors_are_rejected(raw):
    encoded = base64.urlsafe_b64encode(raw.encode()).decode()
    with pytest.raises(ProblemError) as error:
        FeedCursor.decode(encoded)
    assert error.value.status == 400
