"""The accounts each post mentions, one row per distinct account (E2-H9).

Revision ID: 0020_menciones
Revises: 0019_bookmarks
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_menciones"
down_revision: str | None = "0019_bookmarks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "post_mentions",
        sa.Column("post_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user_profiles.id"]),
        sa.PrimaryKeyConstraint("post_id", "user_id"),
    )


def downgrade() -> None:
    op.drop_table("post_mentions")
