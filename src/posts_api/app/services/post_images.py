"""Storing the images of a post, and putting them back on the posts that are read.

Both halves live together because both need the same pair of collaborators: the
rows that say which files belong to which post, and the storage that holds them.
"""

import uuid
from collections.abc import Sequence
from dataclasses import replace

from posts_api.app.errors import ProblemError
from posts_api.app.image_rules import ImageFormat, IncomingImage
from posts_api.app.models.post import PostImage, PostWithAuthor
from posts_api.app.repositories.image_storage import ImageStorage, ImageStorageError
from posts_api.app.repositories.post_media import NewMedia, PostMediaRepository, StoredMedia

KEY_PREFIX = "posts"


def images_unavailable() -> ProblemError:
    return ProblemError(
        status=503,
        code="images-unavailable",
        title="No se pudieron procesar las imágenes",
        detail="No pudimos guardar o leer las imágenes en este momento. Probá de nuevo más tarde.",
    )


class PostImages:
    def __init__(self, media: PostMediaRepository, storage: ImageStorage) -> None:
        self._media = media
        self._storage = storage

    async def save(
        self,
        post_id: uuid.UUID,
        images: Sequence[IncomingImage],
        formats: Sequence[ImageFormat],
    ) -> tuple[PostImage, ...]:
        """Upload the files and record them against the post.

        The upload goes first and the rows second, in the caller's transaction.
        If anything fails after some files are already up, those are deleted
        again so a refused post does not leave files behind.
        """
        uploaded: list[str] = []
        try:
            media = []
            for image, kind in zip(images, formats, strict=True):
                key = f"{KEY_PREFIX}/{post_id}/{uuid.uuid4().hex}.{kind.extension}"
                image.data.seek(0)
                await self._storage.put(key, image.data, content_type=kind.mime_type)
                uploaded.append(key)
                media.append(NewMedia(key, kind.mime_type, image.size))
            stored = await self._media.add(post_id, media)
            return await self._present(stored)
        except Exception as exc:
            await self._discard(uploaded)
            if isinstance(exc, ImageStorageError):
                raise images_unavailable() from exc
            raise

    async def attach(self, posts: list[PostWithAuthor]) -> list[PostWithAuthor]:
        """The same posts with their images, read with one query for the whole page.

        A deleted post keeps its rows but shows none: the files stay where they
        are, the post just no longer says it had them.
        """
        live = {one.id for one in posts if not one.deleted}
        if not live:
            return posts
        stored = await self._media.for_posts(live)
        if not stored:
            return posts
        attached = []
        for post in posts:
            rows = stored.get(post.id)
            if rows is None or post.deleted:
                attached.append(post)
            else:
                attached.append(replace(post, images=await self._present(rows)))
        return attached

    async def _present(self, rows: Sequence[StoredMedia]) -> tuple[PostImage, ...]:
        try:
            return tuple(
                [
                    PostImage(
                        id=row.id, url=await self._storage.url_for(row.key), position=row.position
                    )
                    for row in rows
                ]
            )
        except ImageStorageError as exc:
            raise images_unavailable() from exc

    async def _discard(self, keys: Sequence[str]) -> None:
        for key in keys:
            try:
                await self._storage.delete(key)
            except ImageStorageError:
                # Best effort: the original failure is the one worth reporting.
                continue
