"""store avatars as bytes served from a route, not data URLs

Revision ID: 0003
Revises: 0002
"""
import base64
import re
from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_DATA_URL = re.compile(r"^data:(image/(?:png|jpeg|webp));base64,(.+)$", re.S)


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_data", sa.LargeBinary(), nullable=True))
    op.add_column("users", sa.Column("avatar_type", sa.String(16), nullable=True))
    op.add_column("users", sa.Column("avatar_updated_at", sa.DateTime(timezone=True), nullable=True))

    conn = op.get_bind()
    users = sa.table(
        "users",
        sa.column("id"),
        sa.column("avatar", sa.Text),
        sa.column("avatar_data", sa.LargeBinary),
        sa.column("avatar_type", sa.String),
        sa.column("avatar_updated_at", sa.DateTime(timezone=True)),
    )
    for uid, avatar in conn.execute(sa.select(users.c.id, users.c.avatar).where(users.c.avatar.isnot(None))):
        m = _DATA_URL.match(avatar)
        if not m:
            continue
        conn.execute(
            users.update()
            .where(users.c.id == uid)
            .values(avatar_data=base64.b64decode(m[2]), avatar_type=m[1], avatar_updated_at=datetime.now(UTC))
        )

    with op.batch_alter_table("users") as batch:
        batch.drop_column("avatar")


def downgrade() -> None:
    op.add_column("users", sa.Column("avatar", sa.Text(), nullable=True))
    conn = op.get_bind()
    users = sa.table(
        "users",
        sa.column("id"),
        sa.column("avatar", sa.Text),
        sa.column("avatar_data", sa.LargeBinary),
        sa.column("avatar_type", sa.String),
    )
    rows = conn.execute(
        sa.select(users.c.id, users.c.avatar_data, users.c.avatar_type).where(users.c.avatar_data.isnot(None))
    )
    for uid, data, mime in rows:
        url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
        conn.execute(users.update().where(users.c.id == uid).values(avatar=url))
    with op.batch_alter_table("users") as batch:
        batch.drop_column("avatar_updated_at")
        batch.drop_column("avatar_type")
        batch.drop_column("avatar_data")
