"""Which hashtags a post's text carries, and when a search is for one."""

import re

MAX_HASHTAGS = 10

# A `#` that starts a word: not glued to a previous word character (`a#b`) and
# not the second of a pair (`##b`). `\w` is Unicode-aware, so `#café` and `#ñandú`
# are hashtags, and so is `#123`.
_HASHTAG = re.compile(r"(?<![\w#])#(\w+)")
_WHOLE_HASHTAG = re.compile(r"#(\w+)")


def extract_hashtags(text: str) -> tuple[str, ...]:
    """The distinct hashtags of the text, lower-cased, without the `#`, in order of appearance."""
    found = (match.lower() for match in _HASHTAG.findall(text))
    return tuple(dict.fromkeys(found))


def hashtag_searched(query: str) -> str | None:
    """The hashtag a search is for, when the whole query is a single one.

    `#udesa hola` is not: mixing a hashtag with words is a text search.
    """
    match = _WHOLE_HASHTAG.fullmatch(query)
    return match.group(1).lower() if match else None


def hashtag_positions(text: str, hashtag: str) -> list[int]:
    """Where each occurrence of the hashtag starts in the text, `#` included."""
    return [match.start() for match in _HASHTAG.finditer(text) if match.group(1).lower() == hashtag]
