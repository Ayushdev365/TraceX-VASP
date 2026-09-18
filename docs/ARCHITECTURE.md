# VASPTrace — Architecture

**Team:** TraceX · **Problem Statement:** SIH26182 — Automated Attribution of Unknown
Cryptocurrency Wallets to Nearest VASPs through Blockchain Intelligence APIs.

**Source of truth:** `VASP-Attribution-DPRD.pdf` (DPRD) and `SIH26182.pdf` (PPT). Section
references below (`DPRD §n`) point back to the DPRD. Nothing in this document adds a product
requirement that is not traceable to those two files or to the build brief.

**Claim posture (DPRD §1, §24, §37):** VASPTrace produces an **investigative lead, not legal
proof**. The attribution score is an **explicitly-labelled heuristic**, not a calibrated
probability, until validated per DPRD §20/§25. The system never identifies a beneficial owner
and never executes a freeze, block, or live disclosure submission.

---

## 1. Layered architecture

Three layers, exactly as DPRD §7 defines them.

```
┌──────────────────────────────────────────────────────────────────────────┐
│ WORKFLOW LAYER                                                          │
│   Next.js investigator dashboard · Report generator (JSON + PDF)        │
│   Mock SAHYOG disclosure drafter · Human review gate                    │
├──────────────────────────────────────────────────────────────────────────┤
│ REASONING LAYER              (stateless, deterministic, no LLM)         │
│   Graph traversal engine (NetworkX, budgeted BFS)                       │
│   VASP label matcher · Attribution scorer · Risk indicator engine       │
├──────────────────────────────────────────────────────────────────────────┤
│ DATA LAYER                                                              │
│   Chain adapters (Ethereum, Tron, Mock) behind one interface            │
│   Labelled-address store · Case/trace store · API response cache        │
└──────────────────────────────────────────────────────────────────────────┘
```

### Request path

```
Investigator (browser)
  │  POST /api/v1/traces  { address, chain, hop_depth, case_id? }
  ▼
FastAPI  ── validate address (chain-specific, checksum-verified)
  │
  ├─► ChainAdapter.get_wallet_transactions()  ──►  Etherscan-compatible / Tron API
  │        (paginated · retried · rate-limited · cached · snapshotted)
  │
  ├─► normalize_transaction()  ──►  NormalizedTx (one schema for every chain)
  │
  ├─► GraphEngine: budgeted BFS to hop_depth (default 3, max 6)
  │        cycle-safe · dedup · value-weighted frontier · terminal at VASP nodes
  │
  ├─► VaspMatcher: each visited node → vasp_addresses lookup → candidates per VASP entity
  │
  ├─► RiskEngine: mixer / bridge / fan-out / fan-in / rapid-movement indicators
  │
  ├─► AttributionScorer: deterministic weighted score + factor-by-factor breakdown
  │
  └─► persist Trace + TraceNode/Edge + Attribution + AuditLog  →  200 TraceResult
           │
           ▼
   Dashboard: graph (Cytoscape.js) · "WHY THIS ATTRIBUTION?" evidence panel · risk chips
           │
           ▼
   Human review (accept / reject / deeper trace)   ← hard gate, DPRD §15, §24
           │
           ├─► GET  /traces/{id}/report.json | report.pdf
           └─► POST /traces/{id}/disclosure  → MOCK SAHYOG payload (watermarked DEMO)
```

---

## 2. Key architectural decisions

| # | Decision | Rationale | Alternative rejected |
|---|---|---|---|
| A1 | Attribution core is **rule-based and deterministic**; no LLM in the decision path | DPRD §18, §47(23): evidentiary output must be explainable; an LLM answer cannot be defended in departmental review | LLM-as-judge — black box, unreproducible |
| A2 | **Stateless engine** behind a thin case-intake API | DPRD §6, §7: same engine must be callable from our dashboard now and from SAHYOG later without redesign | Engine coupled to dashboard session |
| A3 | **One `ChainAdapter` interface**, chain logic fully isolated from reasoning | DPRD §7 chain-adapter architecture; lets BTC/BNB/Solana/Polygon land later with zero core changes | Per-chain branching inside the traversal engine |
| A4 | **Budgeted best-first BFS**, not plain BFS | Plain BFS at 6 hops on a high-fan-out address explodes into millions of nodes; budget caps guarantee the DPRD §20 target of <10 s median | Unbounded BFS; graph DB (Scale phase per DPRD §13) |
| A5 | **Synchronous trace endpoint** with hard wall-clock/API/node budgets | Hackathon reliability: no queue, no worker, no polling bugs on stage. Budget exhaustion returns a partial result flagged `truncated=true` rather than hanging | Celery/RQ async job pipeline — more moving parts to fail live |
| A6 | **VASP labels carry mandatory provenance**; unverified labels are a distinct tier that cannot alone produce an attribution | DPRD §16, §21; brief: "Never invent VASP addresses. Never silently treat an unverified address as verified." | Flat address→name map |
| A7 | **Every raw API response is snapshotted** with the trace | DPRD §15 trace snapshotting + repeatability protocol (DPRD §48 task 31); doubles as the demo-time cache | Re-query the chain on every report render |
| A8 | **SQLAlchemy + Alembic**, Postgres primary / SQLite dev fallback | Supabase Postgres is the target (brief), but the demo must still run if the venue network or Supabase is down | Raw `psycopg` against Postgres only |
| A9 | **ReportLab** for PDF, not WeasyPrint | WeasyPrint needs system cairo/pango; no Docker or Homebrew on this machine. ReportLab is a pure-wheel install → reproducible for student developers | WeasyPrint (DPRD §13 lists it as an option), Puppeteer |
| A10 | **Mock provider is a first-class adapter**, never a silent fallback | Brief: "Never present mock data as real blockchain data." Every response carries `data_provenance` and the UI renders a DEMO DATA banner | Seeding fake txs into the real adapter path |
| A11 | **ML is Phase 14 and stays a shadow ranker** | DPRD §18, §41: the rule-based baseline remains primary until a ground-truth set exists | Ship XGBoost scores to the investigator |

---

## 3. Chain adapter contract

Every chain implements exactly this surface (brief requirement). The reasoning layer imports
only `ChainAdapter` — never `EthereumAdapter` or `TronAdapter` directly.

```python
class ChainAdapter(Protocol):
    chain: Chain                       # ETHEREUM | TRON | ...
    native_asset: str                  # "ETH" | "TRX"
    provenance: DataProvenance         # LIVE_API | CACHED | MOCK

    def validate_address(self, address: str) -> AddressValidation: ...
    def get_wallet_transactions(self, address, *, direction, limit, cursor) -> Page[RawTx]: ...
    def get_token_transfers(self, address, *, direction, limit, cursor) -> Page[RawTransfer]: ...
    def get_transaction(self, tx_hash: str) -> RawTx | None: ...
    def normalize_transaction(self, raw: RawTx | RawTransfer) -> NormalizedTx: ...
```

`NormalizedTx` is the single cross-chain schema the graph engine consumes:

```
chain, tx_hash, block_number, timestamp(UTC), from_address, to_address,
asset_symbol, asset_contract|None, amount(Decimal, human units), amount_raw(str),
decimals, kind(NATIVE|TOKEN|INTERNAL), status(SUCCESS|FAILED), fee|None, provenance
```

**Address normalization rule:** all addresses are stored and compared in a canonical form —
Ethereum: lowercase hex; Tron: base58check `T…`. The original user input is preserved verbatim
on the trace record. This closes the DPRD §17 failure mode "missed matches due to
case-sensitivity/format mismatches".

Implemented in MVP: `EthereumAdapter`, `TronAdapter`, `MockAdapter`.
Registered but unimplemented (raise `ChainNotSupported` with a clear message):
`BitcoinAdapter`, `SolanaAdapter`, `PolygonAdapter` — DPRD §11 roadmap chains, gated behind the
same adapter-validation process (EXP-01).

---

## 4. Graph engine

NetworkX `MultiDiGraph`. Nodes = addresses, edges = transactions (multi-edge: two addresses can
transact many times, and each transaction is its own evidence item).

**Node roles:** `SUBJECT` (the queried unknown wallet) · `INTERMEDIATE` · `VASP` ·
`RISK_ENTITY` · `CONTRACT`.

**Traversal:** budgeted best-first BFS, outbound by default (DPRD §6 step 3 — funds flowing
toward a cash-out point), direction configurable.

Expansion rules, in order:
1. **Terminal at VASP.** A node matching a labelled VASP address is recorded as a candidate and
   **not expanded**. An exchange hot wallet has millions of edges and its counterparties are
   other users, not the suspect's path.
2. **Terminal at high fan-out.** A node with counterparty count ≥ `FANOUT_TERMINAL` (default
   500) is not expanded; it is recorded with a `high_fan_out` indicator. Guards DPRD §17
   "runaway cost/latency on high-fan-out wallets".
3. **Dust prune.** Edges below `MIN_EDGE_VALUE_USD_EQ` (default configurable per chain, e.g.
   1 USD-equivalent) are recorded on the graph but do not create new frontier entries.
4. **Frontier priority** = `(hop asc, value_share desc)`. Within a hop, the highest-value flows
   expand first, so a truncated trace is truncated at the *least* material branches.
5. **Cycle/dup prevention** via a `visited` set keyed `(chain, canonical_address)`; edges are
   deduped by `(tx_hash, from, to, asset)`.

**Budgets** (all configurable, all reported in the response):
`max_hops` (≤6) · `max_nodes_expanded` (400) · `max_api_calls` (120) ·
`max_txs_per_address` (200) · `wall_clock_budget_s` (10).
Exhausting any budget sets `truncated=true` and a human-readable `truncation_reason`; the UI
shows this next to the score, because a truncated trace may have stopped short of the true
nearest VASP (DPRD §17, F01/F03).

**Path reconstruction:** `shortest_path` (hop-minimal) plus `strongest_path` (maximal product of
per-hop value share). Both are returned as evidence; the hop-minimal path drives the score.

---

## 5. Attribution engine

Candidates are aggregated **per VASP entity**, not per address — five deposit addresses of the
same exchange are one candidate with `min_hop_distance` and a list of matched addresses.

Score (DPRD §12's general form, made concrete; all weights live in `attribution/config.py` and
are versioned in the trace record so any past result is reproducible):

```
score_raw = 0.30 · hop            # 1 / (1 + (h-1)·0.6)
          + 0.25 · reliability    # label-tier weight
          + 0.15 · interaction    # log1p(tx_count) / log1p(10), capped at 1
          + 0.15 · value_share    # value reaching candidate / total traced outflow
          + 0.10 · path_strength  # product of per-hop value shares along the chosen path
          + 0.05 · temporal       # time-ordering validity + plausible inter-hop delays

penalty   = Σ risk penalties on the path   (mixer .25, bridge .15, high fan-out .10,
                                            sanctioned .10, unverified-label .10)  capped .50

score     = round(100 · clamp(score_raw − penalty, 0, 1))
```

Label-tier weights: `official_vasp_published` 1.00 · `sanctions_list` 1.00 ·
`community_verified` 0.75 · `community_unverified` 0.55 · `demo_unverified` 0.25.

**Refusal rule (brief: "Never force a result").** Return `attribution: null` with
`no_attribution_reason` when: best score < `MIN_ATTRIBUTION_SCORE` (35); or every matched label
is `demo_unverified`; or no VASP was reached within the hop cap ("inconclusive within hop cap",
DPRD §27 F03). The UI renders **"No reliable VASP attribution found"** and offers a deeper trace.

**Score labelling policy (DPRD §48 task 36).** One constant, applied identically in the UI, the
JSON report, the PDF, and the disclosure draft:
`score_type: "heuristic_investigative_score"`, `calibrated: false`, plus the fixed sentence
*"Heuristic investigative score — not a calibrated probability."* Bands:
0–34 Insufficient · 35–54 Low · 55–69 Moderate · 70–84 Strong · 85–100 Very strong.
Scores are never rounded up (DPRD §24).

**Explainability output** — every candidate carries a `ScoreBreakdown`: each factor's raw value,
normalized value, weight, weighted contribution, and a plain-language sentence; every penalty
with its cause; the evidence transaction list; and the label's source + source URL +
verification status + label age.

---

## 6. Risk engine

Neutral-worded **indicators**, never accusations (DPRD §24). Each carries
`severity (info|low|medium|high)`, `evidence` (the addresses/txs that triggered it), and
`detection_basis (labelled_address | heuristic)`.

`mixer_interaction` · `bridge_interaction` · `sanctioned_address_on_path` · `high_fan_out` ·
`high_fan_in` · `rapid_movement` · `repeated_intermediary` · `uniform_amount_splitting` ·
plus the data-quality flags `stale_label_dependency`, `unverified_label_dependency`,
`conflicting_label` (DPRD §21) and `truncated_trace`.

Every risk response includes the fixed disclosure: *"Risk indicators are attention markers for
investigator review. They are not evidence of criminal activity, and detection is limited to
known labelled addresses plus simple heuristics."* (DPRD §24, §27 F05.)

---

## 7. Data provenance and honesty guarantees

Enforced in code, not only in documentation:

1. `TraceResult.data_provenance` ∈ `{live_api, cached, mock_demo, mixed}`; a `mock_demo` or
   `mixed` trace renders an unmissable banner in the UI and a watermark on the PDF.
2. `vasp_addresses.verification_status` ∈ `{verified, unverified, disputed}` with mandatory
   `source` + `source_url`; the seed loader **rejects** any row missing them.
3. Dataset freshness per chain is attached to every trace; older than `STALE_LABEL_DAYS` (30,
   DPRD §21) raises a visible stale-dataset warning.
4. Conflicting labels for one address are surfaced for manual review — never silently resolved.
5. `scoring_config_version` + `label_dataset_version` are stored on every trace, so re-running
   a trace reproduces it exactly unless one of those changed (DPRD §48 task 31).

---

## 8. Security

API keys are server-side only, read from env, never sent to the browser and never logged.
Pydantic validates every request; addresses are chain-validated with checksum verification
before any outbound API call (DPRD §17). Per-IP rate limiting on `/traces`. Parameterized
queries throughout (SQLAlchemy). No private keys, no signing, no wallet connection anywhere in
the system. Errors are sanitized — upstream provider bodies and keys never reach the client.
Every query and state change writes an `audit_logs` row (DPRD F13). Full RBAC/SSO is
Pilot-phase (DPRD §31 "not required for MVP"); the MVP ships a single-role demo identity and
a `user_id` column ready for it.

---

## 9. Directory layout → brief's module map

The brief's suggested top-level modules map onto Python packages inside `backend/app/`, which
keeps imports sane and deployment single-artifact:

| Brief module | Location |
|---|---|
| `frontend/` | `frontend/` |
| `backend/` | `backend/` |
| `blockchain/` | `backend/app/blockchain/` |
| `graph/` | `backend/app/graph/` |
| `attribution/` | `backend/app/attribution/` |
| `risk/` | `backend/app/risk/` |
| `ml/` | `backend/app/ml/` |
| `database/` | `backend/app/database/` |
| `reports/` | `backend/app/reports/` |
| `tests/` | `backend/tests/` + `frontend/src/**/*.test.ts` |
| `docs/` | `docs/` |

See `docs/IMPLEMENTATION_PLAN.md` §2 for the full file tree.
