"""Portable column types and schema helpers.

PostgreSQL is the deployment target; SQLite is the development fallback when
``DATABASE_URL`` is unset. These types render the best native form per dialect so one set
of models and one migration serves both — a ``JSONType`` column becomes ``JSONB`` on
Postgres and ``JSON`` on SQLite, with no branching in the models.

They are ``TypeDecorator`` subclasses rather than ``with_variant`` so that Alembic
autogenerate emits the class name (``app.database.types.JSONType()``) and the Postgres
behaviour survives into the migration file.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Dialect
from sqlalchemy.sql.type_api import TypeEngine
from sqlalchemy.types import TypeDecorator

#: Address column width. The longest form we store is a Tron base58check address (34) or an
#: Ethereum 0x-hex address (42); 128 leaves room for Bitcoin and Solana without a migration.
ADDRESS_LEN = 128
TX_HASH_LEN = 128

#: Amounts are exact decimals, never floats. 38 total digits with 18 after the point covers
#: an 18-decimal ERC-20 token at any realistic supply.
AMOUNT_PRECISION = 38
AMOUNT_SCALE = 18

#: Raw base-unit integers (wei, sun) are stored as strings so no precision is lost and no
#: bigint overflow is possible.
AMOUNT_RAW_LEN = 80


class JSONType(TypeDecorator[Any]):
    """``JSONB`` on PostgreSQL, ``JSON`` elsewhere."""

    impl = sa.JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.JSONB())  # type: ignore[no-untyped-call]
        return dialect.type_descriptor(sa.JSON())


def Amount() -> sa.Numeric[Any]:
    """Exact decimal amount column."""
    return sa.Numeric(AMOUNT_PRECISION, AMOUNT_SCALE, asdecimal=True)


def Timestamp() -> sa.DateTime:
    """Timezone-aware timestamp. Every stored instant is UTC."""
    return sa.DateTime(timezone=True)


def enum_check(column: str, values: type, *, name: str) -> sa.CheckConstraint:
    """A ``CHECK`` constraint restricting ``column`` to a StrEnum's members.

    Enumerations are stored as ``VARCHAR`` with a check rather than as a native PG ``ENUM``:
    adding a value then costs a constraint swap instead of an ``ALTER TYPE`` migration, and
    the same DDL works on SQLite. The allowed set is generated from the Python enum, so the
    database and ``app/schemas/common.py`` cannot drift apart.
    """
    allowed = ", ".join(f"'{member.value}'" for member in values)  # type: ignore[attr-defined]
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=name)
