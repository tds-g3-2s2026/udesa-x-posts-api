"""Which accounts a post's text mentions."""

import re
import uuid
from dataclasses import dataclass

MAX_MENTIONS = 10

# An `@` that starts a word: not glued to a previous word character (`ana@udesa.edu`)
# and not the second of a pair (`@@ana`). Then what users-api accepts as a handle, 4 to
# 15 letters, digits or underscores. The lookahead keeps a longer word from matching
# by its first 15 characters: `@abcdefghijklmnopq` mentions nobody.
_MENTION = re.compile(r"(?<![\w@])@([A-Za-z0-9_]{4,15})(?!\w)")


@dataclass(frozen=True)
class Mention:
    """An account that exists and that a post mentions."""

    id: uuid.UUID
    # Without the `@`, as the app compares it against the words of the text.
    handle: str


def extract_mentions(text: str) -> tuple[str, ...]:
    """The distinct handles of the text, lower-cased, without the `@`, in order of appearance.

    Only what is written: whether an account has that handle is for the repository to say.
    """
    found = (match.lower() for match in _MENTION.findall(text))
    return tuple(dict.fromkeys(found))
