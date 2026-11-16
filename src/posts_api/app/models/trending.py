"""What a trending topic is, in plain Python."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TrendingTopic:
    """A hashtag and how many posts of the window carry it."""

    tag: str
    count: int
