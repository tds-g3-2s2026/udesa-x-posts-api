"""The transactional outbox.

Every event this service publishes is written here, in the same transaction as
the change that caused it, and the publisher sends it to RabbitMQ and deletes
the row once the broker confirms it.

The trigger calls `pg_notify` on every INSERT. The notification is delivered
only when the transaction commits, so the publisher never wakes up for a row it
cannot see yet.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_outbox"
down_revision = "0009_cuenta_eliminada"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_outbox_created_at"), "outbox", ["created_at"], unique=False)
    op.execute(
        """
        CREATE FUNCTION outbox_notify() RETURNS trigger AS $$
        BEGIN
            PERFORM pg_notify('outbox', NEW.id::text);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER outbox_notify_after_insert
        AFTER INSERT ON outbox
        FOR EACH ROW EXECUTE FUNCTION outbox_notify()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER outbox_notify_after_insert ON outbox")
    op.execute("DROP FUNCTION outbox_notify()")
    op.drop_index(op.f("ix_outbox_created_at"), table_name="outbox")
    op.drop_table("outbox")
