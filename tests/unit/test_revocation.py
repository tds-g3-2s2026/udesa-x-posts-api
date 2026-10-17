"""The revocation rule and the reader that feeds it, without a Redis.

The keys and the rule mirror users-api, which writes the marks (ADR-014). What
only a real Redis can prove, that the reader and the writer agree on the
format, lives in the integration suite.
"""

import uuid

import pytest

from posts_api.app.security import is_session_revoked
from posts_api.infrastructure.redis.revocations import (
    RedisRevocationStore,
    revoked_sessions_key,
    revoked_token_key,
)

ISSUED_AT = 1_790_000_000


def test_a_token_with_no_marks_is_valid():
    assert not is_session_revoked(token_marked=False, cutoff=None, issued_at=ISSUED_AT)


def test_a_token_whose_own_session_was_closed_is_revoked():
    assert is_session_revoked(token_marked=True, cutoff=None, issued_at=ISSUED_AT)


def test_a_token_issued_after_the_cutoff_is_valid():
    """The session opened after the password change is the new one."""
    assert not is_session_revoked(token_marked=False, cutoff=ISSUED_AT - 1, issued_at=ISSUED_AT)


def test_a_token_issued_in_the_same_second_as_the_cutoff_is_revoked():
    """The cutoff is truncated to the second, so equal has to count as before."""
    assert is_session_revoked(token_marked=False, cutoff=ISSUED_AT, issued_at=ISSUED_AT)


def test_a_token_issued_before_the_cutoff_is_revoked():
    assert is_session_revoked(token_marked=False, cutoff=ISSUED_AT + 1, issued_at=ISSUED_AT)


def test_the_keys_are_the_ones_users_api_writes():
    user_id = uuid.UUID("0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b")

    assert revoked_token_key("abc") == "revoked:jti:abc"
    assert revoked_sessions_key(user_id) == f"revoked:user:{user_id}"


class FakeRedis:
    """Answers MGET from a dict, the way redis-py does: bytes, or None for a missing key."""

    def __init__(self, marks: dict[str, bytes]) -> None:
        self.marks = marks
        self.calls: list[tuple[str, ...]] = []

    async def mget(self, *keys: str) -> list[bytes | None]:
        self.calls.append(keys)
        return [self.marks.get(key) for key in keys]


def store_with(marks: dict[str, bytes]) -> tuple[RedisRevocationStore, FakeRedis]:
    redis = FakeRedis(marks)
    return RedisRevocationStore(redis), redis  # type: ignore[arg-type]


async def test_both_marks_are_fetched_in_one_round_trip():
    user_id = uuid.uuid4()
    store, redis = store_with({})

    assert not await store.is_revoked("the-jti", user_id, ISSUED_AT)

    assert redis.calls == [(revoked_token_key("the-jti"), revoked_sessions_key(user_id))]


async def test_the_mark_of_a_single_logout_revokes_the_token():
    user_id = uuid.uuid4()
    store, _ = store_with({revoked_token_key("the-jti"): b"1"})

    assert await store.is_revoked("the-jti", user_id, ISSUED_AT)
    assert not await store.is_revoked("another-jti", user_id, ISSUED_AT)


@pytest.mark.parametrize(
    ("cutoff", "revoked"),
    [(ISSUED_AT - 1, False), (ISSUED_AT, True), (ISSUED_AT + 1, True)],
)
async def test_the_cutoff_of_the_account_is_read_as_whole_seconds(cutoff, revoked):
    user_id = uuid.uuid4()
    store, _ = store_with({revoked_sessions_key(user_id): str(cutoff).encode()})

    assert await store.is_revoked("the-jti", user_id, ISSUED_AT) is revoked


async def test_the_cutoff_of_another_account_does_not_revoke_the_token():
    store, _ = store_with({revoked_sessions_key(uuid.uuid4()): str(ISSUED_AT + 60).encode()})

    assert not await store.is_revoked("the-jti", uuid.uuid4(), ISSUED_AT)
