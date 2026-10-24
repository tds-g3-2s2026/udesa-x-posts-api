"""Takes the events this service consumes off RabbitMQ.

The topology is the one `notifications-api` declares for its own queue: the
exchange is shared and declared with the same arguments by everybody, and each
service owns its queue and the dead letter side of it.

Delivery is at least once, so the handler has to tolerate a repeat. A message it
cannot make sense of goes to the dead letter queue, and one it could not handle
because something it depends on failed goes back to the queue.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from aio_pika import ExchangeType, RobustConnection
from aio_pika.abc import AbstractIncomingMessage, AbstractQueue, AbstractRobustConnection
from aio_pika.connection import make_url

from posts_api.app.events import USER_DELETED, Outcome

logger = logging.getLogger(__name__)

# Declared with the same arguments by every service that touches it, so the
# declaration is idempotent and nobody depends on who starts first.
EXCHANGE = "udesa-x.events"
DEAD_LETTER_EXCHANGE = "udesa-x.events.dlx"
QUEUE = "posts-api"
DEAD_LETTER_QUEUE = "posts-api.dlq"
BINDINGS = (USER_DELETED,)

# Messages held unacked at once.
PREFETCH = 10
CONNECT_TIMEOUT_SECONDS = 10
# How long a stopping service waits for the messages it is in the middle of.
DRAIN_TIMEOUT_SECONDS = 10


class EventConsumer:
    def __init__(
        self,
        rabbitmq_url: str,
        handle: Callable[[bytes], Awaitable[Outcome]],
        *,
        retry_seconds: float = 5,
    ) -> None:
        self._rabbitmq_url = rabbitmq_url
        self._handle = handle
        self._retry_seconds = retry_seconds
        self._connection: AbstractRobustConnection | None = None
        self._subscription: tuple[AbstractQueue, str] | None = None
        self._in_flight: set[asyncio.Task] = set()
        # Set once the queue exists and the consumer is attached to it.
        self.ready = asyncio.Event()

    async def run(self) -> None:
        """Consume until cancelled. A broker that is down is not fatal for the service.

        Only the first connection can fail: once it exists the library
        reconnects and restores the exchanges, the queues and the consumer by
        itself. Until it exists the service retries, so starting before the
        broker does not need anybody to restart it.
        """
        try:
            while True:
                try:
                    # Does not return: it waits for as long as the consumer lives.
                    await self._consume()
                except Exception as error:
                    logger.warning(
                        "Events consumer could not start, retrying: %s", type(error).__name__
                    )
                    # A connection that got as far as opening is not left behind.
                    await self.close()
                await asyncio.sleep(self._retry_seconds)
        finally:
            await self.close()

    async def _consume(self) -> None:
        # Built by hand and not with `connect_robust`: that one only hands the
        # connection back once it is up, so a failed or cancelled attempt leaves
        # its reconnection task running with nobody able to close it. Held in
        # `self._connection` from the start, `close` always can.
        self._connection = RobustConnection(make_url(self._rabbitmq_url))
        async with asyncio.timeout(CONNECT_TIMEOUT_SECONDS):
            await self._connection.connect(timeout=CONNECT_TIMEOUT_SECONDS)
        channel = await self._connection.channel()
        await channel.set_qos(prefetch_count=PREFETCH)

        exchange = await channel.declare_exchange(EXCHANGE, ExchangeType.TOPIC, durable=True)
        dead_letters = await channel.declare_exchange(
            DEAD_LETTER_EXCHANGE, ExchangeType.FANOUT, durable=True
        )
        dead_letter_queue = await channel.declare_queue(
            DEAD_LETTER_QUEUE, durable=True, arguments={"x-queue-type": "quorum"}
        )
        await dead_letter_queue.bind(dead_letters, routing_key="")
        queue = await channel.declare_queue(
            QUEUE,
            durable=True,
            arguments={"x-queue-type": "quorum", "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE},
        )
        for routing_key in BINDINGS:
            await queue.bind(exchange, routing_key=routing_key)

        self._subscription = (queue, await queue.consume(self._on_message))
        self.ready.set()
        logger.info("Consuming events from %s", QUEUE)
        # The consumer lives as long as this task does.
        await asyncio.Event().wait()

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        task = asyncio.current_task()
        self._in_flight.add(task)
        try:
            await self._settle(message)
        finally:
            self._in_flight.discard(task)

    async def _settle(self, message: AbstractIncomingMessage) -> None:
        try:
            outcome = await self._handle(message.body)
        except Exception as error:
            # The database or another dependency failed: give the message back.
            # The type and nothing else, the message of an error may carry data.
            logger.error(
                "Event %s failed, requeueing: %s", message.message_id, type(error).__name__
            )
            await message.nack(requeue=True)
            return
        if outcome == "ack":
            await message.ack()
        else:
            logger.warning("Event %s rejected, sent to the dead letter queue", message.message_id)
            await message.reject(requeue=False)

    async def close(self) -> None:
        """Stop taking messages, wait for the ones in progress, and close."""
        if self._connection is None:
            return
        connection, self._connection = self._connection, None
        if self._subscription is not None:
            queue, tag = self._subscription
            self._subscription = None
            # Nothing new arrives while the ones in progress finish. If the
            # channel is already gone there is nothing to cancel.
            with contextlib.suppress(Exception):
                await queue.cancel(tag)
        if self._in_flight:
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(DRAIN_TIMEOUT_SECONDS):
                    await asyncio.gather(*self._in_flight, return_exceptions=True)
        await connection.close()
