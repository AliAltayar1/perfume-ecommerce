from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase


class Base(AsyncAttrs, DeclarativeBase):
    """
    Explicit DeclarativeBase with AsyncAttrs support for modern SQLAlchemy 2.0.
    Provides async attribute loading and serves as the metadata registry for Alembic.
    """
    pass
