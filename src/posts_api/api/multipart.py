"""Reading a post sent as `multipart/form-data`, straight off the request stream.

FastAPI's own upload handling receives every file in full before the endpoint
runs, so a limit on size could only be applied after the bytes were already
here. This feeds the body to the parser chunk by chunk and stops at the byte
that crosses a limit.

Each image goes to a temporary file that stays in memory only while it is
small, so no uploaded file is held whole in the process.
"""

import tempfile
from dataclasses import dataclass, field

from fastapi import Request
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header

from posts_api.app.errors import ProblemError
from posts_api.app.image_rules import (
    MAX_IMAGE_BYTES,
    MAX_IMAGES,
    IncomingImage,
    image_too_large,
    invalid_multipart,
    too_many_images,
)
from posts_api.app.services.posts import MAX_CONTENT_LENGTH

CONTENT_FIELD = b"content"
IMAGES_FIELD = b"images"

# Below this a file lives in memory; above it, in a temporary file on disk.
_SPOOL_BYTES = 256 * 1024

# Not the post's own limit, which applies to the text once its tags are gone:
# this only keeps a field of any size from being buffered.
_MAX_CONTENT_BYTES = 16 * 1024

# Everything the parser will accept in total: the largest legitimate post plus
# the headers and boundaries around its parts.
_MAX_BODY_BYTES = MAX_IMAGES * MAX_IMAGE_BYTES + _MAX_CONTENT_BYTES + 64 * 1024


@dataclass
class PostForm:
    content: str = ""
    images: list[IncomingImage] = field(default_factory=list)

    def close(self) -> None:
        for image in self.images:
            image.close()


def is_multipart(content_type: str | None) -> bool:
    return content_type is not None and content_type.lower().lstrip().startswith(
        "multipart/form-data"
    )


async def read_post_form(request: Request) -> PostForm:
    """The `content` field and the `images` files, in the order they appear.

    Raises `ProblemError` as soon as a limit is crossed, without reading the
    rest of the body. Whatever was received up to then is released.
    """
    _, options = parse_options_header(request.headers.get("content-type"))
    boundary = options.get(b"boundary")
    if not boundary:
        raise invalid_multipart()

    reader = _Reader()
    try:
        parser = MultipartParser(
            boundary,
            {
                "on_part_begin": reader.part_begin,
                "on_header_field": reader.header_field,
                "on_header_value": reader.header_value,
                "on_header_end": reader.header_end,
                "on_headers_finished": reader.headers_finished,
                "on_part_data": reader.part_data,
                "on_part_end": reader.part_end,
                "on_end": reader.end,
            },
            max_size=_MAX_BODY_BYTES,
        )
        async for chunk in request.stream():
            # The parser drops what goes past its size limit without saying so,
            # which would turn an oversized body into a quietly cut one.
            if parser.write(chunk) != len(chunk):
                raise invalid_multipart()
        parser.finalize()
        if not reader.finished:
            raise invalid_multipart()
    except FormParserError as exc:
        reader.abort()
        raise invalid_multipart() from exc
    except BaseException:
        reader.abort()
        raise
    return reader.form


class _Reader:
    """The parser's callbacks, which keep what they need between one chunk and the next."""

    def __init__(self) -> None:
        self.form = PostForm()
        self.finished = False
        self._headers: dict[bytes, bytes] = {}
        self._header_name = bytearray()
        self._header_value = bytearray()
        self._field: bytes | None = None
        self._text = bytearray()
        self._file = None
        self._size = 0

    def part_begin(self) -> None:
        self._headers = {}
        self._field = None
        self._text = bytearray()
        self._file = None
        self._size = 0

    def header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_name += data[start:end]

    def header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value += data[start:end]

    def header_end(self) -> None:
        self._headers[bytes(self._header_name).lower()] = bytes(self._header_value)
        self._header_name = bytearray()
        self._header_value = bytearray()

    def headers_finished(self) -> None:
        _, options = parse_options_header(self._headers.get(b"content-disposition"))
        self._field = options.get(b"name")
        if self._field == IMAGES_FIELD:
            # Refused when the fifth part starts, before any of its bytes are read.
            if len(self.form.images) >= MAX_IMAGES:
                raise too_many_images()
            # Closed with the form, once the post is stored or refused.
            self._file = tempfile.SpooledTemporaryFile(max_size=_SPOOL_BYTES)  # noqa: SIM115

    def part_data(self, data: bytes, start: int, end: int) -> None:
        chunk = data[start:end]
        self._size += len(chunk)
        if self._file is not None:
            if self._size > MAX_IMAGE_BYTES:
                raise image_too_large()
            self._file.write(chunk)
        elif self._field == CONTENT_FIELD:
            if self._size > _MAX_CONTENT_BYTES:
                raise _content_too_long()
            self._text += chunk
        # Any other field is read and dropped.

    def part_end(self) -> None:
        if self._file is not None:
            self.form.images.append(IncomingImage(self._file, self._size))
            self._file = None
        elif self._field == CONTENT_FIELD:
            try:
                self.form.content = self._text.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise invalid_multipart() from exc

    def end(self) -> None:
        self.finished = True

    def abort(self) -> None:
        """Release everything received so far, including the file being written."""
        if self._file is not None:
            self._file.close()
        self.form.close()


def _content_too_long() -> ProblemError:
    return ProblemError(
        status=422,
        code="post-too-long",
        title="No se pudo publicar el post",
        detail=f"El post no puede superar los {MAX_CONTENT_LENGTH} caracteres",
    )
