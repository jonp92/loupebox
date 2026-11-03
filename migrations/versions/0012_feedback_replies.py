"""replies to the person who sent feedback

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback_replies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("feedback_id", sa.Uuid(), sa.ForeignKey("feedback.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("error", sa.String(300)),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("message_id", sa.String(128)),
        sa.Column("in_reply_to", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_feedback_replies_feedback_id", "feedback_replies", ["feedback_id"])


def downgrade() -> None:
    op.drop_table("feedback_replies")
