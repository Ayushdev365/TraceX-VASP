"""Identifier helpers.

Human-facing references (case refs, report refs, disclosure draft refs) appear on printed
evidence, so they are short, unambiguous and copyable by hand. Machine identifiers stay
UUID4.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

CASE_PREFIX = "VT"
REPORT_PREFIX = "VT-RPT"
DISCLOSURE_PREFIX = "VT-DISC"


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


def new_request_id() -> str:
    """Short correlation id for one HTTP request."""
    return f"req_{uuid.uuid4().hex[:16]}"


def case_ref(sequence: int, *, year: int | None = None) -> str:
    """``VT-2026-000123`` — year-scoped so refs stay short across a long deployment."""
    year = year or datetime.now(UTC).year
    return f"{CASE_PREFIX}-{year}-{sequence:06d}"


def report_ref(sequence: int) -> str:
    """``VT-RPT-000045`` — printed in the footer of every PDF page."""
    return f"{REPORT_PREFIX}-{sequence:06d}"


def disclosure_ref(sequence: int) -> str:
    """``VT-DISC-000012`` — identifies a mock disclosure draft."""
    return f"{DISCLOSURE_PREFIX}-{sequence:06d}"
