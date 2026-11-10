import json
import uuid
from datetime import UTC, datetime

import pytest

from posts_api.app.events import (
    InvalidEventError,
    InvitationAccepted,
    PreferencesChanged,
    parse_event,
)
from tests.events import CONTRACTS, body_of, invitation_accepted, preferences_changed, user_deleted


def test_the_example_of_the_contract_is_read():
    schema = json.loads((CONTRACTS / "user.deleted.v1.json").read_text(encoding="utf-8"))
    example = schema["examples"][0]

    event = parse_event(json.dumps(example).encode())

    assert str(event.event_id) == example["id"]
    assert str(event.user_id) == example["data"]["user_id"]
    assert event.at == datetime(2026, 10, 23, 15, 20, tzinfo=UTC)


def test_the_time_of_the_envelope_is_when_the_account_was_closed():
    at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    event = parse_event(body_of(user_deleted(uuid.uuid4(), at=at)))

    assert event.at == at


def test_fields_the_service_does_not_know_are_ignored():
    event = user_deleted(uuid.uuid4())
    event["data"]["reason"] = "requested by the owner"
    event["traceparent"] = "00-abc"

    assert parse_event(body_of(event)).user_id == uuid.UUID(event["data"]["user_id"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e.update(type="user.registered.v1"),
        lambda e: e.update(specversion="0.3"),
        lambda e: e.update(id="not-a-uuid"),
        lambda e: e.update(time="yesterday"),
        lambda e: e.update(time="2026-10-23T15:20:00"),
        lambda e: e.pop("id"),
        lambda e: e.pop("time"),
        lambda e: e.pop("data"),
        lambda e: e.update(data="x"),
        lambda e: e["data"].pop("user_id"),
        lambda e: e["data"].update(user_id="7"),
    ],
)
def test_a_message_that_is_not_a_user_deleted_event_is_invalid(mutate):
    event = user_deleted(uuid.uuid4())
    mutate(event)

    with pytest.raises(InvalidEventError):
        parse_event(body_of(event))


@pytest.mark.parametrize("body", [b"not json", b"[]", b'"text"', b"null", b"\xff\xfe"])
def test_a_body_that_is_not_an_object_is_invalid(body):
    with pytest.raises(InvalidEventError):
        parse_event(body)


def test_the_example_of_the_preferences_contract_is_read():
    schema = json.loads((CONTRACTS / "preferences.changed.v1.json").read_text(encoding="utf-8"))
    example = schema["examples"][0]

    event = parse_event(json.dumps(example).encode())

    assert isinstance(event, PreferencesChanged)
    assert str(event.user_id) == example["data"]["user_id"]
    assert event.feed_language == "es"
    assert event.at == datetime(2026, 11, 5, 15, 20, tzinfo=UTC)


def test_a_change_of_preferences_without_the_language_is_refused():
    event = preferences_changed(uuid.uuid4(), "es")
    event["data"].pop("feed_language")

    with pytest.raises(InvalidEventError):
        parse_event(body_of(event))


def test_the_example_of_the_invitation_contract_is_read():
    schema = json.loads((CONTRACTS / "invitation.accepted.v1.json").read_text(encoding="utf-8"))
    example = schema["examples"][0]

    event = parse_event(json.dumps(example).encode())

    assert isinstance(event, InvitationAccepted)
    assert str(event.invitee_id) == example["data"]["invitee_id"]
    assert str(event.inviter_id) == example["data"]["inviter_id"]
    assert event.inviter_visibility == "public"
    assert event.at == datetime(2026, 11, 8, 18, 42, 10, tzinfo=UTC)


@pytest.mark.parametrize(
    "field", ["invitee_id", "invitee_handle", "inviter_id", "inviter_handle", "inviter_visibility"]
)
def test_an_invitation_missing_a_field_is_refused(field):
    event = invitation_accepted(uuid.uuid4(), uuid.uuid4())
    del event["data"][field]

    with pytest.raises(InvalidEventError):
        parse_event(body_of(event))
