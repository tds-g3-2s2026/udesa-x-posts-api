"""What every integration test needs: the app running on an empty graph."""

import uuid

import httpx
import pytest
from sqlalchemy import delete

from posts_api.infrastructure.database.models import (
    BlockModel,
    FollowModel,
    FollowRequestModel,
    LikeModel,
    MuteModel,
    OutboxModel,
    PostMediaModel,
    PostModel,
    ReportModel,
    RetweetModel,
    UserProfileModel,
)
from posts_api.main import app
from tests.conftest import issue_token
from tests.fakes import FakeImageStorage


@pytest.fixture
async def api():
    """The application running, on an empty graph.

    The tables are emptied before each test instead of after: if one fails, its
    rows stay in the database to be looked at.
    """
    async with app.router.lifespan_context(app):
        async with app.state.session_factory() as session:
            # First: a report points at the profiles and at the posts.
            await session.execute(delete(ReportModel))
            await session.execute(delete(LikeModel))
            await session.execute(delete(RetweetModel))
            await session.execute(delete(BlockModel))
            await session.execute(delete(MuteModel))
            await session.execute(delete(FollowRequestModel))
            await session.execute(delete(FollowModel))
            # The images hang from the posts.
            await session.execute(delete(PostMediaModel))
            # Before the profiles: both tables carry a foreign key to it.
            await session.execute(delete(PostModel))
            await session.execute(delete(UserProfileModel))
            await session.execute(delete(OutboxModel))
            await session.commit()
        # The rate limit counters live outside PostgreSQL, so emptying the
        # tables is not enough to leave one test independent from the next.
        await app.state.redis.flushdb()
        # No bucket exists to test against: the images go to this one, which the
        # tests reach as `app.state.image_storage`.
        app.state.image_storage = FakeImageStorage()

        transport = httpx.ASGITransport(app=app)
        # The prefix travels in the base URL so each test keeps writing the path
        # it cares about, and the request that goes out is the real one.
        async with httpx.AsyncClient(transport=transport, base_url="http://test/api") as client:
            yield client


def handle_of(user_id: uuid.UUID) -> str:
    return f"@u{str(user_id)[:8]}"


def signed_in_as(
    user_id: uuid.UUID, *, profile_visibility: str | None = "public"
) -> dict[str, str]:
    """A token for that account, with its own handle.

    The handle is derived from the id because the column is unique: two accounts
    cannot share one, and a fixed value would blow up the moment a test signs in
    as more than one person.
    """
    token = issue_token(user_id, handle=handle_of(user_id), profile_visibility=profile_visibility)
    return {"Authorization": f"Bearer {token}"}


async def given_a_profile(user_id: uuid.UUID, *, visibility: str = "public") -> None:
    """Put an account on the graph, the way the copy from users-api will."""
    async with app.state.session_factory() as session:
        session.add(UserProfileModel(id=user_id, visibility=visibility, handle=handle_of(user_id)))
        await session.commit()
