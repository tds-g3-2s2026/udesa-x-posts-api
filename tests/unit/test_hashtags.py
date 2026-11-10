import pytest

from posts_api.app.hashtags import extract_hashtags


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Primer día #UdeSA #TDS", ("udesa", "tds")),
        ("#UdeSA y #udesa y #UDESA", ("udesa",)),
        ("café en el #café", ("café",)),
        ("#ñandú", ("ñandú",)),
        ("#123 y #guion_bajo", ("123", "guion_bajo")),
        ("#fin.", ("fin",)),
        ("(#entre-paréntesis)", ("entre",)),
        ("sin hashtags", ()),
        ("a#b no es un hashtag", ()),
        ("##doble tampoco", ()),
        ("# solo, #", ()),
        ("mail@dominio.com#ancla", ()),
    ],
)
def test_hashtags_are_distinct_lowercase_and_in_order_of_appearance(text, expected):
    assert extract_hashtags(text) == expected
