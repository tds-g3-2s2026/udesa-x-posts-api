"""Moves the outbox to RabbitMQ.

The rows are written by the requests, in the same transaction as the change they
describe (see `OutboxRepository`). This publisher runs next to the API as an
asyncio task and does the other half: publish each row to the `udesa-x.events`
exchange and delete it once the broker confirms it.

Delivery is at least once. A crash between the broker's confirmation and the
delete leaves the row for the next pass, and the consumer drops the repeat by
the event id.

Nothing here logs a payload: the id and the type are enough to follow an event,
and a log is not the place for what the events say about the accounts.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable

import asyncpg
from aio_pika import DeliveryMode, ExchangeType, Message, RobustConnection
from aio_pika.abc import AbstractExchange, AbstractRobustConnection
from aio_pika.connection import make_url as make_amqp_url
from aio_pika.exceptions import DeliveryError
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from posts_api.infrastructure.database.models import OutboxModel
from posts_api.infrastructure.rabbitmq.event_consumer import EXCHANGE

logger = logging.getLogger(__name__)

# The channel the trigger on `outbox` notifies on.
NOTIFY_CHANNEL = "outbox"

BATCH_SIZE = 100
CONNECT_TIMEOUT_SECONDS = 10
PUBLISH_TIMEOUT_SECONDS = 10


class OutboxPublisher:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        database_url: str,
        rabbitmq_url: str,
        poll_seconds: float,
    ) -> None:
        self.session_factory = session_factory
        self.rabbitmq_url = rabbitmq_url
        self.poll_seconds = poll_seconds
        self.listen_args = listen_connection_args(database_url)
        self.connection: AbstractRobustConnection | None = None
        self.exchange: AbstractExchange | None = None

    async def run(self) -> None:
        """Publish until cancelled. A broker or a database that is down is not fatal.

        A pass wakes up on a NOTIFY from the database, and also every
        `poll_seconds`: the notification is a hint that makes delivery fast, and
        the polling is what keeps it correct when the listening connection is
        lost without anybody noticing.
        """
        wake = asyncio.Event()
        listener = asyncio.create_task(self.listen(wake))
        try:
            while True:
                # Cleared before the pass, not after: a row committed while the
                # pass runs has to start another one.
                wake.clear()
                try:
                    await self.drain()
                except Exception as error:
                    # The type and nothing else: the message of a broker error
                    # may carry the message that was being published.
                    logger.warning("Outbox pass failed, retrying: %s", type(error).__name__)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(wake.wait(), self.poll_seconds)
        finally:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener
            await self.close()

    async def listen(self, wake: asyncio.Event) -> None:
        """Wake the publisher on every insert, on a connection of its own.

        Not the SQLAlchemy pool: a listener holds its connection for as long as
        it lives, and a pooled one would be taken out of circulation for good.
        """
        while True:
            try:
                connection = await asyncpg.connect(**self.listen_args)
                lost = asyncio.Event()
                connection.add_termination_listener(lambda _connection, lost=lost: lost.set())
                try:
                    await connection.add_listener(NOTIFY_CHANNEL, make_waker(wake))
                    # Whatever was written while there was no listener.
                    wake.set()
                    await lost.wait()
                finally:
                    await connection.close(timeout=5)
            except Exception as error:
                logger.warning("Outbox listener lost, retrying: %s", type(error).__name__)
            await asyncio.sleep(self.poll_seconds)

    async def drain(self) -> None:
        """Publish batches until the table is empty or a batch is interrupted."""
        await self.connect()
        while True:
            published, interrupted = await self.publish_batch()
            if interrupted or published < BATCH_SIZE:
                return

    async def connect(self) -> None:
        if self.connection is not None and not self.connection.is_closed:
            return
        # Robust: once connected, the library reconnects and restores the channel
        # by itself. Only this first connection can fail, and then the next
        # pass tries again. Built by hand and not with `connect_robust`, for the
        # same reason as in `EventConsumer`: that one never hands back a
        # connection whose first attempt failed, so nobody could close it.
        connection = RobustConnection(make_amqp_url(self.rabbitmq_url))
        try:
            async with asyncio.timeout(CONNECT_TIMEOUT_SECONDS):
                await connection.connect(timeout=CONNECT_TIMEOUT_SECONDS)
            # Confirms so that a row is deleted only once the broker has it, and
            # returns raising so that a message nobody is bound to is an error
            # instead of a silent drop.
            channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
            self.exchange = await channel.declare_exchange(
                EXCHANGE, ExchangeType.TOPIC, durable=True
            )
        except BaseException:
            await connection.close()
            raise
        self.connection = connection

    async def publish_batch(self) -> tuple[int, bool]:
        """One pass: lock up to a batch, publish in order, delete what was confirmed.

        A message the broker hands back (no queue bound to its type) or refuses
        stays in the outbox and the pass goes on: one event nobody consumes yet
        must not hold back the others. Any other failure means the broker is not
        there, so the pass stops, and the deletes made before it are still
        committed: those messages are at the broker, and keeping their rows
        would only publish them twice. SKIP LOCKED lets two instances of the
        service share the table without publishing the same row at once.

        Returns how many rows were published and whether the pass was cut short.
        """
        published = 0
        interrupted = False
        async with self.session_factory() as session, session.begin():
            rows = await session.scalars(
                select(OutboxModel)
                .order_by(OutboxModel.created_at)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
            for row in rows:
                try:
                    await self.publish(row)
                except DeliveryError:
                    logger.warning(
                        "Event %s (%s) was returned or refused by the broker, left in the outbox",
                        row.id,
                        row.type,
                    )
                    continue
                except Exception as error:
                    logger.warning(
                        "Event %s (%s) was not published, left in the outbox: %s",
                        row.id,
                        row.type,
                        type(error).__name__,
                    )
                    interrupted = True
                    break
                await session.execute(delete(OutboxModel).where(OutboxModel.id == row.id))
                published += 1
                logger.info("Event %s (%s) published", row.id, row.type)
        return published, interrupted

    async def publish(self, row: OutboxModel) -> None:
        message = Message(
            json.dumps(row.payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=str(row.id),
            type=row.type,
        )
        # The routing key is the whole type, and mandatory makes the broker
        # hand the message back when no queue is bound to it. The timeout covers
        # a broker that went away mid-publish, where the library would wait for
        # the reconnection.
        async with asyncio.timeout(PUBLISH_TIMEOUT_SECONDS):
            await self.exchange.publish(message, routing_key=row.type, mandatory=True)

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()
            self.connection = None
            self.exchange = None


def make_waker(wake: asyncio.Event) -> Callable[..., None]:
    def on_notify(*_args) -> None:
        wake.set()

    return on_notify


def listen_connection_args(database_url: str) -> dict:
    """Connection arguments for asyncpg, taken from the SQLAlchemy URL.

    asyncpg does not read `ssl=` from a DSN (that is SQLAlchemy's spelling), so
    the URL is split here instead of being handed over as it is.
    """
    url = make_url(database_url)
    return {
        "host": url.host,
        "port": url.port,
        "user": url.username,
        "password": url.password,
        "database": url.database,
        "ssl": url.query.get("ssl"),
    }
