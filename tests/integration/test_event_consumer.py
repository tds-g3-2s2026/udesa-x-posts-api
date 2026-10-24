"""The consumer against a real RabbitMQ, from the message to the closed account."""

import asyncio
import contextlib
import json
import uuid

import aio_pika
import pytest
from aio_pika import DeliveryMode, ExchangeType, Message

from posts_api.api.event_handlers import build_event_handler
from posts_api.infrastructure.database.models import UserProfileModel
from posts_api.infrastructure.rabbitmq.event_consumer import (
    DEAD_LETTER_QUEUE,
    EXCHANGE,
    QUEUE,
    EventConsumer,
)
from posts_api.main import app
from tests.conftest import BROKER_URL, requires_broker
from tests.events import body_of, user_deleted
from tests.integration.conftest import given_a_profile

pytestmark = requires_broker


@pytest.fixture
async def broker():
    connection = await aio_pika.connect_robust(BROKER_URL)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(EXCHANGE, ExchangeType.TOPIC, durable=True)
        yield channel, exchange


@pytest.fixture
async def consuming(api, broker):
    """The consumer running, with a handler that can be told to fail a number of times."""
    channel, _ = broker
    # `gate`, when set, holds the handler until the test opens it.
    state = {"failures": 0, "calls": 0, "gate": None}
    real = build_event_handler(app.state.session_factory)

    async def handle(body: bytes):
        state["calls"] += 1
        if state["gate"] is not None:
            await state["gate"].wait()
        if state["failures"] > 0:
            state["failures"] -= 1
            raise RuntimeError("the database is down")
        return await real(body)

    consumer = EventConsumer(BROKER_URL, handle, retry_seconds=0.2)
    task = asyncio.create_task(consumer.run())
    await asyncio.wait_for(consumer.ready.wait(), 15)
    # Whatever an earlier run left behind is not part of this test.
    await (await channel.declare_queue(QUEUE, passive=True)).purge()
    await (await channel.declare_queue(DEAD_LETTER_QUEUE, passive=True)).purge()
    yield state
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def publish(exchange, body: bytes, *, message_id: str | None = None, key="user.deleted.v1"):
    await exchange.publish(
        Message(
            body,
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=message_id,
        ),
        routing_key=key,
    )


async def eventually(check, *, seconds: float = 10):
    """Poll until `check()` is truthy: the consumer works on its own schedule."""
    async with asyncio.timeout(seconds):
        while not (result := await check()):
            await asyncio.sleep(0.05)
    return result


async def is_closed(user_id: uuid.UUID) -> bool:
    async with app.state.session_factory() as session:
        row = await session.get(UserProfileModel, user_id)
    return row is not None and row.deleted_at is not None


async def test_an_event_from_the_exchange_closes_the_account(consuming, broker):
    _, exchange = broker
    leaving = uuid.uuid4()
    await given_a_profile(leaving)
    event = user_deleted(leaving)

    await publish(exchange, body_of(event), message_id=event["id"])

    await eventually(lambda: is_closed(leaving))


async def test_the_same_event_delivered_twice_is_harmless(consuming, broker):
    _, exchange = broker
    leaving = uuid.uuid4()
    await given_a_profile(leaving)
    event = user_deleted(leaving)

    await publish(exchange, body_of(event), message_id=event["id"])
    await publish(exchange, body_of(event), message_id=event["id"])

    async def both_were_handled():
        return consuming["calls"] == 2 and await is_closed(leaving)

    await eventually(both_were_handled)


async def test_a_message_that_cannot_be_read_goes_to_the_dead_letter_queue(consuming, broker):
    channel, exchange = broker
    dead_letters = await channel.declare_queue(DEAD_LETTER_QUEUE, passive=True)

    await publish(exchange, b"this is not an event")

    async def arrived():
        return await dead_letters.get(fail=False)

    message = await eventually(arrived)
    assert message.body == b"this is not an event"
    await message.ack()
    queue = await channel.declare_queue(QUEUE, passive=True)
    assert queue.declaration_result.message_count == 0


async def test_a_failure_of_the_database_puts_the_message_back_until_it_works(consuming, broker):
    _, exchange = broker
    leaving = uuid.uuid4()
    await given_a_profile(leaving)
    consuming["failures"] = 2

    await publish(exchange, body_of(user_deleted(leaving)))

    await eventually(lambda: is_closed(leaving))
    assert consuming["calls"] == 3


async def test_only_the_events_it_is_bound_to_reach_the_queue(consuming, broker):
    channel, exchange = broker

    await publish(
        exchange, json.dumps({"type": "user.registered.v1"}).encode(), key="user.registered.v1"
    )
    await asyncio.sleep(0.5)

    assert consuming["calls"] == 0
    queue = await channel.declare_queue(QUEUE, passive=True)
    assert queue.declaration_result.message_count == 0


async def test_stopping_waits_for_the_message_in_progress(api, broker):
    _, exchange = broker
    leaving = uuid.uuid4()
    await given_a_profile(leaving)
    gate = asyncio.Event()
    handled = asyncio.Event()
    real = build_event_handler(app.state.session_factory)

    async def handle(body: bytes):
        handled.set()
        await gate.wait()
        return await real(body)

    consumer = EventConsumer(BROKER_URL, handle, retry_seconds=0.2)
    task = asyncio.create_task(consumer.run())
    await asyncio.wait_for(consumer.ready.wait(), 15)
    await publish(exchange, body_of(user_deleted(leaving)))
    await asyncio.wait_for(handled.wait(), 10)

    task.cancel()
    await asyncio.sleep(0.2)
    assert not task.done()
    gate.set()
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(task, 10)

    assert await is_closed(leaving)
