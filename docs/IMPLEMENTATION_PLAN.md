# VASPTrace — Implementation Plan

Read with `ARCHITECTURE.md`, `DATA_MODEL.md`, `API_CONTRACT.md`. Phases follow the build brief's
16-phase sequence. **Each phase ends with a stop.** No phase begins until instructed.

---

## 1. Repository assessment (Phase 0 finding)

`/Users/ayushchoukseymaca18/TraceX-VASP` is an **empty directory**. No git repository, no source,
no configuration. Everything is greenfield, so there is no legacy code to preserve or work
around — and no existing conventions to match.

Host toolchain verified on 2026-09-18:

| Tool | Status | Consequence |
|---|---|---|
| Python | 3.9.12 is `python3`; **3.11, 3.13, 3.14** also installed | Pin **3.11** via venv — best wheel availability for scikit-learn/XGBoost/lxml. 3.9 is too old for the modern typing we want. |
| Node | v24.10.0 | Fine for Next.js 15. |
| npm | present | Frontend package manager. |
| git | 2.54.0, **repo not initialised** | `git init` in Phase 1. |
| PostgreSQL client | **not installed** | Use Supabase-hosted Postgres; no local server. Alembic + SQLAlchemy handle migrations over the network. |
| Docker | **not installed** | No containers in the dev loop. Rules out WeasyPrint's system deps → ReportLab for PDF. |

---

## 2. Target file tree

```
TraceX-VASP/
├── README.md                      # setup, demo script, honesty statement
├── .gitignore                     # .env, venv, node_modules, __pycache__, *.pdf artifacts
├── .env.example                   # every key, no values
├── Makefile                       # make backend / frontend / test / lint / seed
├── docs/
│   ├── ARCHITECTURE.md
│   ├── IMPLEMENTATION_PLAN.md
│   ├── DATA_MODEL.md
│   ├── API_CONTRACT.md
│   ├── DEMO_SCRIPT.md             # Phase 16
│   └── VALIDATION.md              # Phase 15: EXP-01…EXP-06 results, honest gaps
├── data/
│   └── labels/
│       ├── manifest.yaml          # source files + URLs + licences + sha256
│       ├── PROVENANCE.md
│       ├── sanctions/             # OFAC / OpenSanctions extracts
│       ├── community/             # public label datasets, cited
│       └── demo/                  # source_tier=demo_unverified only
├── backend/
│   ├── pyproject.toml             # ruff + mypy + pytest config
│   ├── requirements.txt / requirements-dev.txt
│   ├── alembic.ini
│   ├── migrations/versions/
│   ├── app/
│   │   ├── main.py                # FastAPI app, CORS, error handlers, lifespan
│   │   ├── config.py              # pydantic-settings; validates env at boot
│   │   ├── deps.py                # DB session, current user, rate limiter
│   │   ├── api/v1/
│   │   │   ├── router.py
│   │   │   ├── meta.py  addresses.py  traces.py  cases.py
│   │   │   ├── vasps.py  labels.py  reports.py  disclosure.py  audit.py
│   │   ├── schemas/               # Pydantic request/response models (mirror API_CONTRACT)
│   │   │   ├── common.py  trace.py  attribution.py  risk.py  report.py  disclosure.py
│   │   ├── blockchain/
│   │   │   ├── base.py            # ChainAdapter protocol, NormalizedTx, Page, AddressValidation
│   │   │   ├── registry.py        # get_adapter(chain) → adapter | ChainNotSupported
│   │   │   ├── http.py            # shared async client: retries, backoff, timeouts, rate limits
│   │   │   ├── cache.py           # api_response_cache read/write + snapshot pinning
│   │   │   ├── addresses.py       # EIP-55 + Tron base58check validation/canonicalisation
│   │   │   ├── ethereum.py  tron.py  mock.py
│   │   │   └── roadmap.py         # Bitcoin/Solana/Polygon stubs raising ChainNotSupported
│   │   ├── graph/
│   │   │   ├── builder.py         # NormalizedTx[] → NetworkX MultiDiGraph
│   │   │   ├── traversal.py       # budgeted best-first BFS + DFS variant
│   │   │   ├── budget.py          # TraceBudget: counters, wall clock, truncation reasons
│   │   │   └── paths.py           # shortest_path, strongest_path, path_strength
│   │   ├── attribution/
│   │   │   ├── matcher.py         # node → vasp_addresses / risk_entities lookup
│   │   │   ├── candidates.py      # aggregate matches per VASP entity
│   │   │   ├── scoring.py         # deterministic factors → score
│   │   │   ├── config.py          # WEIGHTS, TIER_WEIGHTS, thresholds, SCORING_CONFIG_VERSION
│   │   │   └── explain.py         # ScoreBreakdown + why_summary sentences
│   │   ├── risk/
│   │   │   ├── engine.py  indicators.py  config.py
│   │   ├── reports/
│   │   │   ├── json_report.py  pdf_report.py  legal_notice.py
│   │   ├── sahyog/
│   │   │   └── mock_disclosure.py
│   │   ├── ml/
│   │   │   ├── features.py  dataset.py  train.py  predict.py
│   │   │   ├── MODEL_CARD.md
│   │   │   └── artifacts/.gitkeep
│   │   ├── database/
│   │   │   ├── session.py  models.py  types.py
│   │   │   ├── repositories/      # cases, traces, vasps, labels, audit
│   │   │   └── seeds/
│   │   │       ├── import_labels.py   # provenance-enforcing importer
│   │   │       ├── integrity.py       # duplicate/conflict/format scan
│   │   │       └── demo_fixtures.py   # mock-chain fixtures, clearly marked
│   │   ├── services/
│   │   │   └── trace_service.py   # orchestrates the pipeline; the only place phases 3–9 meet
│   │   └── core/
│   │       ├── audit.py  errors.py  ratelimit.py  logging.py  ids.py
│   └── tests/
│       ├── conftest.py
│       ├── unit/  integration/  fixtures/
└── frontend/
    ├── package.json  next.config.ts  tsconfig.json  eslint.config.mjs  .env.example
    │                       # Tailwind v4: tokens live in globals.css @theme, no config file
    └── src/
        ├── app/
        │   ├── layout.tsx  globals.css  page.tsx            # case intake
        │   ├── api/backend/[...path]/route.ts               # proxy; injects the API key
        │   ├── trace/[traceId]/page.tsx                      # result
        │   └── cases/page.tsx
        ├── components/
        │   ├── intake/TraceForm.tsx  ChainSelector.tsx  HopDepthSlider.tsx
        │   ├── result/ResultHeader.tsx  AttributionCard.tsx  ScoreGauge.tsx
        │   │           WhyThisAttribution.tsx  ScoreBreakdownTable.tsx
        │   │           CandidateList.tsx  NoAttributionPanel.tsx
        │   ├── graph/TraceGraph.tsx  GraphControls.tsx  NodeDetails.tsx  EdgeDetails.tsx
        │   ├── evidence/EvidenceTable.tsx  LabelProvenanceBadge.tsx
        │   ├── risk/RiskChips.tsx  RiskPanel.tsx
        │   ├── review/ReviewGate.tsx
        │   ├── report/ExportPanel.tsx
        │   ├── sahyog/DisclosureDraft.tsx
        │   └── ui/                                           # Button, Card, Badge, Banner…
        ├── lib/api-client.ts  types.ts  format.ts  constants.ts
        └── hooks/useTrace.ts  useGraph.ts
```

---

## 3. Phase plan

Each row lists what gets built, the gate that must pass, and what the demo can do afterwards.
"Demo-able" matters: from Phase 10 on, there is always something to show.

### Phase 1 — Scaffolding · **DONE (2026-09-18)**
Built: `git init`; backend venv on Python 3.11, FastAPI app with `/health` + `/meta/config`,
`config.py` with boot-time validation, JSON logging with secret redaction, uniform error
envelope, request-id middleware, CORS; Next.js 16 + React 19 + Tailwind v4 dashboard shell with
the permanent disclaimer strip, live engine-status indicator and a stub intake form;
`.env.example` (root + frontend); `Makefile`; ruff/mypy-strict/pytest and eslint/tsc wired.

Gate result: `make check` green — ruff clean, `mypy --strict` clean on 31 files, 22 tests pass,
eslint clean, `tsc --noEmit` clean, `next build` succeeds. Both servers boot; the dashboard
renders a live green engine indicator through the proxy.

Deviations from the original Phase 1 scope, all deliberate:
- **Tailwind v4** uses CSS-first configuration, so design tokens live in `src/app/globals.css`
  under `@theme` rather than in a `tailwind.config.ts`. The file in the §2 tree does not exist.
- **Added a server-side proxy** at `frontend/src/app/api/backend/[...path]/route.ts`. The
  browser never calls the backend directly; the route handler injects `X-Api-Key` server-side.
  This was not in the original scope but the alternative — a `NEXT_PUBLIC_` API base URL with a
  client-held key — would have violated the brief's "keys server-side" requirement. Verified
  empirically: a sentinel key configured in the environment appears in **zero** served pages or
  client bundles.
- `RootLayout` is typed explicitly instead of via Next's generated `LayoutProps`, so
  `tsc --noEmit` passes in CI without first running a build to emit `.next/types`.

Environment notes for the team:
- Port **8000 is already occupied** on this machine by another service. Use
  `--port 8010` locally, or free 8000; the `Makefile` still defaults to 8000.
- `create-next-app` left `node_modules/.bin` unpopulated and an incomplete dependency tree
  (`fastq` missing, breaking eslint). A clean `rm -rf node_modules package-lock.json &&
  npm install` fixed both. Worth knowing if a teammate hits it on first clone.
- `frontend/AGENTS.md` is regenerated by `next dev` and is committed intentionally.

### Phase 2 — Schema + label import
Build: SQLAlchemy models for all §2 tables; Alembic initial migration against Supabase;
`import_labels.py` with provenance enforcement; `integrity.py` scan; `label_dataset_versions`;
`GET /vasps`, `/vasps/addresses`, `/labels/versions`, `/meta/chains` coverage block; demo-label
gating via `ALLOW_DEMO_LABELS`.
Gate: migration applies to a clean Supabase DB and rolls back; importer **rejects** a row missing
`source_url` (test asserts the failure); integrity scan flags a deliberately planted duplicate
and a cross-source conflict; `/meta/chains` reports real counts.
Blocked on: Supabase `DATABASE_URL`, and a decision on label sources (see §5 Missing info Q1).

### Phase 3 — Ethereum adapter
Build: `base.py` contract; `addresses.py` EIP-55; `http.py` (httpx async, tenacity retries,
exponential backoff, token-bucket per provider, timeouts); `cache.py`; `ethereum.py` over an
Etherscan-compatible v2 API — normal txs, internal txs, ERC-20 transfers, pagination, cursors;
`normalize_transaction()` → `NormalizedTx`; `POST /addresses/validate`.
Gate: EXP-01-style test — adapter transaction count and key fields match the block explorer for
a fixed set of test addresses (recorded fixtures via VCR-style cassettes so CI is offline);
checksum-mismatch and wrong-chain cases return the documented codes; a forced 429 from the
provider produces a clean `503 UPSTREAM_RATE_LIMITED`, not a stack trace.

### Phase 4 — Tron adapter
Build: `tron.py` over TronGrid/TronScan — TRX transfers, TRC-20 transfers (USDT priority per
DPRD §11), Tron's `sun` decimals, base58check ↔ hex(41) handling, its own pagination and
fingerprint cursors; register in `registry.py`; `mock.py` MockAdapter for both chains with
labelled demo fixtures.
Gate: same EXP-01 fixture test for Tron; `NormalizedTx` from ETH and Tron are
schema-identical (a parametrised test asserts field-by-field equality of shape and types —
DPRD §10 "cross-chain schema consistency test"); MockAdapter always reports
`provenance=mock_demo`.

### Phase 5 — Normalization + observation store
Build: persist `wallets`, `transactions`, `token_transfers` with the documented unique keys and
upserts; decimal handling end-to-end (`Decimal`, never `float`); `trace_snapshot_refs` pinning;
cache TTL + `force_refresh`.
Gate: re-ingesting the same page inserts zero duplicate rows; amounts round-trip exactly
(`amount_raw` → `amount` → `amount_raw`); a pinned snapshot survives cache eviction.

### Phase 6 — Graph engine
Build: `builder.py`, `traversal.py` (budgeted best-first BFS + a DFS variant for comparison),
`budget.py`, `paths.py`; persist `trace_nodes`/`trace_edges`; `POST /traces` returning a
graph-only result (no scoring yet); `GET /traces/{id}`, `GET /traces/{id}/graph`.
Gate: EXP-02 — on a hand-built synthetic graph with a known 3-hop path, the traced path matches
the expected path exactly; cycle test (A→B→C→A) terminates; a 5 000-counterparty fan-out node is
not expanded and is flagged; budget exhaustion yields `truncated=true` with a reason rather than
an exception; deterministic output — same input twice gives identical node/edge sets.

### Phase 7 — VASP matching
Build: `matcher.py` (case-insensitive canonical lookup, batched to one query per hop),
`candidates.py` entity aggregation, terminal-at-VASP rule, conflicting-label detection, label
staleness computation.
Gate: EXP-03 scaffold — precision/recall computed against a held-out validation set (whatever
size we honestly have); a label differing only in case still matches; two conflicting sources for
one address produce a `conflicting_label` indicator instead of a silent pick.

### Phase 8 — Attribution scoring
Build: `attribution/config.py` (weights, tier weights, thresholds, `SCORING_CONFIG_VERSION`),
`scoring.py`, `explain.py`; ranked `attributions` rows; the refusal rule; score-band labelling;
`why_summary` sentence generation.
Gate: unit tests per factor (monotonic in hop distance; saturating in tx count; bounded 0–1);
`sum(contributions) - penalty_total == final_score/100` within rounding tolerance; a
demo-unverified-only match returns `no_attribution` with `only_unverified_labels`; a golden-file
test locks the breakdown JSON so scoring drift is caught (DPRD §35).

### Phase 9 — Risk engine
Build: `risk/engine.py` + indicators; labelled mixer/bridge/sanctions matching; fan-out/fan-in,
rapid-movement, repeated-intermediary, uniform-splitting heuristics; penalty wiring into scoring;
the neutral-wording disclaimer.
Gate: EXP-05 scaffold — every address in the known-mixer test list fires `mixer_interaction`; a
clean synthetic path fires none; penalty application demonstrably lowers the score;
a copy-review test asserts no indicator string contains accusatory language ("criminal",
"launderer", "guilty").

### Phase 10 — Frontend investigation workflow
Build: typed API client generated from the OpenAPI schema; intake form with client-side address
validation and hop slider (1–6, default 3); loading state with stage labels; result page —
header stats, `AttributionCard` + `ScoreGauge`, `WhyThisAttribution`, `ScoreBreakdownTable`,
`CandidateList`, `NoAttributionPanel`, `RiskChips`, provenance/staleness banners, `ReviewGate`;
cases list; `POST /traces/{id}/review`.
Gate: full happy path in the browser against the real backend; no-attribution path renders the
refusal panel, not an empty card; mock-data trace shows the DEMO banner; `tsc --noEmit` and
eslint clean; every score in the UI is accompanied by the heuristic label.

### Phase 11 — Interactive graph + evidence
Build: `TraceGraph.tsx` on Cytoscape.js (`cytoscape-dagre` layered layout so the
subject→intermediate→VASP flow reads top-down); zoom/pan/fit; node + edge selection panels; hop
filter, role filter, evidence-path-only toggle; path highlighting; `EvidenceTable` with explorer
deep links; `LabelProvenanceBadge` showing source, URL, verification status and label age; lazy
rendering above the node cap.
Gate: 300-node graph stays interactive; clicking a node shows address/chain/role/label/tx
count/risk indicators; clicking an edge shows hash/asset/amount/timestamp/direction; the evidence
path is visually distinct; graph renders correctly for a no-attribution trace.

### Phase 12 — Reports
Build: `json_report.py` (the §8 section list), `pdf_report.py` on ReportLab — cover page,
attribution summary, score-breakdown table, hop-path table, evidence table, risk section,
limitations, reproducibility block, fixed legal notice, footer on every page, DEMO watermark when
provenance is not live; `reports` rows with `content_sha256`; `ExportPanel`.
Gate: PDF renders from the stored JSON with no live API call (reproducibility); the legal notice
and "investigative lead, not legal proof" appear in both formats; report content matches the
trace record field-for-field (automated comparison test, DPRD §35); `content_sha256` is stable
across two renders of the same trace.

### Phase 13 — Mock SAHYOG
Build: `mock_disclosure.py`, `POST /traces/{id}/disclosure` with the review gate,
`GET /disclosures/{ref}`, `DisclosureDraft.tsx` with the DEMO banner, copy-to-clipboard and
JSON download; `payload_schema_version`; schema-flexible field mapping.
Gate: drafting without an accepted review returns `409 REVIEW_REQUIRED` (test); the payload
contains every field the brief lists; a network-assertion test proves no outbound request is
made; the banner cannot be dismissed.

### Phase 14 — ML experiment
Build: `features.py` (the brief's feature list), `dataset.py` with **temporal** train/test split
and leakage guards, `train.py` for Logistic Regression → Random Forest → XGBoost,
top-1/top-3/precision/recall/F1 + calibration curve, `ml_experiments` rows,
`MODEL_CARD.md` written from measured output only, `predict.py` exposing `ml_score` as a
**shadow** field.
Gate: leakage tests — the candidate's own label is absent from the feature matrix; no test-set
row shares a subject wallet with a train row; if the dataset is too small for a meaningful
split, `MODEL_CARD.md` says exactly that and the deterministic scorer stays primary. **No
invented numbers, ever.**

### Phase 15 — Testing, security, validation write-up
Build: coverage push on the reasoning layer; rate limiting; input-validation fuzz cases;
`audit_logs` on every mutating action; secret-leak test (API keys absent from responses, logs and
error bodies); SQL-injection and oversized-payload tests; `docs/VALIDATION.md` recording
EXP-01…EXP-06 outcomes **including failures**; the DPRD §29 kill-test checklist with an honest
pass/fail per line.
Gate: full suite green; no secret appears in any response or log; every DPRD §29 kill test has a
recorded verdict.

### Phase 16 — Deployment + demo polish
Build: backend on Render/Railway (env vars, health check, Python 3.11 pin), frontend on Vercel,
Supabase migrations applied; pre-warmed snapshot cache for the demo wallets (rate-limit
insurance, DPRD §28); `docs/DEMO_SCRIPT.md` with the DPRD §39 beats — live trace, open the score
breakdown, a mixer-flagged path, one-click disclosure draft, the honesty framing, and a candid
coverage/calibration statement; offline fallback (recorded snapshots + MockAdapter) that is
visibly labelled as such.
Gate: cold-start trace under 10 s on the demo wallets; full 5–10 minute run-through rehearsed
twice; offline mode works with the venue Wi-Fi off.

---

## 4. Technical risks

Ordered by what is most likely to hurt the demo. DPRD §28 risks carried forward, plus the ones
specific to this build.

| # | Risk | Likelihood | Impact | Mitigation | Contingency |
|---|---|---|---|---|---|
| R1 | **Label coverage too sparse** → most real wallets return "no attribution". The DPRD's own P0 risk, and the single biggest threat to a convincing demo. | High | Very high | Treat the dataset as the product (DPRD §47(22)); prioritise ETH + Tron; import sanctions + cited community sets in Phase 2; measure coverage in `/meta/chains` | Demo on pre-validated wallets whose paths we have verified; state coverage honestly; `demo_unverified` tier keeps the fallback labelled as such |
| R2 | **Provider rate limits during the live demo** (free tiers are 5 req/s or less) | Medium-High | High | Token-bucket limiter, retries with backoff, snapshot cache pre-warmed for demo wallets, `Idempotency-Key` on double-clicks | Serve the demo from pinned snapshots (`provenance: cached`, shown in the UI); offline MockAdapter as last resort |
| R3 | **Traversal blow-up** on a high-fan-out wallet — 6 hops through an exchange hot wallet is combinatorial | Medium | High | Terminal-at-VASP, fan-out terminal, value-weighted frontier, hard budgets, `truncated` flag | Lower default hop depth; pick demo wallets with known path shapes |
| R4 | **Etherscan/TronGrid response-shape drift or endpoint deprecation** mid-build | Medium | Medium | Adapters isolate it; fixtures/cassettes catch drift in CI; multi-provider capability in `http.py` (Bitquery as the second source) | Swap provider behind the same adapter interface |
| R5 | **Uncalibrated score misread as probability** by a judge or an investigator | Medium | Very high | One labelling policy applied in UI, JSON, PDF and disclosure; `calibrated: false` in every payload; bands named in words, not percentages | Say it out loud in the demo — DPRD §39(20) treats candour as a credibility asset |
| R6 | **No ground truth** → EXP-03/04 cannot produce real precision/recall | High | Medium | Build the validation set from publicly reported cases + testnet-constructed paths (DPRD §25); keep it held out | `VALIDATION.md` reports "not yet measured" rather than a fabricated number |
| R7 | **Supabase latency/limits** from the venue network | Medium | Medium | Connection pooling, indexes on the hot `(chain, address)` lookups, batched per-hop label queries | SQLite fallback with the labels pre-seeded locally |
| R8 | **Tron address-format bugs** (base58check vs hex41) causing silent match misses | Medium | High | Canonicalise at the adapter boundary; property-based round-trip tests; the DPRD §17 format-mismatch failure mode is an explicit test case | — |
| R9 | **PDF toolchain friction** on macOS without Homebrew/Docker | Low | Medium | ReportLab (pure wheels) chosen in Phase 0 | Server-side HTML report + browser print-to-PDF |
| R10 | **Scope creep** into ML, extra chains, or RBAC before the core is validated | Medium | High | Phase gates; DPRD §31 "not required for MVP" list is binding; Phase 14 is explicitly a shadow experiment | Cut Phase 14 entirely — the MVP does not need it |
| R11 | **Decimal precision loss** (18-decimal tokens through JS floats) | Medium | Medium | `Decimal` server-side, decimal **strings** on the wire, no arithmetic on amounts in the frontend | — |
| R12 | **Over-trust leading to wrongful action** (DPRD §27 F07) | Medium | Very high | Review gate is a hard requirement, not a setting; disclosure blocked until accepted; fixed legal notice everywhere | Report-template revision if misuse is observed |

---

## 5. Missing information — decisions needed from you

Ranked. Q1 and Q2 block Phase 2; Q3 blocks Phase 3.

**Q1 — Label dataset sources (blocks Phase 2, drives R1).**
I will not write VASP addresses from memory into a seed file; a fabricated label would poison
every downstream claim. I need one of:
 (a) an open label dataset you want used (a public GitHub label repo, a Dune/Etherscan export
 you have rights to) — give me the URL and I will build the importer around it;
 (b) permission for me to fetch OFAC SDN + OpenSanctions crypto-address lists (genuinely public,
 citable, `sanctions_list` tier) — these give strong **risk** coverage but almost no **exchange**
 coverage; or
 (c) a clearly-marked `demo_unverified` seed for the demo only, which by design cannot produce a
 primary attribution unless you also accept lowering that rule.
My recommendation: (b) + (a), with (c) present but flagged, and the coverage notice visible.

**Q2 — Supabase credentials (blocks Phase 2).** `DATABASE_URL` (pooled connection string),
project ref, and whether I should use the service-role key server-side only. Until then I will
develop against SQLite and keep the migration Postgres-targeted.

**Q3 — Chain API keys (blocks Phase 3/4 live mode).** Etherscan (or Etherscan V2 multichain) key,
TronGrid key, Bitquery key if you have one. Without them Phase 3/4 build against fixtures and
the MockAdapter, which is workable but means live mode is untested until keys land.

**Q4 — Demo wallets.** Do you have specific addresses the demo must trace (for example from
public ED/press reporting), or should I select pre-validated ones during Phase 16? One should be
a wallet that passes through a mixer, per DPRD §39(15).

**Q5 — Validation ground truth (affects Phase 14, §20 metrics).** Do you have or can you obtain
wallet→exchange pairs with confirmed outcomes? If not, EXP-03/04 will be reported as "not yet
measured" and ML stays a shadow experiment.

**Q6 — Hop default.** The brief says default 3, max 6; the DPRD says "default 3-6". I am
implementing default **3**, max **6**, investigator-adjustable. Confirm if you want 4.

**Q7 — Traversal direction.** DPRD §6 traces **outbound** (toward a cash-out). Inbound tracing
(who funded the wallet) is a different investigative question. I am shipping outbound as default
with direction as a parameter; confirm that matches your demo narrative.

**Q8 — SAHYOG payload shape.** The real contract is unavailable (DPRD §10, §29). Unless you have
a sample from I4C, I will design `sahyog-mock-v1` from the DPRD's field list and keep it
schema-flexible per DPRD §47(26).

**Q9 — Team ID / deployment accounts.** The PPT's Team ID field is blank. Needed for report
headers and README. Also: do Vercel/Render/Supabase accounts exist, or should Phase 16 assume
fresh signups?

---

## 6. First implementation task (Phase 1, on your go)

Scope — scaffolding only, no domain logic:

1. `git init`; `.gitignore`; `README.md` with setup steps and the claim-posture statement.
2. `backend/`: Python 3.11 venv; `requirements.txt` (fastapi, uvicorn, pydantic v2,
   pydantic-settings, sqlalchemy 2, alembic, psycopg[binary], httpx, tenacity, networkx,
   reportlab, python-dotenv) and `requirements-dev.txt` (pytest, pytest-asyncio, respx, ruff,
   mypy); `pyproject.toml` with ruff/mypy/pytest config; `app/main.py` with the FastAPI app,
   CORS, the uniform error envelope, request-id middleware and structured logging;
   `app/config.py` validating env at boot; `GET /api/v1/health` and `GET /api/v1/meta/config`.
3. `frontend/`: `create-next-app` (TS, App Router, Tailwind); dashboard shell (header with the
   "Investigative lead — not legal proof" strip, sidebar, content area); a stub `TraceForm`;
   `lib/api-client.ts` hitting `/health`; `lib/types.ts` seeded from `API_CONTRACT.md`.
4. `.env.example` listing every key with empty values; `Makefile` targets
   `install / backend / frontend / test / lint / typecheck`.
5. Smoke tests: backend `test_health.py`; frontend renders the shell.

Exit gate: `make lint typecheck test` green; `uvicorn` and `next dev` both boot; the frontend
shows a live green health indicator from the backend. Then I stop and summarise.
