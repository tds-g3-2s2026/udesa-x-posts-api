"""An administrator clearing the content of a post (E5-H10).

The text becomes the placeholder and the images go with it: an image can be
what breaks the rules. The post itself stays, with its likes, retweets and
replies, so a conversation does not lose its thread. Who did it goes to
users-api's audit through the outbox, the same way the reports do (ADR-020).

No FastAPI and no SQLAlchemy here, the same shape `ReportCaseService` uses.
"""

import uuid
from datetime import UTC, datetime

from posts_api.app.errors import ProblemError
from posts_api.app.events import post_content_cleaned
from posts_api.app.repositories.administrator_directory import (
    AdministratorDirectory,
    AdministratorDirectoryUnavailableError,
)
from posts_api.app.repositories.outbox import OutboxRepository
from posts_api.app.repositories.posts import PostRepository
from posts_api.app.services.post_images import PostImages

REMOVED_BY_MODERATION = "[Contenido eliminado por moderación]"
TITLE = "No se pudo limpiar la publicación"


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

    async def clean(self, administrator_id: uuid.UUID, post_id: uuid.UUID) -> None:
        """Replace the text with the placeholder and take the images off.

        A post already cleaned answers the same and leaves nothing new in the
        audit. Runs inside the request's transaction, with the post locked, so
        two administrators at once record it only once.
        """
        post = await self._posts.lock_for_moderation(post_id)
        if post is None:
            raise ProblemError(
                status=404,
                code="post-not-found",
                title=TITLE,
                detail="La publicación no existe",
            )
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
