"""Synthetic demo label generator.

    python -m app.database.seeds.demo_fixtures --out ../data/labels/demo

Why this exists: Phases 6-9 need *some* labels to develop and test against, and the demo
needs a path that reliably terminates at a VASP. Why it is built this way:

* **The VASP names are fictional.** "Meridian Digital Exchange" is not a real company. A
  fabricated address is never attached to a real exchange's name, because that would be a
  false factual claim about a real business — the thing the brief's "never invent VASP
  addresses" rule exists to prevent.
* **The addresses are derived deterministically** from documented seed strings (below), not
  copied from any chain. They are structurally valid so the validators and matcher exercise
  real code paths, and they are astronomically unlikely to collide with a real address.
* **Everything imports at ``demo_unverified``**, the lowest reliability tier, which the
  attribution engine refuses to treat as sufficient evidence on its own (Phase 8).
* **Import is opt-in** (``ALLOW_DEMO_LABELS`` / ``--allow-demo``) and refused in production.

The generator is committed rather than its output alone so anyone can re-derive the files and
confirm no real-world address was smuggled in.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.blockchain.addresses import (
    TRON_ADDRESS_PREFIX,
    b58check_encode,
    to_eip55,
)

#: Namespace mixed into every seed so these addresses cannot coincide with anything derived
#: elsewhere, and so the derivation is auditable from this file alone.
SEED_NAMESPACE = "VASPTrace/synthetic-demo-fixture/v1"

SOURCE_NAME = "VASPTrace synthetic demo fixture (NOT REAL DATA)"
SOURCE_URL = "file:data/labels/PROVENANCE.md#synthetic-demo-fixture"


def derive_address(chain: str, seed: str) -> str:
    """Derive a structurally valid address from a seed string, deterministically."""
    digest = hashlib.sha256(f"{SEED_NAMESPACE}|{chain}|{seed}".encode()).digest()
    body = digest[:20]
    if chain == "ethereum":
        return to_eip55("0x" + body.hex())
    if chain == "tron":
        return b58check_encode(bytes([TRON_ADDRESS_PREFIX]) + body)
    raise ValueError(f"no derivation defined for chain {chain!r}")


@dataclass(frozen=True, slots=True)
class DemoVasp:
    slug: str
    name: str
    kind: str
    jurisdiction: str
    #: (chain, address_type, seed) per owned address
    addresses: tuple[tuple[str, str, str], ...]


# Fictional service providers. Any resemblance to a real exchange's name is unintended.
DEMO_VASPS: tuple[DemoVasp, ...] = (
    DemoVasp(
        slug="demo-meridian-exchange",
        name="DEMO — Meridian Digital Exchange",
        kind="exchange",
        jurisdiction="SG",
        addresses=(
            ("ethereum", "hot_wallet", "meridian/eth/hot/1"),
            ("ethereum", "deposit", "meridian/eth/deposit/1"),
            ("ethereum", "deposit", "meridian/eth/deposit/2"),
            ("tron", "hot_wallet", "meridian/trx/hot/1"),
            ("tron", "deposit", "meridian/trx/deposit/1"),
        ),
    ),
    DemoVasp(
        slug="demo-kavach-custody",
        name="DEMO — Kavach Custody Services",
        kind="custodial_wallet",
        jurisdiction="IN",
        addresses=(
            ("ethereum", "hot_wallet", "kavach/eth/hot/1"),
            ("tron", "deposit", "kavach/trx/deposit/1"),
            ("tron", "deposit", "kavach/trx/deposit/2"),
        ),
    ),
    DemoVasp(
        slug="demo-northwind-otc",
        name="DEMO — Northwind OTC Desk",
        kind="otc_desk",
        jurisdiction="AE",
        addresses=(
            ("ethereum", "hot_wallet", "northwind/eth/hot/1"),
            ("tron", "hot_wallet", "northwind/trx/hot/1"),
        ),
    ),
)

# Fictional obfuscation services, for exercising the risk engine (Phase 9).
DEMO_RISK_ENTITIES: tuple[tuple[str, str, str, str, str], ...] = (
    # (chain, entity_kind, entity_name, severity, seed)
    ("ethereum", "mixer", "DEMO — Obscura Mixer", "high", "obscura/eth/router/1"),
    ("ethereum", "mixer", "DEMO — Obscura Mixer", "high", "obscura/eth/router/2"),
    ("tron", "mixer", "DEMO — Obscura Mixer", "high", "obscura/trx/router/1"),
    ("ethereum", "bridge", "DEMO — Causeway Bridge", "medium", "causeway/eth/bridge/1"),
    ("tron", "bridge", "DEMO — Causeway Bridge", "medium", "causeway/trx/bridge/1"),
    ("ethereum", "gambling", "DEMO — Rollhouse Casino", "low", "rollhouse/eth/1"),
)

VASP_HEADER = (
    "vasp_slug",
    "vasp_name",
    "vasp_kind",
    "jurisdiction",
    "chain",
    "address",
    "address_type",
    "verification_status",
    "notes",
)
RISK_HEADER = (
    "chain",
    "address",
    "entity_kind",
    "entity_name",
    "severity",
    "verification_status",
    "notes",
)

NOTE = "Synthetic demo fixture — not a real address and not a real service provider."


def write_fixtures(out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)

    vasp_path = out_dir / "demo_vasp_addresses.csv"
    with vasp_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(VASP_HEADER)
        for vasp in DEMO_VASPS:
            for chain, address_type, seed in vasp.addresses:
                writer.writerow(
                    (
                        vasp.slug,
                        vasp.name,
                        vasp.kind,
                        vasp.jurisdiction,
                        chain,
                        derive_address(chain, seed),
                        address_type,
                        "unverified",
                        NOTE,
                    )
                )

    risk_path = out_dir / "demo_risk_entities.csv"
    with risk_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(RISK_HEADER)
        for chain, kind, name, severity, seed in DEMO_RISK_ENTITIES:
            writer.writerow(
                (chain, derive_address(chain, seed), kind, name, severity, "unverified", NOTE)
            )

    return vasp_path, risk_path


def main(argv: list[str] | None = None) -> int:
    default_out = (
        Path(__file__).resolve().parents[3] / ".." / "data" / "labels" / "demo"
    ).resolve()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=default_out)
    args = parser.parse_args(argv)

    vasp_path, risk_path = write_fixtures(args.out)
    vasp_rows = sum(len(v.addresses) for v in DEMO_VASPS)
    print(f"wrote {vasp_path} ({vasp_rows} addresses across {len(DEMO_VASPS)} demo VASPs)")
    print(f"wrote {risk_path} ({len(DEMO_RISK_ENTITIES)} demo risk entities)")
    print("\nThese are synthetic. They are not real addresses and not real service providers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
