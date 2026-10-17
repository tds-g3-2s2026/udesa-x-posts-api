"""Keep deleted posts as thread anchors."""

import sqlalchemy as sa
from alembic import op

revision = "0007_borrado_logico_posts"
down_revision = "0006_retweets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("posts", "deleted_at")
