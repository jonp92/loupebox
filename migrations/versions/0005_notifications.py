"""notification channels and outbox

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "notification_channels",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("config", _JSON, nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("min_role", sa.Enum("viewer", "editor", "admin", name="role", native_enum=False, length=16), nullable=False),
        sa.Column("extra_recipients", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_notification_channels_site_id", "notification_channels", ["site_id"])

    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("channel_id", sa.Uuid(), sa.ForeignKey("notification_channels.id", ondelete="SET NULL")),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("payload", _JSON, nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "sending", "sent", "failed", "held", name="outboxstatus", native_enum=False, length=16),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("summary_id", sa.Uuid()),
        sa.Column("provider_message_id", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_notification_outbox_channel_id", "notification_outbox", ["channel_id"])
    op.create_index("ix_notification_outbox_site_id", "notification_outbox", ["site_id"])
    op.create_index("ix_outbox_status_next", "notification_outbox", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_table("notification_outbox")
    op.drop_table("notification_channels")
