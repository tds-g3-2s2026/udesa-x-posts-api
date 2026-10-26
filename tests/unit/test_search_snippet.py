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


@pytest.mark.parametrize("query", ["", "ab", "  ab  "])
def test_e2_h10_ca1_query_requires_three_trimmed_characters(query):
    with pytest.raises(ProblemError):
        normalize_query(query)
