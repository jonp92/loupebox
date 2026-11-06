"""per-site retention settings and the index the email-strip sweep walks

Revision ID: 0018
Revises: 0017
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sites", sa.Column("retention_delete_days", sa.Integer(), nullable=True))
    op.add_column("sites", sa.Column("retention_strip_email_days", sa.Integer(), nullable=True))
    op.create_index(
        "ix_feedback_site_email_created",
        "feedback",
        ["site_id", "created_at"],
        postgresql_where=sa.text("email IS NOT NULL"),
        sqlite_where=sa.text("email IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_feedback_site_email_created", table_name="feedback")
    op.drop_column("sites", "retention_strip_email_days")
    op.drop_column("sites", "retention_delete_days")
