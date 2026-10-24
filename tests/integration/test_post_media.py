import uuid

import pytest
from sqlalchemy import func, select

from posts_api.app.image_rules import MAX_IMAGE_BYTES
from posts_api.app.repositories.post_media import PostMediaRepository
from posts_api.infrastructure.database.models import PostMediaModel, PostModel
from posts_api.infrastructure.s3.image_storage import UnconfiguredImageStorage
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import signed_in_as
from tests.integration.test_feed import insert_follow
from tests.integration.test_likes import block

pytestmark = requires_services

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def png_of(size: int) -> bytes:
    return PNG + b"\x00" * (size - len(PNG))


def pictures(*contents: bytes) -> list:
    return [("images", (f"photo-{n}.png", one, "image/png")) for n, one in enumerate(contents)]


async def post_with(api, author, *, text: str | None = "hola", files=None):
    """Always multipart, even with no files: a form without any is sent urlencoded otherwise."""
    parts = [("content", (None, text))] if text is not None else []
    return await api.post("/posts", files=[*parts, *(files or [])], headers=signed_in_as(author))


async def stored_posts() -> int:
    async with app.state.session_factory() as session:
        return await session.scalar(select(func.count()).select_from(PostModel))


async def stored_media() -> int:
    async with app.state.session_factory() as session:
        return await session.scalar(select(func.count()).select_from(PostMediaModel))


async def test_e2_h7_ca1_a_fifth_image_is_refused(api):
    author = uuid.uuid4()

    response = await post_with(api, author, files=pictures(PNG, PNG, PNG, PNG, PNG))

    assert response.status_code == 422
    assert response.json()["type"] == "https://udesa-x.dev/errors/too-many-images"
    assert response.json()["detail"] == "Un post admite hasta 4 imágenes."
    assert (await stored_posts(), await stored_media()) == (0, 0)
    assert app.state.image_storage.files == {}


async def test_e2_h7_ca1_four_images_are_accepted_in_the_order_they_were_sent(api):
    author = uuid.uuid4()
    files = pictures(PNG, JPEG, PNG, JPEG)

    response = await post_with(api, author, files=files)

    assert response.status_code == 201
    images = response.json()["images"]
    assert [one["position"] for one in images] == [0, 1, 2, 3]
    storage = app.state.image_storage
    types = [storage.content_types[key] for key in storage.files]
    assert types == ["image/png", "image/jpeg", "image/png", "image/jpeg"]
    assert all(uuid.UUID(one["id"]) for one in images)
    assert all(one["url"].startswith("https://bucket.test/posts/") for one in images)


async def test_e2_h7_ca2_an_image_over_1mb_is_refused(api):
    author = uuid.uuid4()

    response = await post_with(api, author, files=pictures(png_of(MAX_IMAGE_BYTES + 1)))

    assert response.status_code == 422
    assert response.json()["type"] == "https://udesa-x.dev/errors/image-too-large"
    assert response.json()["detail"] == "Cada imagen puede pesar hasta 1 MB."
    assert (await stored_posts(), await stored_media()) == (0, 0)


async def test_e2_h7_ca2_an_image_of_exactly_1mb_is_accepted(api):
    author = uuid.uuid4()

    response = await post_with(api, author, files=pictures(png_of(MAX_IMAGE_BYTES)))

    assert response.status_code == 201
    assert len(app.state.image_storage.files) == 1


async def test_e2_h7_ca3_a_text_file_renamed_to_jpg_is_refused(api):
    author = uuid.uuid4()
    files = [("images", ("photo.jpg", b"this is plain text, not a picture", "image/jpeg"))]

    response = await post_with(api, author, files=files)

    assert response.status_code == 422
    assert response.json()["type"] == "https://udesa-x.dev/errors/image-format-not-supported"
    assert response.json()["detail"] == "Solo se aceptan imágenes JPG o PNG."
    assert app.state.image_storage.files == {}


async def test_e2_h7_ca3_a_real_png_is_accepted(api):
    author = uuid.uuid4()
    # The extension and the declared type say it is a text file: only the bytes count.
    files = [("images", ("notes.txt", PNG, "text/plain"))]

    response = await post_with(api, author, files=files)

    assert response.status_code == 201
    assert list(app.state.image_storage.content_types.values()) == ["image/png"]


async def test_a_real_gif_is_refused_like_any_other_unsupported_format(api):
    author = uuid.uuid4()
    files = [("images", ("anim.png", b"GIF89a" + b"\x00" * 32, "image/png"))]

    response = await post_with(api, author, files=files)

    assert response.json()["type"] == "https://udesa-x.dev/errors/image-format-not-supported"


async def test_a_post_may_be_only_images(api):
    author = uuid.uuid4()

    response = await post_with(api, author, text=None, files=pictures(PNG))

    assert response.status_code == 201
    assert response.json()["content"] == ""
    assert len(response.json()["images"]) == 1


async def test_a_blank_text_without_images_is_still_refused(api):
    author = uuid.uuid4()

    response = await post_with(api, author, text="   ")

    assert response.status_code == 422
    assert response.json()["type"] == "https://udesa-x.dev/errors/post-is-blank"


async def test_a_multipart_post_without_images_answers_with_an_empty_list(api):
    author = uuid.uuid4()

    response = await post_with(api, author, text="solo texto")

    assert response.status_code == 201
    assert response.json()["images"] == []
    assert response.json()["content"] == "solo texto"


async def test_the_text_of_a_multipart_post_gets_the_same_checks(api):
    author = uuid.uuid4()

    too_long = await post_with(api, author, text="a" * 281, files=pictures(PNG))
    tagged = await post_with(api, author, text="<b>hola</b>", files=pictures(PNG))

    assert too_long.json()["type"] == "https://udesa-x.dev/errors/post-too-long"
    assert tagged.status_code == 201
    assert tagged.json()["content"] == "hola"


async def test_a_multipart_post_is_charged_once_and_before_its_files_are_read(api):
    author = uuid.uuid4()
    redis = app.state.redis
    await redis.set(f"post:rate:{author}", 30)

    refused = await post_with(api, author, files=pictures(PNG))

    assert refused.status_code == 429
    assert app.state.image_storage.puts == 0
    assert int(await redis.get(f"post:rate:{author}")) == 31


async def test_one_multipart_post_costs_one_attempt(api):
    author = uuid.uuid4()

    await post_with(api, author, files=pictures(PNG, PNG, PNG))

    assert int(await app.state.redis.get(f"post:rate:{author}")) == 1


async def test_four_images_of_exactly_1mb_with_a_full_text_are_accepted(api):
    author = uuid.uuid4()
    files = pictures(*([png_of(MAX_IMAGE_BYTES)] * 4))

    response = await post_with(api, author, text="a" * 280, files=files)

    assert response.status_code == 201
    assert len(response.json()["images"]) == 4


async def test_a_body_that_is_not_multipart_is_a_bad_request(api):
    author = uuid.uuid4()
    headers = {
        **signed_in_as(author),
        "Content-Type": "multipart/form-data; boundary=xyz",
    }

    garbage = await api.post("/posts", content=b"this has no parts at all", headers=headers)
    truncated = await api.post(
        "/posts",
        content=b'--xyz\r\nContent-Disposition: form-data; name="content"\r\n\r\nhola',
        headers=headers,
    )

    for response in (garbage, truncated):
        assert response.status_code == 400
        assert response.json()["type"] == "https://udesa-x.dev/errors/invalid-multipart"
        assert response.json()["detail"] == "No se pudo leer el contenido enviado."


async def test_a_multipart_request_without_a_boundary_is_a_bad_request(api):
    author = uuid.uuid4()
    headers = {**signed_in_as(author), "Content-Type": "multipart/form-data"}

    response = await api.post("/posts", content=b"anything", headers=headers)

    assert response.status_code == 400
    assert response.json()["type"] == "https://udesa-x.dev/errors/invalid-multipart"


async def test_a_body_far_over_the_limits_is_cut_without_storing_anything(api):
    author = uuid.uuid4()
    files = [("notes", ("big.bin", b"\x00" * (6 * 1024 * 1024), "application/octet-stream"))]

    response = await post_with(api, author, files=files)

    assert response.status_code == 400
    assert response.json()["type"] == "https://udesa-x.dev/errors/invalid-multipart"


async def test_other_fields_of_the_form_are_ignored(api):
    author = uuid.uuid4()
    files = [("avatar", ("a.png", PNG, "image/png")), *pictures(PNG)]

    response = await post_with(api, author, files=files)

    assert response.status_code == 201
    assert len(response.json()["images"]) == 1


async def test_multipart_needs_a_token(api):
    response = await api.post("/posts", files=pictures(PNG))

    assert response.status_code == 401


async def test_a_failed_upload_leaves_no_post_and_removes_what_was_already_up(api):
    author = uuid.uuid4()
    app.state.image_storage.fail_on_put = 2

    response = await post_with(api, author, files=pictures(PNG, PNG, PNG))

    assert response.status_code == 503
    assert response.json()["type"] == "https://udesa-x.dev/errors/images-unavailable"
    assert app.state.image_storage.files == {}
    assert (await stored_posts(), await stored_media()) == (0, 0)


async def test_a_refused_cleanup_does_not_hide_the_original_failure(api):
    author = uuid.uuid4()
    app.state.image_storage.fail_on_put = 2
    app.state.image_storage.fail_on_delete = True

    response = await post_with(api, author, files=pictures(PNG, PNG))

    assert response.status_code == 503
    assert response.json()["type"] == "https://udesa-x.dev/errors/images-unavailable"
    assert (await stored_posts(), await stored_media()) == (0, 0)


async def test_a_database_failure_after_the_upload_removes_the_files_and_the_post(api, monkeypatch):
    async def broken(self, post_id, media):
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(PostMediaRepository, "add", broken)

    with pytest.raises(RuntimeError):
        await post_with(api, uuid.uuid4(), files=pictures(PNG, PNG))

    assert app.state.image_storage.files == {}
    assert (await stored_posts(), await stored_media()) == (0, 0)


async def test_a_text_part_over_16_kib_is_refused_as_too_long(api):
    response = await post_with(api, uuid.uuid4(), text="a" * (16 * 1024 + 1))

    assert response.status_code == 422
    assert response.json()["type"] == "https://udesa-x.dev/errors/post-too-long"
    assert await stored_posts() == 0


async def test_a_text_part_that_is_not_utf8_is_an_invalid_multipart(api):
    response = await post_with(api, uuid.uuid4(), text=b"\xff\xfe\xfa")

    assert response.status_code == 400
    assert response.json()["type"] == "https://udesa-x.dev/errors/invalid-multipart"
    assert await stored_posts() == 0


async def test_without_a_bucket_publishing_an_image_is_unavailable_but_text_still_works(api):
    author = uuid.uuid4()
    app.state.image_storage = UnconfiguredImageStorage()

    with_image = await post_with(api, author, files=pictures(PNG))
    text_only = await post_with(api, author, text="sin imagen")
    as_json = await api.post("/posts", json={"content": "json"}, headers=signed_in_as(author))

    assert with_image.status_code == 503
    assert (text_only.status_code, as_json.status_code) == (201, 201)


async def test_json_posts_keep_their_errors(api):
    author = uuid.uuid4()
    headers = signed_in_as(author)

    no_content = await api.post("/posts", json={}, headers=headers)
    not_json = await api.post(
        "/posts", content=b"{broken", headers={**headers, "Content-Type": "application/json"}
    )
    empty = await api.post("/posts", headers={**headers, "Content-Type": "application/json"})

    for response in (no_content, not_json, empty):
        assert response.status_code == 422
        assert response.json()["type"] == "https://udesa-x.dev/errors/validation-failed"
    assert no_content.json()["errors"] == [{"field": "content", "message": "Field required"}]


async def test_a_post_with_a_json_body_has_no_images(api):
    author = uuid.uuid4()

    response = await api.post("/posts", json={"content": "hola"}, headers=signed_in_as(author))

    assert response.json()["images"] == []


async def published_with_images(api, author, count=2) -> str:
    response = await post_with(api, author, files=pictures(*([PNG] * count)))
    assert response.status_code == 201
    return response.json()["id"]


async def test_the_single_post_carries_its_images_in_order(api):
    author, reader = uuid.uuid4(), uuid.uuid4()
    post = await published_with_images(api, author, 3)

    response = await api.get(f"/posts/{post}", headers=signed_in_as(reader))

    images = response.json()["images"]
    assert [one["position"] for one in images] == [0, 1, 2]
    assert set(images[0]) == {"id", "url", "position"}


async def test_the_feed_carries_the_images_with_one_extra_query_per_page(api, monkeypatch):
    viewer, author = uuid.uuid4(), uuid.uuid4()
    await insert_follow(viewer, author)
    with_images = [await published_with_images(api, author) for _ in range(3)]
    plain = await api.post("/posts", json={"content": "sin fotos"}, headers=signed_in_as(author))
    calls = []
    original = PostMediaRepository.for_posts

    async def counting(self, post_ids):
        calls.append(set(post_ids))
        return await original(self, post_ids)

    monkeypatch.setattr(PostMediaRepository, "for_posts", counting)

    response = await api.get("/feed", headers=signed_in_as(viewer))

    items = {one["id"]: one for one in response.json()["items"]}
    assert len(calls) == 1
    assert [len(items[one]["images"]) for one in with_images] == [2, 2, 2]
    assert items[plain.json()["id"]]["images"] == []


async def test_a_retweet_row_carries_the_images_of_the_original(api):
    author, sharer, viewer = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await insert_follow(viewer, sharer)
    post = await published_with_images(api, author)
    await api.post(f"/posts/{post}/retweet", headers=signed_in_as(sharer))

    response = await api.get("/feed", headers=signed_in_as(viewer))

    row = response.json()["items"][0]
    assert row["retweetedBy"] == f"@u{str(sharer)[:8]}"
    assert [one["position"] for one in row["images"]] == [0, 1]


async def test_profile_posts_carry_their_images(api):
    author, viewer = uuid.uuid4(), uuid.uuid4()
    await published_with_images(api, author)

    response = await api.get(f"/users/{author}/posts", headers=signed_in_as(viewer))

    assert len(response.json()["items"][0]["images"]) == 2


async def test_replies_have_no_images_and_are_listed_with_an_empty_list(api):
    author, replier = uuid.uuid4(), uuid.uuid4()
    post = await published_with_images(api, author)
    created = await api.post(
        f"/posts/{post}/replies", json={"content": "respuesta"}, headers=signed_in_as(replier)
    )

    listing = await api.get(f"/posts/{post}/replies", headers=signed_in_as(author))

    assert created.json()["images"] == []
    assert listing.json()["items"][0]["images"] == []


async def test_a_deleted_post_shows_no_images(api):
    author = uuid.uuid4()
    post = await published_with_images(api, author)

    await api.delete(f"/posts/{post}", headers=signed_in_as(author))
    response = await api.get(f"/posts/{post}", headers=signed_in_as(author))

    assert response.json()["deleted"] is True
    assert response.json()["images"] == []


async def test_the_images_of_a_post_the_viewer_cannot_read_are_not_reachable(api):
    author, blocked = uuid.uuid4(), uuid.uuid4()
    post = await published_with_images(api, author)
    await block(author, blocked)

    response = await api.get(f"/posts/{post}", headers=signed_in_as(blocked))

    assert response.status_code == 404
    assert "images" not in response.json()


async def test_a_failure_signing_a_url_is_reported_as_unavailable(api):
    author = uuid.uuid4()
    post = await published_with_images(api, author)
    app.state.image_storage.fail_on_url = True

    response = await api.get(f"/posts/{post}", headers=signed_in_as(author))

    assert response.status_code == 503
    assert response.json()["type"] == "https://udesa-x.dev/errors/images-unavailable"
