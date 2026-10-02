import uuid
from types import SimpleNamespace

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from posts_api.api.deps import get_current_user
from posts_api.app.errors import ProblemError
from posts_api.app.models.follow import ProfileVisibility
from posts_api.app.security import load_public_key
from tests.conftest import issue_token


def fake_request():
    """The verification key and expected issuer loaded at startup."""
    import os

    key = load_public_key(os.environ["JWT_PUBLIC_KEY"])
    state = SimpleNamespace(jwt_public_key=key, settings=SimpleNamespace(jwt_issuer="users-api"))
    return SimpleNamespace(app=SimpleNamespace(state=state))


def bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_a_valid_token_yields_the_account_that_signed_in():
    subject = uuid.uuid4()

    resolved = get_current_user(fake_request(), bearer(issue_token(subject, handle="@pepita")))

    assert resolved.id == subject
    assert resolved.handle == "@pepita"


def test_a_token_without_a_handle_still_authenticates():
    """Tokens minted before users-api started sending it stay valid."""
    subject = uuid.uuid4()

    resolved = get_current_user(fake_request(), bearer(issue_token(subject, handle=None)))

    assert resolved.id == subject
    assert resolved.handle is None


def test_a_token_carrying_protected_resolves_to_that_visibility():
    subject = uuid.uuid4()

    resolved = get_current_user(
        fake_request(), bearer(issue_token(subject, profile_visibility="protected"))
    )

    assert resolved.profile_visibility is ProfileVisibility.PROTECTED


def test_a_token_without_a_visibility_claim_still_authenticates():
    """Same reasoning as the handle: tokens minted before this existed stay valid."""
    subject = uuid.uuid4()

    resolved = get_current_user(
        fake_request(), bearer(issue_token(subject, profile_visibility=None))
    )

    assert resolved.id == subject
    assert resolved.profile_visibility is None


def test_a_token_with_a_nonsense_visibility_value_is_ignored_rather_than_rejected():
    """A client should never get logged out over a field it does not read."""
    subject = uuid.uuid4()

    resolved = get_current_user(
        fake_request(), bearer(issue_token(subject, profile_visibility="not-a-real-value"))
    )

    assert resolved.id == subject
    assert resolved.profile_visibility is None


def test_a_tampered_token_is_answered_with_401():
    token = issue_token()
    tampered = token[:-4] + "AAAA"

    with pytest.raises(ProblemError) as error:
        get_current_user(fake_request(), bearer(tampered))

    assert error.value.status == 401
    assert error.value.code == "invalid-token"


def test_an_expired_token_is_answered_with_401():
    expired = issue_token(expires_in_minutes=-1)

    with pytest.raises(ProblemError) as error:
        get_current_user(fake_request(), bearer(expired))

    assert error.value.status == 401


def test_something_that_is_not_a_token_is_answered_with_401():
    with pytest.raises(ProblemError) as error:
        get_current_user(fake_request(), bearer("no-soy-un-token"))

    assert error.value.status == 401
