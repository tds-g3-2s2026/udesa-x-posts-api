"""The profile photo and the cover of an account.

The files go to the same bucket as the images of the posts, through the same
storage, with the limits of their kind. The profile keeps only where each one
is; the URL is signed on every read.
"""

import logging
import uuid
from dataclasses import dataclass

from posts_api.app.image_rules import (
    PROFILE_TITLE,
    IncomingImage,
    ProfileImageKind,
    detect_format,
    image_format_not_supported,
    image_too_large,
)
from posts_api.app.models.follow import Account, UserProfile
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.image_storage import (
    ImageStorage,
    ImageStorageError,
    signed_url_or_none,
)
from posts_api.app.repositories.profile_images import ProfileImageRepository
from posts_api.app.services.post_images import images_unavailable

logger = logging.getLogger(__name__)

KEY_PREFIX = "profiles"


@dataclass(frozen=True)
class ProfileImageChange:
    """What a replacement left: the URL of the new file and the key of the one it replaced."""

    url: str
    previous_key: str | None


class ProfileImages:
    def __init__(
        self, keys: ProfileImageRepository, follows: FollowRepository, storage: ImageStorage
    ) -> None:
        self._keys = keys
        self._follows = follows
        self._storage = storage

    async def replace(
        self, owner: Account, kind: ProfileImageKind, image: IncomingImage
    ) -> ProfileImageChange:
        """Upload the file and point the profile at it, in the caller's transaction.

        The previous file is not deleted here: the caller deletes it with
        `discard` once the transaction is committed. Deleting it first would
        leave the profile pointing at nothing if the commit failed.
        """
        if image.size > kind.max_bytes:
            raise image_too_large(kind.too_large_detail, title=PROFILE_TITLE)
        # By the first bytes, not by the name or the declared type.
        found = detect_format(image.header())
        if found is None:
            raise image_format_not_supported(title=PROFILE_TITLE)

        await self._follows.ensure_profile(owner)
        key = f"{KEY_PREFIX}/{owner.id}/{kind.name}/{uuid.uuid4().hex}.{found.extension}"
        # Uploaded before the row is locked: the lock is held until the commit,
        # and a 10 MB upload should not keep the profile locked that long.
        image.data.seek(0)
        try:
            await self._storage.put(key, image.data, content_type=found.mime_type)
        except ImageStorageError as exc:
            raise images_unavailable() from exc

        try:
            previous = await self._keys.lock_key(owner.id, kind)
            await self._keys.set_key(owner.id, kind, key)
            url = await self._storage.url_for(key)
        except Exception as exc:
            # The row change is rolled back with the request; the file would stay.
            await self.discard(key)
            if isinstance(exc, ImageStorageError):
                raise images_unavailable() from exc
            raise
        return ProfileImageChange(url=url, previous_key=previous)

    async def remove(self, owner: Account, kind: ProfileImageKind) -> str | None:
        """Take the image off the profile and say which file it was, for `discard`.

        Removing one that is not there is not an error: the profile is already
        in the state that was asked for.
        """
        previous = await self._keys.lock_key(owner.id, kind)
        if previous is not None:
            await self._keys.set_key(owner.id, kind, None)
        return previous

    async def discard(self, key: str | None) -> None:
        """Delete a file the profile no longer points at.

        Best effort: the profile already changed, so a bucket that fails here
        leaves a loose file behind, not a broken profile.
        """
        if key is None:
            return
        try:
            await self._storage.delete(key)
        except ImageStorageError:
            logger.warning("Could not delete %s from the bucket; the file stays there", key)

    async def urls_of(self, profile: UserProfile) -> tuple[str | None, str | None]:
        """The signed URLs of the photo and the cover, `None` for the ones it does not have."""
        return (
            await signed_url_or_none(self._storage, profile.avatar_key),
            await signed_url_or_none(self._storage, profile.cover_key),
        )
