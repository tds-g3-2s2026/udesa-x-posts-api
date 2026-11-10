import pytest

from posts_api.app.hashtags import extract_hashtags, hashtag_positions, hashtag_searched


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


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("#UdeSA", "udesa"),
        ("#café", "café"),
        ("#ab", "ab"),
        ("#udesa hola", None),
        ("hola #udesa", None),
        ("udesa", None),
        ("##udesa", None),
        ("#", None),
    ],
)
def test_only_a_query_that_is_a_single_hashtag_searches_by_hashtag(query, expected):
    assert hashtag_searched(query) == expected


def test_hashtag_positions_are_where_each_occurrence_starts():
    assert hashtag_positions("#UdeSA hoy, #tds y #udesa", "udesa") == [0, 19]
