"""Custom lists of accounts (E3-H8).

Revision ID: 0017_listas
Revises: 0016_visibilidad_vigente
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_listas"
down_revision: str | None = "0016_visibilidad_vigente"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lists",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["user_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lists_owner", "lists", ["owner_id", "created_at"])
    op.create_table(
        "list_members",
        sa.Column("list_id", sa.UUID(), nullable=False),
        sa.Column("member_id", sa.UUID(), nullable=False),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["list_id"], ["lists.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["member_id"], ["user_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("list_id", "member_id"),
    )
    op.create_index("ix_list_members_member", "list_members", ["member_id"])


def downgrade() -> None:
    op.drop_index("ix_list_members_member", table_name="list_members")
    op.drop_table("list_members")
    op.drop_index("ix_lists_owner", table_name="lists")
    op.drop_table("lists")
