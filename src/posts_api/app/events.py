"""The events this service consumes, read from the message body.

The shape is the CloudEvents envelope that `contracts/events/` describes. Only
what the service uses is read, and extra fields are ignored: the producer
validates against the schema, and a consumer that refused what it does not
know would break on the first compatible change.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

USER_DELETED = "user.deleted.v1"

# What the handler tells the consumer to do with the message: take it off the
# queue, or send it to the dead letter queue because retrying cannot fix it. A
# failure that may pass (the database is down) is not an outcome: it is raised.
Outcome = Literal["ack", "reject"]


class InvalidEventError(Exception):
    """The message is not an event this service can act on, and never will be."""


@dataclass(frozen=True)
class UserDeleted:
    event_id: uuid.UUID
    user_id: uuid.UUID
    # `time` of the envelope: when users-api closed the account.
    at: datetime


def parse_user_deleted(body: bytes) -> UserDeleted:
    try:
        envelope = json.loads(body)
    except ValueError as exc:
        raise InvalidEventError("The body is not JSON") from exc
    if not isinstance(envelope, dict):
        raise InvalidEventError("The body is not an object")
    if envelope.get("specversion") != "1.0" or envelope.get("type") != USER_DELETED:
        raise InvalidEventError(f"Not a {USER_DELETED} event")
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise InvalidEventError("The event has no data")
    try:
        event_id = uuid.UUID(str(envelope["id"]))
        user_id = uuid.UUID(str(data["user_id"]))
        at = datetime.fromisoformat(str(envelope["time"]))
    except (KeyError, ValueError) as exc:
        raise InvalidEventError("The event is missing a field or it is malformed") from exc
    if at.tzinfo is None:
        raise InvalidEventError("The time of the event has no time zone")
    return UserDeleted(event_id=event_id, user_id=user_id, at=at)
