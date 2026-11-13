"""An administrator clearing the content of a post (E5-H10)."""

import uuid

import pytest
from sqlalchemy import func, select

from posts_api.infrastructure.database.models import PostHashtagModel, PostMediaModel
from posts_api.main import app
from tests.conftest import requires_services
from tests.events import ADMIN_ACTION_RECORDED
from tests.integration.conftest import given_a_profile, signed_in_as
from tests.integration.test_admin_reports import ADMIN, as_moderator, audit_events
from tests.integration.test_admin_reports import users_api as users_api
from tests.integration.test_post_media import PNG, pictures, post_with

pytestmark = requires_services

PLACEHOLDER = "[Contenido eliminado por moderación]"


async def published(api, text: str = "Compren seguidores #oferta", *, images: int = 0):
    author, reader = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(author)
    await given_a_profile(reader)
    response = await post_with(api, author, text=text, files=pictures(*[PNG] * images))
    assert response.status_code == 201
    return author, reader, response.json()["id"]


async def clean(api, post_id: str, headers: dict[str, str] | None = None):
    return await api.post(
        f"/admin/posts/{post_id}/clean-content",
        headers=as_moderator() if headers is None else headers,
    )


async def read(api, reader: uuid.UUID, post_id: str) -> dict:
    response = await api.get(f"/posts/{post_id}", headers=signed_in_as(reader))
    assert response.status_code == 200
    return response.json()


async def count_of(model, post_id: str) -> int:
    async with app.state.session_factory() as session:
        return await session.scalar(
            select(func.count()).select_from(model).where(model.post_id == uuid.UUID(post_id))
        )


async def test_e5_h10_ca2_the_post_text_is_replaced_by_the_placeholder(api, users_api):
    _, reader, post_id = await published(api)

    response = await clean(api, post_id)

    assert response.status_code == 204
    assert (await read(api, reader, post_id))["content"] == PLACEHOLDER


async def test_e5_h10_the_images_and_the_hashtags_go_too(api, users_api):
    _, reader, post_id = await published(api, images=2)
    assert len(app.state.image_storage.files) == 2

    assert (await clean(api, post_id)).status_code == 204

    assert (await read(api, reader, post_id))["images"] == []
    assert await count_of(PostMediaModel, post_id) == 0
    assert app.state.image_storage.files == {}
    # Otherwise searching #oferta would still bring the post.
    assert await count_of(PostHashtagModel, post_id) == 0


async def test_e5_h10_cleaning_is_recorded_for_the_audit(api, users_api):
    author, _, post_id = await published(api)

    await clean(api, post_id)

    [event] = await audit_events()
    ADMIN_ACTION_RECORDED.validate(event)
    assert event["data"] == {
        "actor_id": str(ADMIN),
        "actor_email": "moderador@udesa.edu.ar",
        "action": "post.content_cleaned",
        "target_type": "post",
        "target_id": post_id,
        "details": {"author_id": str(author)},
    }


async def test_e5_h10_cleaning_twice_is_recorded_once(api, users_api):
    _, reader, post_id = await published(api)

    assert (await clean(api, post_id)).status_code == 204
    assert (await clean(api, post_id)).status_code == 204

    assert (await read(api, reader, post_id))["content"] == PLACEHOLDER
    assert len(await audit_events()) == 1


async def test_e5_h10_writing_the_placeholder_does_not_shield_an_image(api, users_api):
    _, reader, post_id = await published(api, text=PLACEHOLDER, images=1)

    assert (await clean(api, post_id)).status_code == 204

    assert (await read(api, reader, post_id))["images"] == []
    assert len(await audit_events()) == 1


@pytest.mark.parametrize("deleted", [False, True])
async def test_e5_h10_an_unknown_or_deleted_post_is_not_found(api, users_api, deleted):
    post_id = str(uuid.uuid4())
    if deleted:
        author, _, post_id = await published(api)
        assert (
            await api.delete(f"/posts/{post_id}", headers=signed_in_as(author))
        ).status_code == 204

    response = await clean(api, post_id)

    assert response.status_code == 404
    assert response.json()["type"].endswith("/post-not-found")
    assert await audit_events() == []


async def test_e5_h10_nothing_changes_when_users_api_does_not_answer(api, users_api):
    _, reader, post_id = await published(api, images=1)
    users_api.identity_answer = "down"

    response = await clean(api, post_id)

    assert response.status_code == 503
    post = await read(api, reader, post_id)
    assert post["content"] == "Compren seguidores #oferta"
    assert len(post["images"]) == 1
    assert await audit_events() == []


async def test_e5_h10_a_user_token_cannot_clean(api, users_api):
    author, _, post_id = await published(api)

    response = await clean(api, post_id, headers=signed_in_as(author))

    assert response.status_code == 403
    assert response.json()["type"].endswith("/administrator-required")
