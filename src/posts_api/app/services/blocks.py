"""The rules of blocking another account.

No FastAPI and no SQLAlchemy here, the same shape `FollowService` uses.
"""

import uuid

from posts_api.app.errors import ProblemError
from posts_api.app.models.follow import Account, BlockedAccount
from posts_api.app.pagination import Cursor
from posts_api.app.repositories.blocks import BlockRepository
from posts_api.app.repositories.follow_requests import FollowRequestRepository
from posts_api.app.repositories.follows import FollowRepository


class BlockService:
    def __init__(
        self,
        blocks: BlockRepository,
        follows: FollowRepository,
        requests: FollowRequestRepository,
    ) -> None:
        self._blocks = blocks
        self._follows = follows
        self._requests = requests

    async def block(self, blocker: Account, blocked_id: uuid.UUID) -> None:
        """Block the account and tear down everything that connected the two.

        Blocking twice is not an error, the same as following twice: the
        second call finds the block already there and changes nothing.
        """
        if blocker.id == blocked_id:
            raise ProblemError(
                status=409,
                code="cannot-block-yourself",
                title="No se pudo bloquear la cuenta",
                detail="No podés bloquearte a vos mismo",
            )

        await self._follows.ensure_profile(blocker)
        if await self._follows.find_profile(blocked_id) is None:
            raise ProblemError(
                status=404,
                code="user-not-found",
                title="No se pudo bloquear la cuenta",
                detail="La cuenta que querés bloquear no existe",
            )

        if not await self._blocks.add(blocker.id, blocked_id):
            return

        # Both directions: whoever blocks stops following and stops being
        # followed. Each removed relationship moves its own two counters, in
        # the same transaction as the block.
        for follower_id, followee_id in ((blocker.id, blocked_id), (blocked_id, blocker.id)):
            if await self._follows.remove_follow(follower_id, followee_id):
                await self._follows.move_counters(follower_id, followee_id, by=-1)
            # A request left open would be approved later and rebuild the very
            # relationship the block just removed.
            await self._requests.cancel(follower_id, followee_id)

    async def unblock(self, blocker: Account, blocked_id: uuid.UUID) -> None:
        """Lift the block. What it tore down stays torn down.

        The follows were removed on purpose, and bringing them back would decide
        on the user's behalf who they follow again.
        """
        await self._blocks.remove(blocker.id, blocked_id)

    async def blocked_by(
        self, owner: Account, *, cursor: str | None = None
    ) -> tuple[list[BlockedAccount], str | None]:
        await self._follows.ensure_profile(owner)
        decoded = Cursor.decode(cursor) if cursor is not None else None
        return await self._blocks.blocked_by(owner.id, cursor=decoded)
