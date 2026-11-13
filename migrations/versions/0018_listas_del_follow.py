"""Each membership of a list hangs from the owner's follow of that account (E3-H8).

0017 pointed the membership at the account alone. Now it points at the follow, so
deleting the follow (unfollow, block or closing the account) takes the account
out of every list of the owner in the same statement.

Revision ID: 0018_listas_del_follow
Revises: 0017_listas
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_listas_del_follow"
down_revision: str | None = "0017_listas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_lists_id_owner", "lists", ["id", "owner_id"])
    op.add_column("list_members", sa.Column("owner_id", sa.UUID(), nullable=True))
    op.execute(
        "UPDATE list_members AS m SET owner_id = l.owner_id FROM lists AS l WHERE l.id = m.list_id"
    )
    # A membership whose follow is already gone would break the new key.
    op.execute(
        "DELETE FROM list_members AS m WHERE NOT EXISTS ("
        "SELECT 1 FROM follows AS f "
        "WHERE f.follower_id = m.owner_id AND f.followee_id = m.member_id)"
    )
    op.alter_column("list_members", "owner_id", nullable=False)

    op.drop_index("ix_list_members_member", table_name="list_members")
    op.drop_constraint("list_members_list_id_fkey", "list_members", type_="foreignkey")
    op.drop_constraint("list_members_member_id_fkey", "list_members", type_="foreignkey")
    op.create_foreign_key(
        "fk_list_members_list_owner",
        "list_members",
        "lists",
        ["list_id", "owner_id"],
        ["id", "owner_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_list_members_follow",
        "list_members",
        "follows",
        ["owner_id", "member_id"],
        ["follower_id", "followee_id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_list_members_owner_member", "list_members", ["owner_id", "member_id"])


def downgrade() -> None:
    op.drop_index("ix_list_members_owner_member", table_name="list_members")
    op.drop_constraint("fk_list_members_follow", "list_members", type_="foreignkey")
    op.drop_constraint("fk_list_members_list_owner", "list_members", type_="foreignkey")
    op.create_foreign_key(
        "list_members_list_id_fkey",
        "list_members",
        "lists",
        ["list_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "list_members_member_id_fkey",
        "list_members",
        "user_profiles",
        ["member_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_list_members_member", "list_members", ["member_id"])
    op.drop_column("list_members", "owner_id")
    op.drop_constraint("uq_lists_id_owner", "lists", type_="unique")
