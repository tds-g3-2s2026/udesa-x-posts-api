import uuid

import httpx
from sqlalchemy import func, select

from posts_api.app.services import lists as list_rules
from posts_api.infrastructure.database.models import ListMemberModel
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, handle_of, signed_in_as
from tests.integration.test_mutes import follow, is_following
from tests.integration.test_user_deleted import close_account

pytestmark = requires_services


async def given_profiles(*user_ids: uuid.UUID) -> None:
    for user_id in user_ids:
        await given_a_profile(user_id)


async def create_list(api, owner: uuid.UUID, name: str = "Compañeros de Taller") -> dict:
    response = await api.post("/lists", json={"name": name}, headers=signed_in_as(owner))
    assert response.status_code == 201
    return response.json()


async def add_member(api, owner: uuid.UUID, list_id: str, member: uuid.UUID) -> httpx.Response:
    return await api.post(f"/lists/{list_id}/members/{member}", headers=signed_in_as(owner))


async def members_of(api, owner: uuid.UUID, list_id: str) -> list[str]:
    response = await api.get(f"/lists/{list_id}/members", headers=signed_in_as(owner))
    assert response.status_code == 200
    return [one["handle"] for one in response.json()]


async def lists_of(api, owner: uuid.UUID) -> list[tuple[str, int]]:
    response = await api.get("/lists", headers=signed_in_as(owner))
    assert response.status_code == 200
    return [(one["name"], one["membersCount"]) for one in response.json()]


async def memberships(list_id: str) -> int:
    async with app.state.session_factory() as session:
        return await session.scalar(
            select(func.count())
            .select_from(ListMemberModel)
            .where(ListMemberModel.list_id == uuid.UUID(list_id))
        )


async def test_e3_h8_ca1_an_account_can_be_in_two_lists(api):
    owner, friend = uuid.uuid4(), uuid.uuid4()
    await given_profiles(owner, friend)
    await follow(api, owner, friend)
    first = await create_list(api, owner, "Taller")
    second = await create_list(api, owner, "Fútbol")

    assert (await add_member(api, owner, first["id"], friend)).status_code == 204
    assert (await add_member(api, owner, second["id"], friend)).status_code == 204

    assert await members_of(api, owner, first["id"]) == [handle_of(friend)]
    assert await members_of(api, owner, second["id"]) == [handle_of(friend)]
    assert await lists_of(api, owner) == [("Taller", 1), ("Fútbol", 1)]


async def test_a_new_list_starts_empty_with_its_name_trimmed(api):
    owner = uuid.uuid4()
    await given_a_profile(owner)

    created = await create_list(api, owner, "  Taller  ")

    assert created["name"] == "Taller"
    assert created["membersCount"] == 0
    assert await members_of(api, owner, created["id"]) == []


async def test_only_accounts_the_owner_follows_can_be_added(api):
    owner, stranger = uuid.uuid4(), uuid.uuid4()
    await given_profiles(owner, stranger)
    created = await create_list(api, owner)

    response = await add_member(api, owner, created["id"], stranger)

    assert response.status_code == 409
    assert response.json()["type"].endswith("/not-following")
    assert await members_of(api, owner, created["id"]) == []


async def test_an_unknown_account_cannot_be_added(api):
    owner = uuid.uuid4()
    await given_a_profile(owner)
    created = await create_list(api, owner)

    response = await add_member(api, owner, created["id"], uuid.uuid4())

    assert response.status_code == 404
    assert response.json()["type"].endswith("/user-not-found")


async def test_adding_an_account_twice_leaves_one_membership(api):
    owner, friend = uuid.uuid4(), uuid.uuid4()
    await given_profiles(owner, friend)
    await follow(api, owner, friend)
    created = await create_list(api, owner)

    await add_member(api, owner, created["id"], friend)
    again = await add_member(api, owner, created["id"], friend)

    assert again.status_code == 204
    assert await memberships(created["id"]) == 1


async def test_taking_an_account_out_keeps_the_follow(api):
    owner, friend = uuid.uuid4(), uuid.uuid4()
    await given_profiles(owner, friend)
    await follow(api, owner, friend)
    created = await create_list(api, owner)
    await add_member(api, owner, created["id"], friend)

    response = await api.delete(
        f"/lists/{created['id']}/members/{friend}", headers=signed_in_as(owner)
    )

    assert response.status_code == 204
    assert await members_of(api, owner, created["id"]) == []
    assert await is_following(owner, friend)


async def test_a_list_is_private_to_its_owner(api):
    owner, other, friend = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_profiles(owner, other, friend)
    await follow(api, owner, friend)
    await follow(api, other, friend)
    created = await create_list(api, owner, "Taller")
    await add_member(api, owner, created["id"], friend)
    path = f"/lists/{created['id']}"
    as_other = signed_in_as(other)

    attempts = [
        await api.get(f"{path}/members", headers=as_other),
        await api.patch(path, json={"name": "Mía"}, headers=as_other),
        await api.post(f"{path}/members/{friend}", headers=as_other),
        await api.delete(f"{path}/members/{friend}", headers=as_other),
        await api.delete(path, headers=as_other),
    ]

    assert [one.status_code for one in attempts] == [404] * 5
    assert all(one.json()["type"].endswith("/list-not-found") for one in attempts)
    assert await lists_of(api, other) == []
    assert await lists_of(api, owner) == [("Taller", 1)]


async def test_renaming_a_list(api):
    owner = uuid.uuid4()
    await given_a_profile(owner)
    created = await create_list(api, owner, "Taller")

    response = await api.patch(
        f"/lists/{created['id']}", json={"name": "Taller de Software"}, headers=signed_in_as(owner)
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Taller de Software"
    assert await lists_of(api, owner) == [("Taller de Software", 0)]


async def test_deleting_a_list_takes_its_members_with_it(api):
    owner, friend = uuid.uuid4(), uuid.uuid4()
    await given_profiles(owner, friend)
    await follow(api, owner, friend)
    created = await create_list(api, owner)
    await add_member(api, owner, created["id"], friend)

    response = await api.delete(f"/lists/{created['id']}", headers=signed_in_as(owner))

    assert response.status_code == 204
    assert await lists_of(api, owner) == []
    assert await memberships(created["id"]) == 0
    assert await is_following(owner, friend)


async def test_a_list_needs_a_name_of_fifty_characters_at_most(api):
    owner = uuid.uuid4()
    await given_a_profile(owner)

    blank = await api.post("/lists", json={"name": "   "}, headers=signed_in_as(owner))
    too_long = await api.post("/lists", json={"name": "x" * 51}, headers=signed_in_as(owner))

    assert blank.status_code == 422
    assert blank.json()["type"].endswith("/list-name-required")
    assert too_long.status_code == 422
    assert too_long.json()["type"].endswith("/list-name-too-long")
    assert await lists_of(api, owner) == []


async def test_an_account_has_twenty_lists_at_most(api, monkeypatch):
    # Two instead of twenty: the rule is the same and the test stays short.
    monkeypatch.setattr(list_rules, "MAX_LISTS", 2)
    owner = uuid.uuid4()
    await given_a_profile(owner)
    await create_list(api, owner, "Una")
    await create_list(api, owner, "Otra")

    response = await api.post("/lists", json={"name": "Una más"}, headers=signed_in_as(owner))

    assert response.status_code == 422
    assert response.json()["type"].endswith("/too-many-lists")
    assert len(await lists_of(api, owner)) == 2


async def test_a_list_holds_a_hundred_accounts_at_most(api, monkeypatch):
    monkeypatch.setattr(list_rules, "MAX_MEMBERS", 1)
    owner, first, second = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_profiles(owner, first, second)
    await follow(api, owner, first)
    await follow(api, owner, second)
    created = await create_list(api, owner)
    await add_member(api, owner, created["id"], first)

    full = await add_member(api, owner, created["id"], second)
    # Already inside: a full list does not turn that into an error.
    again = await add_member(api, owner, created["id"], first)

    assert full.status_code == 422
    assert full.json()["type"].endswith("/list-full")
    assert again.status_code == 204
    assert await members_of(api, owner, created["id"]) == [handle_of(first)]


async def test_lists_need_a_session(api):
    response = await api.get("/lists")

    assert response.status_code == 401


async def owner_with_a_member_in_two_lists(api) -> tuple[uuid.UUID, uuid.UUID, list[str]]:
    owner, friend = uuid.uuid4(), uuid.uuid4()
    await given_profiles(owner, friend)
    await follow(api, owner, friend)
    lists = [(await create_list(api, owner, name))["id"] for name in ("Taller", "Fútbol")]
    for list_id in lists:
        await add_member(api, owner, list_id, friend)
    return owner, friend, lists


async def test_e3_h8_ca3_unfollowing_removes_the_account_from_every_list(api):
    owner, friend, lists = await owner_with_a_member_in_two_lists(api)

    response = await api.delete(f"/users/{friend}/follow", headers=signed_in_as(owner))

    assert response.status_code == 204
    assert [await members_of(api, owner, list_id) for list_id in lists] == [[], []]


async def test_e3_h8_ca3_blocking_removes_the_account_from_every_list(api):
    owner, friend, lists = await owner_with_a_member_in_two_lists(api)

    response = await api.post(f"/users/{friend}/block", headers=signed_in_as(owner))

    assert response.status_code == 204
    assert [await members_of(api, owner, list_id) for list_id in lists] == [[], []]


async def test_being_blocked_by_a_member_takes_them_out_too(api):
    # The block removes the follow in both directions, and the membership with it.
    owner, friend, lists = await owner_with_a_member_in_two_lists(api)

    response = await api.post(f"/users/{owner}/block", headers=signed_in_as(friend))

    assert response.status_code == 204
    assert [await members_of(api, owner, list_id) for list_id in lists] == [[], []]


async def test_a_member_who_closes_the_account_leaves_every_list(api):
    owner, friend, lists = await owner_with_a_member_in_two_lists(api)

    await close_account(friend)

    assert [await members_of(api, owner, list_id) for list_id in lists] == [[], []]
    assert await lists_of(api, owner) == [("Taller", 0), ("Fútbol", 0)]
