"""Quote posts: the post a post quotes, and how many times a post was quoted (E2-H13).

Revision ID: 0021_citas
Revises: 0020_menciones
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_citas"
down_revision: str | None = "0020_menciones"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("quoted_post_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_posts_quoted_post_id_posts", "posts", "posts", ["quoted_post_id"], ["id"]
    )
    op.add_column(
        "posts", sa.Column("quotes_count", sa.Integer(), server_default="0", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("posts", "quotes_count")
    op.drop_constraint("fk_posts_quoted_post_id_posts", "posts", type_="foreignkey")
    op.drop_column("posts", "quoted_post_id")
