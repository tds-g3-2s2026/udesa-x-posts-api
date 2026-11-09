"""Which hashtags a post's text carries."""

import re

MAX_HASHTAGS = 10

# A `#` that starts a word: not glued to a previous word character (`a#b`) and
# not the second of a pair (`##b`). `\w` is Unicode-aware, so `#café` and `#ñandú`
# are hashtags, and so is `#123`.
_HASHTAG = re.compile(r"(?<![\w#])#(\w+)")


def extract_hashtags(text: str) -> tuple[str, ...]:
    """The distinct hashtags of the text, lower-cased, without the `#`, in order of appearance."""
    found = (match.lower() for match in _HASHTAG.findall(text))
    return tuple(dict.fromkeys(found))
