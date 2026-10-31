import base64
import uuid

import pytest

from posts_api.app.errors import ProblemError
from posts_api.app.pagination import Cursor


@pytest.mark.parametrize(
    "timestamp",
    ["0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59"],
)
def test_e2_h10_ca4_extreme_cursor_offsets_are_invalid(timestamp):
    raw = f"{timestamp}|{uuid.uuid4()}".encode()
    cursor = base64.urlsafe_b64encode(raw).decode()

    with pytest.raises(ProblemError):
        Cursor.decode(cursor)
