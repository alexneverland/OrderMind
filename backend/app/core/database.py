from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from backend.app.config import settings

# Engine configuration: Handle SQLite specific arguments safely
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

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


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(target_engine=None) -> None:
    """Create all tables in the target database."""
    # Import all models to ensure they are registered with Base.metadata
    from backend.app.models import (
        company,
        customer,
        product,
        memory,
        order,
        export,
    )  # noqa: F401
    
    bind_engine = target_engine or engine
    Base.metadata.create_all(bind=bind_engine)
