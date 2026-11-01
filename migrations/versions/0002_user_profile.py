"""user names and avatar

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("first_name", sa.String(100), nullable=False, server_default=""))
    op.add_column("users", sa.Column("last_name", sa.String(100), nullable=False, server_default=""))
    op.add_column("users", sa.Column("avatar", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
