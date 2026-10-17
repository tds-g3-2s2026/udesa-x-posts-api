"""The rules of another user's profile screen (E2-H14)."""

import uuid

from posts_api.app.errors import ProblemError
from posts_api.app.models.follow import Account, ProfileVisibility
from posts_api.app.models.profile import Profile
from posts_api.app.repositories.blocks import BlockRepository
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.user_directory import UserDirectory, UserDirectoryUnavailableError


def profile_not_found() -> ProblemError:
    return ProblemError(
        status=404,
        code="user-not-found",
        title="No se pudo obtener el perfil",
        detail="La cuenta no existe",
    )


class ProfileService:
    def __init__(
        self, follows: FollowRepository, blocks: BlockRepository, directory: UserDirectory
    ) -> None:
        self._follows = follows
        self._blocks = blocks
        self._directory = directory

    async def profile_of(self, user_id: uuid.UUID, viewer: Account) -> Profile:
        """The header of `user_id`'s profile, as `viewer` gets to see it.

        A protected account the viewer does not follow still shows its header,
        with `is_private` set: CA.3 hides the posts, not the account. The
        posts themselves are refused by their listing, not here.

        A block in either direction answers the same 404 as an account that
        does not exist, as `visible_to` does for posts, so the response cannot
        be read as confirmation of the block. So does an account users-api no
        longer has.
        """
        # Opening a profile puts the viewer on the graph, the same bootstrap
        # the followers and following screens do.
        await self._follows.ensure_profile(viewer)

        target = await self._follows.find_profile(user_id)
        if target is None or await self._blocked_either_way(user_id, viewer.id):
            raise profile_not_found()

        try:
            details = await self._directory.details_of(user_id)
        except UserDirectoryUnavailableError:
            # The local half is still worth showing: the handle, the counters
            # and the follow button work without users-api.
            details = None
        else:
            if details is None:
                raise profile_not_found()

        return Profile(
            id=target.id,
            handle=target.handle,
            is_private=target.visibility is ProfileVisibility.PROTECTED,
            followers_count=target.followers_count,
            following_count=target.following_count,
            followed_by_viewer=await self._follows.is_following(viewer.id, user_id),
            details=details,
        )

    async def _blocked_either_way(self, user_id: uuid.UUID, viewer_id: uuid.UUID) -> bool:
        return await self._blocks.has_blocked(user_id, viewer_id) or await self._blocks.has_blocked(
            viewer_id, user_id
        )
