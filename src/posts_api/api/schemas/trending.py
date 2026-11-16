"""One entry of the trending ranking on the wire."""

from pydantic import BaseModel

from posts_api.app.models.trending import TrendingTopic


class TrendingTopicResponse(BaseModel):
    tag: str
    count: int

    @classmethod
    def of(cls, topic: TrendingTopic) -> "TrendingTopicResponse":
        return cls(tag=topic.tag, count=topic.count)
