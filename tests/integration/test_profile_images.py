"""Uploading, replacing and deleting the profile photo and the cover."""

import uuid

import pytest
from sqlalchemy import select

from posts_api.app.image_rules import AVATAR, COVER
from posts_api.app.repositories.profile_images import ProfileImageRepository
from posts_api.infrastructure.database.models import UserProfileModel
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import signed_in_as
from tests.integration.test_post_media import JPEG, PNG, png_of
from tests.integration.test_profile import users_api  # noqa: F401  (fixture)

pytestmark = requires_services

ERRORS = "https://udesa-x.dev/errors"
GIF = b"GIF89a" + b"\x00" * 32


def image(content: bytes, name: str = "foto.png", content_type: str = "image/png") -> list:
    return [("image", (name, content, content_type))]


async def put_avatar(api, owner, content=PNG, **kwargs):
    return await api.put(
        "/users/me/avatar", files=image(content, **kwargs), headers=signed_in_as(owner)
    )


async def put_cover(api, owner, content=PNG, **kwargs):
    return await api.put(
        "/users/me/cover", files=image(content, **kwargs), headers=signed_in_as(owner)
    )


async def keys_of(owner: uuid.UUID) -> tuple[str | None, str | None]:
    async with app.state.session_factory() as session:
        row = (
            await session.execute(
                select(UserProfileModel.avatar_key, UserProfileModel.cover_key).where(
                    UserProfileModel.id == owner
                )
            )
        ).one()
        return row.avatar_key, row.cover_key


def key_in(url: str) -> str:
    """The key the fake bucket signed, back out of its URL."""
    return url.removeprefix("https://bucket.test/").split("?")[0]


async def test_e1_h8_ca1_only_jpg_and_png_are_accepted(api):
    owner = uuid.uuid4()

    png = await put_avatar(api, owner, PNG)
    jpeg = await put_cover(api, owner, JPEG, name="portada.jpg", content_type="image/jpeg")
    gif = await put_avatar(api, owner, GIF, name="foto.gif", content_type="image/gif")

    assert (png.status_code, jpeg.status_code) == (200, 200)
    assert png.json()["avatarUrl"].startswith(f"https://bucket.test/profiles/{owner}/avatar/")
    assert jpeg.json()["coverUrl"].startswith(f"https://bucket.test/profiles/{owner}/cover/")
    storage = app.state.image_storage
    assert sorted(storage.content_types.values()) == ["image/jpeg", "image/png"]
    assert gif.status_code == 422
    assert gif.json()["type"] == f"{ERRORS}/image-format-not-supported"
    assert gif.json()["title"] == "No se pudo actualizar la imagen"
    # The refused one changed nothing: the PNG is still the photo.
    assert (await keys_of(owner))[0] == key_in(png.json()["avatarUrl"])


async def test_e1_h8_ca2_an_avatar_over_5_mb_is_rejected(api):
    owner = uuid.uuid4()

    response = await put_avatar(api, owner, png_of(AVATAR.max_bytes + 1))

    assert response.status_code == 422
    assert response.json()["type"] == f"{ERRORS}/image-too-large"
    assert response.json()["detail"] == "La foto de perfil puede pesar hasta 5 MB."
    assert app.state.image_storage.files == {}


async def test_an_avatar_of_exactly_5_mb_is_accepted(api):
    response = await put_avatar(api, uuid.uuid4(), png_of(AVATAR.max_bytes))

    assert response.status_code == 200


async def test_e1_h8_ca2_a_cover_over_10_mb_is_rejected(api):
    owner = uuid.uuid4()

    response = await put_cover(api, owner, png_of(COVER.max_bytes + 1))

    assert response.status_code == 422
    assert response.json()["type"] == f"{ERRORS}/image-too-large"
    assert response.json()["detail"] == "La portada puede pesar hasta 10 MB."
    assert app.state.image_storage.files == {}


async def test_the_cover_has_its_own_limit_above_the_one_of_the_photo(api):
    owner = uuid.uuid4()
    six_mb = png_of(6 * 1_048_576)

    cover = await put_cover(api, owner, six_mb)
    avatar = await put_avatar(api, owner, six_mb)

    assert cover.status_code == 200
    assert avatar.status_code == 422


async def test_e1_h8_ca3_a_renamed_file_is_rejected_by_its_content(api):
    owner = uuid.uuid4()

    renamed_text = await put_avatar(api, owner, b"no soy una imagen", name="foto.png")
    # The opposite: a real PNG with a name and a type that say otherwise.
    real_png = await put_avatar(api, owner, PNG, name="foto.gif", content_type="image/gif")

    assert renamed_text.status_code == 422
    assert renamed_text.json()["type"] == f"{ERRORS}/image-format-not-supported"
    assert real_png.status_code == 200
    key = key_in(real_png.json()["avatarUrl"])
    assert key.endswith(".png")
    assert app.state.image_storage.content_types[key] == "image/png"


async def test_e1_h8_ca4_replacing_the_avatar_deletes_the_old_file(api):
    owner = uuid.uuid4()
    first = key_in((await put_avatar(api, owner, PNG)).json()["avatarUrl"])

    second = await put_avatar(api, owner, JPEG, content_type="image/jpeg")

    assert second.status_code == 200
    new = key_in(second.json()["avatarUrl"])
    assert new != first
    assert set(app.state.image_storage.files) == {new}
    assert (await keys_of(owner))[0] == new


async def test_replacing_the_cover_leaves_the_photo_alone(api):
    owner = uuid.uuid4()
    avatar = key_in((await put_avatar(api, owner)).json()["avatarUrl"])
    await put_cover(api, owner)

    cover = key_in((await put_cover(api, owner)).json()["coverUrl"])

    assert set(app.state.image_storage.files) == {avatar, cover}
    assert await keys_of(owner) == (avatar, cover)


async def test_e1_h8_ca6_deleting_the_avatar_goes_back_to_the_default(api, users_api):  # noqa: F811
    owner = uuid.uuid4()
    users_api.has(owner)
    await put_avatar(api, owner)

    deleted = await api.delete("/users/me/avatar", headers=signed_in_as(owner))

    assert deleted.status_code == 204
    assert app.state.image_storage.files == {}
    profile = await api.get(f"/users/{owner}", headers=signed_in_as(uuid.uuid4()))
    assert profile.json()["avatarUrl"] is None
    # Asking again is not an error: the profile is already without a photo.
    again = await api.delete("/users/me/avatar", headers=signed_in_as(owner))
    assert again.status_code == 204


async def test_deleting_the_cover_keeps_the_photo(api):
    owner = uuid.uuid4()
    avatar = key_in((await put_avatar(api, owner)).json()["avatarUrl"])
    await put_cover(api, owner)

    response = await api.delete("/users/me/cover", headers=signed_in_as(owner))

    assert response.status_code == 204
    assert set(app.state.image_storage.files) == {avatar}
    assert await keys_of(owner) == (avatar, None)


async def test_deleting_without_ever_having_a_profile_is_not_an_error(api):
    response = await api.delete("/users/me/cover", headers=signed_in_as(uuid.uuid4()))

    assert response.status_code == 204


async def test_e1_h8_ca7_the_upload_is_streamed_to_storage(api):
    owner = uuid.uuid4()

    response = await put_cover(api, owner, png_of(3 * 1_048_576))

    assert response.status_code == 200
    # The request was written to a temporary file on disk as it arrived, and the
    # storage was handed that file to read from, never the bytes in memory.
    assert app.state.image_storage.from_disk[key_in(response.json()["coverUrl"])] is True


async def test_without_the_image_part_the_upload_is_a_bad_request(api):
    owner = uuid.uuid4()
    files = [("foto", ("foto.png", PNG, "image/png"))]

    response = await api.put("/users/me/avatar", files=files, headers=signed_in_as(owner))

    assert response.status_code == 400
    assert response.json()["type"] == f"{ERRORS}/invalid-multipart"
    assert response.json()["title"] == "No se pudo actualizar la imagen"
    assert app.state.image_storage.files == {}


async def test_two_images_in_one_upload_are_a_bad_request(api):
    owner = uuid.uuid4()
    files = [*image(PNG), *image(PNG)]

    response = await api.put("/users/me/avatar", files=files, headers=signed_in_as(owner))

    assert response.status_code == 400
    assert response.json()["type"] == f"{ERRORS}/invalid-multipart"
    assert app.state.image_storage.files == {}


async def test_a_body_that_is_not_multipart_is_a_bad_request(api):
    response = await api.put(
        "/users/me/avatar", json={"image": "foto.png"}, headers=signed_in_as(uuid.uuid4())
    )

    assert response.status_code == 400
    assert response.json()["type"] == f"{ERRORS}/invalid-multipart"


async def test_uploading_needs_a_token(api):
    response = await api.put("/users/me/avatar", files=image(PNG))

    assert response.status_code == 401


async def test_a_failed_upload_keeps_the_previous_photo(api):
    owner = uuid.uuid4()
    first = key_in((await put_avatar(api, owner)).json()["avatarUrl"])
    app.state.image_storage.fail_on_put = 2

    response = await put_avatar(api, owner)

    assert response.status_code == 503
    assert response.json()["type"] == f"{ERRORS}/images-unavailable"
    assert set(app.state.image_storage.files) == {first}
    assert (await keys_of(owner))[0] == first


async def test_a_failure_signing_the_new_photo_removes_it_and_keeps_the_previous(api):
    owner = uuid.uuid4()
    first = key_in((await put_avatar(api, owner)).json()["avatarUrl"])
    app.state.image_storage.fail_on_url = True

    response = await put_avatar(api, owner)

    assert response.status_code == 503
    assert set(app.state.image_storage.files) == {first}
    assert (await keys_of(owner))[0] == first


async def test_a_database_failure_after_the_upload_removes_the_new_file(api, monkeypatch):
    owner = uuid.uuid4()

    async def broken(self, user_id, kind, key):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(ProfileImageRepository, "set_key", broken)

    with pytest.raises(RuntimeError):
        await put_avatar(api, owner)

    assert app.state.image_storage.files == {}


async def test_an_old_file_the_bucket_refuses_to_delete_does_not_undo_the_new_photo(api):
    owner = uuid.uuid4()
    first = key_in((await put_avatar(api, owner)).json()["avatarUrl"])
    app.state.image_storage.fail_on_delete = True

    response = await put_avatar(api, owner)

    assert response.status_code == 200
    new = key_in(response.json()["avatarUrl"])
    assert (await keys_of(owner))[0] == new
    # Left behind in the bucket, logged: the profile is what had to change.
    assert set(app.state.image_storage.files) == {first, new}
