"""ADR-014: the marks users-api writes in its Redis close sessions here too.

The tests write those marks the way users-api does, with the same keys and
formats, into the database `AUTH_REDIS_URL` points at, and ask an authenticated
endpoint what it makes of the token. Each test uses its own account and `jti`,
so nothing has to be flushed from a database that is not this service's.
"""

import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis

from posts_api.infrastructure.redis.revocations import revoked_sessions_key, revoked_token_key
from posts_api.main import app
from tests.conftest import issue_token as sign_token
from tests.conftest import requires_services
from tests.integration.conftest import handle_of

pytestmark = requires_services

# Any authenticated endpoint will do; this one only lists.
PROTECTED = "/blocks"


def issue_token(user_id: uuid.UUID | None = None, **options) -> str:
    """The handle is unique per account: the first request stores it in the profile."""
    user_id = user_id or uuid.uuid4()
    return sign_token(user_id, handle=handle_of(user_id), **options)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def users_api_revokes_all_sessions(user_id: uuid.UUID, *, at: datetime) -> None:
    """What `revoke_all` does in users-api: a cutoff in whole Unix seconds, with a TTL."""
    await app.state.auth_redis.set(revoked_sessions_key(user_id), int(at.timestamp()), ex=900)


async def users_api_logs_out(jti: str) -> None:
    """What `revoke_token` does in users-api."""
    await app.state.auth_redis.set(revoked_token_key(jti), "1", ex=900)


async def test_e3_h5_ca4_an_account_put_under_review_loses_the_tokens_it_had(api):
    user_id = uuid.uuid4()
    before = issue_token(user_id, issued_at=datetime.now(UTC) - timedelta(seconds=30))

    assert (await api.get(PROTECTED, headers=bearer(before))).status_code == 200

    await users_api_revokes_all_sessions(user_id, at=datetime.now(UTC))
    response = await api.get(PROTECTED, headers=bearer(before))

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["type"] == "https://udesa-x.dev/errors/session-revoked"
    assert body["title"] == "La sesión ya no es válida"
    assert body["detail"] == "Tu sesión se cerró. Iniciá sesión de nuevo"


async def test_a_token_issued_after_the_cutoff_keeps_working(api):
    user_id = uuid.uuid4()
    await users_api_revokes_all_sessions(user_id, at=datetime.now(UTC) - timedelta(seconds=30))

    response = await api.get(PROTECTED, headers=bearer(issue_token(user_id)))

    assert response.status_code == 200


async def test_a_token_issued_in_the_second_of_the_cutoff_is_revoked(api):
    user_id = uuid.uuid4()
    moment = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=5)
    await users_api_revokes_all_sessions(user_id, at=moment)

    response = await api.get(PROTECTED, headers=bearer(issue_token(user_id, issued_at=moment)))

    assert response.status_code == 401
    assert response.json()["type"].endswith("/session-revoked")


async def test_the_cutoff_of_one_account_does_not_touch_another(api):
    await users_api_revokes_all_sessions(uuid.uuid4(), at=datetime.now(UTC) + timedelta(hours=1))

    response = await api.get(PROTECTED, headers=bearer(issue_token(uuid.uuid4())))

    assert response.status_code == 200


async def test_a_logout_revokes_that_token_and_not_the_other_sessions_of_the_account(api):
    user_id = uuid.uuid4()
    closed_jti = str(uuid.uuid4())
    closed = issue_token(user_id, jti=closed_jti)
    other = issue_token(user_id)
    await users_api_logs_out(closed_jti)

    revoked = await api.get(PROTECTED, headers=bearer(closed))
    still_open = await api.get(PROTECTED, headers=bearer(other))

    assert revoked.status_code == 401
    assert revoked.json()["type"].endswith("/session-revoked")
    assert still_open.status_code == 200


async def test_when_the_revocation_marks_cannot_be_read_the_request_is_refused(api):
    """Fail closed. Port 9 is where nothing listens, so the connection is refused."""
    working = app.state.auth_redis
    app.state.auth_redis = Redis.from_url("redis://127.0.0.1:9/0")
    try:
        response = await api.get(PROTECTED, headers=bearer(issue_token()))
    finally:
        await app.state.auth_redis.aclose()
        app.state.auth_redis = working

    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == "https://udesa-x.dev/errors/auth-unavailable"
