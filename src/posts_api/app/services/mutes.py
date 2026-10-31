"""The rules of muting another account.

Muting only changes what the muter sees. It touches no follow and writes no
event, so the muted account has no way to find out.
"""

import uuid

from posts_api.app.errors import ProblemError
from posts_api.app.models.follow import Account, MutedAccount
from posts_api.app.pagination import Cursor
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.mutes import MuteRepository


class MuteService:
    def __init__(self, mutes: MuteRepository, follows: FollowRepository) -> None:
        self._mutes = mutes
        self._follows = follows

    async def mute(self, muter: Account, muted_id: uuid.UUID) -> None:
        """Mute the account. Muting twice is not an error and changes nothing."""
        if muter.id == muted_id:
            raise ProblemError(
                status=409,
                code="cannot-mute-yourself",
                title="No se pudo silenciar la cuenta",
                detail="No podés silenciarte a vos mismo",
            )

        await self._follows.ensure_profile(muter)
        if await self._follows.find_profile(muted_id) is None:
            raise ProblemError(
                status=404,
                code="user-not-found",
                title="No se pudo silenciar la cuenta",
                detail="La cuenta que querés silenciar no existe",
            )

        await self._mutes.add(muter.id, muted_id)

    async def unmute(self, muter: Account, muted_id: uuid.UUID) -> None:
        """Lift the mute. Unmuting an account that was not muted changes nothing."""
        await self._mutes.remove(muter.id, muted_id)

    async def muted_by(
        self, owner: Account, *, cursor: str | None = None
    ) -> tuple[list[MutedAccount], str | None]:
        await self._follows.ensure_profile(owner)
        decoded = Cursor.decode(cursor) if cursor is not None else None
        return await self._mutes.muted_by(owner.id, cursor=decoded)
