"""The followers and posts of one account, for its backoffice detail (E5-H4)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import update

from posts_api.infrastructure.database.models import PostModel, UserProfileModel
from posts_api.main import app
from tests.conftest import issue_token, requires_services
from tests.integration.conftest import given_a_profile, signed_in_as

pytestmark = requires_services

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


def as_administrator(role: str = "moderator") -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(role=role)}"}


async def given_posts(author_id: uuid.UUID, count: int) -> list[uuid.UUID]:
    """Straight into the table. The first one is the post the rest answer."""
    ids: list[uuid.UUID] = []
    async with app.state.session_factory() as session:
        for index in range(count):
            post = PostModel(
                author_id=author_id,
                content=f"post {index}",
                created_at=NOW,
                parent_id=ids[0] if ids else None,
            )
            session.add(post)
            await session.flush()
            ids.append(post.id)
        await session.commit()
    return ids


async def counts_of(api, user_id: uuid.UUID, role: str = "moderator"):
    return await api.get(f"/admin/posts/accounts/{user_id}/counts", headers=as_administrator(role))


async def test_e5_h4_ca1_counts_followers_and_posts_of_an_account(api):
    account = uuid.uuid4()
    await given_a_profile(account)
    for _ in range(2):
        await api.post(f"/users/{account}/follow", headers=signed_in_as(uuid.uuid4()))
    await given_posts(account, 3)

    for role in ("moderator", "superadmin"):
        response = await counts_of(api, account, role)

        assert response.status_code == 200
        # Replies count as posts too.
        assert response.json() == {"followers": 2, "posts": 3}


async def test_e5_h4_ca1_deleted_posts_do_not_count(api):
    account = uuid.uuid4()
    await given_a_profile(account)
    first, _ = await given_posts(account, 2)
    async with app.state.session_factory() as session:
        await session.execute(update(PostModel).where(PostModel.id == first).values(deleted_at=NOW))
        await session.commit()

    response = await counts_of(api, account)

    assert response.json() == {"followers": 0, "posts": 1}


async def test_e5_h4_ca1_an_account_without_profile_counts_zero(api):
    response = await counts_of(api, uuid.uuid4())

    assert response.status_code == 200
    assert response.json() == {"followers": 0, "posts": 0}


async def test_a_closed_account_counts_zero(api):
    account = uuid.uuid4()
    await given_a_profile(account)
    await given_posts(account, 2)
    async with app.state.session_factory() as session:
        await session.execute(
            update(UserProfileModel).where(UserProfileModel.id == account).values(deleted_at=NOW)
        )
        await session.commit()

    response = await counts_of(api, account)

    assert response.json() == {"followers": 0, "posts": 0}


async def test_an_app_user_cannot_read_the_counts(api):
    account = uuid.uuid4()
    await given_a_profile(account)

    response = await api.get(
        f"/admin/posts/accounts/{account}/counts", headers=signed_in_as(uuid.uuid4())
    )

    assert response.status_code == 403
