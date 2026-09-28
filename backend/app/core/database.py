from typing import Generator
import sqlite3
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from backend.app.config import settings

SQLITE_BUSY_TIMEOUT_MS = 5000

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Apply connection-local SQLite settings to every pooled connection."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        finally:
            cursor.close()

if make_url(settings.DATABASE_URL).get_backend_name() != "sqlite":
    raise ValueError("OrderMind currently supports SQLite databases only")

# FastAPI may use a DB connection on another worker thread. SQLite's normal
# SQLAlchemy pool is sufficient; the timeout limits waits on short write locks.
connect_args = {"check_same_thread": False, "timeout": SQLITE_BUSY_TIMEOUT_MS / 1000}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=False,
    future=True
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
    future=True
)

Base = declarative_base()


def enable_sqlite_wal(database_engine: Engine = engine) -> str:
    """Enable persistent WAL once at app startup, outside a transaction."""
    if database_engine.url.database in (None, ":memory:"):
        return "memory"
    with database_engine.connect() as connection:
        mode = connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar_one()
    if mode.lower() != "wal":
        raise RuntimeError(f"SQLite WAL mode could not be enabled: {mode}")
    return mode.lower()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
