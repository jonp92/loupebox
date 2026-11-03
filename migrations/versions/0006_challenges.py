"""public-ingest challenges: per-site mode/config and the replay guard

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sites", sa.Column("challenge_mode", sa.String(24), nullable=False, server_default="off"))
    op.add_column("sites", sa.Column("challenge_config", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table(
        "used_challenges",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_used_challenges_expires_at", "used_challenges", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_used_challenges_expires_at", table_name="used_challenges")
    op.drop_table("used_challenges")
    op.drop_column("sites", "challenge_config")
    op.drop_column("sites", "challenge_mode")
