"""SQLAlchemy 2.1 declarative base for the Postgres backend."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Stable, deterministic names for constraints and indexes not named by hand.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _enum_in(column: str, enum_cls) -> str:
    """SQL `column IN ('a', 'b', ...)` from a string enum's members."""
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return f"{column} IN ({values})"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
