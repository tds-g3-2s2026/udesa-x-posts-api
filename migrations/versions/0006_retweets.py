"""Store retweets independently from their original posts."""

import sqlalchemy as sa
from alembic import op

revision = "0006_retweets"
down_revision = "0005_likes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retweets",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("post_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_profiles.id"]),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"]),
        sa.PrimaryKeyConstraint("user_id", "post_id"),
    )
    op.create_index("ix_retweets_user_created", "retweets", ["user_id", "created_at", "post_id"])
    op.create_index("ix_retweets_post", "retweets", ["post_id"])


def downgrade() -> None:
    op.drop_table("retweets")
