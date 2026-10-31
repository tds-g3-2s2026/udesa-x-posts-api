"""Reading an upload sent as `multipart/form-data`, straight off the request stream.

FastAPI's own upload handling receives every file in full before the endpoint
runs, so a limit on size could only be applied after the bytes were already
here. This feeds the body to the parser chunk by chunk and stops at the byte
that crosses a limit.

Each image goes to a temporary file that stays in memory only while it is
small, so no uploaded file is held whole in the process.

Two forms are read this way: a post, with its text and up to four images, and
a profile photo or cover, a single image with a larger limit.
"""

import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import Request
from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header

from posts_api.app.errors import ProblemError
from posts_api.app.image_rules import (
    MAX_IMAGE_BYTES,
    MAX_IMAGES,
    PROFILE_TITLE,
    IncomingImage,
    ProfileImageKind,
    image_too_large,
    invalid_multipart,
    too_many_images,
)
from posts_api.app.services.posts import MAX_CONTENT_LENGTH

CONTENT_FIELD = b"content"
IMAGES_FIELD = b"images"
PROFILE_IMAGE_FIELD = b"image"

# Below this a file lives in memory; above it, in a temporary file on disk.
_SPOOL_BYTES = 256 * 1024

# Not the post's own limit, which applies to the text once its tags are gone:
# this only keeps a field of any size from being buffered.
_MAX_CONTENT_BYTES = 16 * 1024

# Room for the headers and boundaries around the parts.
_ENVELOPE_BYTES = 64 * 1024


@dataclass(frozen=True)
class _Rules:
    """What one kind of form accepts, and the error each limit answers with."""

    files_field: bytes
    max_files: int
    max_file_bytes: int
    too_many: Callable[[], ProblemError]
    too_large: Callable[[], ProblemError]
    invalid: Callable[[], ProblemError]
    # The text field read along with the files, if this form has one.
    text_field: bytes | None = None

    @property
    def max_body_bytes(self) -> int:
        """Everything the parser accepts in total: the largest legitimate form plus its envelope."""
        text = _MAX_CONTENT_BYTES if self.text_field else 0
        return self.max_files * self.max_file_bytes + text + _ENVELOPE_BYTES


_POST_RULES = _Rules(
    files_field=IMAGES_FIELD,
    max_files=MAX_IMAGES,
    max_file_bytes=MAX_IMAGE_BYTES,
    too_many=too_many_images,
    too_large=image_too_large,
    invalid=invalid_multipart,
    text_field=CONTENT_FIELD,
)


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
    return await _read(request, _POST_RULES)


async def read_profile_image(request: Request, kind: ProfileImageKind) -> IncomingImage:
    """The one `image` file of a profile photo or cover, cut at the limit of its kind.

    A body that is not multipart, has no `image` part or has more than one is
    refused as unreadable: the form has exactly one thing in it.
    """

    def invalid() -> ProblemError:
        return invalid_multipart(title=PROFILE_TITLE)

    if not is_multipart(request.headers.get("content-type")):
        raise invalid()
    rules = _Rules(
        files_field=PROFILE_IMAGE_FIELD,
        max_files=1,
        max_file_bytes=kind.max_bytes,
        too_many=invalid,
        too_large=lambda: image_too_large(kind.too_large_detail, title=PROFILE_TITLE),
        invalid=invalid,
    )
    form = await _read(request, rules)
    if not form.images:
        raise invalid()
    return form.images[0]


async def _read(request: Request, rules: _Rules) -> PostForm:
    _, options = parse_options_header(request.headers.get("content-type"))
    boundary = options.get(b"boundary")
    if not boundary:
        raise rules.invalid()

    reader = _Reader(rules)
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
            max_size=rules.max_body_bytes,
        )
        async for chunk in request.stream():
            # The parser drops what goes past its size limit without saying so,
            # which would turn an oversized body into a quietly cut one.
            if parser.write(chunk) != len(chunk):
                raise rules.invalid()
        parser.finalize()
        if not reader.finished:
            raise rules.invalid()
    except FormParserError as exc:
        reader.abort()
        raise rules.invalid() from exc
    except BaseException:
        reader.abort()
        raise
    return reader.form


class _Reader:
    """The parser's callbacks, which keep what they need between one chunk and the next."""

    def __init__(self, rules: _Rules) -> None:
        self._rules = rules
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
        if self._field == self._rules.files_field:
            # Refused when the part past the limit starts, before any of its bytes are read.
            if len(self.form.images) >= self._rules.max_files:
                raise self._rules.too_many()
            # Closed with the form, once the upload is stored or refused.
            self._file = tempfile.SpooledTemporaryFile(max_size=_SPOOL_BYTES)  # noqa: SIM115

    def part_data(self, data: bytes, start: int, end: int) -> None:
        chunk = data[start:end]
        self._size += len(chunk)
        if self._file is not None:
            if self._size > self._rules.max_file_bytes:
                raise self._rules.too_large()
            self._file.write(chunk)
        elif self._field is not None and self._field == self._rules.text_field:
            if self._size > _MAX_CONTENT_BYTES:
                raise _content_too_long()
            self._text += chunk
        # Any other field is read and dropped.

    def part_end(self) -> None:
        if self._file is not None:
            self.form.images.append(IncomingImage(self._file, self._size))
            self._file = None
        elif self._field is not None and self._field == self._rules.text_field:
            try:
                self.form.content = self._text.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise self._rules.invalid() from exc

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
