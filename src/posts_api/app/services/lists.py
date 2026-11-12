"""The rules of the lists an account puts together (E3-H8).

A list is private to its owner and only holds accounts the owner follows. No
code here takes an account out of the lists when the follow ends: each
membership hangs from that follow and the database deletes it along with it
(see `ListMemberModel`).
"""

import uuid
from dataclasses import replace

from posts_api.app.errors import ProblemError
from posts_api.app.models.follow import Account
from posts_api.app.models.lists import AccountList, ListMember
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.lists import ListRepository

# Enough for what the screen is for, and a ceiling on what one account stores.
MAX_LISTS = 20
MAX_MEMBERS = 100
MAX_NAME_LENGTH = 50


def valid_name(name: str, *, title: str) -> str:
    """The name without surrounding spaces, refused when it is empty or too long."""
    clean = name.strip()
    if not clean:
        raise ProblemError(
            status=422, code="list-name-required", title=title, detail="La lista necesita un nombre"
        )
    if len(clean) > MAX_NAME_LENGTH:
        raise ProblemError(
            status=422,
            code="list-name-too-long",
            title=title,
            detail=f"El nombre puede tener hasta {MAX_NAME_LENGTH} caracteres",
        )
    return clean


class ListService:
    def __init__(self, lists: ListRepository, follows: FollowRepository) -> None:
        self._lists = lists
        self._follows = follows

    async def create(self, owner: Account, name: str) -> AccountList:
        title = "No se pudo crear la lista"
        clean = valid_name(name, title=title)
        await self._follows.ensure_profile(owner)
        await self._lists.lock_owner(owner.id)
        if await self._lists.count_owned(owner.id) >= MAX_LISTS:
            raise ProblemError(
                status=422,
                code="too-many-lists",
                title=title,
                detail=f"Podés tener hasta {MAX_LISTS} listas",
            )
        return await self._lists.create(owner.id, clean)

    async def lists_of(self, owner: Account) -> list[AccountList]:
        return await self._lists.owned_by(owner.id)

    async def rename(self, owner: Account, list_id: uuid.UUID, name: str) -> AccountList:
        title = "No se pudo renombrar la lista"
        clean = valid_name(name, title=title)
        found = await self._owned(owner, list_id, title=title)
        await self._lists.rename(list_id, clean)
        return replace(found, name=clean)

    async def delete(self, owner: Account, list_id: uuid.UUID) -> None:
        await self._owned(owner, list_id, title="No se pudo borrar la lista")
        await self._lists.delete(list_id)

    async def members(self, owner: Account, list_id: uuid.UUID) -> list[ListMember]:
        await self._owned(owner, list_id, title="No se pudo abrir la lista")
        return await self._lists.members(list_id)

    async def add_member(self, owner: Account, list_id: uuid.UUID, member_id: uuid.UUID) -> None:
        """Put an account in the list. Adding it twice is not an error and changes nothing."""
        title = "No se pudo sumar la cuenta a la lista"
        await self._owned(owner, list_id, title=title)
        if await self._follows.find_profile(member_id) is None:
            raise ProblemError(
                status=404,
                code="user-not-found",
                title=title,
                detail="La cuenta que querés sumar no existe",
            )
        # The membership hangs from the owner's follow, so the database would
        # refuse it anyway. Checked here to answer why instead of failing.
        if not await self._follows.is_following(owner.id, member_id):
            raise ProblemError(
                status=409,
                code="not-following",
                title=title,
                detail="Solo podés sumar cuentas que seguís",
            )

        await self._lists.lock(list_id)
        if await self._lists.is_member(list_id, member_id):
            return
        if await self._lists.count_members(list_id) >= MAX_MEMBERS:
            raise ProblemError(
                status=422,
                code="list-full",
                title=title,
                detail=f"Una lista puede tener hasta {MAX_MEMBERS} cuentas",
            )
        await self._lists.add_member(list_id, owner.id, member_id)

    async def remove_member(self, owner: Account, list_id: uuid.UUID, member_id: uuid.UUID) -> None:
        """Take an account out of the list. Taking out one that was not there changes nothing."""
        await self._owned(owner, list_id, title="No se pudo sacar la cuenta de la lista")
        await self._lists.remove_member(list_id, member_id)

    async def _owned(self, owner: Account, list_id: uuid.UUID, *, title: str) -> AccountList:
        found = await self._lists.find_owned(list_id, owner.id)
        if found is None:
            raise ProblemError(
                status=404, code="list-not-found", title=title, detail="La lista no existe"
            )
        return found
