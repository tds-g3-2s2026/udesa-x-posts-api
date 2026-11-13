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


async def _fetch(statement: str) -> list[tuple]:
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as connection:
        rows = (await connection.execute(text(statement))).all()
    await engine.dispose()
    return [tuple(row) for row in rows]


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


def test_soft_delete_migration_preserves_existing_posts():
    config = Config("alembic.ini")
    command.downgrade(config, "0006_retweets")
    asyncio.run(
        _execute("""
        INSERT INTO user_profiles (id, visibility, followers_count, following_count)
        VALUES ('77777777-7777-4777-8777-777777777777', 'public', 0, 0);
    """)
    )
    asyncio.run(
        _execute("""
        INSERT INTO posts (author_id, content, likes_count, retweets_count, replies_count)
        VALUES ('77777777-7777-4777-8777-777777777777', 'preserved', 0, 0, 0)
    """)
    )
    command.upgrade(config, "head")

    async def check():
        engine = create_async_engine(get_settings().database_url)
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT content, deleted_at FROM posts "
                        "WHERE author_id = '77777777-7777-4777-8777-777777777777'"
                    )
                )
            ).one()
            assert row.content == "preserved" and row.deleted_at is None
        await engine.dispose()

    asyncio.run(check())
    asyncio.run(
        _execute("DELETE FROM posts WHERE author_id = '77777777-7777-4777-8777-777777777777'")
    )
    asyncio.run(
        _execute("DELETE FROM user_profiles WHERE id = '77777777-7777-4777-8777-777777777777'")
    )


def test_lists_from_0017_keep_the_members_their_owner_follows():
    """0017 reached production before memberships hung from the follow. Each one
    gets the list's owner, and one whose follow was already gone is dropped."""
    owner = "88888888-8888-4888-8888-888888888881"
    followed = "88888888-8888-4888-8888-888888888882"
    unfollowed = "88888888-8888-4888-8888-888888888883"
    list_id = "88888888-8888-4888-8888-888888888884"
    config = Config("alembic.ini")
    command.downgrade(config, "0017_listas")
    for profile in (owner, followed, unfollowed):
        asyncio.run(
            _execute(
                "INSERT INTO user_profiles (id, visibility, followers_count, following_count) "
                f"VALUES ('{profile}', 'public', 0, 0)"
            )
        )
    asyncio.run(
        _execute(f"INSERT INTO follows (follower_id, followee_id) VALUES ('{owner}', '{followed}')")
    )
    asyncio.run(
        _execute(
            f"INSERT INTO lists (id, owner_id, name) VALUES ('{list_id}', '{owner}', 'Taller')"
        )
    )
    for member in (followed, unfollowed):
        asyncio.run(
            _execute(
                f"INSERT INTO list_members (list_id, member_id) VALUES ('{list_id}', '{member}')"
            )
        )

    command.upgrade(config, "head")

    rows = asyncio.run(_fetch("SELECT owner_id::text, member_id::text FROM list_members"))
    assert rows == [(owner, followed)]
    asyncio.run(_execute(f"DELETE FROM follows WHERE follower_id = '{owner}'"))
    asyncio.run(
        _execute(f"DELETE FROM user_profiles WHERE id IN ('{owner}', '{followed}', '{unfollowed}')")
    )
