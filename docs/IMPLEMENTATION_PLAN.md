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

### Phase 2 — Schema + label import · **DONE (2026-09-18)**
Built: SQLAlchemy 2 models for all 19 tables; async engine (psycopg3 / aiosqlite) with Alembic;
one initial migration; `manifest.py`, `import_labels.py`, `integrity.py`, `demo_fixtures.py`;
`labels` repository with batched per-hop lookup; `GET /vasps`, `/vasps/{slug}`,
`/vasps/addresses`, `/labels/versions`, `/meta/chains`; a real database probe on `/health`;
`data/labels/manifest.yaml` + `PROVENANCE.md`; Makefile targets `migrate`, `seed`, `seed-demo`,
`seed-check`, `demo-fixtures`.

Gate result: `make check` green — ruff clean, `mypy --strict` clean on 48 files, **95 tests
pass** (22 → 95). Verified beyond the stated gate:
- migration applies, downgrades to base, and re-applies; `alembic check` reports no drift, so
  the models and the migration cannot silently diverge;
- both honesty `CHECK` constraints are enforced by the database itself — a `verified` label
  without a date and a `demo_unverified` label claiming verification are both rejected at the
  SQL level, not only in application code;
- the importer rejects a missing `source_url`, a non-citable URL, an invalid address, a
  wrong-chain address, an unknown column, and a `verified` claim with no date, naming the exact
  file and line; a failure writes **nothing** (atomicity asserted);
- a checksummed and a lowercase query both resolve to the same canonical row;
- two sources disagreeing about one address return both claims with a conflict notice, never a
  silent pick.

Deviations from the original Phase 2 scope, all deliberate:
- **`blockchain/addresses.py` moved forward from Phase 3.** The importer cannot validate a
  label address without it. It is pure functions, so it carries no Phase 3 dependencies — and
  Phase 3 is correspondingly smaller. 26 of the 95 tests cover it.
- **Async SQLAlchemy instead of sync.** Phase 3+ uses async httpx; a sync session inside an
  `async def` endpoint would block the event loop for a whole trace. Added `greenlet` and
  `aiosqlite`; `resolve_database_url` rewrites the sync-driver URLs Supabase's dashboard hands
  out, because getting that wrong fails at the first query rather than at startup.
- **All 19 tables in one migration**, not just the ones Phase 2 reads. A migration per phase
  would mean re-shaping tables that already hold demo data mid-build.
- **`pycryptodome` added** for keccak256 (EIP-55). Single well-maintained wheel; the
  alternative (`eth-utils`) pulls a much larger tree.
- **Two tables added beyond the brief's list**, both DPRD-derived rather than invented:
  `label_dataset_versions` (DPRD §15 versioning, §21 freshness) and `trace_snapshot_refs`
  (DPRD §15 snapshotting). `api_response_cache` and `disclosure_requests` were already in
  `DATA_MODEL.md`.
- **One Phase 1 test updated**: `/health` now probes the database, so its `database`
  dependency reports `ok` via the SQLite fallback rather than `not_configured`.

A real bug was found and fixed in address validation: an uppercase `0X` prefix was rejected.
Since EIP-55's checksum covers only the 40-character body, the prefix's case carries no
information — rejecting it turned a harmless paste variation into exactly the silent false
negative this module exists to prevent (DPRD §17).

**Still blocked (unchanged): Q1 label sources and Q2 `DATABASE_URL`.** What that means
concretely:
- The importer, integrity scan, schema and endpoints are complete and tested, but the only
  labels currently loadable are the **synthetic demo fixture** — fictional VASP names with
  deterministically-derived addresses, at `demo_unverified` tier, opt-in only, refused in
  production, and unable to support a primary attribution. See `data/labels/PROVENANCE.md`.
- The migration is verified against SQLite only. It is written Postgres-first (JSONB via a
  `TypeDecorator`, batch mode only on SQLite), but **the Supabase apply is untested** until
  `DATABASE_URL` arrives.

### Phase 3 — Ethereum adapter · **DONE (2026-09-18)**
Built: `base.py` (`ChainAdapter` protocol, `NormalizedTx`, `Page`, `FetchStats`); `http.py`
(shared provider client: token-bucket rate limiting, retries with backoff, timeouts,
upsert caching into `api_response_cache`, key sanitisation); `ethereum.py` over the
Etherscan-compatible V2 API covering `txlist`, `txlistinternal` and `tokentx`;
`registry.py` with `ProviderNotConfigured` distinct from `ChainNotSupported`;
`POST /addresses/validate`.

Gate result: `make check` green — ruff clean, `mypy --strict` clean on 56 files, **143 tests
pass** (95 → 143). Every provider call is mocked with respx, so the suite is offline and
needs no API key or quota. Verified:
- native, internal and ERC-20 records all normalise into one schema, with 6-decimal USDT
  handled correctly (reading it as 18 decimals would understate the amount a trillion-fold);
- hashes and contract addresses are canonicalised, so provider casing cannot defeat matching;
- Etherscan's "No transactions found" (an HTTP 200 with `status: "0"`) is an empty result,
  not a failure — treating it as an error would turn a quiet wallet into a broken trace;
- a rate-limit rejection arriving as an HTTP 200 body surfaces as `UpstreamRateLimited`;
- 429 and 5xx retry three times then surface cleanly; a transient 5xx followed by success
  recovers; an error's message and details never contain the API key;
- the 10 000-record provider cap sets `complete=false` with a reason, rather than stopping
  silently — which would look identical to "no VASP exists" (DPRD §17);
- an invalid address is rejected before any request, so no quota is spent;
- a cache hit reports `provenance: cached` and costs zero API calls, so a warm-cache demo is
  never presented as a fresh live pull.

Two real bugs were found and fixed in the caching layer, both of which would only have
appeared on the SQLite dev fallback or under `force_refresh` — easy to miss until demo day:
- SQLite has no timezone type, so `expires_at` read back naive and comparing it to an aware
  `now()` raised `TypeError`, disabling caching entirely on the fallback.
- `force_refresh` inserted a second row for an existing `cache_key`, violating the unique
  constraint mid-trace. Writes are now an upsert, and a row pinned as a trace snapshot keeps
  its non-expiring status.

Deviations from the original Phase 3 scope, all deliberate:
- **No `MockAdapter` yet.** It was scoped for Phase 4, and `registry.py` now raises
  `ProviderNotConfigured` naming `ETHERSCAN_API_KEY` rather than silently substituting demo
  data. "No key" and "provider down" need different fixes, so they are different errors.
- **Internal transfers included in `get_wallet_transactions`.** Not in the original wording,
  but omitting them loses real fund flow: a wallet can reach an exchange entirely through a
  contract call and the trace would show nothing.
- **`sort=desc` (newest first).** A trace trimmed by a budget then keeps the most recent
  activity, which is what an investigator following live funds needs.

**Untested against the live API (Q3 unanswered).** Every test runs against recorded
responses. The adapter has never made a real Etherscan call, so EXP-01 — comparing adapter
output to the reference explorer for 20+ wallets — cannot run until `ETHERSCAN_API_KEY`
exists. The response shapes are implemented from Etherscan's documented V2 contract.

### Phase 4 — Tron adapter + MockAdapter · **DONE (2026-09-18)**
Built: `tron.py` over TronGrid v1 (native TRX via the nested `raw_data.contract` shape, TRC-20
via the flattened shape, fingerprint paging, hex↔base58 handling); `mock.py` with three
scripted scenarios; registry extended to both MVP chains with per-chain key requirements;
`USE_MOCK_CHAIN_DATA` setting; `http.py` gained `secret_headers` because TronGrid passes its
key as a header rather than a query parameter.

Gate result: `make check` green — ruff clean, `mypy --strict` clean on 59 files, **177 tests
pass** (143 → 177). Verified:
- **cross-chain schema consistency (DPRD §10):** a parametrised test asserts Ethereum and
  Tron `NormalizedTx` objects have identical fields and types, `Decimal` amounts, string raw
  amounts and UTC-aware timestamps — if they diverged, every layer above would need to know
  which chain it was looking at and the adapter abstraction would have failed;
- hex `41…` addresses are canonicalised to base58 `T…`, so a provider that returns the other
  form cannot cause a silent label miss;
- millisecond timestamps are read as milliseconds (seconds would place every transaction in
  1970 and destroy the temporal scoring factor);
- non-transfer contracts (votes, resource freezing, value-less calls) are skipped;
  `contractRet != "SUCCESS"` marks a transaction failed;
- the TronGrid key travels as a header and never appears in the URL, where it could be
  logged or cached;
- a fingerprint becomes a cursor **only** when a next-page link is present — TronGrid returns
  one on the final page too, which would page forever;
- amounts round-trip exactly: `int(amount × 10^decimals) == amount_raw`.

MockAdapter scenarios, each deterministic across runs (DPRD §48 task 31 repeatability):
`clean` → two intermediates → a demo exchange deposit (3 hops); `mixer` → a demo mixer →
intermediate → demo custody deposit, so Phase 9 has something to fire on; `dead_end` → three
unlabelled hops, exercising the "No reliable VASP attribution found" path. Terminals are the
demo fixture's own addresses, so a trace lands on a label that exists after `make seed-demo`.

A real bug was found and fixed in `mock.py`: `derive_address` returns the *display* form
(EIP-55 checksummed on Ethereum) while every lookup uses the canonical form, so the adjacency
map was keyed by checksummed addresses and no Ethereum hop ever matched. Same root cause as
the Phase 2 `0X`-prefix bug — the DPRD §17 format-mismatch failure mode, which is proving to
be the most recurrent defect class in this codebase. Both are now guarded by tests.

Deviations, all deliberate:
- **`/meta/chains` now reports `degraded`** for a chain whose adapter exists but has no key.
  Previously it claimed `supported` with `adapter_provenance: mock_demo`, which implied
  synthetic data was available by default. It is not — mock mode is opt-in, so the honest
  answer is that no trace can run, and the coverage notice names the missing setting.
- **No silent mock fallback.** `ProviderNotConfigured` names both the key to set *and*
  `USE_MOCK_CHAIN_DATA` as the offline alternative, rather than dead-ending.
- **`roadmap.py` was not created.** The registry's `ROADMAP_NOTES` covers it in one place;
  a file of stub classes that only raise would be indirection without benefit.

**Untested against the live API (Q3 unanswered).** As with Ethereum, every Tron test runs
against recorded responses; the adapter has never made a real TronGrid call, so EXP-01 cannot
run until `TRONGRID_API_KEY` exists.

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
