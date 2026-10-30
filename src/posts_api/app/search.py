"""Literal search terms and compact highlighted excerpts."""

from dataclasses import dataclass

from posts_api.app.errors import ProblemError


@dataclass(frozen=True)
class SnippetSegment:
    text: str
    highlighted: bool


def normalize_query(value: str) -> str:
    query = value.strip()
    if len(query) < 3 or "\x00" in query:
        raise ProblemError(
            status=422,
            code="invalid-query",
            title="Búsqueda inválida",
            detail="Escribí al menos 3 caracteres",
        )
    return query


def snippet(content: str, query: str, match_positions: list[int]) -> list[SnippetSegment]:
    matches = [(position, position + len(query)) for position in match_positions]
    start = max(0, matches[0][0] - 40) if matches and len(content) > 160 else 0
    end = min(len(content), start + 160 - int(start > 0))
    if end < len(content):
        end -= 1
    segments: list[SnippetSegment] = []

    def append(text: str, highlighted: bool = False) -> None:
        if not text:
            return
        if segments and segments[-1].highlighted == highlighted:
            segments[-1] = SnippetSegment(segments[-1].text + text, highlighted)
        else:
            segments.append(SnippetSegment(text, highlighted))

    append("…" if start else "")
    position = start
    visible_matches: list[tuple[int, int]] = []
    for match_start, match_end in matches:
        left, right = max(start, match_start), min(end, match_end)
        if left >= right:
            continue
        if visible_matches and left <= visible_matches[-1][1]:
            visible_matches[-1] = (visible_matches[-1][0], max(visible_matches[-1][1], right))
        else:
            visible_matches.append((left, right))
    for left, right in visible_matches:
        append(content[position:left])
        append(content[left:right], True)
        position = right
    append(content[position:end])
    append("…" if end < len(content) else "")
    return segments
