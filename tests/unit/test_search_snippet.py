import pytest

from posts_api.app.errors import ProblemError
from posts_api.app.search import normalize_query, snippet


@pytest.mark.parametrize(
    "content,query",
    [
        ("Estudiar en UDESA con Udesa", "udesa"),
        ("á🙂" * 90 + "universidad" + "🙂" * 100, "universidad"),
        ("literal %_\\ no patrón", "%_\\"),
        ("x" * 280, "x" * 200),
    ],
)
def test_e2_h10_ca3_snippet_highlights_within_160_unicode_characters(content, query):
    parts = snippet(content, query)
    assert len("".join(part.text for part in parts)) <= 160
    assert any(part.highlighted for part in parts)
    assert all(part.text for part in parts)


@pytest.mark.parametrize("query", ["", "ab", "  ab  ", "abc\x00def"])
def test_e2_h10_ca1_query_rejects_short_or_unusable_values(query):
    with pytest.raises(ProblemError):
        normalize_query(query)


def test_e2_h10_ca3_repeated_matches_beyond_the_excerpt_are_omitted():
    content = "UdeSA " * 44 + "final"

    parts = snippet(content, "udesa")
    rendered = "".join(part.text for part in parts)

    assert len(rendered) == 160
    assert rendered.endswith("…")
    assert "final" not in rendered
    assert sum(part.highlighted for part in parts) > 1
    assert all("udesa".startswith(part.text.lower()) for part in parts if part.highlighted)
