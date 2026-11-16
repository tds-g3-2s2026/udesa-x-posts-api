"""Bookmarks: which account saved which post to its private list.

Revision ID: 0019_bookmarks
Revises: 0018_listas_del_follow
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_bookmarks"
down_revision: str | None = "0018_listas_del_follow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bookmarks",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("post_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_profiles.id"]),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"]),
        sa.PrimaryKeyConstraint("user_id", "post_id"),
    )
    op.create_index("ix_bookmarks_user_created", "bookmarks", ["user_id", "created_at", "post_id"])


def downgrade() -> None:
    op.drop_table("bookmarks")
