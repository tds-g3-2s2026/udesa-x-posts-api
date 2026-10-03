import uuid
from datetime import UTC, datetime, timedelta

from posts_api.infrastructure.database.models import PostModel
from posts_api.main import app
from tests.conftest import issue_token, requires_services
from tests.integration.conftest import given_a_profile, signed_in_as

pytestmark = requires_services

SINCE = datetime(2026, 10, 3, 3, 0, tzinfo=UTC)


def as_administrator(role: str = "moderator") -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(role=role)}"}


async def given_posts_at(*moments: datetime) -> None:
    author = uuid.uuid4()
    await given_a_profile(author)
    async with app.state.session_factory() as session:
        session.add_all(
            PostModel(author_id=author, content="Hola", created_at=moment) for moment in moments
        )
        await session.commit()


async def test_counts_the_posts_published_from_the_given_moment_on(api):
    await given_posts_at(SINCE - timedelta(seconds=1), SINCE, SINCE + timedelta(hours=5))

    for role in ("moderator", "superadmin"):
        response = await api.get(
            "/admin/posts/metrics",
            params={"since": SINCE.isoformat()},
            headers=as_administrator(role),
        )

        assert response.status_code == 200
        assert response.json() == {"published": 2}


async def test_an_app_account_cannot_read_the_metrics(api):
    response = await api.get(
        "/admin/posts/metrics",
        params={"since": SINCE.isoformat()},
        headers=signed_in_as(uuid.uuid4()),
    )

    assert response.status_code == 403
    assert response.json()["type"].endswith("administrator-required")


async def test_a_moment_without_offset_is_refused(api):
    response = await api.get(
        "/admin/posts/metrics",
        params={"since": "2026-10-03T00:00:00"},
        headers=as_administrator(),
    )

    assert response.status_code == 422
