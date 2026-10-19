import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from posts_api.app.models.follow import Account
from posts_api.app.repositories.likes import LikeRepository
from posts_api.app.repositories.posts import PostRepository
from posts_api.app.repositories.retweets import RetweetRepository
from posts_api.app.services.posts import PostService
from posts_api.infrastructure.database.models import LikeModel, PostModel, ReportModel, RetweetModel
from posts_api.main import app
from tests.conftest import issue_token, requires_services
from tests.integration.conftest import given_a_profile, signed_in_as
from tests.integration.test_likes import approve_follow, block, publish

pytestmark = requires_services


async def remove(api, author, post):
    return await api.delete(f"/posts/{post}", headers=signed_in_as(author))


async def read(api, viewer, post):
    return await api.get(f"/posts/{post}", headers=signed_in_as(viewer))


async def answer(api, viewer, post):
    return await api.post(
        f"/posts/{post}/replies", json={"content": "respuesta"}, headers=signed_in_as(viewer)
    )


async def test_e2_h3_ca1_only_the_author_can_delete(api):
    author = uuid.uuid4()
    post = await publish(api, author, "texto conservado")
    assert (await api.delete(f"/posts/{post}")).status_code == 401
    assert (await remove(api, author, uuid.uuid4())).status_code == 404
    assert (await remove(api, author, post)).status_code == 204
    async with app.state.session_factory() as session:
        row = await session.get(PostModel, uuid.UUID(post))
        at = row.deleted_at
        assert row.content == "texto conservado"
        assert at is not None and at <= datetime.now(UTC)
    assert (await remove(api, author, post)).status_code == 204
    async with app.state.session_factory() as session:
        assert (await session.get(PostModel, uuid.UUID(post))).deleted_at == at
    marker = (await read(api, author, post)).json()
    assert marker["deleted"] is True and marker["content"] is None
    assert marker["entryId"] == f"post:{post}"


async def test_e2_h3_ca1_a_visible_post_of_someone_else_is_403(api):
    author, stranger = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    assert (await remove(api, stranger, post)).status_code == 403
    await block(author, stranger)
    assert (await remove(api, stranger, post)).status_code == 404
    protected_author = uuid.uuid4()
    await given_a_profile(protected_author, visibility="protected")
    created = await api.post(
        "/posts",
        json={"content": "privado"},
        headers=signed_in_as(protected_author, profile_visibility="protected"),
    )
    post = created.json()["id"]
    outsider = uuid.uuid4()
    assert (await remove(api, outsider, post)).status_code == 404
    response = await api.delete(
        f"/posts/{post}",
        headers={"Authorization": f"Bearer {issue_token(outsider, role='superadmin')}"},
    )
    assert response.status_code == 404


async def test_e2_h3_ca3_deleting_removes_all_interactions_and_feed_entries(api):
    author, fan, viewer = [uuid.uuid4() for _ in range(3)]
    post = await publish(api, author)
    survivor = await publish(api, author, "sigue visible")
    await approve_follow(viewer, author)
    await approve_follow(viewer, fan)
    for person in (fan, viewer):
        headers = signed_in_as(person)
        assert (await api.post(f"/posts/{post}/retweet", headers=headers)).status_code == 201
        assert (await api.put(f"/posts/{post}/like", headers=headers)).status_code == 204
    assert len((await api.get("/feed", headers=signed_in_as(viewer))).json()["items"]) == 3
    assert (await remove(api, author, post)).status_code == 204
    rows = (await api.get("/feed", headers=signed_in_as(viewer))).json()["items"]
    assert [row["id"] for row in rows] == [survivor]
    marker = (await read(api, viewer, post)).json()
    assert (marker["likesCount"], marker["retweetsCount"]) == (0, 0)
    assert marker["likedByMe"] is marker["retweetedByMe"] is False
    async with app.state.session_factory() as session:
        for model in (LikeModel, RetweetModel):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
    for method, suffix in [
        ("put", "like"),
        ("delete", "like"),
        ("post", "retweet"),
        ("delete", "retweet"),
    ]:
        assert (
            await getattr(api, method)(f"/posts/{post}/{suffix}", headers=signed_in_as(viewer))
        ).status_code == 404


async def test_e2_h3_ca4_deleted_post_with_replies_keeps_its_thread(api):
    author, replier = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    child = (await answer(api, replier, post)).json()["id"]
    grandchild = (await answer(api, author, child)).json()["id"]
    assert (await remove(api, author, post)).status_code == 204
    assert (await remove(api, replier, child)).status_code == 204
    replies = (await api.get(f"/posts/{post}/replies", headers=signed_in_as(author))).json()[
        "items"
    ]
    assert [(row["id"], row["deleted"], row["content"]) for row in replies] == [(child, True, None)]
    assert (await read(api, author, post)).json()["repliesCount"] == 1
    assert (await read(api, author, grandchild)).json()["content"] == "respuesta"
    assert (await answer(api, replier, post)).status_code == 409
    assert (await answer(api, replier, grandchild)).status_code == 201
    await block(author, replier)
    assert (await read(api, replier, post)).status_code == 404


async def test_existing_reports_survive_and_deleted_posts_cannot_be_reported(api):
    author, reporter = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    await given_a_profile(reporter)
    async with app.state.session_factory() as session:
        session.add(
            ReportModel(
                reporter_id=reporter, target_id=author, post_id=uuid.UUID(post), reason="spam"
            )
        )
        await session.commit()
    await remove(api, author, post)
    async with app.state.session_factory() as session:
        assert await session.scalar(select(ReportModel.post_id)) == uuid.UUID(post)
    response = await api.post(
        "/reports", json={"postId": post, "reason": "spam"}, headers=signed_in_as(uuid.uuid4())
    )
    assert response.status_code == 404


async def test_deletion_rolls_back_relations_and_timestamp_together(api, monkeypatch):
    author, fan = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    await api.post(f"/posts/{post}/retweet", headers=signed_in_as(fan))

    async def fail(*args):
        raise RuntimeError("simulated failure")

    async with app.state.session_factory() as session:
        posts = PostRepository(session)
        monkeypatch.setattr(posts, "mark_deleted", fail)
        service = PostService(
            posts,
            None,
            None,
            LikeRepository(session),
            RetweetRepository(session),
            post_limit=100,
            window_seconds=3600,
        )
        with pytest.raises(RuntimeError):
            await service.delete(uuid.UUID(post), Account(id=author))
        await session.rollback()
    assert (await read(api, author, post)).json()["deleted"] is False
    async with app.state.session_factory() as session:
        assert await session.get(RetweetModel, (fan, uuid.UUID(post))) is not None


@pytest.mark.parametrize("kind", ["like", "unlike", "retweet", "unretweet", "reply"])
async def test_deletion_serializes_with_interactions(api, kind):
    author, fan = uuid.uuid4(), uuid.uuid4()
    post = await publish(api, author)
    await given_a_profile(fan)
    operations = {
        "like": lambda: api.put(f"/posts/{post}/like", headers=signed_in_as(fan)),
        "unlike": lambda: api.delete(f"/posts/{post}/like", headers=signed_in_as(fan)),
        "retweet": lambda: api.post(f"/posts/{post}/retweet", headers=signed_in_as(fan)),
        "unretweet": lambda: api.delete(f"/posts/{post}/retweet", headers=signed_in_as(fan)),
        "reply": lambda: answer(api, fan, post),
    }
    deletion, interaction = await asyncio.gather(remove(api, author, post), operations[kind]())
    assert deletion.status_code == 204
    assert interaction.status_code in (201, 204, 404, 409)
    async with app.state.session_factory() as session:
        row = await session.get(PostModel, uuid.UUID(post))
        assert row.likes_count == row.retweets_count == 0
        assert await session.scalar(select(func.count()).select_from(LikeModel)) == 0
        assert await session.scalar(select(func.count()).select_from(RetweetModel)) == 0


async def test_e2_h3_ca3_deleting_between_feed_pages_keeps_cursor_valid(api):
    from datetime import timedelta

    from sqlalchemy import update

    from posts_api.app.feed_pagination import FeedCursor
    from posts_api.app.repositories.feed import FeedRepository

    author, viewer = uuid.uuid4(), uuid.uuid4()
    posts = [await publish(api, author, f"post {i}") for i in range(5)]
    await approve_follow(viewer, author)
    async with app.state.session_factory() as session:
        await session.execute(
            update(PostModel).values(created_at=datetime.now(UTC) - timedelta(days=1))
        )
        await session.commit()
        page, cursor = await FeedRepository(session).for_viewer(viewer, limit=2)
    ids = [str(post.id) for post in page]
    remaining = [post for post in posts if post not in ids]
    await remove(api, author, ids[-1])
    await remove(api, author, remaining[0])
    async with app.state.session_factory() as session:
        rest, next_cursor = await FeedRepository(session).for_viewer(
            viewer, cursor=FeedCursor.decode(cursor), limit=2
        )
    assert len(rest) == 2 and next_cursor is None
    assert set(str(post.id) for post in rest) == set(remaining[1:])


async def test_e2_h3_ca1_simultaneous_deletions_keep_one_timestamp(api):
    author = uuid.uuid4()
    post = await publish(api, author)
    responses = await asyncio.gather(*(remove(api, author, post) for _ in range(5)))
    assert [response.status_code for response in responses] == [204] * 5
    async with app.state.session_factory() as session:
        first = (await session.get(PostModel, uuid.UUID(post))).deleted_at
    await remove(api, author, post)
    async with app.state.session_factory() as session:
        assert (await session.get(PostModel, uuid.UUID(post))).deleted_at == first


async def test_report_waits_for_deletion_and_rejects_the_deleted_target(api, monkeypatch):
    from posts_api.app.errors import ProblemError
    from posts_api.app.models.report import ReportReason
    from posts_api.app.repositories.follows import FollowRepository
    from posts_api.app.repositories.reports import ReportRepository
    from posts_api.app.services.reports import ReportService

    author, reporter = uuid.uuid4(), uuid.uuid4()
    post_id = uuid.UUID(await publish(api, author))
    await given_a_profile(reporter)
    attempting = asyncio.Event()

    async with app.state.session_factory() as deletion_session:
        posts = PostRepository(deletion_session)
        await posts.lock_visible(post_id, viewer_id=author)
        await posts.mark_deleted(post_id)

        async def report():
            async with app.state.session_factory() as session:
                targets = PostRepository(session)
                original = targets.lock_visible

                async def lock(*args, **kwargs):
                    attempting.set()
                    return await original(*args, **kwargs)

                monkeypatch.setattr(targets, "lock_visible", lock)
                service = ReportService(
                    ReportRepository(session), FollowRepository(session), targets, None, None
                )
                with pytest.raises(ProblemError) as error:
                    await service.report(
                        Account(id=reporter), reason=ReportReason.SPAM, post_id=post_id
                    )
                assert error.value.status == 404
                await session.rollback()

        task = asyncio.create_task(report())
        await asyncio.wait_for(attempting.wait(), timeout=5)
        assert not task.done()
        await deletion_session.commit()
        await asyncio.wait_for(task, timeout=5)

    async with app.state.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(ReportModel)) == 0


async def test_deletion_waits_for_an_accepted_report_and_preserves_it(api, monkeypatch):
    from posts_api.app.models.report import ReportReason
    from posts_api.app.repositories.follows import FollowRepository
    from posts_api.app.repositories.reports import ReportRepository
    from posts_api.app.services.reports import ReportService

    author, reporter = uuid.uuid4(), uuid.uuid4()
    post_id = uuid.UUID(await publish(api, author))
    await given_a_profile(reporter)
    validated, release, deleting = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class PausedLimiter:
        async def hit(self, *args, **kwargs):
            validated.set()
            await release.wait()
            return 1

    async def report():
        async with app.state.session_factory() as session:
            service = ReportService(
                ReportRepository(session),
                FollowRepository(session),
                PostRepository(session),
                PausedLimiter(),
                None,
            )
            await service.report(Account(id=reporter), reason=ReportReason.SPAM, post_id=post_id)
            await session.commit()

    async def delete():
        async with app.state.session_factory() as session:
            posts = PostRepository(session)
            original = posts.lock_visible

            async def lock(*args, **kwargs):
                deleting.set()
                return await original(*args, **kwargs)

            monkeypatch.setattr(posts, "lock_visible", lock)
            service = PostService(
                posts,
                None,
                None,
                LikeRepository(session),
                RetweetRepository(session),
                post_limit=100,
                window_seconds=3600,
            )
            await service.delete(post_id, Account(id=author))
            await session.commit()

    report_task = asyncio.create_task(report())
    await asyncio.wait_for(validated.wait(), timeout=5)
    delete_task = asyncio.create_task(delete())
    await asyncio.wait_for(deleting.wait(), timeout=5)
    assert not delete_task.done()
    release.set()
    await asyncio.wait_for(asyncio.gather(report_task, delete_task), timeout=5)
    async with app.state.session_factory() as session:
        assert (await session.get(PostModel, post_id)).deleted_at is not None
        assert await session.scalar(select(ReportModel.post_id)) == post_id
