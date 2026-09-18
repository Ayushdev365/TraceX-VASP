"""Application settings.

All configuration arrives through the environment (see ``.env.example``). Settings are
validated at boot so a misconfigured deployment fails immediately and loudly rather than
halfway through an investigator's trace.

Secrets live here and nowhere else. Nothing in this module may be serialised into an API
response; ``public_config()`` is the only sanctioned way to expose values to the browser.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "staging", "production"]

# Fixed disclosure strings. Defined once, in code, so the UI, the JSON report, the PDF and
# the mock disclosure draft cannot drift apart (DPRD sec.24, sec.48 task 36).
LEAD_NOT_PROOF = "This output is an investigative lead and not legal proof."
SCORE_DISCLAIMER = "Heuristic investigative score — not a calibrated probability."
RISK_DISCLAIMER = (
    "Risk indicators are attention markers for investigator review. They are not evidence "
    "of criminal activity, and detection is limited to known labelled addresses plus simple "
    "heuristics."
)
MOCK_SAHYOG_BANNER = "DEMO / MOCK SAHYOG REQUEST — not transmitted to any portal or VASP."

# Score bands. Words, not percentages, so a band is never mistaken for a probability.
SCORE_BANDS: tuple[tuple[int, str], ...] = (
    (85, "very_strong"),
    (70, "strong"),
    (55, "moderate"),
    (35, "low"),
    (0, "insufficient"),
)


class Settings(BaseSettings):
    """Environment-backed settings, validated at import time."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ─── app ────────────────────────────────────────────────────────────────
    app_env: AppEnv = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:3000"
    engine_version: str = "0.1.0"

    demo_api_key: str = ""

    # ─── database (Phase 2) ─────────────────────────────────────────────────
    database_url: str = ""
    db_echo: bool = False

    # ─── blockchain providers (Phase 3/4) ───────────────────────────────────
    etherscan_api_key: str = ""
    etherscan_base_url: str = "https://api.etherscan.io/v2/api"
    trongrid_api_key: str = ""
    trongrid_base_url: str = "https://api.trongrid.io"
    tronscan_base_url: str = "https://apilist.tronscanapi.com/api"
    bitquery_api_key: str = ""
    bitquery_base_url: str = "https://streaming.bitquery.io/graphql"

    # ─── traversal budgets (Phase 6) ────────────────────────────────────────
    default_hop_depth: int = Field(default=3, ge=1, le=6)
    max_hop_depth: int = Field(default=6, ge=1, le=6)
    max_nodes_expanded: int = Field(default=400, ge=1)
    max_api_calls_per_trace: int = Field(default=120, ge=1)
    max_txs_per_address: int = Field(default=200, ge=1)
    wall_clock_budget_s: float = Field(default=10.0, gt=0)
    fanout_terminal: int = Field(default=500, ge=2)

    # ─── attribution / labels (Phase 7/8) ───────────────────────────────────
    min_attribution_score: int = Field(default=35, ge=0, le=100)
    stale_label_days: int = Field(default=30, ge=1)
    allow_demo_labels: bool = False
    # Serve synthetic chain data instead of calling a provider. Explicit opt-in only:
    # there is no silent fallback, and every result is labelled mock_demo end to end.
    use_mock_chain_data: bool = False

    # ─── caching & rate limiting ────────────────────────────────────────────
    chain_cache_ttl_s: int = Field(default=900, ge=0)
    rate_limit_traces_per_minute: int = Field(default=10, ge=1)
    rate_limit_traces_per_hour: int = Field(default=100, ge=1)

    # ─── derived / validation ───────────────────────────────────────────────

    @field_validator("cors_origins")
    @classmethod
    def _strip_origins(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _check_consistency(self) -> Settings:
        if self.default_hop_depth > self.max_hop_depth:
            raise ValueError(
                f"DEFAULT_HOP_DEPTH ({self.default_hop_depth}) cannot exceed "
                f"MAX_HOP_DEPTH ({self.max_hop_depth})"
            )
        if self.app_env == "production":
            # Fail fast rather than serve real case data without the basics in place.
            missing = [
                name
                for name, value in (
                    ("DEMO_API_KEY", self.demo_api_key),
                    ("DATABASE_URL", self.database_url),
                )
                if not value
            ]
            if missing:
                raise ValueError("production requires " + ", ".join(missing) + " to be set")
            if self.allow_demo_labels:
                raise ValueError("ALLOW_DEMO_LABELS must be false in production")
            if self.use_mock_chain_data:
                raise ValueError("USE_MOCK_CHAIN_DATA must be false in production")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin for origin in (o.strip() for o in self.cors_origins.split(",")) if origin]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def auth_enabled(self) -> bool:
        """MVP auth is on only when a demo key is configured (Phase 1 convenience)."""
        return bool(self.demo_api_key)

    def public_config(self) -> dict[str, Any]:
        """Non-secret configuration safe to return to the browser.

        Deliberately explicit: a new secret added to ``Settings`` cannot leak here by
        accident, because nothing is included unless it is named below.
        """
        return {
            "engine_version": self.engine_version,
            "app_env": self.app_env,
            "hop_depth": {
                "default": self.default_hop_depth,
                "min": 1,
                "max": self.max_hop_depth,
            },
            "attribution": {
                "min_attribution_score": self.min_attribution_score,
                "score_type": "heuristic_investigative_score",
                "calibrated": False,
                "bands": [{"min_score": minimum, "band": band} for minimum, band in SCORE_BANDS],
            },
            "labels": {"stale_label_days": self.stale_label_days},
            "disclaimers": {
                "lead_not_proof": LEAD_NOT_PROOF,
                "score": SCORE_DISCLAIMER,
                "risk": RISK_DISCLAIMER,
                "mock_sahyog": MOCK_SAHYOG_BANNER,
            },
        }


def score_band(score: int) -> str:
    """Map a 0-100 heuristic score onto its named band. Never rounds up (DPRD sec.24)."""
    for minimum, band in SCORE_BANDS:
        if score >= minimum:
            return band
    return "insufficient"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Use this everywhere instead of instantiating Settings."""
    return Settings()
