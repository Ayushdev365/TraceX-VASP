"""Label-source manifest parsing.

A manifest declares, for every label file, where the data came from and under what terms.
The importer refuses to run without one, which is the mechanism behind the rule "never
invent VASP addresses": a label with no citable source cannot physically enter the database,
because there is nowhere to put it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from app.schemas.common import LabelTier, Severity


class SourceKind(StrEnum):
    VASP_ADDRESSES = "vasp_addresses"
    RISK_ENTITIES = "risk_entities"


class ManifestError(ValueError):
    """Raised when a manifest is malformed or a declared file is missing."""


@dataclass(frozen=True, slots=True)
class LabelSource:
    """One declared label file."""

    name: str
    kind: SourceKind
    url: str
    path: Path
    tier: LabelTier
    licence: str
    retrieved: date
    default_severity: Severity | None = None
    notes: str | None = None

    def sha256(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class LabelManifest:
    version: str
    sources: tuple[LabelSource, ...]
    path: Path

    @property
    def demo_sources(self) -> tuple[LabelSource, ...]:
        return tuple(s for s in self.sources if s.tier is LabelTier.DEMO_UNVERIFIED)

    def without_demo(self) -> LabelManifest:
        kept = tuple(s for s in self.sources if s.tier is not LabelTier.DEMO_UNVERIFIED)
        return LabelManifest(version=self.version, sources=kept, path=self.path)


_REQUIRED_SOURCE_FIELDS = ("name", "kind", "url", "file", "tier", "licence", "retrieved")


def _parse_source(raw: Any, index: int, base_dir: Path) -> LabelSource:
    if not isinstance(raw, dict):
        raise ManifestError(f"sources[{index}] must be a mapping")

    missing = [field for field in _REQUIRED_SOURCE_FIELDS if not raw.get(field)]
    if missing:
        raise ManifestError(
            f"sources[{index}] ({raw.get('name', 'unnamed')}) is missing required "
            f"field(s): {', '.join(missing)}. Every label file must declare where it came "
            f"from — an uncited label cannot be imported."
        )

    try:
        kind = SourceKind(raw["kind"])
    except ValueError as exc:
        raise ManifestError(
            f"sources[{index}] has kind={raw['kind']!r}; expected one of "
            f"{', '.join(k.value for k in SourceKind)}"
        ) from exc

    try:
        tier = LabelTier(raw["tier"])
    except ValueError as exc:
        raise ManifestError(
            f"sources[{index}] has tier={raw['tier']!r}; expected one of "
            f"{', '.join(t.value for t in LabelTier)}"
        ) from exc

    url = str(raw["url"])
    if not (url.startswith(("http://", "https://")) or url.startswith("file:")):
        raise ManifestError(
            f"sources[{index}] url must be a citable http(s) URL, or a file: reference for "
            f"a locally-documented synthetic source; got {url!r}"
        )

    path = (base_dir / str(raw["file"])).resolve()

    retrieved_raw = raw["retrieved"]
    retrieved = (
        retrieved_raw if isinstance(retrieved_raw, date) else date.fromisoformat(str(retrieved_raw))
    )

    severity = Severity(raw["default_severity"]) if raw.get("default_severity") else None

    return LabelSource(
        name=str(raw["name"]),
        kind=kind,
        url=url,
        path=path,
        tier=tier,
        licence=str(raw["licence"]),
        retrieved=retrieved,
        default_severity=severity,
        notes=str(raw["notes"]) if raw.get("notes") else None,
    )


def load_manifest(path: Path) -> LabelManifest:
    """Parse and validate a manifest. Raises :class:`ManifestError` on any problem."""
    if not path.exists():
        raise ManifestError(f"manifest not found: {path}")

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ManifestError(f"{path} must contain a YAML mapping")

    version = document.get("version")
    if not version:
        raise ManifestError(
            f"{path} must declare a 'version' — it becomes the dataset version pinned to "
            f"every trace for reproducibility"
        )

    raw_sources = document.get("sources") or []
    if not isinstance(raw_sources, list):
        raise ManifestError(f"{path}: 'sources' must be a list")

    base_dir = path.parent
    sources = tuple(_parse_source(raw, index, base_dir) for index, raw in enumerate(raw_sources))

    missing_files = [str(s.path) for s in sources if not s.path.exists()]
    if missing_files:
        raise ManifestError("declared label file(s) not found: " + ", ".join(missing_files))

    return LabelManifest(version=str(version), sources=sources, path=path)
