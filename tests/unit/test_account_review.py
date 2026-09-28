import uuid

import httpx
import pytest

from posts_api.infrastructure.users_api import account_review
from posts_api.infrastructure.users_api.account_review import (
    HttpAccountReview,
    build_users_api_client,
)


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(account_review, "BACKOFF_SECONDS", 0)
    # The session fixture that runs the migrations loads alembic.ini, whose
    # fileConfig disables every logger that already existed, this one included.
    monkeypatch.setattr(account_review.logger, "disabled", False)


def users_api_answering(*statuses: int) -> tuple[HttpAccountReview, list[httpx.Request]]:
    """A client whose users-api answers these statuses in order."""
    received: list[httpx.Request] = []
    pending = list(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(pending.pop(0))

    client = build_users_api_client(
        "http://users-api", "the-secret", transport=httpx.MockTransport(handler)
    )
    return HttpAccountReview(client), received


async def test_asks_for_the_review_on_the_internal_route_with_the_secret():
    review, received = users_api_answering(204)
    user_id = uuid.uuid4()

    await review.put_under_review(user_id)

    assert [str(one.url) for one in received] == [
        f"http://users-api/internal/users/{user_id}/review"
    ]
    assert received[0].method == "POST"
    assert received[0].headers["X-Internal-Token"] == "the-secret"


async def test_retries_once_when_users_api_fails():
    review, received = users_api_answering(503, 204)

    await review.put_under_review(uuid.uuid4())

    assert len(received) == 2


async def test_gives_up_without_raising_after_the_retry(caplog):
    review, received = users_api_answering(503, 503)
    user_id = uuid.uuid4()

    await review.put_under_review(user_id)

    assert len(received) == 2
    assert str(user_id) in caplog.text
