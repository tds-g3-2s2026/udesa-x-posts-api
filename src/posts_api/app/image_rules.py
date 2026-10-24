"""What an image has to be to go on a post.

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
        title="No se pudo publicar el post",
        detail="Un post admite hasta 4 imágenes.",
    )


def image_too_large() -> ProblemError:
    return ProblemError(
        status=422,
        code="image-too-large",
        title="No se pudo publicar el post",
        detail="Cada imagen puede pesar hasta 1 MB.",
    )


def image_format_not_supported() -> ProblemError:
    return ProblemError(
        status=422,
        code="image-format-not-supported",
        title="No se pudo publicar el post",
        detail="Solo se aceptan imágenes JPG o PNG.",
    )


def invalid_multipart() -> ProblemError:
    return ProblemError(
        status=400,
        code="invalid-multipart",
        title="No se pudo publicar el post",
        detail="No se pudo leer el contenido enviado.",
    )
