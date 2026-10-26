"""What following someone leaves in the outbox.

The publisher is covered in `test_outbox_publisher.py`. Here the app points at a
broker nobody listens on (see `tests/conftest.py`), so the events stay in the
outbox for the tests to read.
"""

import uuid

import pytest
from sqlalchemy import func, select

from posts_api.infrastructure.database.models import FollowModel, OutboxModel
from posts_api.infrastructure.database.outbox_repository import SqlAlchemyOutboxRepository
from posts_api.main import app
from tests.conftest import requires_services
from tests.events import FOLLOW_CREATED
from tests.integration.conftest import given_a_profile, handle_of, signed_in_as
from tests.integration.test_follow_requests import a_request_from

pytestmark = requires_services


async def outbox_events() -> list[dict]:
    async with app.state.session_factory() as session:
        rows = await session.scalars(select(OutboxModel).order_by(OutboxModel.created_at))
        return [row.payload for row in rows]


async def count(model) -> int:
    async with app.state.session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def test_e4_h1_ca1_following_a_public_account_queues_follow_created(api):
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)

    response = await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))

    assert response.status_code == 204
    [event] = await outbox_events()
    FOLLOW_CREATED.validate(event)
    assert event["data"] == {
        "follower_id": str(follower),
        "follower_handle": handle_of(follower),
        "followee_id": str(followee),
    }


async def test_e4_h1_ca1_follow_writes_outbox_row_in_same_transaction(api, monkeypatch):
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)

    async def failing_add(self, event):
        # The follow and the row reach the database inside the transaction
        # before the failure, so only a rollback can take both back.
        self.session.add(OutboxModel(id=event.id, type=event.type, payload=event.envelope))
        await self.session.flush()
        raise RuntimeError("the outbox write failed")

    monkeypatch.setattr(SqlAlchemyOutboxRepository, "add", failing_add)

    with pytest.raises(RuntimeError):
        await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))

    assert await count(FollowModel) == 0
    assert await count(OutboxModel) == 0


async def test_e4_h1_ca1_accepted_request_writes_follow_created(api):
    requester, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")
    request_id = await a_request_from(api, requester, target)
    # Asking is not following yet: nobody gets told about a request.
    assert await outbox_events() == []

    response = await api.post(
        f"/follow-requests/{request_id}/approve", headers=signed_in_as(target)
    )

    assert response.status_code == 204
    [event] = await outbox_events()
    FOLLOW_CREATED.validate(event)
    assert event["data"] == {
        "follower_id": str(requester),
        "follower_handle": handle_of(requester),
        "followee_id": str(target),
    }


async def test_a_rejected_request_queues_nothing(api):
    requester, target = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(target, visibility="protected")
    request_id = await a_request_from(api, requester, target)

    await api.post(f"/follow-requests/{request_id}/reject", headers=signed_in_as(target))

    assert await outbox_events() == []


async def test_following_twice_queues_a_single_event(api):
    follower, followee = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(followee)

    await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))
    await api.post(f"/users/{followee}/follow", headers=signed_in_as(follower))

    assert len(await outbox_events()) == 1
