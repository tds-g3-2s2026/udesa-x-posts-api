"""The rules of publishing a post, and of reading one and its replies.

No FastAPI and no SQLAlchemy here on purpose, the same shape `FollowService`
uses: the service receives its repositories and raises `ProblemError`, so the
rules can be read, tested and defended without starting the application.
"""

import re
import uuid
from datetime import datetime

from posts_api.app.errors import ProblemError
from posts_api.app.models.follow import Account
from posts_api.app.models.post import Post, PostWithAuthor
from posts_api.app.pagination import Cursor
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.likes import LikeRepository
from posts_api.app.repositories.posts import PostRepository
from posts_api.app.repositories.rate_limiter import RateLimiter
from posts_api.app.repositories.retweets import RetweetRepository

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


def post_not_found() -> ProblemError:
    """The `404` for a post that does not exist and for one the viewer cannot read.

    One function so every endpoint that looks a post up answers with exactly the
    same body: a difference between two of them would tell a caller which posts
    exist behind a block or a protected account.
    """
    return ProblemError(
        status=404,
        code="post-not-found",
        title="No se pudo obtener el post",
        detail="El post no existe",
    )


class PostService:
    def __init__(
        self,
        posts: PostRepository,
        follows: FollowRepository,
        rate_limiter: RateLimiter,
        likes: LikeRepository,
        retweets: RetweetRepository,
        *,
        post_limit: int,
        window_seconds: int,
    ) -> None:
        self._likes = likes
        self._retweets = retweets
        self._posts = posts
        self._follows = follows
        self._rate_limiter = rate_limiter
        self._post_limit = post_limit
        self._window_seconds = window_seconds

    async def create(
        self, author: Account, content: str, *, parent_id: uuid.UUID | None = None
    ) -> Post:
        """Publish a post, or refuse it and say exactly which rule stopped it.

        A reply goes through the same checks as any post, and through the same
        rate limit counter: answering is publishing, and a second counter would
        let somebody double their quota by alternating the two.
        """
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

        if parent_id is None:
            return await self._posts.create(author.id, sanitized)

        # The parent is looked up as the author, with the visibility rule on:
        # one they cannot read is answered exactly like one that does not exist.
        parent = await self._posts.lock_visible(parent_id, viewer_id=author.id)
        if parent is None:
            raise post_not_found()
        if parent.deleted:
            raise ProblemError(
                status=409,
                code="post-deleted",
                title="No se pudo responder",
                detail="Esta publicación fue eliminada.",
            )
        reply = await self._posts.create(author.id, sanitized, parent_id=parent_id)
        # Same transaction as the insert: either both land or neither does.
        await self._posts.count_reply(parent_id)
        return reply

    async def delete(self, post_id: uuid.UUID, viewer: Account) -> None:
        post = await self._posts.lock_visible(post_id, viewer_id=viewer.id)
        if post is None:
            raise post_not_found()
        if post.author_id != viewer.id:
            raise ProblemError(
                status=403,
                code="post-author-required",
                title="No se pudo eliminar la publicación",
                detail="Solo el autor puede eliminar la publicación.",
            )
        if post.deleted:
            return
        await self._likes.remove_for_post(post_id)
        await self._retweets.remove_for_post(post_id)
        await self._posts.mark_deleted(post_id)

    async def get(self, post_id: uuid.UUID, viewer: Account) -> PostWithAuthor:
        """A single post, or `404` if it does not exist or the viewer cannot see it.

        Both cases answer the same way and for the same reason `FollowRequestService`
        already uses for a request aimed at somebody else: telling them apart
        would confirm that a protected account's post exists, which is exactly
        what the visibility rule exists to keep from leaking.
        """
        return await self._visible_post(post_id, viewer.id)

    async def replies_to(
        self, post_id: uuid.UUID, viewer: Account, *, cursor: str | None = None
    ) -> tuple[list[PostWithAuthor], str | None]:
        """The replies to a post, or the same `404` as the post itself.

        The parent is checked first: listing the replies of a post the viewer
        cannot read would otherwise be a way to find out that it exists.
        """
        await self._visible_post(post_id, viewer.id)
        decoded = Cursor.decode(cursor) if cursor is not None else None
        return await self._posts.replies_to(post_id, viewer_id=viewer.id, cursor=decoded)

    async def _visible_post(self, post_id: uuid.UUID, viewer_id: uuid.UUID) -> PostWithAuthor:
        post = await self._posts.find_visible(post_id, viewer_id=viewer_id, include_deleted=True)
        if post is None:
            raise post_not_found()
        return post

    async def count_published_since(self, since: datetime) -> int:
        """How many posts were published from `since` on, for the backoffice."""
        return await self._posts.count_created_since(since)

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
