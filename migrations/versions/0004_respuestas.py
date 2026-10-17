"""Replies: a post can point at the post it answers.

Revision ID: 0004_respuestas
Revises: 0003_denuncias
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_respuestas"
down_revision: str | None = "0003_denuncias"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("parent_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_posts_parent_id_posts", "posts", "posts", ["parent_id"], ["id"])
    op.create_index(
        "ix_posts_parent_created",
        "posts",
        ["parent_id", "created_at", "id"],
        postgresql_where=sa.text("parent_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_posts_parent_created", table_name="posts")
    op.drop_constraint("fk_posts_parent_id_posts", "posts", type_="foreignkey")
    op.drop_column("posts", "parent_id")
