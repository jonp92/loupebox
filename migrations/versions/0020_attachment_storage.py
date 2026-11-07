"""remember which storage backend holds each image file

Revision ID: 0020
Revises: 0019
"""
import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Every image so far is on local disk.
    op.add_column(
        "feedback_attachments",
        sa.Column("storage", sa.String(16), nullable=False, server_default="local"),
    )


def downgrade() -> None:
    op.drop_column("feedback_attachments", "storage")
