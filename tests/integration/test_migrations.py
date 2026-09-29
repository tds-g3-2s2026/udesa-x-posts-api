"""The migration chain against the database production really has.

Synchronous on purpose: Alembic runs its own event loop, the same reason the
fixture that applies the migrations is synchronous.
"""

import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from posts_api.config.settings import get_settings
from tests.conftest import requires_services

pytestmark = requires_services


async def _execute(statement: str) -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as connection:
        await connection.execute(text(statement))
    await engine.dispose()


async def _tables() -> set[str]:
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as connection:
        names = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
    await engine.dispose()
    return set(names)


def test_a_database_that_applied_0001_without_posts_reaches_head():
    """Production applied 0001 before `posts` was added to it. This rebuilds that
    database and checks the chain still gets to the head with every table."""
    config = Config("alembic.ini")
    command.downgrade(config, "0002_bloqueos")
    asyncio.run(_execute("DROP TABLE posts"))

    command.upgrade(config, "head")

    assert {"posts", "reports"} <= asyncio.run(_tables())


def test_the_posts_revision_does_nothing_where_0001_already_made_the_table():
    config = Config("alembic.ini")
    command.downgrade(config, "0002_bloqueos")

    command.upgrade(config, "head")

    assert {"posts", "reports"} <= asyncio.run(_tables())
