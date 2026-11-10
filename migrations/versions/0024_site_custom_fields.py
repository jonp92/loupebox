"""per-site custom fields: what the feedback form asks besides the message

Revision ID: 0024
Revises: 0023
"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sites", sa.Column("custom_fields", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("sites", "custom_fields")
