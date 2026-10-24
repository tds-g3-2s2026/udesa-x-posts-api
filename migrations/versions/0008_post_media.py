"""Store the images attached to a post."""

import sqlalchemy as sa
from alembic import op

revision = "0008_post_media"
down_revision = "0007_borrado_logico_posts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "post_media",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("post_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("s3_key", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("position BETWEEN 0 AND 3", name="ck_post_media_position"),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"]),
        sa.PrimaryKeyConstraint("id"),
        # Also the index the page lookup reads: `post_id` leads it.
        sa.UniqueConstraint("post_id", "position", name="uq_post_media_post_position"),
    )


def downgrade() -> None:
    op.drop_table("post_media")
