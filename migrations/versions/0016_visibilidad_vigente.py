"""The instant of the last visibility event applied to each profile.

Revision ID: 0016_visibilidad_vigente
Revises: 0015_hashtags
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_visibilidad_vigente"
down_revision: str | None = "0015_hashtags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL on the profiles that exist: the first event of each one replaces whatever
    # a token wrote.
    op.add_column(
        "user_profiles",
        sa.Column("visibility_changed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "visibility_changed_at")
