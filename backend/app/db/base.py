import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for AI QA & Release Engineer."""


def utcnow() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def new_id() -> str:
    """Return a string UUIDv4 identifier."""
    return str(uuid.uuid4())
