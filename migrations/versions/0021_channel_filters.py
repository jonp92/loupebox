"""per-channel filters: only notify for the items a channel is interested in

Revision ID: 0021
Revises: 0020
"""
import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # An empty filter matches everything, so existing channels behave as before.
    op.add_column(
        "notification_channels",
        sa.Column("filters", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("notification_channels", "filters")
