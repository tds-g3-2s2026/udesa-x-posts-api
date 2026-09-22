"""What every integration test needs: the app running on an empty graph."""

import uuid

import httpx
import pytest
from sqlalchemy import delete

from posts_api.infrastructure.database.models import (
    FollowModel,
    FollowRequestModel,
    PostModel,
    UserProfileModel,
)
from posts_api.main import app
from tests.conftest import issue_token


@pytest.fixture
async def api():
    """The application running, on an empty graph.

    The tables are emptied before each test instead of after: if one fails, its
    rows stay in the database to be looked at.
    """
    async with app.router.lifespan_context(app):
        async with app.state.session_factory() as session:
            await session.execute(delete(FollowRequestModel))
            await session.execute(delete(FollowModel))
            # Before the profiles: both tables carry a foreign key to it.
            await session.execute(delete(PostModel))
            await session.execute(delete(UserProfileModel))
            await session.commit()
        # The rate limit counters live outside PostgreSQL, so emptying the
        # tables is not enough to leave one test independent from the next.
        await app.state.redis.flushdb()

        transport = httpx.ASGITransport(app=app)
        # The prefix travels in the base URL so each test keeps writing the path
        # it cares about, and the request that goes out is the real one.
        async with httpx.AsyncClient(transport=transport, base_url="http://test/api") as client:
            yield client


def handle_of(user_id: uuid.UUID) -> str:
    return f"@u{str(user_id)[:8]}"


def signed_in_as(user_id: uuid.UUID) -> dict[str, str]:
    """A token for that account, with its own handle.

    The handle is derived from the id because the column is unique: two accounts
    cannot share one, and a fixed value would blow up the moment a test signs in
    as more than one person.
    """
    return {"Authorization": f"Bearer {issue_token(user_id, handle=handle_of(user_id))}"}


async def given_a_profile(user_id: uuid.UUID, *, visibility: str = "public") -> None:
    """Put an account on the graph, the way the copy from users-api will."""
    async with app.state.session_factory() as session:
        session.add(UserProfileModel(id=user_id, visibility=visibility, handle=handle_of(user_id)))
        await session.commit()
