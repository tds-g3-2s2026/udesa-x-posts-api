"""The hashtags of each post, one row per distinct hashtag.

Revision ID: 0015_hashtags
Revises: 0014_idioma_de_los_posts
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_hashtags"
down_revision: str | None = "0014_idioma_de_los_posts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "post_hashtags",
        sa.Column("post_id", sa.UUID(), nullable=False),
        sa.Column("tag", sa.String(length=280), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"]),
        sa.PrimaryKeyConstraint("post_id", "tag"),
    )
    op.create_index("ix_post_hashtags_tag_post", "post_hashtags", ["tag", "post_id"])


def downgrade() -> None:
    op.drop_index("ix_post_hashtags_tag_post", table_name="post_hashtags")
    op.drop_table("post_hashtags")
