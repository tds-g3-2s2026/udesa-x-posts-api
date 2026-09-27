"""Blocks between accounts.

Revision ID: 0002_bloqueos
Revises: 0001_esquema_actual
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_bloqueos"
down_revision: str | None = "0001_esquema_actual"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "blocks",
        sa.Column("blocker_id", sa.UUID(), nullable=False),
        sa.Column("blocked_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["blocker_id"], ["user_profiles.id"]),
        sa.ForeignKeyConstraint(["blocked_id"], ["user_profiles.id"]),
        sa.PrimaryKeyConstraint("blocker_id", "blocked_id"),
        sa.CheckConstraint("blocker_id <> blocked_id", name="ck_blocks_not_self"),
    )
    op.create_index(
        "ix_blocks_blocker_cursor", "blocks", ["blocker_id", "created_at", "blocked_id"]
    )
    op.create_index("ix_blocks_blocked", "blocks", ["blocked_id", "blocker_id"])


def downgrade() -> None:
    op.drop_index("ix_blocks_blocked", table_name="blocks")
    op.drop_index("ix_blocks_blocker_cursor", table_name="blocks")
    op.drop_table("blocks")
