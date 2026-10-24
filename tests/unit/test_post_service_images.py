import io

import pytest

from posts_api.app.errors import ProblemError
from posts_api.app.image_rules import MAX_IMAGE_BYTES, MAX_IMAGES, PNG, IncomingImage
from posts_api.app.services.posts import PostService

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


def image_of(size: int) -> IncomingImage:
    return IncomingImage(io.BytesIO(PNG_BYTES), size=size)


def test_the_service_names_the_format_of_each_file():
    assert PostService._formats_of([image_of(16)]) == [PNG]


def test_the_service_refuses_more_images_than_the_limit_on_its_own():
    images = [image_of(16) for _ in range(MAX_IMAGES + 1)]

    with pytest.raises(ProblemError) as raised:
        PostService._formats_of(images)

    assert raised.value.code == "too-many-images"


def test_the_service_refuses_an_image_over_the_limit_on_its_own():
    with pytest.raises(ProblemError) as raised:
        PostService._formats_of([image_of(MAX_IMAGE_BYTES + 1)])

    assert raised.value.code == "image-too-large"
