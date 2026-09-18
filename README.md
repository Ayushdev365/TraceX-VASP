# VASPTrace

**Automated Blockchain Intelligence & VASP Attribution Engine**
Smart India Hackathon 2026 · Problem Statement **SIH26182** · Team **TraceX**

Traces an unknown cryptocurrency wallet across a blockchain transaction graph, matches the
addresses it visits against a labelled Virtual Asset Service Provider (VASP) dataset, and
returns ranked candidate attributions with an explainable score breakdown, risk indicators, a
hop-by-hop evidence trail, an investigation-ready report, and a **mock** SAHYOG-shaped
disclosure draft.

---

## What this system claims, and what it does not

This matters more than any feature, and it is enforced in code rather than stated only here.

**It does:**
- identify a **wallet-to-VASP relationship** within a bounded hop depth, from public on-chain data;
- show the exact path, transactions and labels behind every attribution, so an investigator can verify it independently;
- report **"No reliable VASP attribution found"** when the evidence is insufficient, rather than forcing a result.

**It does not:**
- identify any wallet owner's real-world identity;
- execute any freezing, blocking or account-suspension action;
- submit anything to SAHYOG or to any VASP — disclosure output is a draft for an officer to review;
- present a calibrated probability. The attribution score is an **explicitly-labelled heuristic** until validated against a ground-truth set.

> **This output is an investigative lead and not legal proof.**

---

## Status

Phase 5 of 16 complete — data layer finished. See
[docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) for the full phase plan.

| Phase | Scope | Status |
|---|---|---|
| 0 | Architecture, data model, API contract, plan | Done |
| 1 | Backend + frontend shells, config, logging, error envelope, health | Done |
| 2 | PostgreSQL schema, VASP label import with provenance enforcement | Done |
| 3 | Ethereum adapter, provider HTTP layer, address validation | Done |
| 4 | Tron adapter + offline MockAdapter | Done |
| 5 | Transaction normalization + observation store | Done |
| 6 | NetworkX graph traversal engine | Next |
| 7–9 | VASP matching, attribution scoring, risk engine | Planned |
| 10–13 | Investigator workflow, interactive graph, reports, mock SAHYOG | Planned |
| 14–16 | ML experiment, testing/security, deployment | Planned |

Tracing is not available yet: the intake form is present but submission is disabled, because
the traversal engine lands in Phase 6. Nothing in the UI is wired to placeholder data.

**Label coverage today is the synthetic demo fixture only** — fictional VASPs with
deterministically-derived addresses, at the lowest reliability tier, opt-in via
`ALLOW_DEMO_LABELS` and refused in production. Real label sources are an open decision; see
[data/labels/PROVENANCE.md](data/labels/PROVENANCE.md).

---

## Documentation

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layers, request path, key decisions, adapter contract, graph rules, scoring formula |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Every table, column, constraint and index; label-import rules |
| [docs/API_CONTRACT.md](docs/API_CONTRACT.md) | Endpoints, payload shapes, error codes |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Repository assessment, file tree, 16 phases with gates, risks, open questions |

---

## Getting started

Requires **Python 3.11+** and **Node 20+**. No Docker or local PostgreSQL needed.

```bash
# 1. install both sides
make install

# 2. configure
cp .env.example backend/.env            # backend settings and provider keys
cp frontend/.env.example frontend/.env.local

# 3. run (two terminals)
make backend     # http://127.0.0.1:8000  — API docs at /api/v1/docs
make frontend    # http://localhost:3000  — investigator dashboard
```

The dashboard header shows a live engine indicator. With no keys configured it reports
`4 not configured`, which is correct: an unconfigured dependency is named rather than
disguised as healthy.

### Development commands

```bash
make check          # lint + typecheck + test — run before every commit
make lint           # ruff (backend) + eslint (frontend)
make typecheck      # mypy --strict (backend) + tsc --noEmit (frontend)
make test           # pytest
make format         # ruff auto-fix
```

### Database and labels

```bash
make migrate        # apply migrations (Supabase, or the local SQLite fallback)
make migration m="add x"   # generate a migration after changing a model
make seed-check     # validate label sources + integrity scan, writing nothing
make seed           # import real label sources (skips demo_unverified)
make seed-demo      # import including the synthetic demo fixture
make demo-fixtures  # regenerate the synthetic demo label files
```

`make seed-check` is worth running before any import: it validates every row, runs the
duplicate/conflict/format scan, and rolls back. An import either applies completely or writes
nothing.

---

## Configuration

Copy `.env.example` and fill in what you have; the app starts with an empty configuration and
reports what is missing.

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Supabase/PostgreSQL connection string (Phase 2) |
| `ETHERSCAN_API_KEY` | Ethereum transaction data |
| `TRONGRID_API_KEY` | Tron transaction data |
| `USE_MOCK_CHAIN_DATA` | Serve labelled synthetic chain data offline; refused in production |
| `DEMO_API_KEY` | Bearer key the frontend proxy sends to the backend |
| `DEFAULT_HOP_DEPTH` / `MAX_HOP_DEPTH` | Traversal depth (3 / 6) |
| `MIN_ATTRIBUTION_SCORE` | Below this, no attribution is returned (35) |
| `ALLOW_DEMO_LABELS` | Permit `demo_unverified` labels; refused in production |

**Secrets never reach the browser.** The frontend calls the backend only through a Next.js
server-side route handler (`src/app/api/backend/[...path]/route.ts`) which injects the key
server-side. No variable holding a secret is prefixed `NEXT_PUBLIC_`, and
`app/core/logging.py` redacts configured secret values and key-bearing query parameters from
every log line.

Without a chain's API key its adapter refuses to run and says exactly why
(`PROVIDER_NOT_CONFIGURED`, naming the missing setting) rather than silently substituting
demo data — "no key" and "provider down" need different fixes.

To work offline, set `USE_MOCK_CHAIN_DATA=true`. That is an **explicit opt-in**: there is no
silent fallback. Everything it returns carries `data_provenance: mock_demo` end to end and is
banner-flagged in the UI and watermarked on the PDF. Mock data is never presented as real
blockchain data, and the setting is refused when `APP_ENV=production`.

Every provider read is cached in `api_response_cache` with the API key stripped. A cache hit
reports `data_provenance: cached`, so a demo served from a warm cache is never described as a
fresh live pull.

---

## Repository layout

```
backend/app/blockchain/   chain adapters behind one interface (Ethereum, Tron, Mock)
backend/app/graph/        NetworkX traversal, budgets, path reconstruction
backend/app/attribution/  label matching, deterministic scoring, explanation
backend/app/risk/         mixer/bridge/fan-out indicators
backend/app/reports/      JSON + PDF generation
backend/app/sahyog/       mock disclosure drafting
backend/app/ml/           Phase 14 shadow ranker + MODEL_CARD.md
backend/app/database/     SQLAlchemy models, repositories, label importer
frontend/src/components/  intake · result · graph · evidence · risk · review · report
data/labels/              label source files with mandatory provenance
```

The attribution decision is **rule-based and deterministic**. No LLM sits in the decision
path, because an unexplainable answer cannot be defended in a departmental or legal review.

---

## Licence and attribution

Built for Smart India Hackathon 2026 by Team TraceX. Blockchain data is retrieved from
third-party public APIs subject to their own terms. Labelled-address data carries mandatory
source attribution; see `data/labels/PROVENANCE.md`.
