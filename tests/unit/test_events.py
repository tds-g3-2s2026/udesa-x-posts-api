import json
import uuid
from datetime import UTC, datetime

import pytest
from jsonschema import ValidationError

from posts_api.app.events import (
    INTERACTION_CREATED,
    InvalidEventError,
    InvitationAccepted,
    PreferencesChanged,
    interaction_created,
    parse_event,
)
from tests.events import (
    CONTRACTS,
    body_of,
    invitation_accepted,
    preferences_changed,
    user_deleted,
)
from tests.events import (
    INTERACTION_CREATED as INTERACTION_CREATED_SCHEMA,
)


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
    assert event.profile_visibility == "protected"
    assert event.at == datetime(2026, 11, 5, 15, 20, tzinfo=UTC)


def test_a_change_of_preferences_published_before_the_visibility_existed_is_read():
    event = parse_event(body_of(preferences_changed(uuid.uuid4(), "es")))

    assert isinstance(event, PreferencesChanged)
    assert event.profile_visibility is None


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


@pytest.mark.parametrize("kind", ["like", "retweet"])
def test_an_interaction_without_a_reply_carries_a_null_reply_id(kind):
    actor, post, author = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime(2026, 11, 8, 18, 42, 10, tzinfo=UTC)

    event = interaction_created(kind, actor, post, author, actor_handle="@ana", now=now)

    INTERACTION_CREATED_SCHEMA.validate(event.envelope)
    assert event.type == INTERACTION_CREATED
    assert event.envelope["source"] == "posts-api"
    assert event.envelope["time"] == "2026-11-08T18:42:10.000Z"
    assert event.envelope["data"] == {
        "kind": kind,
        "actor_id": str(actor),
        "actor_handle": "@ana",
        "post_id": str(post),
        "post_author_id": str(author),
        "reply_id": None,
    }


def test_a_reply_interaction_carries_the_reply_and_an_unknown_handle_is_null():
    actor, post, author, reply = (uuid.uuid4() for _ in range(4))

    event = interaction_created(
        "reply", actor, post, author, actor_handle=None, reply_id=reply, now=datetime.now(UTC)
    )

    INTERACTION_CREATED_SCHEMA.validate(event.envelope)
    assert event.envelope["data"]["actor_handle"] is None
    assert event.envelope["data"]["post_id"] == str(post)
    assert event.envelope["data"]["reply_id"] == str(reply)


def test_a_reply_interaction_without_its_reply_breaks_the_schema():
    event = interaction_created(
        "reply",
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        actor_handle=None,
        now=datetime.now(UTC),
    )

    with pytest.raises(ValidationError):
        INTERACTION_CREATED_SCHEMA.validate(event.envelope)
