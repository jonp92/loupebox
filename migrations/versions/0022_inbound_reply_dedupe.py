"""inbound email: store each customer reply once

Revision ID: 0022
Revises: 0021
"""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

WHERE = sa.text("direction = 'inbound' AND message_id IS NOT NULL")


def upgrade() -> None:
    op.create_index(
        "uq_feedback_replies_inbound_message_id",
        "feedback_replies",
        ["message_id"],
        unique=True,
        postgresql_where=WHERE,
        sqlite_where=WHERE,
    )


def downgrade() -> None:
    op.drop_index("uq_feedback_replies_inbound_message_id", table_name="feedback_replies")
