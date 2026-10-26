"""The publisher against a real RabbitMQ and a real PostgreSQL.

Each test binds its own exclusive queue, which disappears with the connection,
so nothing is left on the broker. The events that must find no queue use a type
nobody binds, so the result does not depend on what else runs on the broker.
"""

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import aio_pika
import pytest
from aio_pika import DeliveryMode, ExchangeType
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine

from posts_api.app import events
from posts_api.infrastructure.database.models import OutboxModel
from posts_api.infrastructure.database.session import build_session_factory
from posts_api.infrastructure.rabbitmq import outbox_publisher
from posts_api.infrastructure.rabbitmq.outbox_publisher import EXCHANGE, OutboxPublisher
from tests.conftest import BROKER_URL, requires_broker
from tests.events import FOLLOW_CREATED

pytestmark = requires_broker

UNREACHABLE = "amqp://posts:posts@127.0.0.1:1"


@pytest.fixture
async def engine():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE outbox"))
    yield engine
    # Rows left behind would be published by the next lifespan of the app.
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE outbox"))
    await engine.dispose()


@pytest.fixture
async def queue():
    """A queue bound to the events these tests publish, gone when the test ends."""
    connection = await aio_pika.connect_robust(BROKER_URL)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(EXCHANGE, ExchangeType.TOPIC, durable=True)
        queue = await channel.declare_queue(exclusive=True, auto_delete=True)
        await queue.bind(exchange, events.FOLLOW_CREATED)
        yield queue


def make_publisher(engine, *, poll_seconds: float = 60, rabbitmq_url: str | None = None):
    return OutboxPublisher(
        session_factory=build_session_factory(engine),
        database_url=os.environ["DATABASE_URL"],
        rabbitmq_url=rabbitmq_url or BROKER_URL,
        poll_seconds=poll_seconds,
    )


def follow_event() -> events.Event:
    return events.follow_created(
        uuid.uuid4(), uuid.uuid4(), follower_handle="@alumno_01", now=datetime.now(UTC)
    )


async def insert(engine, envelope: dict, *, created_at: datetime | None = None) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO outbox (id, type, payload, created_at) "
                "VALUES (:id, :type, CAST(:payload AS jsonb), COALESCE(:created_at, now()))"
            ),
            {
                "id": uuid.UUID(envelope["id"]),
                "type": envelope["type"],
                "payload": json.dumps(envelope),
                "created_at": created_at,
            },
        )


async def pending(engine) -> list[str]:
    async with engine.connect() as connection:
        rows = await connection.scalars(select(OutboxModel.id).order_by(OutboxModel.created_at))
        return [str(row) for row in rows]


def unbound_event() -> dict:
    # A type that no queue is bound to, so the broker returns the message.
    return {
        **follow_event().envelope,
        "type": f"test.unbound.{uuid.uuid4().hex}.v1",
    }


async def next_message(queue, timeout: float = 10):
    async with asyncio.timeout(timeout):
        while (message := await queue.get(fail=False)) is None:
            await asyncio.sleep(0.05)
    return message


async def test_e4_h1_ca1_rows_deleted_once_published(engine, queue):
    event = follow_event()
    await insert(engine, event.envelope)
    publisher = make_publisher(engine)

    try:
        await publisher.drain()
    finally:
        await publisher.close()

    message = await next_message(queue)
    await message.ack()
    assert json.loads(message.body) == event.envelope
    FOLLOW_CREATED.validate(json.loads(message.body))
    assert message.routing_key == event.type
    assert message.exchange == EXCHANGE
    assert message.content_type == "application/json"
    assert message.delivery_mode == DeliveryMode.PERSISTENT
    assert message.message_id == str(event.id)
    assert message.type == event.type
    assert await pending(engine) == []


async def test_without_a_bound_queue_the_row_stays(engine):
    envelope = unbound_event()
    await insert(engine, envelope)
    publisher = make_publisher(engine)

    try:
        await publisher.drain()
    finally:
        await publisher.close()

    # mandatory: the broker handed the message back, and a message that reached
    # nobody is not a delivered one.
    assert await pending(engine) == [envelope["id"]]


async def test_a_returned_event_stays_without_holding_back_the_ones_behind_it(engine, queue):
    now = datetime.now(UTC)
    first = follow_event().envelope
    stuck = unbound_event()
    last = follow_event().envelope
    for index, envelope in enumerate((first, stuck, last)):
        await insert(engine, envelope, created_at=now + timedelta(seconds=index))
    publisher = make_publisher(engine)

    try:
        await publisher.drain()
    finally:
        await publisher.close()

    # The one nobody is bound to waits in the outbox; the ones around it went out.
    assert await pending(engine) == [stuck["id"]]
    delivered = []
    for _ in range(2):
        message = await next_message(queue)
        await message.ack()
        delivered.append(message.message_id)
    assert delivered == [first["id"], last["id"]]


async def test_a_broker_lost_mid_pass_keeps_what_was_confirmed_and_leaves_the_rest(engine, queue):
    now = datetime.now(UTC)
    first, second, third = (follow_event().envelope for _ in range(3))
    for index, envelope in enumerate((first, second, third)):
        await insert(engine, envelope, created_at=now + timedelta(seconds=index))
    publisher = make_publisher(engine)
    await publisher.connect()
    publish = publisher.publish
    attempted = []

    async def lose_the_broker_before_the_second(row):
        attempted.append(str(row.id))
        if str(row.id) == second["id"]:
            await publisher.connection.close()
        await publish(row)

    publisher.publish = lose_the_broker_before_the_second
    try:
        published, interrupted = await publisher.publish_batch()
    finally:
        await publisher.close()

    # Not a returned message: the pass stops there instead of trying the third,
    # and the delete of the first, already at the broker, is still committed.
    assert attempted == [first["id"], second["id"]]
    assert (published, interrupted) == (1, True)
    assert await pending(engine) == [second["id"], third["id"]]
    message = await next_message(queue)
    await message.ack()
    assert message.message_id == first["id"]


@pytest.fixture
def opened(monkeypatch) -> list:
    """Every connection the publisher creates, to check none is left open."""
    created = []

    class RecordingConnection(outbox_publisher.RobustConnection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr(outbox_publisher, "RobustConnection", RecordingConnection)
    return created


async def test_a_refused_exchange_declaration_closes_the_connection(engine, opened, monkeypatch):
    # An exchange that already exists with another type: the broker closes the
    # channel instead of declaring it.
    name = f"test.conflict.{uuid.uuid4().hex}"
    admin = await aio_pika.connect_robust(BROKER_URL)
    async with admin:
        channel = await admin.channel()
        conflicting = await channel.declare_exchange(name, ExchangeType.FANOUT, auto_delete=False)
        monkeypatch.setattr(outbox_publisher, "EXCHANGE", name)
        publisher = make_publisher(engine)
        try:
            with pytest.raises(aio_pika.exceptions.ChannelPreconditionFailed):
                await publisher.connect()
        finally:
            await conflicting.delete()

    # Nothing half open is kept or leaked: the next pass starts from scratch.
    assert publisher.connection is None
    assert [connection.is_closed for connection in opened] == [True]


async def test_a_first_connection_that_never_came_up_is_closed(engine, opened):
    publisher = make_publisher(engine, rabbitmq_url=UNREACHABLE)

    with pytest.raises(aio_pika.exceptions.AMQPConnectionError):
        await publisher.connect()

    # Left open, its reconnection machinery would outlive the attempt with
    # nobody holding it, one more on every pass while the broker is down.
    assert publisher.connection is None
    assert [connection.is_closed for connection in opened] == [True]


async def test_a_notification_wakes_the_publisher_before_the_poll_does(engine, queue):
    publisher = make_publisher(engine, poll_seconds=60)
    task = asyncio.create_task(publisher.run())
    try:
        # Let the first, empty pass finish and the listener attach.
        await asyncio.sleep(1)
        event = follow_event()
        await insert(engine, event.envelope)

        message = await next_message(queue, timeout=5)
        await message.ack()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert message.message_id == str(event.id)
    assert await pending(engine) == []


async def test_polling_publishes_even_when_the_listener_is_lost(engine, queue):
    publisher = make_publisher(engine, poll_seconds=0.3)
    # A listener that can never connect: only the polling is left to find rows.
    publisher.listen_args = {**publisher.listen_args, "port": 1}
    event = follow_event()
    await insert(engine, event.envelope)
    task = asyncio.create_task(publisher.run())
    try:
        message = await next_message(queue, timeout=5)
        await message.ack()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert message.message_id == str(event.id)


async def test_the_publisher_survives_an_unreachable_broker_and_keeps_the_rows(engine):
    event = follow_event()
    await insert(engine, event.envelope)
    publisher = make_publisher(engine, poll_seconds=0.1, rabbitmq_url=UNREACHABLE)
    task = asyncio.create_task(publisher.run())

    await asyncio.sleep(0.6)

    # Still running after several failed passes, and nothing was lost.
    assert not task.done()
    assert await pending(engine) == [str(event.id)]
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
