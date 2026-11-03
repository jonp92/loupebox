"""notification channels: encrypted signing secret (webhooks)

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notification_channels", sa.Column("secret", sa.String(255)))


def downgrade() -> None:
    op.drop_column("notification_channels", "secret")
