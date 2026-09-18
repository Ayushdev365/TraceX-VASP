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

from decimal import Decimal
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


class ExactDecimal(TypeDecorator[Decimal]):
    """Exact decimal storage on both dialects.

    PostgreSQL ``NUMERIC`` is exact. SQLite has no decimal type: SQLAlchemy's ``Numeric``
    routes through a C double there, so ``1234.567890123456789012`` reads back as
    ``1234.567890123456891160`` — silently wrong in the eighteenth decimal place.

    That is not tolerable for a system whose output is meant to be evidentiary: a report has
    to show the amount that actually moved. On SQLite the value is therefore stored as text
    and parsed back to ``Decimal``, which is exact. The dev fallback then behaves like
    production instead of being quietly less trustworthy.
    """

    impl = sa.Numeric
    cache_ok = True

    def __init__(
        self,
        precision: int = AMOUNT_PRECISION,
        scale: int = AMOUNT_SCALE,
        **kwargs: Any,
    ) -> None:
        # Alembic autogenerate renders this as ``ExactDecimal(precision=38, scale=18)``, so
        # the signature has to accept what it emits.
        kwargs.pop("asdecimal", None)
        super().__init__(precision, scale, asdecimal=True, **kwargs)

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "sqlite":
            return dialect.type_descriptor(sa.String(AMOUNT_RAW_LEN))
        return dialect.type_descriptor(sa.Numeric(AMOUNT_PRECISION, AMOUNT_SCALE, asdecimal=True))

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> Any:
        if value is None:
            return None
        if dialect.name == "sqlite":
            return format(value, "f")  # plain notation, never scientific
        return value

    def process_result_value(self, value: Any, dialect: Dialect) -> Decimal | None:
        if value is None:
            return None
        return value if isinstance(value, Decimal) else Decimal(str(value))


def Amount() -> ExactDecimal:
    """Exact decimal amount column."""
    return ExactDecimal()


def format_amount(value: Decimal | None) -> str | None:
    """Render an amount for the API, a report or a PDF.

    Always plain notation: ``Decimal("0.000000000000000001")`` reprs as ``1E-18``, which
    is correct but unreadable on an evidence table and easy to misread as a different
    magnitude. Trailing zeros are trimmed so ``1.5`` does not print as
    ``1.500000000000000000``.
    """
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


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
