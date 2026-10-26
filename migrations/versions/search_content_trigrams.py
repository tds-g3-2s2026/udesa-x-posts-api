"""Index literal publication searches."""

from alembic import op

revision = "search_content_trigrams"
down_revision = "0011_estado_de_denuncias"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "ix_posts_content_trgm",
        "posts",
        ["content"],
        postgresql_using="gin",
        postgresql_ops={"content": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_posts_content_trgm", table_name="posts")
