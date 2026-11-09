"""The events of the queue, in both directions, as CloudEvents 1.0 envelopes.

The shape is the one `contracts/events/` describes (ADR-017).

Consumed: only what the service uses is read, and extra fields are ignored.
The producer validates against the schema, and a consumer that refused what it
does not know would break on the first compatible change.

Published: pure functions that take what happened and return the envelope.
Nothing here touches a database or a broker, and the tests validate every
envelope built here against its schema.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

USER_DELETED = "user.deleted.v1"
PREFERENCES_CHANGED = "preferences.changed.v1"

SOURCE = "posts-api"
SPEC_VERSION = "1.0"
FOLLOW_CREATED = "follow.created.v1"
ADMIN_ACTION_RECORDED = "admin.action_recorded.v1"

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


@dataclass(frozen=True)
class PreferencesChanged:
    event_id: uuid.UUID
    user_id: uuid.UUID
    # A string and not a closed type: a value this version does not know is a
    # compatible change of the contract, and whoever handles it decides.
    feed_language: str
    # Absent from the events published before the contract carried it: those do
    # not say anything about the visibility.
    profile_visibility: str | None
    # `time` of the envelope: when users-api saved the change.
    at: datetime


def parse_event(body: bytes) -> UserDeleted | PreferencesChanged:
    """The event in the message, or `InvalidEventError` if it is not one this service reads."""
    try:
        envelope = json.loads(body)
    except ValueError as exc:
        raise InvalidEventError("The body is not JSON") from exc
    if not isinstance(envelope, dict):
        raise InvalidEventError("The body is not an object")
    event_type = envelope.get("type")
    if envelope.get("specversion") != "1.0" or event_type not in (
        USER_DELETED,
        PREFERENCES_CHANGED,
    ):
        raise InvalidEventError(f"Not an event this service reads: {event_type}")
    data = envelope.get("data")
    if not isinstance(data, dict):
        raise InvalidEventError("The event has no data")
    try:
        event_id = uuid.UUID(str(envelope["id"]))
        user_id = uuid.UUID(str(data["user_id"]))
        at = datetime.fromisoformat(str(envelope["time"]))
        feed_language = str(data["feed_language"]) if event_type == PREFERENCES_CHANGED else None
    except (KeyError, ValueError) as exc:
        raise InvalidEventError("The event is missing a field or it is malformed") from exc
    if at.tzinfo is None:
        raise InvalidEventError("The time of the event has no time zone")
    if feed_language is None:
        return UserDeleted(event_id=event_id, user_id=user_id, at=at)
    profile_visibility = data.get("profile_visibility")
    return PreferencesChanged(
        event_id=event_id,
        user_id=user_id,
        feed_language=feed_language,
        profile_visibility=str(profile_visibility) if profile_visibility is not None else None,
        at=at,
    )


@dataclass(frozen=True)
class Event:
    """A complete envelope to publish. Its `id` is what consumers deduplicate on."""

    envelope: dict[str, Any]

    @property
    def id(self) -> uuid.UUID:
        return uuid.UUID(self.envelope["id"])

    @property
    def type(self) -> str:
        return self.envelope["type"]


def build_event(event_type: str, data: dict[str, Any], *, now: datetime) -> Event:
    return Event(
        envelope={
            "specversion": SPEC_VERSION,
            "id": str(uuid.uuid4()),
            "source": SOURCE,
            "type": event_type,
            # RFC 3339 in UTC, with the `Z` suffix the schemas' examples use.
            "time": now.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "data": data,
        }
    )


def follow_created(
    follower_id: uuid.UUID,
    followee_id: uuid.UUID,
    *,
    follower_handle: str | None,
    now: datetime,
) -> Event:
    """A follow that exists, either direct or by an approved request: the same event."""
    return build_event(
        FOLLOW_CREATED,
        {
            "follower_id": str(follower_id),
            "follower_handle": follower_handle,
            "followee_id": str(followee_id),
        },
        now=now,
    )


def admin_action_recorded(
    actor_id: uuid.UUID,
    actor_email: str,
    action: str,
    target_id: uuid.UUID,
    reports_count: int,
    *,
    now: datetime,
) -> Event:
    return build_event(
        ADMIN_ACTION_RECORDED,
        {
            "actor_id": str(actor_id),
            "actor_email": actor_email,
            "action": action,
            "target_type": "user",
            "target_id": str(target_id),
            "details": {"reports_count": reports_count},
        },
        now=now,
    )
