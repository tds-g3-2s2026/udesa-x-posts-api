import io
import uuid

import pytest

from posts_api.app.errors import ProblemError
from posts_api.app.image_rules import AVATAR, COVER, IncomingImage
from posts_api.app.models.follow import Account
from posts_api.app.services.profile_images import ProfileImages
from tests.fakes import FakeImageStorage

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


@pytest.mark.parametrize("kind", [AVATAR, COVER])
async def test_the_service_refuses_an_image_over_the_limit_on_its_own(kind):
    """The reader already cuts the stream; the service does not trust it to have."""
    storage = FakeImageStorage()
    # Nothing past the checks is reached, so no repository is needed.
    images = ProfileImages(keys=None, follows=None, storage=storage)
    image = IncomingImage(io.BytesIO(PNG_BYTES), size=kind.max_bytes + 1)

    with pytest.raises(ProblemError) as raised:
        await images.replace(Account(id=uuid.uuid4()), kind, image)

    assert raised.value.code == "image-too-large"
    assert raised.value.detail == kind.too_large_detail
    assert storage.files == {}
