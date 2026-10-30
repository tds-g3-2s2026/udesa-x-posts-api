"""Mutes between accounts (E3-H10).

Revision ID: 0012_silenciados
Revises: search_content_trigrams
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_silenciados"
down_revision: str | None = "search_content_trigrams"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mutes",
        sa.Column("muter_id", sa.UUID(), nullable=False),
        sa.Column("muted_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["muter_id"], ["user_profiles.id"]),
        sa.ForeignKeyConstraint(["muted_id"], ["user_profiles.id"]),
        sa.PrimaryKeyConstraint("muter_id", "muted_id"),
        sa.CheckConstraint("muter_id <> muted_id", name="ck_mutes_not_self"),
    )
    op.create_index("ix_mutes_muter_cursor", "mutes", ["muter_id", "created_at", "muted_id"])


def downgrade() -> None:
    op.drop_index("ix_mutes_muter_cursor", table_name="mutes")
    op.drop_table("mutes")
