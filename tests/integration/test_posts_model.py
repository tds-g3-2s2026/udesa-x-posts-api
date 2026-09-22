"""The `posts` table itself, before there is an endpoint on top of it."""

import uuid

from posts_api.infrastructure.database.models import PostModel
from posts_api.main import app
from tests.conftest import requires_services
from tests.integration.conftest import given_a_profile

pytestmark = requires_services


async def test_e2_h1_ca4_a_post_gets_a_time_ordered_id_and_its_counters_at_zero(api):
    author = uuid.uuid4()
    await given_a_profile(author)

    async with app.state.session_factory() as session:
        row = PostModel(author_id=author, content="Hola UdeSA-X")
        session.add(row)
        await session.commit()
        await session.refresh(row)

    # Version 7 and not merely present: this is what proves PostgreSQL is the
    # one generating it with `uuidv7()`, the primary key A19 of ARQUITECTURA.md
    # fixes for this table, and not some other default quietly filling in.
    assert row.id is not None
    assert row.id.version == 7
    assert row.created_at is not None
    assert (row.likes_count, row.retweets_count, row.replies_count) == (0, 0, 0)
