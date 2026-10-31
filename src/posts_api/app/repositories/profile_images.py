"""Where each account's profile photo and cover are in the bucket, on its profile row."""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from posts_api.app.image_rules import AVATAR, COVER, ProfileImageKind
from posts_api.infrastructure.database.models import UserProfileModel

_COLUMNS: dict[ProfileImageKind, InstrumentedAttribute] = {
    AVATAR: UserProfileModel.avatar_key,
    COVER: UserProfileModel.cover_key,
}


class ProfileImageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_key(self, user_id: uuid.UUID, kind: ProfileImageKind) -> str | None:
        """The current key, with the row locked until the transaction ends.

        Two uploads of the same account land one after the other: the second
        reads the key the first one wrote, so it is the one that gets replaced
        and no file is left without a row pointing at it.
        """
        return await self._session.scalar(
            select(_COLUMNS[kind]).where(UserProfileModel.id == user_id).with_for_update()
        )

    async def set_key(self, user_id: uuid.UUID, kind: ProfileImageKind, key: str | None) -> None:
        await self._session.execute(
            update(UserProfileModel)
            .where(UserProfileModel.id == user_id)
            .values({_COLUMNS[kind].key: key})
        )
