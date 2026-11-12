"""The lists an account puts together, and the accounts in them (E3-H8).

Every route acts on the caller's own lists: a list made by someone else answers
404, the same as one that does not exist.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from posts_api.api.deps import CurrentUserDep, SessionDep
from posts_api.app.models.lists import AccountList, ListMember
from posts_api.app.repositories.follows import FollowRepository
from posts_api.app.repositories.lists import ListRepository
from posts_api.app.services.lists import ListService

router = APIRouter(prefix="/lists", tags=["lists"])


class ListNameRequest(BaseModel):
    name: str


class ListSummary(BaseModel):
    id: uuid.UUID
    name: str
    members_count: int = Field(serialization_alias="membersCount")
    created_at: datetime = Field(serialization_alias="createdAt")

    @classmethod
    def of(cls, found: AccountList) -> "ListSummary":
        return cls(
            id=found.id,
            name=found.name,
            members_count=found.members_count,
            created_at=found.created_at,
        )


class ListMemberSummary(BaseModel):
    id: uuid.UUID
    handle: str | None
    added_at: datetime = Field(serialization_alias="addedAt")

    @classmethod
    def of(cls, member: ListMember) -> "ListMemberSummary":
        return cls(id=member.id, handle=member.handle, added_at=member.added_at)


def get_list_service(session: SessionDep) -> ListService:
    return ListService(ListRepository(session), FollowRepository(session))


ServiceDep = Annotated[ListService, Depends(get_list_service)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_list(
    body: ListNameRequest, current_user: CurrentUserDep, service: ServiceDep
) -> ListSummary:
    """Create an empty list. The owner comes from the token, never from the body."""
    return ListSummary.of(await service.create(current_user, body.name))


@router.get("")
async def my_lists(current_user: CurrentUserDep, service: ServiceDep) -> list[ListSummary]:
    """The caller's lists, oldest first. There are twenty at most, so no paging."""
    return [ListSummary.of(found) for found in await service.lists_of(current_user)]


@router.patch("/{list_id}")
async def rename_list(
    list_id: uuid.UUID, body: ListNameRequest, current_user: CurrentUserDep, service: ServiceDep
) -> ListSummary:
    return ListSummary.of(await service.rename(current_user, list_id, body.name))


@router.delete("/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_list(
    list_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep
) -> None:
    await service.delete(current_user, list_id)


@router.get("/{list_id}/members")
async def list_members(
    list_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep
) -> list[ListMemberSummary]:
    """The accounts in the list, the most recently added first. A hundred at most."""
    return [ListMemberSummary.of(one) for one in await service.members(current_user, list_id)]


@router.post("/{list_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_member(
    list_id: uuid.UUID, user_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep
) -> None:
    await service.add_member(current_user, list_id, user_id)


@router.delete("/{list_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    list_id: uuid.UUID, user_id: uuid.UUID, current_user: CurrentUserDep, service: ServiceDep
) -> None:
    await service.remove_member(current_user, list_id, user_id)
