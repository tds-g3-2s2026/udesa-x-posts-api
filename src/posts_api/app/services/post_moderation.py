"""What an administrator does with posts (E5-H10): read them and clear their content.

Reading skips the visibility rules on purpose: the backoffice has to see every
post, also those of protected accounts.

When the content is cleared, the text becomes the placeholder and the images
go with it: an image can be what breaks the rules. The post itself stays, with
its likes, retweets and replies, so a conversation does not lose its thread.
Who did it goes to users-api's audit through the outbox, the same way the
reports do (ADR-020).

No FastAPI and no SQLAlchemy here, the same shape `ReportCaseService` uses.
"""

import uuid
from datetime import UTC, datetime

from posts_api.app.errors import ProblemError
from posts_api.app.events import post_content_cleaned
from posts_api.app.models.post import PostWithAuthor
from posts_api.app.pagination import Cursor
from posts_api.app.repositories.administrator_directory import (
    AdministratorDirectory,
    AdministratorDirectoryUnavailableError,
)
from posts_api.app.repositories.outbox import OutboxRepository
from posts_api.app.repositories.posts import PostRepository
from posts_api.app.services.post_images import PostImages

REMOVED_BY_MODERATION = "[Contenido eliminado por moderación]"
TITLE = "No se pudo limpiar la publicación"


def post_not_found(title: str) -> ProblemError:
    return ProblemError(
        status=404, code="post-not-found", title=title, detail="La publicación no existe"
    )


class PostModerationService:
    def __init__(
        self,
        posts: PostRepository,
        images: PostImages,
        administrators: AdministratorDirectory,
        outbox: OutboxRepository,
    ) -> None:
        self._posts = posts
        self._images = images
        self._administrators = administrators
        self._outbox = outbox

    async def post(self, post_id: uuid.UUID) -> PostWithAuthor:
        """One post with its images, whoever wrote it. A deleted one answers 404."""
        found = await self._posts.find_for_moderation(post_id)
        if found is None:
            raise post_not_found("No se encontró la publicación")
        return (await self._images.attach([found]))[0]

    async def posts_of(
        self, author_id: uuid.UUID, *, cursor: str | None = None
    ) -> tuple[list[PostWithAuthor], str | None]:
        """What the account wrote, replies included, newest first, one page at a time.

        An account with nothing, or one this service never heard of, answers an
        empty page: the detail of the account already says whether it exists.
        """
        decoded = Cursor.decode(cursor) if cursor is not None else None
        posts, next_cursor = await self._posts.by_author_for_moderation(author_id, cursor=decoded)
        return await self._images.attach(posts), next_cursor

    async def clean(self, administrator_id: uuid.UUID, post_id: uuid.UUID) -> None:
        """Replace the text with the placeholder and take the images off.

        A post already cleaned answers the same and leaves nothing new in the
        audit. Runs inside the request's transaction, with the post locked, so
        two administrators at once record it only once.
        """
        post = await self._posts.lock_for_moderation(post_id)
        if post is None:
            raise post_not_found(TITLE)
        # Asked before changing anything: without the email there is no audit,
        # and the post stays as it was for the administrator to try again.
        try:
            actor_email = await self._administrators.email_of(administrator_id)
        except AdministratorDirectoryUnavailableError as error:
            raise ProblemError(
                status=503,
                code="users-api-unavailable",
                title=TITLE,
                detail="No se pudo obtener la identidad del administrador. Probá de nuevo",
            ) from error

        had_images = await self._images.remove(post_id)
        # Checked after the images: someone could write the placeholder
        # themselves to keep an image out of reach.
        if post.content == REMOVED_BY_MODERATION and not had_images:
            return
        await self._posts.replace_content(post_id, REMOVED_BY_MODERATION)
        await self._outbox.add(
            post_content_cleaned(
                administrator_id, actor_email, post_id, post.author_id, now=datetime.now(UTC)
            )
        )
