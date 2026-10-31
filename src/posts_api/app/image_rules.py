"""What an image has to be to go on a post or on a profile.

Shared by the code that reads the request, which cuts the stream as soon as a
limit is crossed, and by the service, which enforces the same limits again on
whatever it is handed: neither trusts the other to have checked.
"""

from dataclasses import dataclass
from typing import BinaryIO

from posts_api.app.errors import ProblemError

MAX_IMAGES = 4
# 1 MiB. A file of exactly this size is accepted; one byte more is refused.
MAX_IMAGE_BYTES = 1_048_576

POST_TITLE = "No se pudo publicar el post"
PROFILE_TITLE = "No se pudo actualizar la imagen"


@dataclass(frozen=True)
class ProfileImageKind:
    """The profile photo or the cover: one file each, with its own limit."""

    name: str
    max_bytes: int
    too_large_detail: str


# In MiB, like the limit of the images of a post.
AVATAR = ProfileImageKind("avatar", 5 * 1_048_576, "La foto de perfil puede pesar hasta 5 MB.")
COVER = ProfileImageKind("cover", 10 * 1_048_576, "La portada puede pesar hasta 10 MB.")


@dataclass(frozen=True)
class ImageFormat:
    mime_type: str
    extension: str
    signature: bytes


JPEG = ImageFormat("image/jpeg", "jpg", b"\xff\xd8\xff")
PNG = ImageFormat("image/png", "png", b"\x89PNG\r\n\x1a\n")

_FORMATS = (JPEG, PNG)
HEADER_BYTES = max(len(one.signature) for one in _FORMATS)


def detect_format(header: bytes) -> ImageFormat | None:
    """The format the first bytes say, or `None`.

    The file name and the declared content type are not looked at: both are
    chosen by whoever sends the request, the bytes are what gets stored.
    """
    for candidate in _FORMATS:
        if header.startswith(candidate.signature):
            return candidate
    return None


@dataclass
class IncomingImage:
    """One uploaded file, already received and not yet stored."""

    data: BinaryIO
    size: int

    def header(self) -> bytes:
        self.data.seek(0)
        head = self.data.read(HEADER_BYTES)
        self.data.seek(0)
        return head

    def close(self) -> None:
        self.data.close()


def too_many_images() -> ProblemError:
    return ProblemError(
        status=422,
        code="too-many-images",
        title=POST_TITLE,
        detail="Un post admite hasta 4 imágenes.",
    )


# The codes are the same for a post and for a profile, so the app tells them
# apart the same way; the title and the limit in the detail say which one it was.
def image_too_large(
    detail: str = "Cada imagen puede pesar hasta 1 MB.", title: str = POST_TITLE
) -> ProblemError:
    return ProblemError(status=422, code="image-too-large", title=title, detail=detail)


def image_format_not_supported(title: str = POST_TITLE) -> ProblemError:
    return ProblemError(
        status=422,
        code="image-format-not-supported",
        title=title,
        detail="Solo se aceptan imágenes JPG o PNG.",
    )


def invalid_multipart(title: str = POST_TITLE) -> ProblemError:
    return ProblemError(
        status=400,
        code="invalid-multipart",
        title=title,
        detail="No se pudo leer el contenido enviado.",
    )
