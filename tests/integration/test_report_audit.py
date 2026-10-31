import asyncio
import uuid
from datetime import UTC, datetime

import aio_pika
import pytest
from aio_pika import ExchangeType

from posts_api.infrastructure.database.outbox_repository import SqlAlchemyOutboxRepository
from posts_api.infrastructure.rabbitmq.outbox_publisher import EXCHANGE, OutboxPublisher
from posts_api.infrastructure.users_api.administrator_directory import HttpAdministratorDirectory
from posts_api.main import app
from tests.conftest import BROKER_URL, requires_broker, requires_services
from tests.events import ADMIN_ACTION_RECORDED
from tests.integration.test_admin_reports import (
    ADMIN,
    audit_events,
    close,
    given_a_case,
    statuses_of,
    stored_reports,
)
from tests.integration.test_admin_reports import (
    users_api as users_api,
)

pytestmark = requires_services


@pytest.mark.parametrize("action,status", [("dismiss", "dismissed"), ("resolve", "resolved")])
async def test_e5_h6_ca1_effective_decision_queues_audit_with_current_email(
    api, users_api, action, status
):
    target = await given_a_case(reporters=3)
    before = datetime.now(UTC)
    assert (await close(api, action, target)).status_code == 204
    [event] = await audit_events()
    ADMIN_ACTION_RECORDED.validate(event)
    assert event["data"] == {
        "actor_id": str(ADMIN),
        "actor_email": "moderador@udesa.edu.ar",
        "action": "report." + status,
        "target_type": "user",
        "target_id": str(target),
        "details": {"reports_count": 3},
    }
    assert datetime.fromisoformat(event["time"]) >= before.replace(microsecond=0)
    assert await statuses_of(target) == {status}
    assert all(
        abs((when - datetime.fromisoformat(event["time"])).total_seconds()) < 0.001
        for _, _, when in await stored_reports(target)
    )
    users_api.identity_answer = {"id": str(ADMIN), "email": "changed@udesa.edu.ar"}
    calls = list(users_api.calls)
    assert (await close(api, action, target)).status_code == 204
    assert await audit_events() == [event]
    assert users_api.calls == calls


@pytest.mark.parametrize(
    "identity",
    [
        "down",
        401,
        404,
        503,
        {},
        {"id": str(ADMIN)},
        {"id": str(uuid.uuid4()), "email": "other@udesa.edu.ar"},
        {"id": str(ADMIN), "email": "invalid"},
        {"id": str(ADMIN), "email": 42},
        {"id": str(ADMIN), "email": "@udesa.edu.ar"},
        {"id": str(ADMIN), "email": "a@@udesa.edu.ar"},
        {"id": str(ADMIN), "email": ""},
        {"id": "not-a-uuid", "email": "admin@udesa.edu.ar"},
    ],
)
async def test_e5_h6_identity_failure_keeps_case_pending_without_event(api, users_api, identity):
    target = await given_a_case()
    before = await stored_reports(target)
    users_api.identity_answer = identity
    response = await close(api, "resolve", target)
    assert response.status_code == 503
    assert response.json()["type"].endswith("/users-api-unavailable")
    assert await stored_reports(target) == before
    assert await audit_events() == []
    assert users_api.calls == [("GET", f"/internal/administrators/{ADMIN}/identity", "secreto")] * 2


async def test_e5_h6_outbox_failure_rolls_back_decision_and_event(api, users_api, monkeypatch):
    target = await given_a_case()
    original = SqlAlchemyOutboxRepository.add

    async def fail(self, event):
        await original(self, event)
        await self.session.flush()
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(SqlAlchemyOutboxRepository, "add", fail)
    with pytest.raises(RuntimeError, match="outbox unavailable"):
        await close(api, "dismiss", target)
    assert await statuses_of(target) == {"pending"}
    assert await audit_events() == []


async def test_e5_h6_concurrent_decisions_queue_only_one_event(api, users_api, monkeypatch):
    target = await given_a_case()
    barrier = asyncio.Barrier(2)
    original = HttpAdministratorDirectory.email_of

    async def identify(self, actor_id):
        email = await original(self, actor_id)
        await asyncio.wait_for(barrier.wait(), 5)
        return email

    monkeypatch.setattr(HttpAdministratorDirectory, "email_of", identify)
    responses = await asyncio.wait_for(
        asyncio.gather(
            close(api, "dismiss", target),
            close(api, "resolve", target),
        ),
        10,
    )
    assert [response.status_code for response in responses] == [204, 204]
    [event] = await audit_events()
    status = (await statuses_of(target)).pop()
    assert event["data"]["action"] == "report." + status
    assert users_api.lifts_of(target) == 1


@requires_broker
async def test_e5_h6_shared_publisher_delivers_committed_audit(api, users_api):
    target = await given_a_case()
    assert (await close(api, "resolve", target)).status_code == 204
    [event] = await audit_events()
    connection = await aio_pika.connect_robust(BROKER_URL)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(EXCHANGE, ExchangeType.TOPIC, durable=True)
        queue = await channel.declare_queue(exclusive=True, auto_delete=True)
        await queue.bind(exchange, "admin.action_recorded.v1")
        publisher = OutboxPublisher(
            session_factory=app.state.session_factory,
            database_url=app.state.settings.database_url,
            rabbitmq_url=BROKER_URL,
            poll_seconds=60,
        )
        try:
            await publisher.drain()
            message = await queue.get(timeout=5)
            import json

            assert json.loads(message.body) == event
            await message.ack()
            assert await audit_events() == []
        finally:
            await publisher.close()
