"""drop default ports from stored allowed origins

Browsers never send :443 / :80 in the Origin header, so a stored origin with one never matched.

Revision ID: 0014
Revises: 0013
"""
from urllib.parse import urlsplit

from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

_DEFAULT_PORTS = {"http": 80, "https": 443}
sites = sa.table("sites", sa.column("id", sa.Uuid()), sa.column("allowed_origins", sa.JSON()))


def _strip_default_port(origin: str) -> str:
    parts = urlsplit(origin)
    if parts.port is not None and parts.port == _DEFAULT_PORTS.get(parts.scheme):
        return f"{parts.scheme}://{parts.hostname}"
    return origin


def upgrade() -> None:
    conn = op.get_bind()
    for site_id, origins in conn.execute(sa.select(sites.c.id, sites.c.allowed_origins)).all():
        fixed = sorted({_strip_default_port(o) for o in origins or []})
        if fixed != origins:
            conn.execute(sites.update().where(sites.c.id == site_id).values(allowed_origins=fixed))


def downgrade() -> None:
    pass  # the old form never matched a browser Origin, so there is nothing worth restoring
