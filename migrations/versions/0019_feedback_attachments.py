"""images sent with feedback, and the per-site switch for them

Revision ID: 0019
Revises: 0018
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sites", sa.Column("attachments_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "feedback_attachments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("feedback_id", sa.Uuid(), sa.ForeignKey("feedback.id", ondelete="CASCADE"), nullable=False),
        sa.Column("site_id", sa.Uuid(), sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_key", sa.String(100), nullable=False, unique=True),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_feedback_attachments_feedback_id", "feedback_attachments", ["feedback_id"])
    op.create_index("ix_feedback_attachments_site_id", "feedback_attachments", ["site_id"])


def downgrade() -> None:
    op.drop_table("feedback_attachments")
    op.drop_column("sites", "attachments_enabled")
