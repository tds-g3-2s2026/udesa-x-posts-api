"""Reports between accounts.

Revision ID: 0003_denuncias
Revises: 0002b_tabla_de_posts
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_denuncias"
down_revision: str | None = "0002b_tabla_de_posts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("reporter_id", sa.UUID(), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("post_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["reporter_id"], ["user_profiles.id"]),
        sa.ForeignKeyConstraint(["target_id"], ["user_profiles.id"]),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "reason IN ('spam', 'harassment', 'inappropriate_content', 'impersonation')",
            name="ck_reports_reason",
        ),
        sa.CheckConstraint("reporter_id <> target_id", name="ck_reports_not_self"),
    )
    op.create_index("ix_reports_target_reporter", "reports", ["target_id", "reporter_id"])


def downgrade() -> None:
    op.drop_index("ix_reports_target_reporter", table_name="reports")
    op.drop_table("reports")
