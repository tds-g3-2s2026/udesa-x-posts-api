import uuid

from tests.conftest import requires_services
from tests.integration.conftest import handle_of, signed_in_as
from tests.integration.test_blocks import feed_contents
from tests.integration.test_likes import publish
from tests.integration.test_lists import add_member, create_list, given_profiles
from tests.integration.test_mutes import follow, mute
from tests.integration.test_retweets import share

pytestmark = requires_services


async def list_feed(api, owner: uuid.UUID, list_id: str) -> list[dict]:
    response = await api.get(f"/lists/{list_id}/feed", headers=signed_in_as(owner))
    assert response.status_code == 200
    return response.json()["items"]


async def a_list_with(api, owner: uuid.UUID, *members: uuid.UUID) -> str:
    list_id = (await create_list(api, owner))["id"]
    for member in members:
        await add_member(api, owner, list_id, member)
    return list_id


async def test_e3_h8_ca2_the_list_feed_only_has_its_members(api):
    owner, member, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_profiles(owner, member, other)
    await follow(api, owner, member)
    await follow(api, owner, other)
    await publish(api, member, "Entregué el TP de Taller")
    await publish(api, other, "Mañana hay partido")
    list_id = await a_list_with(api, owner, member)

    posts = await list_feed(api, owner, list_id)

    assert [one["content"] for one in posts] == ["Entregué el TP de Taller"]
    # The main feed keeps both: the list is another way of reading, not a filter.
    assert sorted(await feed_contents(api, owner)) == [
        "Entregué el TP de Taller",
        "Mañana hay partido",
    ]


async def test_the_list_feed_brings_what_its_members_retweet(api):
    owner, member, author = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_profiles(owner, member, author)
    await follow(api, owner, member)
    post_id = await publish(api, author, "La biblioteca abre hasta las 23")
    await share(api, member, post_id)
    list_id = await a_list_with(api, owner, member)

    posts = await list_feed(api, owner, list_id)

    assert [(one["content"], one["retweetedBy"]) for one in posts] == [
        ("La biblioteca abre hasta las 23", handle_of(member))
    ]


async def test_the_list_feed_leaves_out_a_muted_member(api):
    owner, member = uuid.uuid4(), uuid.uuid4()
    await given_profiles(owner, member)
    await follow(api, owner, member)
    await publish(api, member, "Entregué el TP de Taller")
    list_id = await a_list_with(api, owner, member)

    await mute(api, owner, member)

    assert await list_feed(api, owner, list_id) == []


async def test_the_feed_of_someone_elses_list_is_not_found(api):
    owner, other, member = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await given_profiles(owner, other, member)
    await follow(api, owner, member)
    list_id = await a_list_with(api, owner, member)

    response = await api.get(f"/lists/{list_id}/feed", headers=signed_in_as(other))

    assert response.status_code == 404
    assert response.json()["type"].endswith("/list-not-found")


async def test_e3_h8_ca4_deleting_a_list_keeps_the_main_feed(api):
    owner, member = uuid.uuid4(), uuid.uuid4()
    await given_profiles(owner, member)
    await follow(api, owner, member)
    await publish(api, member, "Entregué el TP de Taller")
    list_id = await a_list_with(api, owner, member)

    deleted = await api.delete(f"/lists/{list_id}", headers=signed_in_as(owner))

    assert deleted.status_code == 204
    assert await feed_contents(api, owner) == ["Entregué el TP de Taller"]
    gone = await api.get(f"/lists/{list_id}/feed", headers=signed_in_as(owner))
    assert gone.status_code == 404
