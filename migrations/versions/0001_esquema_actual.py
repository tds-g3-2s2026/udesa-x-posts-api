"""Initial graph schema.

Apply to an empty database before the first deployment. Later schema changes
need incremental migrations; never stamp an existing database without checking
that its schema matches this revision.

Revision ID: 0001_esquema_actual
Revises:
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_esquema_actual"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("handle", sa.String(length=16), nullable=True),
        sa.Column(
            "visibility",
            sa.String(length=16),
            server_default="public",
            nullable=False,
        ),
        sa.Column(
            "followers_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "following_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "visibility IN ('public', 'protected')", name="ck_user_profiles_visibility"
        ),
    )
    op.create_index(op.f("ix_user_profiles_handle"), "user_profiles", ["handle"], unique=True)

    op.create_table(
        "follows",
        sa.Column("follower_id", sa.UUID(), nullable=False),
        sa.Column("followee_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["follower_id"], ["user_profiles.id"]),
        sa.ForeignKeyConstraint(["followee_id"], ["user_profiles.id"]),
        sa.PrimaryKeyConstraint("follower_id", "followee_id"),
        sa.CheckConstraint("follower_id <> followee_id", name="ck_follows_not_self"),
    )

    op.create_table(
        "follow_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("requester_id", sa.UUID(), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["requester_id"], ["user_profiles.id"]),
        sa.ForeignKeyConstraint(["target_id"], ["user_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name="ck_follow_requests_status",
        ),
    )
    op.create_index(
        op.f("ix_follow_requests_requester_id"), "follow_requests", ["requester_id"], unique=False
    )
    op.create_index(
        op.f("ix_follow_requests_target_id"), "follow_requests", ["target_id"], unique=False
    )
    op.create_index(
        "uq_follow_requests_open_pair",
        "follow_requests",
        ["requester_id", "target_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_follow_requests_open_pair", table_name="follow_requests")
    op.drop_index(op.f("ix_follow_requests_target_id"), table_name="follow_requests")
    op.drop_index(op.f("ix_follow_requests_requester_id"), table_name="follow_requests")
    op.drop_table("follow_requests")
    op.drop_table("follows")
    op.drop_index(op.f("ix_user_profiles_handle"), table_name="user_profiles")
    op.drop_table("user_profiles")
