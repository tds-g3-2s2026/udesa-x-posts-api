"""Profile photo and cover of each account.

Revision ID: 0013_imagenes_de_perfil
Revises: 0012_silenciados
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_imagenes_de_perfil"
down_revision: str | None = "0012_silenciados"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("avatar_key", sa.String(255), nullable=True))
    op.add_column("user_profiles", sa.Column("cover_key", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("user_profiles", "cover_key")
    op.drop_column("user_profiles", "avatar_key")
