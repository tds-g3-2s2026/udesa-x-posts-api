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
    op.add_column(
        "user_profiles",
        sa.Column("feed_language", sa.String(8), nullable=False, server_default="all"),
    )
    op.create_check_constraint(
        "ck_user_profiles_feed_language", "user_profiles", "feed_language IN ('es', 'en', 'all')"
    )
    op.add_column(
        "user_profiles",
        sa.Column("feed_language_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "feed_language_at")
    op.drop_constraint("ck_user_profiles_feed_language", "user_profiles", type_="check")
    op.drop_column("user_profiles", "feed_language")
    op.drop_constraint("ck_posts_language", "posts", type_="check")
    op.drop_column("posts", "language")
