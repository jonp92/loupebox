"""assignee, tags and internal notes on feedback

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("feedback") as batch:
        batch.add_column(sa.Column("assignee_id", sa.Uuid()))
        batch.create_foreign_key("fk_feedback_assignee", "users", ["assignee_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_feedback_assignee_id", ["assignee_id"])
    op.create_table(
        "feedback_tags",
        sa.Column("feedback_id", sa.Uuid(), sa.ForeignKey("feedback.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag", sa.String(32), primary_key=True),
    )
    op.create_index("ix_feedback_tags_tag", "feedback_tags", ["tag"])
    op.create_table(
        "feedback_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("feedback_id", sa.Uuid(), sa.ForeignKey("feedback.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_feedback_notes_feedback_id", "feedback_notes", ["feedback_id"])


def downgrade() -> None:
    op.drop_table("feedback_notes")
    op.drop_table("feedback_tags")
    with op.batch_alter_table("feedback") as batch:
        batch.drop_index("ix_feedback_assignee_id")
        batch.drop_constraint("fk_feedback_assignee", type_="foreignkey")
        batch.drop_column("assignee_id")
