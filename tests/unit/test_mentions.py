import pytest

from posts_api.app.mentions import extract_mentions


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hola @JuanPerez y @maria_01", ("juanperez", "maria_01")),
        ("@Ana_X, @ANA_X y @ana_x", ("ana_x",)),
        ("(@fulano) y @mengano.", ("fulano", "mengano")),
        ("@abcd", ("abcd",)),
        ("@abcdefghijklmno", ("abcdefghijklmno",)),
        ("sin menciones", ()),
        ("@abc es muy corto", ()),
        ("@abcdefghijklmnop es muy largo", ()),
        ("ana@udesa.edu.ar no es una mención", ()),
        ("@@doble tampoco", ()),
        ("@ solo, y @", ()),
        ("@juán tiene una letra que no es de un handle", ()),
        ("@usuario_ñ tampoco", ()),
    ],
)
def test_mentions_are_distinct_lowercase_and_in_order_of_appearance(text, expected):
    assert extract_mentions(text) == expected
