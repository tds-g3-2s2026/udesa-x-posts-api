import pytest

from posts_api.infrastructure.health import (
    DependencyStatus,
    build_report,
    check_postgres,
    check_redis,
)


class FakeConnection:
    def __init__(self, *, fails: bool) -> None:
        self.fails = fails

    async def execute(self, statement):
        if self.fails:
            raise ConnectionError("could not connect")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeEngine:
    def __init__(self, *, fails: bool = False) -> None:
        self.fails = fails

    def connect(self):
        return FakeConnection(fails=self.fails)


class FakeRedis:
    def __init__(self, *, fails: bool = False) -> None:
        self.fails = fails

    async def ping(self):
        if self.fails:
            raise ConnectionError("could not connect")
        return True


async def test_healthy_postgres_reports_ok():
    status = await check_postgres(FakeEngine())
    assert status.is_healthy


async def test_unreachable_postgres_reports_the_error():
    status = await check_postgres(FakeEngine(fails=True))
    assert not status.is_healthy
    assert "could not connect" in status.detail


async def test_healthy_redis_reports_ok():
    status = await check_redis(FakeRedis())
    assert status.is_healthy


async def test_unreachable_redis_reports_the_error():
    status = await check_redis(FakeRedis(fails=True))
    assert not status.is_healthy
    assert "could not connect" in status.detail


def test_all_dependencies_healthy_returns_200():
    body, status_code = build_report(
        [DependencyStatus("postgres", True), DependencyStatus("redis", True)]
    )
    assert status_code == 200
    assert body["status"] == "ok"
    assert body["dependencies"] == {"postgres": "ok", "redis": "ok"}


@pytest.mark.parametrize("failing", ["postgres", "redis"])
def test_a_single_failing_dependency_returns_503(failing):
    statuses = [
        DependencyStatus(name, name != failing, None if name != failing else "no connection")
        for name in ("postgres", "redis")
    ]
    body, status_code = build_report(statuses)
    assert status_code == 503
    assert body["status"] == "degraded"
    assert body["dependencies"][failing] == "no connection"
