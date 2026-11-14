"""What the backoffice reads of the posts, to clean them from their detail (E5-H10)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from posts_api.infrastructure.database.models import PostModel
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, handle_of, signed_in_as
from tests.integration.test_admin_reports import as_moderator
from tests.integration.test_admin_reports import users_api as users_api
from tests.integration.test_post_media import PNG, pictures, post_with
from tests.integration.test_replies import publish, reply
from tests.integration.test_retweets import share

pytestmark = requires_services


async def detail(api, post_id: str, headers: dict[str, str] | None = None):
    return await api.get(
        f"/admin/posts/{post_id}", headers=as_moderator() if headers is None else headers
    )


async def posts_of(api, user_id: uuid.UUID, cursor: str | None = None):
    return await api.get(
        f"/admin/posts/accounts/{user_id}/posts",
        params={} if cursor is None else {"cursor": cursor},
        headers=as_moderator(),
    )


async def test_e5_h10_an_administrator_reads_a_post_of_a_protected_account(api):
    author = uuid.uuid4()
    await given_a_profile(author, visibility="protected")
    created = await post_with(api, author, text="Solo para mis seguidores", files=pictures(PNG))
    post_id = created.json()["id"]

    response = await detail(api, post_id)

    assert response.status_code == 200
    post = response.json()
    assert (post["content"], post["authorHandle"]) == (
        "Solo para mis seguidores",
        handle_of(author),
    )
    assert len(post["images"]) == 1
    assert post["likedByMe"] is False


@pytest.mark.parametrize("deleted", [False, True])
async def test_e5_h10_a_deleted_or_unknown_post_is_not_found(api, deleted):
    post_id = str(uuid.uuid4())
    if deleted:
        author = uuid.uuid4()
        await given_a_profile(author)
        post_id = await publish(api, author)
        await api.delete(f"/posts/{post_id}", headers=signed_in_as(author))

    response = await detail(api, post_id)

    assert response.status_code == 404
    assert response.json()["type"].endswith("/post-not-found")


async def test_e5_h10_an_account_lists_what_it_wrote_newest_first(api):
    author, other = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    await given_a_profile(other)
    await publish(api, author, "primero")
    answered = await publish(api, other, "de otra cuenta")
    await reply(api, author, answered, "respuesta")
    gone = await publish(api, author, "borrado")
    await api.delete(f"/posts/{gone}", headers=signed_in_as(author))
    await share(api, author, answered)
    await publish(api, author, "último")

    response = await posts_of(api, author)

    assert response.status_code == 200
    # Replies count, retweets and deleted posts do not: only what can be cleaned.
    items = response.json()["items"]
    assert [one["content"] for one in items] == ["último", "respuesta", "primero"]
    assert items[1]["parentId"] == answered
    assert response.json()["nextCursor"] is None


async def test_e5_h10_the_list_comes_in_pages_of_twenty(api):
    author = uuid.uuid4()
    await given_a_profile(author)
    start = datetime(2026, 11, 1, tzinfo=UTC)
    async with app.state.session_factory() as session:
        session.add_all(
            PostModel(author_id=author, content=f"post {n}", created_at=start + timedelta(hours=n))
            for n in range(21)
        )
        await session.commit()

    first = (await posts_of(api, author)).json()
    second = (await posts_of(api, author, first["nextCursor"])).json()

    assert [one["content"] for one in first["items"]][:2] == ["post 20", "post 19"]
    assert len(first["items"]) == 20
    assert [one["content"] for one in second["items"]] == ["post 0"]
    assert second["nextCursor"] is None


async def test_e5_h10_a_cleaned_post_reads_as_cleaned(api, users_api):
    author = uuid.uuid4()
    await given_a_profile(author)
    post_id = await publish(api, author, "Compren seguidores")

    await api.post(f"/admin/posts/{post_id}/clean-content", headers=as_moderator())

    assert (await detail(api, post_id)).json()["content"] == (
        "[Contenido eliminado por moderación]"
    )


async def test_e5_h10_a_user_token_reads_nothing_here(api):
    author = uuid.uuid4()
    await given_a_profile(author)
    post_id = await publish(api, author)
    as_user = signed_in_as(author)

    single = await detail(api, post_id, headers=as_user)
    listing = await api.get(f"/admin/posts/accounts/{author}/posts", headers=as_user)

    assert (single.status_code, listing.status_code) == (403, 403)
