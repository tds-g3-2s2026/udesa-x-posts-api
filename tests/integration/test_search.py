import base64
import os
import uuid
from datetime import UTC, datetime

import pytest

from posts_api.infrastructure.database.models import (
    BlockModel,
    FollowModel,
    PostModel,
    RetweetModel,
    UserProfileModel,
)
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile, signed_in_as

pytestmark = requires_services
NOW = datetime(2026, 10, 25, tzinfo=UTC)


async def insert_posts(author, contents, *, parent=None):
    async with app.state.session_factory() as session:
        rows = [
            PostModel(author_id=author, content=text, created_at=NOW, parent_id=parent)
            for text in contents
        ]
        session.add_all(rows)
        await session.flush()
        ids = [row.id for row in rows]
        await session.commit()
        return ids


async def test_e2_h10_ca1_posts_and_replies_match_case_insensitively_once(api):
    owner, viewer = uuid.uuid4(), uuid.uuid4()
    await given_a_profile(owner)
    await given_a_profile(viewer)
    parent = (await insert_posts(owner, ["Estudio en UdeSA"]))[0]
    reply = (await insert_posts(owner, ["UDESA también"], parent=parent))[0]
    async with app.state.session_factory() as session:
        session.add(RetweetModel(user_id=viewer, post_id=parent))
        await session.commit()
    response = await api.get(
        "/search/posts", params={"q": "  udesa  "}, headers=signed_in_as(viewer)
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert {item["id"] for item in items} == {str(parent), str(reply)}
    assert len(items) == 2
    assert next(item for item in items if item["id"] == str(reply))["parentId"] == str(parent)
    assert all(any(part["highlighted"] for part in item["snippet"]) for item in items)


async def test_e2_h10_ca1_wildcards_are_literal_and_accents_are_preserved(api):
    owner = uuid.uuid4()
    await given_a_profile(owner)
    expected = (await insert_posts(owner, ["literal %_\\ y café", "literal abc y cafe"]))[0]
    for query in ["%_\\", "CAFÉ"]:
        response = await api.get("/search/posts", params={"q": query}, headers=signed_in_as(owner))
        assert [item["id"] for item in response.json()["items"]] == [str(expected)]


async def test_e2_h10_ca4_twenty_visible_results_with_tied_dates_and_last_page(api):
    owner = uuid.uuid4()
    await given_a_profile(owner)
    ids = await insert_posts(owner, [f"universidad {i}" for i in range(21)])
    first = (
        await api.get("/search/posts", params={"q": "universidad"}, headers=signed_in_as(owner))
    ).json()
    second = (
        await api.get(
            "/search/posts",
            params={"q": "universidad", "cursor": first["nextCursor"]},
            headers=signed_in_as(owner),
        )
    ).json()
    assert len(first["items"]) == 20
    assert len(second["items"]) == 1
    assert second["nextCursor"] is None
    assert [item["id"] for item in first["items"] + second["items"]] == [
        str(value) for value in sorted(ids, reverse=True)
    ]


async def test_e2_h10_ca5_protected_deleted_and_blocked_authors_are_filtered(api):
    viewer, private, blocked, incoming, deleted = [uuid.uuid4() for _ in range(5)]
    for owner in [viewer, private, blocked, incoming, deleted]:
        await given_a_profile(owner, visibility="protected" if owner == private else "public")
        await insert_posts(owner, ["universidad"])
    async with app.state.session_factory() as session:
        session.add_all(
            [
                BlockModel(blocker_id=viewer, blocked_id=blocked),
                BlockModel(blocker_id=incoming, blocked_id=viewer),
            ]
        )
        row = await session.get(UserProfileModel, deleted)
        row.deleted_at = NOW
        await session.commit()

    async def results():
        return (
            await api.get(
                "/search/posts", params={"q": "universidad"}, headers=signed_in_as(viewer)
            )
        ).json()["items"]

    assert {item["authorId"] for item in await results()} == {str(viewer)}
    async with app.state.session_factory() as session:
        session.add(FollowModel(follower_id=viewer, followee_id=private))
        await session.commit()
    assert {item["authorId"] for item in await results()} == {str(viewer), str(private)}
    async with app.state.session_factory() as session:
        post = await session.get(PostModel, uuid.UUID((await results())[0]["id"]))
        post.deleted_at = NOW
        await session.commit()
    assert len(await results()) == 1


@pytest.mark.parametrize("query", ["ab", " ab ", "   "])
async def test_e2_h10_ca1_invalid_normalized_queries_are_422(api, query):
    response = await api.get(
        "/search/posts", params={"q": query}, headers=signed_in_as(uuid.uuid4())
    )
    assert response.status_code == 422


async def test_e2_h10_ca4_invalid_cursor_and_missing_session(api):
    assert (await api.get("/search/posts", params={"q": "universidad"})).status_code == 401
    response = await api.get(
        "/search/posts",
        params={"q": "universidad", "cursor": "invalid"},
        headers=signed_in_as(uuid.uuid4()),
    )
    assert response.status_code == 400


async def test_e2_h10_ca5_internal_blocks_check_is_authenticated_and_batched(api):
    viewer, outgoing, incoming, other = [uuid.uuid4() for _ in range(4)]
    for user_id in [viewer, outgoing, incoming, other]:
        await given_a_profile(user_id)
    async with app.state.session_factory() as session:
        session.add_all(
            [
                BlockModel(blocker_id=viewer, blocked_id=outgoing),
                BlockModel(blocker_id=incoming, blocked_id=viewer),
            ]
        )
        await session.commit()
    body = {
        "viewer_id": str(viewer),
        "user_ids": [str(value) for value in [outgoing, incoming, other]],
    }
    path = "http://test/internal/blocks/check"
    assert (await api.post(path, json=body)).status_code == 401
    response = await api.post(
        path, json=body, headers={"X-Internal-Token": os.environ["INTERNAL_API_TOKEN"]}
    )
    assert set(response.json()["excluded_ids"]) == {str(outgoing), str(incoming)}
    body["user_ids"] = [str(other)] * 51
    assert (
        await api.post(
            path, json=body, headers={"X-Internal-Token": os.environ["INTERNAL_API_TOKEN"]}
        )
    ).status_code == 422


async def test_e2_h10_ca4_cursor_without_timezone_is_400(api):
    cursor = base64.urlsafe_b64encode(f"2026-10-25|{uuid.uuid4()}".encode()).decode()
    response = await api.get(
        "/search/posts",
        params={"q": "universidad", "cursor": cursor},
        headers=signed_in_as(uuid.uuid4()),
    )
    assert response.status_code == 400
