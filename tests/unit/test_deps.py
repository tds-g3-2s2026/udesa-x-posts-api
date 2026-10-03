import uuid
from types import SimpleNamespace

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from redis.exceptions import ConnectionError as RedisConnectionError

from posts_api.api.deps import get_current_user
from posts_api.app.errors import ProblemError
from posts_api.app.models.follow import ProfileVisibility
from posts_api.app.repositories.revocations import RevocationStore
from posts_api.app.security import load_public_key
from tests.conftest import issue_token


def fake_request():
    """The verification key and expected issuer loaded at startup."""
    import os

    key = load_public_key(os.environ["JWT_PUBLIC_KEY"])
    state = SimpleNamespace(jwt_public_key=key, settings=SimpleNamespace(jwt_issuer="users-api"))
    return SimpleNamespace(app=SimpleNamespace(state=state))


class NothingRevoked(RevocationStore):
    async def is_revoked(self, jti: str, user_id: uuid.UUID, issued_at: float) -> bool:
        return False


class Revoked(RevocationStore):
    """Remembers what it was asked, to prove the token's own claims are the ones used."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, uuid.UUID, float]] = []

    async def is_revoked(self, jti: str, user_id: uuid.UUID, issued_at: float) -> bool:
        self.asked.append((jti, user_id, issued_at))
        return True


class RedisDown(RevocationStore):
    async def is_revoked(self, jti: str, user_id: uuid.UUID, issued_at: float) -> bool:
        raise RedisConnectionError("connection refused")


def bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


async def test_a_valid_token_yields_the_account_that_signed_in():
    subject = uuid.uuid4()

    resolved = await get_current_user(
        fake_request(), bearer(issue_token(subject, handle="@pepita")), NothingRevoked()
    )

    assert resolved.id == subject
    assert resolved.handle == "@pepita"


async def test_a_token_without_a_handle_still_authenticates():
    """Tokens minted before users-api started sending it stay valid."""
    subject = uuid.uuid4()

    resolved = await get_current_user(
        fake_request(), bearer(issue_token(subject, handle=None)), NothingRevoked()
    )

    assert resolved.id == subject
    assert resolved.handle is None


async def test_a_token_carrying_protected_resolves_to_that_visibility():
    subject = uuid.uuid4()

    resolved = await get_current_user(
        fake_request(),
        bearer(issue_token(subject, profile_visibility="protected")),
        NothingRevoked(),
    )

    assert resolved.profile_visibility is ProfileVisibility.PROTECTED


async def test_a_token_without_a_visibility_claim_still_authenticates():
    """Same reasoning as the handle: tokens minted before this existed stay valid."""
    subject = uuid.uuid4()

    resolved = await get_current_user(
        fake_request(), bearer(issue_token(subject, profile_visibility=None)), NothingRevoked()
    )

    assert resolved.id == subject
    assert resolved.profile_visibility is None


async def test_a_token_with_a_nonsense_visibility_value_is_ignored_rather_than_rejected():
    """A client should never get logged out over a field it does not read."""
    subject = uuid.uuid4()

    resolved = await get_current_user(
        fake_request(),
        bearer(issue_token(subject, profile_visibility="not-a-real-value")),
        NothingRevoked(),
    )

    assert resolved.id == subject
    assert resolved.profile_visibility is None


async def test_a_tampered_token_is_answered_with_401():
    token = issue_token()
    tampered = token[:-4] + "AAAA"

    with pytest.raises(ProblemError) as error:
        await get_current_user(fake_request(), bearer(tampered), NothingRevoked())

    assert error.value.status == 401
    assert error.value.code == "invalid-token"


async def test_an_expired_token_is_answered_with_401():
    expired = issue_token(expires_in_minutes=-1)

    with pytest.raises(ProblemError) as error:
        await get_current_user(fake_request(), bearer(expired), NothingRevoked())

    assert error.value.status == 401


async def test_something_that_is_not_a_token_is_answered_with_401():
    with pytest.raises(ProblemError) as error:
        await get_current_user(fake_request(), bearer("no-soy-un-token"), NothingRevoked())

    assert error.value.status == 401


async def test_a_revoked_token_is_answered_with_401_session_revoked():
    subject = uuid.uuid4()
    revocations = Revoked()

    with pytest.raises(ProblemError) as error:
        await get_current_user(fake_request(), bearer(issue_token(subject)), revocations)

    assert error.value.status == 401
    assert error.value.code == "session-revoked"
    assert error.value.title == "La sesión ya no es válida"
    assert error.value.detail == "Tu sesión se cerró. Iniciá sesión de nuevo"
    # The mark is looked up by the claims of the token, not by anything else.
    [(jti, user_id, issued_at)] = revocations.asked
    assert user_id == subject
    assert jti
    assert isinstance(issued_at, int)


async def test_a_token_is_not_checked_for_revocation_when_its_signature_is_wrong():
    revocations = Revoked()

    with pytest.raises(ProblemError) as error:
        await get_current_user(fake_request(), bearer("no-soy-un-token"), revocations)

    assert error.value.code == "invalid-token"
    assert revocations.asked == []


async def test_when_the_revocation_marks_cannot_be_read_the_request_is_refused_with_503():
    """Fail closed: a token that cannot be checked is not a token that can pass."""
    with pytest.raises(ProblemError) as error:
        await get_current_user(fake_request(), bearer(issue_token()), RedisDown())

    assert error.value.status == 503
    assert error.value.code == "auth-unavailable"
