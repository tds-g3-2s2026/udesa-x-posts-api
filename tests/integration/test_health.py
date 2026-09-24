import tomllib
from pathlib import Path

import httpx
import pytest

from posts_api.main import app
from tests.conftest import requires_services

pytestmark = requires_services


@pytest.fixture
async def api():
    """Start the app the same way uvicorn does, and talk to it over ASGI.

    Running the lifespan opens the connections; the session fixture applies
    the real migrations before the app starts.
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


async def test_healthcheck_reports_the_version_declared_in_pyproject(api):
    pyproject = Path(__file__).parents[2] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text())["project"]["version"]

    response = await api.get("/healthcheck")

    assert response.json()["version"] == declared
