"""The rules of publishing a post.

No FastAPI and no SQLAlchemy here on purpose, the same shape `FollowService`
uses: the service receives its repositories and raises `ProblemError`, so the
rules can be read, tested and defended without starting the application.
"""

import re
import uuid

from posts_api.app.errors import ProblemError
from posts_api.app.models.follow import Account
from posts_api.app.models.post import Post, PostWithAuthor
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.posts import PostRepository
from posts_api.app.repositories.rate_limiter import RateLimiter

MAX_CONTENT_LENGTH = 280

# Its own prefix so the counter cannot collide with the one follows uses on
# the same Redis.
RATE_LIMIT_KEY = "post:rate:{user_id}"

# Anything between angle brackets, tag or not: a post is never rendered as
# HTML by a client that follows the contract, so there is no case where a real
# `<` belongs in the stored content either.
_TAG = re.compile(r"<[^>]*>")


def _strip_tags(content: str) -> str:
    """Remove every HTML tag, scripts included, before the content is stored.

    This runs here and not only in the app: the endpoint is public, and anyone
    can call it directly, skipping whatever the app would have sanitized on
    its side. The tag is gone before the content ever reaches the database, so
    there is nothing left for a careless renderer downstream to execute.
    """
    return _TAG.sub("", content)


class PostService:
    def __init__(
        self,
        posts: PostRepository,
        follows: FollowRepository,
        rate_limiter: RateLimiter,
        *,
        post_limit: int,
        window_seconds: int,
    ) -> None:
        self._posts = posts
        self._follows = follows
        self._rate_limiter = rate_limiter
        self._post_limit = post_limit
        self._window_seconds = window_seconds

    async def create(self, author: Account, content: str) -> Post:
        """Publish a post, or refuse it and say exactly which rule stopped it."""
        await self._charge_the_rate_limit(author.id)
        await self._follows.ensure_profile(author)

        # Measured after stripping tags, not before: the length limit caps the
        # text of the post, and markup an attacker stuffed in to inflate the
        # count past it was never part of the text to begin with.
        sanitized = _strip_tags(content).strip()

        if not sanitized:
            raise ProblemError(
                status=422,
                code="post-is-blank",
                title="No se pudo publicar el post",
                detail="El post no puede estar vacío",
            )
        if len(sanitized) > MAX_CONTENT_LENGTH:
            raise ProblemError(
                status=422,
                code="post-too-long",
                title="No se pudo publicar el post",
                detail=f"El post no puede superar los {MAX_CONTENT_LENGTH} caracteres",
            )

        return await self._posts.create(author.id, sanitized)

    async def get(self, post_id: uuid.UUID, viewer: Account) -> PostWithAuthor:
        """A single post, or `404` if it does not exist or the viewer cannot see it.

        Both cases answer the same way and for the same reason `FollowRequestService`
        already uses for a request aimed at somebody else: telling them apart
        would confirm that a protected account's post exists, which is exactly
        what the visibility rule exists to keep from leaking.
        """
        post = await self._posts.find_visible(post_id, viewer_id=viewer.id)
        if post is None:
            raise ProblemError(
                status=404,
                code="post-not-found",
                title="No se pudo obtener el post",
                detail="El post no existe",
            )
        return post

    async def _charge_the_rate_limit(self, author_id: uuid.UUID) -> None:
        """Count the attempt before anything else runs.

        A limit that only applies after the content was already validated and
        the database already touched does not protect anything: same
        reasoning `FollowService` uses for follow attempts.
        """
        key = RATE_LIMIT_KEY.format(user_id=author_id)
        attempts = await self._rate_limiter.hit(key, window_seconds=self._window_seconds)
        if attempts <= self._post_limit:
            return

        seconds_left = await self._rate_limiter.seconds_left(key)
        raise ProblemError(
            status=429,
            code="too-many-posts",
            title="Demasiados posts",
            detail=f"Alcanzaste el límite de {self._post_limit} por hora. Probá más tarde.",
            headers={"Retry-After": str(seconds_left)},
        )
