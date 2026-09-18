"""Settings validation and the score-band labelling policy."""

from __future__ import annotations

import logging

import pytest
from app.config import Settings, score_band
from app.core.logging import JsonFormatter, RedactingFilter


def test_default_hop_depth_cannot_exceed_max() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        Settings(default_hop_depth=5, max_hop_depth=3, _env_file=None)


def test_production_requires_key_and_database() -> None:
    with pytest.raises(ValueError, match="DEMO_API_KEY"):
        Settings(app_env="production", _env_file=None)


def test_production_refuses_demo_labels() -> None:
    with pytest.raises(ValueError, match="ALLOW_DEMO_LABELS"):
        Settings(
            app_env="production",
            demo_api_key="x" * 32,
            database_url="postgresql+psycopg://u:p@h:5432/db",
            allow_demo_labels=True,
            _env_file=None,
        )


def test_cors_origins_parse_into_a_list() -> None:
    settings = Settings(
        cors_origins="http://localhost:3000, https://vasptrace.vercel.app ",
        _env_file=None,
    )
    assert settings.cors_origin_list == [
        "http://localhost:3000",
        "https://vasptrace.vercel.app",
    ]


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (100, "very_strong"),
        (85, "very_strong"),
        (84, "strong"),
        (70, "strong"),
        (69, "moderate"),
        (55, "moderate"),
        (54, "low"),
        (35, "low"),
        (34, "insufficient"),
        (0, "insufficient"),
    ],
)
def test_score_bands_never_round_up(score: int, expected: str) -> None:
    """A score one point below a boundary must stay in the lower band (DPRD sec.24)."""
    assert score_band(score) == expected


def test_public_config_excludes_every_secret_field() -> None:
    settings = Settings(
        demo_api_key="demo-key-value-0123456789",
        etherscan_api_key="etherscan-secret-0123456789",
        trongrid_api_key="trongrid-secret-0123456789",
        database_url="postgresql+psycopg://user:pw@host:5432/db",
        _env_file=None,
    )
    serialised = str(settings.public_config())
    for secret in (
        "demo-key-value-0123456789",
        "etherscan-secret-0123456789",
        "trongrid-secret-0123456789",
        "pw@host",
    ):
        assert secret not in serialised


def test_log_redaction_scrubs_secrets_and_query_keys() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="calling https://api.etherscan.io/v2/api?module=account&apikey=SUPERSECRETKEY123",
        args=(),
        exc_info=None,
    )
    record.provider_key = "SUPERSECRETKEY123"

    assert RedactingFilter(("SUPERSECRETKEY123",)).filter(record)
    emitted = JsonFormatter().format(record)

    assert "SUPERSECRETKEY123" not in emitted
    assert "REDACTED" in emitted
