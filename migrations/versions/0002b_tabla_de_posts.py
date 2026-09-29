"""The posts table, for a database that applied 0001 before it had it.

Production applied 0001 on 2026-09-21, and `posts` was added to 0001 the next
day. Alembic never runs an applied revision again, so that database never got
the table. On any database created afterwards 0001 already made it, and this
revision does nothing.

Revision ID: 0002b_tabla_de_posts
Revises: 0002_bloqueos
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002b_tabla_de_posts"
down_revision: str | None = "0002_bloqueos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("posts"):
        return

    op.create_table(
        "posts",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("content", sa.String(length=280), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("likes_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retweets_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("replies_count", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["user_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_posts_author_created", "posts", ["author_id", "created_at", "id"])


def downgrade() -> None:
    # Nothing to undo: on a database built from scratch the table belongs to
    # 0001, whose downgrade drops it.
    pass
