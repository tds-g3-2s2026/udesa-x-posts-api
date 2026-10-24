import io

from posts_api.app.image_rules import JPEG, PNG, IncomingImage, detect_format


def test_a_jpeg_is_told_by_its_first_three_bytes():
    assert detect_format(b"\xff\xd8\xff\xe0\x00\x10JFIF") is JPEG
    assert detect_format(b"\xff\xd8\xff") is JPEG


def test_a_png_is_told_by_its_eight_byte_signature():
    assert detect_format(b"\x89PNG\r\n\x1a\n\x00\x00") is PNG


def test_anything_else_is_not_an_image_we_accept():
    assert detect_format(b"GIF89a") is None
    assert detect_format(b"RIFF....WEBP") is None
    assert detect_format(b"plain text") is None
    # Starts like a PNG but the signature is cut short.
    assert detect_format(b"\x89PNG\r\n") is None
    assert detect_format(b"") is None


def test_reading_the_header_leaves_the_file_where_it_started():
    image = IncomingImage(io.BytesIO(b"\x89PNG\r\n\x1a\nrest"), size=12)

    assert image.header() == b"\x89PNG\r\n\x1a\n"
    assert image.data.read() == b"\x89PNG\r\n\x1a\nrest"
