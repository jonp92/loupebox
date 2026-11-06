"""trigram indexes so searching feedback does not read every row of the site

Revision ID: 0017
Revises: 0016

Postgres only. Search is `ILIKE '%term%'` on message, email and name, which a plain index cannot serve.
`pg_trgm` is a trusted extension from Postgres 13, so the database owner can create it. If the database
refuses (an older server, a restricted role), the migration goes on without the indexes: search still works,
it is just slower on a large site. Create the extension as a superuser and run this migration again by
downgrading to 0016 and upgrading.
"""
import warnings

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

COLUMNS = ("message", "email", "name")


def _name(column: str) -> str:
    return f"ix_feedback_{column}_trgm"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    try:
        with bind.begin_nested():  # a failed CREATE EXTENSION must not abort the whole migration
            op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    except sa.exc.DBAPIError as e:
        warnings.warn(f"pg_trgm is not available, so search stays unindexed: {str(e.orig).splitlines()[0]}")
        return
    for column in COLUMNS:
        op.create_index(
            _name(column), "feedback", [column], postgresql_using="gin", postgresql_ops={column: "gin_trgm_ops"}
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for column in COLUMNS:  # the extension stays: other things in the database may use it
        op.execute(f"DROP INDEX IF EXISTS {_name(column)}")
