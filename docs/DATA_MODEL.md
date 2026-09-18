# VASPTrace — Data Model

PostgreSQL (Supabase-compatible), accessed via SQLAlchemy 2.0 + Alembic. SQLite is supported for
local dev only; the schema avoids Postgres-only features except `JSONB` (mapped to `JSON` on
SQLite) and `citext` (avoided — canonical lowercasing is done in application code instead, so
address matching behaves identically on both engines).

Entity set is the brief's list, aligned with DPRD §23. Two additions, both traceable to the
DPRD rather than invented: `api_response_cache` (DPRD §13 caching + §15 trace snapshotting) and
`label_dataset_versions` (DPRD §15 dataset versioning, §21 freshness indicator).

---

## 1. Enumerations

Stored as `VARCHAR` + `CHECK` constraint (portable, and avoids Alembic enum-migration pain).

| Enum | Values |
|---|---|
| `chain` | `ethereum`, `tron`, `bitcoin`, `bnb`, `solana`, `polygon` |
| `data_provenance` | `live_api`, `cached`, `mock_demo`, `mixed` |
| `node_role` | `subject`, `intermediate`, `vasp`, `risk_entity`, `contract` |
| `tx_kind` | `native`, `token`, `internal` |
| `tx_status` | `success`, `failed` |
| `direction` | `in`, `out` |
| `vasp_kind` | `exchange`, `custodial_wallet`, `payment_processor`, `otc_desk`, `broker` |
| `risk_entity_kind` | `mixer`, `bridge`, `gambling`, `darknet_market`, `sanctioned`, `scam_reported` |
| `label_source_tier` | `official_vasp_published`, `sanctions_list`, `community_verified`, `community_unverified`, `demo_unverified` |
| `verification_status` | `verified`, `unverified`, `disputed` |
| `trace_status` | `pending`, `running`, `completed`, `partial`, `failed` |
| `review_decision` | `pending`, `accepted`, `rejected`, `deeper_trace_requested` |
| `report_format` | `json`, `pdf` |
| `case_status` | `open`, `under_review`, `closed` |
| `user_role` | `investigator`, `analyst`, `admin` |

---

## 2. Tables

### 2.1 `users`
Single demo identity in MVP; the column shape is RBAC-ready for Pilot (DPRD §31, F12).

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `email` | `VARCHAR(255)` UNIQUE NOT NULL | |
| `full_name` | `VARCHAR(255)` | |
| `role` | `VARCHAR(32)` NOT NULL DEFAULT `'investigator'` | CHECK in `user_role` |
| `agency` | `VARCHAR(255)` | e.g. "MP Cyber Cell" — used in disclosure drafts |
| `designation` | `VARCHAR(255)` | investigator details on the SAHYOG draft |
| `is_active` | `BOOLEAN` NOT NULL DEFAULT true | |
| `last_login_at`, `created_at` | `TIMESTAMPTZ` | |

### 2.2 `cases`
DPRD F10 case grouping.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `case_ref` | `VARCHAR(64)` UNIQUE NOT NULL | investigator-facing, e.g. `VT-2026-000123` |
| `title` | `VARCHAR(255)` | |
| `description` | `TEXT` | |
| `status` | `VARCHAR(32)` NOT NULL DEFAULT `'open'` | CHECK `case_status` |
| `created_by` | `UUID` FK→`users.id` | |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | |

Index: `(status, created_at DESC)`.

### 2.3 `wallets`
Addresses the system has encountered. Canonical form only; never stores keys or seeds.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `chain` | `VARCHAR(16)` NOT NULL | CHECK `chain` |
| `address` | `VARCHAR(128)` NOT NULL | **canonical** (ETH lowercase hex, Tron base58check) |
| `address_display` | `VARCHAR(128)` | checksummed/original form for the UI |
| `is_contract` | `BOOLEAN` | null = unknown |
| `first_seen_at`, `last_seen_at` | `TIMESTAMPTZ` | from observed txs |
| `tx_count_observed` | `INTEGER` | count seen by our traces, not chain total |
| `created_at` | `TIMESTAMPTZ` | |

Constraints: `UNIQUE (chain, address)`. Index: `(chain, address)`.

### 2.4 `transactions`
Normalized native/internal transfers (`NormalizedTx`, `kind != 'token'`).

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `chain` | `VARCHAR(16)` NOT NULL | |
| `tx_hash` | `VARCHAR(128)` NOT NULL | |
| `block_number` | `BIGINT` | |
| `block_timestamp` | `TIMESTAMPTZ` NOT NULL | UTC |
| `from_address`, `to_address` | `VARCHAR(128)` NOT NULL | canonical |
| `asset_symbol` | `VARCHAR(32)` NOT NULL | `ETH`, `TRX` |
| `amount` | `NUMERIC(38,18)` NOT NULL | human units |
| `amount_raw` | `VARCHAR(80)` NOT NULL | wei/sun, exact integer as string |
| `decimals` | `SMALLINT` NOT NULL | |
| `kind` | `VARCHAR(16)` NOT NULL | CHECK `tx_kind` |
| `status` | `VARCHAR(16)` NOT NULL | CHECK `tx_status` |
| `fee` | `NUMERIC(38,18)` | |
| `provenance` | `VARCHAR(16)` NOT NULL | CHECK `data_provenance` |
| `raw_ref` | `UUID` FK→`api_response_cache.id` | which snapshot produced this row |
| `created_at` | `TIMESTAMPTZ` | |

Constraints: `UNIQUE (chain, tx_hash, from_address, to_address, asset_symbol, kind)` — a single
hash can move value between several address pairs (internal transfers).
Indexes: `(chain, from_address, block_timestamp DESC)`, `(chain, to_address, block_timestamp DESC)`,
`(chain, tx_hash)`.

### 2.5 `token_transfers`
ERC-20 / TRC-20 movements, kept separate because USDT-on-Tron is the dominant rail (DPRD §11)
and its query patterns differ (contract-scoped).

Same columns as `transactions` plus:

| Column | Type | Notes |
|---|---|---|
| `asset_contract` | `VARCHAR(128)` NOT NULL | token contract, canonical |
| `log_index` | `INTEGER` | disambiguates multiple transfers in one tx |

Constraints: `UNIQUE (chain, tx_hash, log_index)`.
Indexes: `(chain, from_address, block_timestamp DESC)`, `(chain, to_address, block_timestamp DESC)`,
`(chain, asset_contract)`.

### 2.6 `vasps`
The VASP entity — one row per service provider, independent of how many addresses it owns.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `slug` | `VARCHAR(64)` UNIQUE NOT NULL | `binance`, `wazirx` |
| `name` | `VARCHAR(255)` NOT NULL | |
| `legal_entity` | `VARCHAR(255)` | as published, if known |
| `kind` | `VARCHAR(32)` NOT NULL | CHECK `vasp_kind` |
| `jurisdiction` | `VARCHAR(8)` | ISO-3166 alpha-2 |
| `is_fiu_ind_registered` | `BOOLEAN` | null = unknown; relevant to whether an Indian LEA can route a request |
| `website` | `VARCHAR(512)` | |
| `nodal_officer_channel` | `VARCHAR(512)` | public LEA/grievance contact page only — no scraped personal data |
| `notes` | `TEXT` | |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | |

> `is_fiu_ind_registered` and `nodal_officer_channel` are set **only** from a cited public
> source, or left null. They feed the disclosure draft's routing line.

### 2.7 `vasp_addresses`
The product's core asset (DPRD §16, §47(22)). Provenance columns are **NOT NULL** — the
importer rejects a row that cannot cite where the label came from.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `vasp_id` | `UUID` FK→`vasps.id` NOT NULL | |
| `chain` | `VARCHAR(16)` NOT NULL | |
| `address` | `VARCHAR(128)` NOT NULL | canonical |
| `address_type` | `VARCHAR(32)` | `hot_wallet`, `deposit`, `cold_wallet`, `contract` |
| `source` | `VARCHAR(255)` NOT NULL | dataset/publisher name |
| `source_url` | `VARCHAR(1024)` NOT NULL | citable URL |
| `source_tier` | `VARCHAR(32)` NOT NULL | CHECK `label_source_tier` → drives the reliability factor |
| `verification_status` | `VARCHAR(16)` NOT NULL | CHECK `verification_status` |
| `verified_by` | `VARCHAR(255)` | who confirmed it |
| `verified_at` | `TIMESTAMPTZ` | null ⇒ cannot be `verified` (DB CHECK) |
| `reliability` | `NUMERIC(3,2)` NOT NULL | 0.00–1.00; defaults from `source_tier`, overridable |
| `notes` | `TEXT` | |
| `dataset_version_id` | `UUID` FK→`label_dataset_versions.id` NOT NULL | |
| `last_updated_at`, `created_at` | `TIMESTAMPTZ` NOT NULL | |
| `is_active` | `BOOLEAN` NOT NULL DEFAULT true | soft-retire a withdrawn label without losing history |

Constraints:
- `UNIQUE (chain, address, vasp_id, source)` — the same address from two sources is two rows, so
  agreement and **conflict** are both visible (DPRD §21 conflicting-label warning).
- `CHECK (verification_status <> 'verified' OR verified_at IS NOT NULL)`.
- `CHECK (source_tier <> 'demo_unverified' OR verification_status = 'unverified')`.

Indexes: `(chain, address) WHERE is_active` — the hot lookup on every traversal node;
`(vasp_id)`, `(source_tier)`.

### 2.8 `risk_entities`
Mixers, bridges, sanctioned addresses. Same provenance discipline as `vasp_addresses`.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `chain` | `VARCHAR(16)` NOT NULL | |
| `address` | `VARCHAR(128)` NOT NULL | canonical |
| `entity_kind` | `VARCHAR(32)` NOT NULL | CHECK `risk_entity_kind` |
| `entity_name` | `VARCHAR(255)` | e.g. "Tornado Cash router" |
| `severity` | `VARCHAR(16)` NOT NULL | `info`/`low`/`medium`/`high` |
| `source`, `source_url`, `source_tier` | as §2.7, NOT NULL | OFAC SDN / OpenSanctions per DPRD §16 |
| `verification_status` | `VARCHAR(16)` NOT NULL | |
| `dataset_version_id` | `UUID` FK NOT NULL | |
| `last_updated_at`, `created_at` | `TIMESTAMPTZ` | |
| `is_active` | `BOOLEAN` NOT NULL DEFAULT true | |

Constraints: `UNIQUE (chain, address, entity_kind, source)`. Index: `(chain, address) WHERE is_active`.

### 2.9 `label_dataset_versions`
DPRD §15 dataset versioning / §21 freshness.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `version` | `VARCHAR(64)` UNIQUE NOT NULL | e.g. `2026-09-18.1` |
| `chain` | `VARCHAR(16)` | null = multi-chain import |
| `source_manifest` | `JSONB` NOT NULL | every source file + URL + sha256 + row count |
| `vasp_address_count`, `risk_entity_count` | `INTEGER` NOT NULL | |
| `imported_by` | `UUID` FK→`users.id` | |
| `imported_at` | `TIMESTAMPTZ` NOT NULL | drives the stale-dataset warning |
| `integrity_report` | `JSONB` | duplicate/conflict scan results (DPRD §35) |

### 2.10 `traces`
One attribution run.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `case_id` | `UUID` FK→`cases.id` | nullable — ad-hoc lookups allowed |
| `subject_address` | `VARCHAR(128)` NOT NULL | canonical |
| `subject_address_input` | `VARCHAR(128)` NOT NULL | exactly what the investigator typed |
| `chain` | `VARCHAR(16)` NOT NULL | |
| `hop_depth` | `SMALLINT` NOT NULL | CHECK between 1 and 6 |
| `direction` | `VARCHAR(8)` NOT NULL DEFAULT `'out'` | |
| `status` | `VARCHAR(16)` NOT NULL | CHECK `trace_status` |
| `data_provenance` | `VARCHAR(16)` NOT NULL | |
| `truncated` | `BOOLEAN` NOT NULL DEFAULT false | |
| `truncation_reason` | `VARCHAR(255)` | |
| `nodes_expanded`, `api_calls_made`, `tx_analyzed_count` | `INTEGER` NOT NULL | shown on the result page |
| `duration_ms` | `INTEGER` | DPRD §20 time-to-attribution metric |
| `label_dataset_version_id` | `UUID` FK NOT NULL | reproducibility |
| `scoring_config_version` | `VARCHAR(32)` NOT NULL | reproducibility |
| `budget_config` | `JSONB` NOT NULL | exact budgets used |
| `engine_version` | `VARCHAR(32)` NOT NULL | git describe / package version |
| `review_decision` | `VARCHAR(32)` NOT NULL DEFAULT `'pending'` | CHECK `review_decision` |
| `reviewed_by` | `UUID` FK→`users.id` | |
| `reviewed_at` | `TIMESTAMPTZ` | |
| `review_note` | `TEXT` | |
| `error_message` | `VARCHAR(1024)` | when `status='failed'` |
| `created_by` | `UUID` FK→`users.id` | |
| `created_at` | `TIMESTAMPTZ` NOT NULL | |

Indexes: `(case_id, created_at DESC)`, `(chain, subject_address, created_at DESC)`.

### 2.11 `trace_nodes`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `trace_id` | `UUID` FK→`traces.id` ON DELETE CASCADE NOT NULL | |
| `address` | `VARCHAR(128)` NOT NULL | canonical |
| `address_display` | `VARCHAR(128)` | |
| `role` | `VARCHAR(16)` NOT NULL | CHECK `node_role` |
| `hop_distance` | `SMALLINT` NOT NULL | 0 = subject |
| `matched_vasp_id` | `UUID` FK→`vasps.id` | set when role=`vasp` |
| `matched_vasp_address_id` | `UUID` FK→`vasp_addresses.id` | the exact label row used |
| `matched_risk_entity_id` | `UUID` FK→`risk_entities.id` | |
| `in_degree`, `out_degree` | `INTEGER` | as observed within this trace |
| `counterparty_count` | `INTEGER` | for fan-out/fan-in indicators |
| `value_in`, `value_out` | `NUMERIC(38,18)` | native-equivalent, per trace |
| `expanded` | `BOOLEAN` NOT NULL | false ⇒ frontier was cut here |
| `not_expanded_reason` | `VARCHAR(64)` | `vasp_terminal`/`fanout_terminal`/`budget`/`max_hop` |
| `attrs` | `JSONB` | assets seen, first/last activity |

Constraints: `UNIQUE (trace_id, address)`. Index: `(trace_id, hop_distance)`.

### 2.12 `trace_edges`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `trace_id` | `UUID` FK→`traces.id` ON DELETE CASCADE NOT NULL | |
| `from_node_id`, `to_node_id` | `UUID` FK→`trace_nodes.id` NOT NULL | |
| `tx_hash` | `VARCHAR(128)` NOT NULL | |
| `direction` | `VARCHAR(8)` NOT NULL | relative to the subject's flow |
| `asset_symbol` | `VARCHAR(32)` NOT NULL | |
| `asset_contract` | `VARCHAR(128)` | |
| `amount` | `NUMERIC(38,18)` NOT NULL | |
| `block_timestamp` | `TIMESTAMPTZ` NOT NULL | |
| `hop_index` | `SMALLINT` NOT NULL | which hop this edge belongs to |
| `chain` | `VARCHAR(16)` NOT NULL | |
| `value_share` | `NUMERIC(9,8)` | this edge's share of the source node's outflow |
| `is_on_evidence_path` | `BOOLEAN` NOT NULL DEFAULT false | drives path highlighting in the UI |
| `attrs` | `JSONB` | log_index, fee, status |

Constraints: `UNIQUE (trace_id, tx_hash, from_node_id, to_node_id, asset_symbol, COALESCE(log_index...))`
— implemented as a `dedup_key VARCHAR(255)` computed in the app + `UNIQUE (trace_id, dedup_key)`,
which is portable to SQLite.
Indexes: `(trace_id, hop_index)`, `(trace_id, is_on_evidence_path)`.

### 2.13 `attributions`
One row per **candidate** VASP, so the UI can show a ranked list (DPRD §6: "returns a ranked
list of candidate VASP attributions").

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `trace_id` | `UUID` FK→`traces.id` ON DELETE CASCADE NOT NULL | |
| `vasp_id` | `UUID` FK→`vasps.id` NOT NULL | |
| `rank` | `SMALLINT` NOT NULL | 1 = best |
| `is_primary` | `BOOLEAN` NOT NULL DEFAULT false | rank 1 **and** above `MIN_ATTRIBUTION_SCORE` |
| `score` | `SMALLINT` NOT NULL | 0–100 |
| `score_band` | `VARCHAR(16)` NOT NULL | `insufficient`…`very_strong` |
| `score_type` | `VARCHAR(48)` NOT NULL DEFAULT `'heuristic_investigative_score'` | never "probability" |
| `calibrated` | `BOOLEAN` NOT NULL DEFAULT false | |
| `min_hop_distance` | `SMALLINT` NOT NULL | |
| `matched_address_ids` | `JSONB` NOT NULL | `vasp_addresses.id[]` that matched |
| `interaction_tx_count` | `INTEGER` NOT NULL | |
| `interaction_value` | `NUMERIC(38,18)` | |
| `value_share` | `NUMERIC(9,8)` | |
| `score_breakdown` | `JSONB` NOT NULL | factors, weights, contributions, penalties, sentences |
| `evidence` | `JSONB` NOT NULL | evidence path node/edge ids + supporting tx hashes |
| `risk_indicators` | `JSONB` NOT NULL | indicators on this candidate's path |
| `ml_score` | `SMALLINT` | Phase 14 shadow score; never shown as the decision |
| `ml_model_version` | `VARCHAR(64)` | |
| `created_at` | `TIMESTAMPTZ` | |

Constraints: `UNIQUE (trace_id, vasp_id)`, `UNIQUE (trace_id, rank)`.
A trace with zero candidates simply has no `attributions` rows; the reason lives in
`traces.truncation_reason` / the computed `no_attribution_reason` in the response.

### 2.14 `reports`

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `trace_id` | `UUID` FK→`traces.id` NOT NULL | |
| `format` | `VARCHAR(8)` NOT NULL | CHECK `report_format` |
| `report_ref` | `VARCHAR(64)` UNIQUE NOT NULL | printed on the PDF, e.g. `VT-RPT-000045` |
| `payload` | `JSONB` | the JSON report, stored verbatim so the PDF is reproducible |
| `file_path` | `VARCHAR(512)` | local/object-store path for the PDF |
| `content_sha256` | `CHAR(64)` | integrity of the exported artifact |
| `template_version` | `VARCHAR(32)` NOT NULL | DPRD §35 template-change QC |
| `generated_by` | `UUID` FK→`users.id` | |
| `generated_at` | `TIMESTAMPTZ` NOT NULL | |

### 2.15 `disclosure_requests`
Mock SAHYOG drafts. Named explicitly so no one mistakes it for a live submission log.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `trace_id` | `UUID` FK NOT NULL | |
| `attribution_id` | `UUID` FK→`attributions.id` NOT NULL | which candidate it addresses |
| `vasp_id` | `UUID` FK NOT NULL | |
| `draft_ref` | `VARCHAR(64)` UNIQUE NOT NULL | `VT-DISC-000012` |
| `mode` | `VARCHAR(16)` NOT NULL DEFAULT `'mock_demo'` | CHECK `mode IN ('mock_demo')` in MVP — a live mode cannot be created by accident |
| `payload` | `JSONB` NOT NULL | SAHYOG-shaped structured request |
| `payload_schema_version` | `VARCHAR(32)` NOT NULL | schema-flexible per DPRD §47(26) |
| `requested_information` | `JSONB` NOT NULL | KYC, deposit-address owner, login IPs, etc. |
| `created_by` | `UUID` FK | |
| `created_at` | `TIMESTAMPTZ` | |

`CHECK`: a row may only exist when the parent trace's `review_decision = 'accepted'` — enforced
in the service layer and asserted by a test (DPRD §24: no disclosure without human review).

### 2.16 `api_response_cache`
Caching (DPRD §13) + trace snapshotting (DPRD §15) in one table.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` PK | |
| `cache_key` | `VARCHAR(255)` UNIQUE NOT NULL | `sha256(provider|endpoint|sorted params)` |
| `chain` | `VARCHAR(16)` NOT NULL | |
| `provider` | `VARCHAR(64)` NOT NULL | `etherscan`, `trongrid`, `bitquery`, `mock` |
| `endpoint` | `VARCHAR(255)` NOT NULL | |
| `request_params` | `JSONB` NOT NULL | API key stripped before storage |
| `response_body` | `JSONB` NOT NULL | raw upstream response |
| `http_status` | `SMALLINT` NOT NULL | |
| `fetched_at` | `TIMESTAMPTZ` NOT NULL | |
| `expires_at` | `TIMESTAMPTZ` | null = keep as an immutable snapshot |
| `is_snapshot` | `BOOLEAN` NOT NULL DEFAULT false | true ⇒ exempt from cache eviction |

Index: `(cache_key)`, `(expires_at)`.

### 2.17 `trace_snapshot_refs`
Join table pinning which cached responses produced a given trace, so a report can be regenerated
months later (DPRD §15).

`trace_id` FK, `api_response_cache_id` FK, `PRIMARY KEY (trace_id, api_response_cache_id)`.
Inserting a row sets `api_response_cache.is_snapshot = true`.

### 2.18 `audit_logs`
DPRD F13.

| Column | Type | Notes |
|---|---|---|
| `id` | `BIGSERIAL` PK | append-only |
| `user_id` | `UUID` FK→`users.id` | nullable for system actions |
| `action` | `VARCHAR(64)` NOT NULL | `trace.create`, `trace.review`, `report.export`, `disclosure.draft`, `labels.import`, `auth.login` |
| `target_type` | `VARCHAR(32)` | `trace`, `case`, `report`, … |
| `target_id` | `VARCHAR(64)` | |
| `metadata` | `JSONB` | request summary; **never** API keys or full request bodies |
| `ip_address` | `VARCHAR(64)` | |
| `user_agent` | `VARCHAR(255)` | |
| `created_at` | `TIMESTAMPTZ` NOT NULL | |

Index: `(created_at DESC)`, `(user_id, created_at DESC)`, `(target_type, target_id)`.

### 2.19 `ml_experiments` (Phase 14, optional)
`id`, `model_name`, `model_version`, `algorithm`, `feature_set_version`, `train_rows`,
`test_rows`, `split_strategy`, `metrics JSONB` (top-1/top-3/precision/recall/F1/calibration),
`artifact_path`, `notes`, `created_at`. Backs `ml/MODEL_CARD.md`; metrics are only ever written
by the training script, never hand-edited.

---

## 3. Relationship summary

```
users ──< cases ──< traces ──< trace_nodes ──< trace_edges
                       │  ├──< attributions ──< disclosure_requests
                       │  ├──< reports
                       │  └──< trace_snapshot_refs >── api_response_cache
                       └──> label_dataset_versions

vasps ──< vasp_addresses >── label_dataset_versions
risk_entities >── label_dataset_versions
wallets, transactions, token_transfers  (observation store, chain-keyed, trace-independent)
users ──< audit_logs
```

`trace_nodes`/`trace_edges` are intentionally **denormalized per trace** rather than pointing at
the global `transactions` table. A trace must stay byte-identical when replayed even if the
observation store is later refreshed — that is the DPRD §15 reproducibility requirement.

---

## 4. Seeding and import rules

1. Label seeds live in `data/labels/<source>/*.csv|json` with a sibling `PROVENANCE.md` naming
   the publisher, URL, licence, and retrieval date.
2. `python -m app.database.seeds.import_labels --manifest data/labels/manifest.yaml` creates one
   `label_dataset_versions` row and inserts labels atomically.
3. The importer **fails the whole import** if any row lacks `source`, `source_url`, or
   `source_tier`, or claims `verified` without `verified_at`.
4. After import it runs the integrity scan (duplicates, cross-source conflicts, malformed
   addresses per chain) and writes `integrity_report` — DPRD §13 dataset gate, §35 QC.
5. Demo-only labels must use `source_tier='demo_unverified'`, live under
   `data/labels/demo/`, and are excluded unless `ALLOW_DEMO_LABELS=true`. They can never
   produce a primary attribution on their own (see `ARCHITECTURE.md` §5 refusal rule).
