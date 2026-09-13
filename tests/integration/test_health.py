import httpx
import pytest
from sqlalchemy import text

from posts_api.main import app
from tests.conftest import requires_services

pytestmark = requires_services


@pytest.fixture
async def api():
    """Start the app the same way uvicorn does, and talk to it over ASGI.

    Running the lifespan is the point: it is what opens the connections and
    creates the tables, so these tests cover the startup path that the unit
    tests cannot reach.
    """
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_healthcheck_reports_every_dependency_as_ok(api):
    response = await api.get("/healthcheck")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dependencies"] == {"postgres": "ok", "redis": "ok"}


async def test_startup_creates_the_graph_tables(api):
    expected = {"user_profiles", "follows", "follow_requests"}

    async with app.state.engine.connect() as connection:
        rows = await connection.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        tables = {row[0] for row in rows}

    assert expected <= tables
