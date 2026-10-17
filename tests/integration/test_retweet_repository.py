import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from posts_api.app.repositories.retweets import RetweetRepository
from posts_api.infrastructure.database.models import PostModel, RetweetModel, UserProfileModel
from posts_api.main import app
from tests.conftest import requires_services

pytestmark = requires_services


async def seed():
    user = uuid.uuid4()
    async with app.state.session_factory() as session:
        session.add(UserProfileModel(id=user))
        await session.flush()
        post = PostModel(author_id=user, content="original")
        session.add(post)
        await session.flush()
        post_id = post.id
        await session.commit()
    return user, post_id


async def test_e2_h5_ca2_repository_insertion_is_idempotent(api):
    user, post = await seed()
    async with app.state.session_factory() as session:
        repo = RetweetRepository(session)
        assert await repo.add(user, post) is True
        await repo.move_counter(post, by=1)
        assert await repo.add(user, post) is False
        await session.commit()
    async with app.state.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RetweetModel)) == 1
        assert (await session.get(PostModel, post)).retweets_count == 1


async def test_e2_h5_ca3_repository_removal_and_counter_are_transactional(api):
    user, post = await seed()
    async with app.state.session_factory() as session:
        repo = RetweetRepository(session)
        await repo.add(user, post)
        await repo.move_counter(post, by=1)
        await session.rollback()
    async with app.state.session_factory() as session:
        assert await session.get(RetweetModel, (user, post)) is None
        assert (await session.get(PostModel, post)).retweets_count == 0
        repo = RetweetRepository(session)
        await repo.add(user, post)
        await repo.move_counter(post, by=1)
        await session.commit()
    async with app.state.session_factory() as session:
        repo = RetweetRepository(session)
        assert await repo.remove(user, post) is True
        await repo.move_counter(post, by=-1)
        assert await repo.remove(user, post) is False
        await repo.move_counter(post, by=-1)
        await session.commit()
    async with app.state.session_factory() as session:
        assert (await session.get(PostModel, post)).retweets_count == 0


async def test_retweet_primary_key_and_foreign_keys_are_enforced(api):
    user, post = await seed()
    async with app.state.session_factory() as session:
        session.add(RetweetModel(user_id=user, post_id=post))
        await session.commit()
    for user_id, post_id in [(user, post), (uuid.uuid4(), post), (user, uuid.uuid4())]:
        async with app.state.session_factory() as session:
            session.add(RetweetModel(user_id=user_id, post_id=post_id))
            with pytest.raises(IntegrityError):
                await session.flush()
