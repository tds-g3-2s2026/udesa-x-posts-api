"""The language of each post, and the language each account reads its feed in.

Revision ID: 0014_idioma_de_los_posts
Revises: 0013_imagenes_de_perfil
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_idioma_de_los_posts"
down_revision: str | None = "0013_imagenes_de_perfil"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NULL on the posts already published: they are not reprocessed.
    op.add_column("posts", sa.Column("language", sa.String(8), nullable=True))
    op.create_check_constraint("ck_posts_language", "posts", "language IN ('es', 'en', 'other')")
    op.create_table(
        "feed_preferences",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("language IN ('es', 'en', 'all')", name="ck_feed_preferences_language"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("feed_preferences")
    op.drop_constraint("ck_posts_language", "posts", type_="check")
    op.drop_column("posts", "language")
