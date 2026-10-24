"""Mark the accounts users-api closed."""

import sqlalchemy as sa
from alembic import op

revision = "0009_cuenta_eliminada"
down_revision = "0008_post_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "deleted_at")
