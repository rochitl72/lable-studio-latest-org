"""Async SQLAlchemy session + Base setup.

Production target is PostgreSQL (asyncpg). The test suite points DATABASE_URL
at SQLite, which is why the connect args are dialect-dependent.
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

log = logging.getLogger("annoforge.db")


class Base(DeclarativeBase):
    pass


def _engine_kwargs() -> dict:
    if settings.is_sqlite:
        # SQLite needs this to be usable from more than one thread.
        return {"connect_args": {"check_same_thread": False}}
    # Postgres: keep a modest pool and recycle connections so a restarted
    # database server doesn't leave stale handles behind.
    return {
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }


engine = create_async_engine(
    settings.DATABASE_URL, echo=False, future=True, **_engine_kwargs()
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# Columns added to EXISTING tables after the first release. `create_all` can
# add whole missing tables, but it will not add a column to a table that already
# exists — so a database created by an older version of the app would be missing
# these, and every query touching that table would fail (e.g. login → 500).
# We reconcile them explicitly on startup with ADD COLUMN IF NOT EXISTS, which
# is a no-op once the column is present. Add future additive columns here.
#
# Format: (table, column, Postgres column definition).
_ADDITIVE_COLUMNS = [
    ("users", "must_change_password", "BOOLEAN NOT NULL DEFAULT FALSE"),
]


def _reconcile_sync(sync_conn) -> None:
    """Add any post-release columns that a pre-existing table is missing.

    Works on both PostgreSQL and SQLite by asking the database which columns
    actually exist (via the inspector) and issuing a plain `ADD COLUMN` only for
    the ones that don't — so we never depend on `ADD COLUMN IF NOT EXISTS`,
    which SQLite lacks. If the table itself is absent, `create_all` already made
    it fresh with every column, so there's nothing to do.
    """
    from sqlalchemy import inspect as sa_inspect

    insp = sa_inspect(sync_conn)
    tables = set(insp.get_table_names())
    for table, column, ddl in _ADDITIVE_COLUMNS:
        if table not in tables:
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        if column in existing:
            continue
        try:
            sync_conn.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN {column} {ddl}')
            log.info("Reconciled missing column %s.%s", table, column)
        except Exception:
            # Never let reconciliation crash startup — log and continue so the
            # rest of the app can still come up (and the operator can migrate).
            log.exception("Could not reconcile column %s.%s", table, column)


async def init_db():
    """Create any missing tables, reconcile added columns, then seed accounts.

    Two schema steps run here so a fresh OR an older database both end up
    correct without a manual migration:
      1. `create_all` adds any whole tables the models define but the database
         lacks (e.g. `project_members` on an older DB).
      2. `_reconcile_additive_columns` adds columns that were introduced on
         already-existing tables (which `create_all` can't do).
    For controlled, versioned changes, Alembic (`alembic upgrade head`) is still
    the source of truth; this startup reconciliation is a safety net so the app
    is never left un-runnable by simple additive drift.
    """
    import app.models  # noqa: F401  — registers the mappings

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_reconcile_sync)

    from app.db.bootstrap import ensure_bootstrap_admin, ensure_seed_test_user

    await ensure_bootstrap_admin()
    await ensure_seed_test_user()
