"""Database initialization script for KisanVaani.

Creates SQLite tables defined in db.models.
Run as: python -m db.init_db  (from the kisanvaani/ directory)
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

# Allow running as `python -m db.init_db` from the kisanvaani/ directory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import DATABASE_URL  # noqa: E402
from db.models import Base  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def get_engine(database_url: str = DATABASE_URL):
    """Create a SQLAlchemy engine for the configured database."""
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, echo=False, future=True, connect_args=connect_args)


def ensure_sqlite_dir(database_url: str) -> None:
    """Ensure the parent directory exists for a SQLite database URL."""
    if not database_url.startswith("sqlite:///"):
        return
    db_path = Path(database_url.replace("sqlite:///", "", 1))
    if not db_path.is_absolute():
        db_path = (PROJECT_ROOT / db_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("SQLite directory ready: %s", db_path.parent)


def init_db(database_url: str = DATABASE_URL) -> None:
    """Create all database tables if they do not exist."""
    try:
        ensure_sqlite_dir(database_url)
        engine = get_engine(database_url)
        Base.metadata.create_all(engine)
        table_names = inspect(engine).get_table_names()
        logger.info("Database initialized at %s", database_url)
        logger.info("Tables present: %s", ", ".join(sorted(table_names)) or "<none>")
    except Exception:
        logger.exception("Database initialization failed")
        raise


if __name__ == "__main__":
    init_db()
