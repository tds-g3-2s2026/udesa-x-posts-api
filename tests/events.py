"""The events of the queue as the contract describes them."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

CONTRACTS = Path(__file__).resolve().parent.parent / "contracts" / "events"


def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((CONTRACTS / f"{name}.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


USER_DELETED = _validator("user.deleted.v1")
FOLLOW_CREATED = _validator("follow.created.v1")


def user_deleted(
    user_id: uuid.UUID, *, at: datetime | None = None, event_id: uuid.UUID | None = None
) -> dict:
    """A `user.deleted.v1` message, checked against the schema before it is used."""
    event = {
        "specversion": "1.0",
        "id": str(event_id or uuid.uuid4()),
        "source": "users-api",
        "type": "user.deleted.v1",
        "time": (at or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
        "data": {"user_id": str(user_id)},
    }
    USER_DELETED.validate(event)
    return event


def body_of(event: dict) -> bytes:
    return json.dumps(event).encode("utf-8")
