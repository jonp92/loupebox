"""index for the list's counts and status filters

Revision ID: 0016
Revises: 0015
"""
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_feedback_site_status_created", "feedback", ["site_id", "status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_feedback_site_status_created", table_name="feedback")
