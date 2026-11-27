"""Index visible feed candidates in chronological cursor order."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_feed_indexes"
down_revision: str | None = "0021_citas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # An interrupted concurrent build can leave an invalid index with the target name.
        op.drop_index(
            "ix_posts_feed_recent", table_name="posts", postgresql_concurrently=True, if_exists=True
        )
        op.create_index(
            "ix_posts_feed_recent",
            "posts",
            [sa.text("created_at DESC"), sa.text("id DESC")],
            postgresql_include=["author_id"],
            postgresql_where=sa.text("parent_id IS NULL AND deleted_at IS NULL"),
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_retweets_feed_recent",
            table_name="retweets",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.create_index(
            "ix_retweets_feed_recent",
            "retweets",
            [sa.text("created_at DESC"), sa.text("post_id DESC"), sa.text("user_id DESC")],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_retweets_feed_recent",
            table_name="retweets",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_index(
            "ix_posts_feed_recent", table_name="posts", postgresql_concurrently=True, if_exists=True
        )
