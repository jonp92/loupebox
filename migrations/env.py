from alembic import context
from sqlalchemy import create_engine

import app.models  # noqa: F401  (register tables)
from app.core.config import settings
from app.db.base import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
