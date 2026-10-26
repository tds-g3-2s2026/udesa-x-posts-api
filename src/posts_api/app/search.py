"""Literal search terms and compact highlighted excerpts."""

import re
from dataclasses import dataclass

from posts_api.app.errors import ProblemError


@dataclass(frozen=True)
class SnippetSegment:
    text: str
    highlighted: bool


def normalize_query(value: str) -> str:
    query = value.strip()
    if len(query) < 3:
        raise ProblemError(
            status=422,
            code="invalid-query",
            title="Búsqueda inválida",
            detail="Escribí al menos 3 caracteres",
        )
    return query


def snippet(content: str, query: str) -> list[SnippetSegment]:
    matches = list(re.finditer(re.escape(query), content, re.IGNORECASE))
    start = max(0, matches[0].start() - 40) if matches and len(content) > 160 else 0
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
    for match in matches:
        left, right = max(start, match.start()), min(end, match.end())
        if left >= right:
            continue
        append(content[position:left])
        append(content[left:right], True)
        position = right
    append(content[position:end])
    append("…" if end < len(content) else "")
    return segments
