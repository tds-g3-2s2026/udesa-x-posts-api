"""The state of each report, so the backoffice can close its cases (E5-H7).

Every report already stored starts pending: nobody looked at any of them yet.

Revision ID: 0011_estado_de_denuncias
Revises: 0010_outbox
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_estado_de_denuncias"
down_revision: str | None = "0010_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUS_CHECK = "status IN ('pending', 'dismissed', 'resolved')"


def upgrade() -> None:
    op.add_column(
        "reports",
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
    )
    op.create_check_constraint("ck_reports_status", "reports", STATUS_CHECK)
    op.add_column("reports", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reports", sa.Column("decided_by", sa.UUID(), nullable=True))
    op.create_index(
        "ix_reports_pending_target",
        "reports",
        ["target_id", "reporter_id"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_reports_pending_target", table_name="reports")
    op.drop_column("reports", "decided_by")
    op.drop_column("reports", "decided_at")
    op.drop_constraint("ck_reports_status", "reports", type_="check")
    op.drop_column("reports", "status")
