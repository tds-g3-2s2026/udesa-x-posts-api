"""The rules of another user's profile screen (E2-H14)."""

import uuid

from posts_api.app.errors import ProblemError
from posts_api.app.models.follow import Account, ProfileVisibility, UserProfile
from posts_api.app.models.post import PostWithAuthor
from posts_api.app.models.profile import Profile
from posts_api.app.pagination import Cursor
from posts_api.app.repositories.blocks import BlockRepository
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.profile_posts import ProfilePostRepository
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
        self,
        follows: FollowRepository,
        blocks: BlockRepository,
        directory: UserDirectory,
        posts: ProfilePostRepository,
    ) -> None:
        self._follows = follows
        self._blocks = blocks
        self._directory = directory
        self._posts = posts

    async def profile_of(self, user_id: uuid.UUID, viewer: Account) -> Profile:
        """The header of `user_id`'s profile, as `viewer` gets to see it.

        A protected account the viewer does not follow still shows its header,
        with `is_private` set: CA.3 hides the posts, not the account. The
        posts themselves are refused by `posts_of`.

        users-api not having the account answers the same 404 as the graph
        not having it.
        """
        target = await self._visible_target(user_id, viewer)

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

    async def posts_of(
        self, user_id: uuid.UUID, viewer: Account, *, cursor: str | None = None
    ) -> tuple[list[PostWithAuthor], str | None]:
        """One page of `user_id`'s posts, newest first.

        A protected account the viewer does not follow answers 403 and not an
        empty page: the screen has to say the account is private, not that it
        never posted.
        """
        target = await self._visible_target(user_id, viewer)

        if (
            target.visibility is ProfileVisibility.PROTECTED
            and viewer.id != user_id
            and not await self._follows.is_following(viewer.id, user_id)
        ):
            raise ProblemError(
                status=403,
                code="account-is-private",
                title="No se pudieron obtener las publicaciones",
                detail="Esta cuenta es protegida y no la seguís",
            )

        decoded = Cursor.decode(cursor) if cursor is not None else None
        return await self._posts.by_author(user_id, viewer.id, cursor=decoded)

    async def _visible_target(self, user_id: uuid.UUID, viewer: Account) -> UserProfile:
        """The account behind the profile, or the 404 both endpoints share.

        Opening a profile puts the viewer on the graph, the same bootstrap the
        followers and following screens do. A block in either direction
        answers the same 404 as an account that does not exist, as
        `visible_to` does for posts, so the response cannot be read as
        confirmation of the block.
        """
        await self._follows.ensure_profile(viewer)

        target = await self._follows.find_profile(user_id)
        if target is None or await self._blocked_either_way(user_id, viewer.id):
            raise profile_not_found()
        return target

    async def _blocked_either_way(self, user_id: uuid.UUID, viewer_id: uuid.UUID) -> bool:
        return await self._blocks.has_blocked(user_id, viewer_id) or await self._blocks.has_blocked(
            viewer_id, user_id
        )
