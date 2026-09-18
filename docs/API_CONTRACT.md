# VASPTrace — API Contract

Base URL: `/api/v1` · JSON in/out, UTF-8 · all timestamps ISO-8601 UTC (`2026-09-18T07:44:12Z`)
· all monetary amounts are **decimal strings**, never floats (`"1250.435"`), with `amount_raw`
carrying the exact integer base unit · FastAPI serves OpenAPI at `/docs`.

Every response that contains chain data carries `data_provenance` ∈
`live_api | cached | mock_demo | mixed`. Every response containing a score carries
`score_type: "heuristic_investigative_score"`, `calibrated: false`, and the fixed
`disclaimer` string. These are non-optional (brief + DPRD §24, §41).

---

## 1. Endpoint index

| Method | Path | Purpose | Phase |
|---|---|---|---|
| `GET` | `/health` | liveness + dependency status | 1 |
| `GET` | `/meta/chains` | supported chains, adapter status, label coverage & freshness | 1 |
| `GET` | `/meta/config` | public knobs (hop min/max, score bands, disclaimers) | 1 |
| `POST` | `/addresses/validate` | chain-specific address validation | 3 |
| `POST` | `/traces` | **run a trace** (synchronous) | 6–9 |
| `GET` | `/traces/{trace_id}` | full trace result | 6 |
| `GET` | `/traces/{trace_id}/graph` | graph payload for the visualizer | 11 |
| `GET` | `/traces/{trace_id}/attributions/{attribution_id}/evidence` | full evidence bundle for one candidate | 11 |
| `POST` | `/traces/{trace_id}/review` | human review gate (accept/reject/deeper) | 10 |
| `GET` | `/traces/{trace_id}/report.json` | JSON report | 12 |
| `GET` | `/traces/{trace_id}/report.pdf` | PDF report (`application/pdf`) | 12 |
| `POST` | `/traces/{trace_id}/disclosure` | draft MOCK SAHYOG request | 13 |
| `GET` | `/disclosures/{draft_ref}` | retrieve a draft | 13 |
| `GET`/`POST` | `/cases`, `GET /cases/{id}` | case grouping | 10 |
| `GET` | `/vasps`, `/vasps/{slug}` | VASP directory | 2 |
| `GET` | `/vasps/addresses` | label lookup (`?chain=&address=` or `?q=`) | 2 |
| `GET` | `/labels/versions` | dataset versions + integrity reports | 2 |
| `GET` | `/audit-logs` | audit trail (admin) | 15 |

---

## 2. Core types

```ts
type Chain = "ethereum" | "tron";                     // MVP; roadmap chains return 400 with a clear message
type DataProvenance = "live_api" | "cached" | "mock_demo" | "mixed";
type NodeRole = "subject" | "intermediate" | "vasp" | "risk_entity" | "contract";
type ScoreBand = "insufficient" | "low" | "moderate" | "strong" | "very_strong";
type LabelTier = "official_vasp_published" | "sanctions_list"
               | "community_verified" | "community_unverified" | "demo_unverified";
```

```ts
interface ScoreFactor {
  key: "hop_distance" | "label_reliability" | "interaction_count"
     | "value_share" | "path_strength" | "temporal_consistency";
  label: string;              // "Hop distance"
  raw_value: string;          // "2 hops"
  normalized: number;         // 0..1
  weight: number;             // 0..1
  contribution: number;       // normalized * weight, rounded to 4dp
  explanation: string;        // "VASP reached in 2 hops — short, direct paths score higher."
}

interface ScorePenalty {
  key: string;                // "mixer_interaction"
  label: string;
  penalty: number;            // subtracted from the 0..1 raw score
  reason: string;
  evidence_addresses: string[];
}

interface ScoreBreakdown {
  factors: ScoreFactor[];
  penalties: ScorePenalty[];
  raw_score: number;          // 0..1 before penalties
  penalty_total: number;
  final_score: number;        // 0..100 integer
  band: ScoreBand;
  score_type: "heuristic_investigative_score";
  calibrated: false;
  scoring_config_version: string;
  disclaimer: string;         // "Heuristic investigative score — not a calibrated probability."
}

interface RiskIndicator {
  key: string;                // "mixer_interaction" | "high_fan_out" | ...
  label: string;
  severity: "info" | "low" | "medium" | "high";
  detection_basis: "labelled_address" | "heuristic";
  description: string;        // neutral wording, no accusation
  evidence_addresses: string[];
  evidence_tx_hashes: string[];
}

interface LabelProvenance {
  vasp_address_id: string;
  address: string;
  address_type: string | null;
  source: string;
  source_url: string;
  source_tier: LabelTier;
  verification_status: "verified" | "unverified" | "disputed";
  verified_at: string | null;
  reliability: number;        // 0..1
  label_age_days: number;
  is_stale: boolean;          // > STALE_LABEL_DAYS
}
```

---

## 3. `GET /meta/chains`

```json
{
  "chains": [
    {
      "chain": "ethereum",
      "display_name": "Ethereum",
      "native_asset": "ETH",
      "status": "supported",
      "adapter_provenance": "live_api",
      "providers": ["etherscan"],
      "coverage": {
        "vasp_count": 18,
        "vasp_address_count": 412,
        "risk_entity_count": 96,
        "label_dataset_version": "2026-09-18.1",
        "label_dataset_age_days": 0,
        "is_stale": false,
        "coverage_level": "partial",
        "coverage_notice": "Partial label coverage. A non-match does not mean no VASP exists."
      }
    },
    { "chain": "bitcoin", "status": "roadmap", "coverage": null }
  ],
  "stale_label_days_threshold": 30
}
```

`status` ∈ `supported | degraded | roadmap`. `degraded` means the adapter is configured but its
last health probe failed — the UI disables that chain with the reason shown (DPRD §27 F09).

---

## 4. `POST /addresses/validate`

Request: `{ "address": "0x742d...", "chain": "ethereum" }`

```json
{
  "valid": true,
  "chain": "ethereum",
  "canonical_address": "0x742d35cc6634c0532925a3b844bc454e4438f44e",
  "display_address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
  "checksum_valid": true,
  "address_kind": "eoa_or_unknown",
  "normalization_note": null,
  "error": null
}
```

On failure: `valid: false` with `error.code` ∈ `INVALID_LENGTH | INVALID_CHARSET |
CHECKSUM_MISMATCH | INVALID_BASE58_CHECKSUM | WRONG_CHAIN_FORMAT` and a plain-language
`error.message`. Wrong-chain detection is explicit: pasting a `T…` address with
`chain=ethereum` returns `WRONG_CHAIN_FORMAT` with `suggested_chain: "tron"`.

---

## 5. `POST /traces` — the main call

```json
{
  "address": "0x742d35Cc6634C0532925a3b844Bc454e4438f44e",
  "chain": "ethereum",
  "hop_depth": 3,
  "direction": "out",
  "case_id": null,
  "case_ref_hint": "VT-2026-000123",
  "options": { "include_token_transfers": true, "force_refresh": false }
}
```

`hop_depth`: integer 1–6, default 3 (brief). `direction` default `"out"` (DPRD §6 step 3).
`422` on validation failure; `400 CHAIN_NOT_SUPPORTED` for roadmap chains.

### 200 response — `TraceResult`

```json
{
  "trace_id": "9f1c…",
  "case_id": null,
  "case_ref": null,
  "status": "completed",
  "subject": {
    "address_input": "0x742d35Cc…f44e",
    "canonical_address": "0x742d35cc…f44e",
    "display_address": "0x742d35Cc…f44e",
    "chain": "ethereum"
  },
  "run": {
    "hop_depth_requested": 3,
    "max_hop_reached": 3,
    "direction": "out",
    "transactions_analyzed": 1184,
    "unique_addresses_discovered": 217,
    "nodes_expanded": 96,
    "api_calls_made": 41,
    "duration_ms": 6280,
    "truncated": false,
    "truncation_reason": null,
    "started_at": "2026-09-18T07:44:12Z"
  },
  "data_provenance": "live_api",
  "provenance_notice": null,
  "dataset": {
    "label_dataset_version": "2026-09-18.1",
    "label_dataset_age_days": 0,
    "is_stale": false,
    "coverage_level": "partial",
    "coverage_notice": "Partial label coverage…"
  },
  "engine": { "engine_version": "0.1.0", "scoring_config_version": "sc-v1" },

  "primary_attribution": {
    "attribution_id": "a12…",
    "rank": 1,
    "vasp": {
      "id": "…", "slug": "example-exchange", "name": "Example Exchange",
      "kind": "exchange", "jurisdiction": "SC", "is_fiu_ind_registered": null,
      "website": "https://…", "nodal_officer_channel": "https://…/law-enforcement"
    },
    "score": 86,
    "score_band": "very_strong",
    "score_type": "heuristic_investigative_score",
    "calibrated": false,
    "min_hop_distance": 2,
    "interaction_tx_count": 8,
    "interaction_value": "12.4081",
    "interaction_asset_summary": [ { "asset": "ETH", "amount": "12.4081", "tx_count": 8 } ],
    "value_share": 0.71,
    "score_breakdown": { "…": "ScoreBreakdown" },
    "matched_labels": [ { "…": "LabelProvenance" } ],
    "evidence_path": {
      "hops": 2,
      "nodes": ["0x742d…", "0x9ab1…", "0x28c6…"],
      "edges": [
        { "edge_id": "e1", "tx_hash": "0xabc…", "from": "0x742d…", "to": "0x9ab1…",
          "asset": "ETH", "amount": "9.5", "timestamp": "2026-08-14T11:02:00Z",
          "hop_index": 1, "value_share": 0.82 }
      ],
      "path_strength": 0.61
    },
    "supporting_transactions": ["0xabc…", "0xdef…"],
    "risk_indicators": [ { "…": "RiskIndicator" } ],
    "why_summary": [
      "Address labelled as an Example Exchange deposit wallet (source: OFAC/OpenSanctions-style citable list, verified 2026-09-01).",
      "Reached in 2 hops from the subject wallet.",
      "8 transactions totalling 12.4081 ETH reached this VASP's addresses.",
      "71% of the subject wallet's traced outflow ended at this VASP.",
      "Transaction timestamps are consistently ordered along the path."
    ]
  },

  "candidates": [ "…ranked list, same shape as primary_attribution…" ],

  "no_attribution": null,

  "risk_summary": {
    "indicators": [ { "…": "RiskIndicator" } ],
    "highest_severity": "medium",
    "disclaimer": "Risk indicators are attention markers for investigator review. They are not evidence of criminal activity, and detection is limited to known labelled addresses plus simple heuristics."
  },

  "review": { "decision": "pending", "reviewed_by": null, "reviewed_at": null, "note": null },

  "limitations": [
    "Attribution is limited to addresses present in the labelled dataset; coverage is partial.",
    "Traversal stopped at 3 hops. A VASP further away would not be found.",
    "The score is a heuristic investigative score and has not been statistically calibrated."
  ],
  "disclaimer": "This output is an investigative lead and not legal proof.",
  "next_actions": { "can_export_report": true, "can_draft_disclosure": false,
                    "can_draft_disclosure_reason": "Investigator review required before drafting a disclosure request." }
}
```

### The no-attribution response (never force a result)

`primary_attribution: null`, `candidates: []` or below-threshold candidates listed with
`is_primary: false`, and:

```json
"no_attribution": {
  "headline": "No reliable VASP attribution found.",
  "reason_code": "no_vasp_within_hop_cap",
  "reason": "No labelled VASP address was reached within 3 hops of this wallet.",
  "what_this_does_not_mean": "This does not mean the wallet has no VASP relationship — only that none was found within the current hop cap and label coverage.",
  "suggested_next_steps": [
    "Re-run with a deeper trace (up to 6 hops).",
    "Check the dataset coverage notice for this chain.",
    "Review the traced graph manually for unlabelled intermediaries."
  ]
}
```

`reason_code` ∈ `no_vasp_within_hop_cap` · `below_score_threshold` ·
`only_unverified_labels` · `no_outbound_activity` · `trace_truncated_before_match`.

### Errors

| HTTP | `error.code` | When |
|---|---|---|
| 400 | `CHAIN_NOT_SUPPORTED` | roadmap chain requested |
| 422 | `INVALID_ADDRESS` | validation failed (includes the validate-endpoint detail) |
| 429 | `RATE_LIMITED` | our per-IP limit; `Retry-After` set |
| 502 | `UPSTREAM_PROVIDER_ERROR` | chain API failed after retries; `provider` + `attempts`, never the upstream body |
| 503 | `UPSTREAM_RATE_LIMITED` | provider quota exhausted; `Retry-After` set |
| 504 | `TRACE_BUDGET_EXCEEDED` | only when zero usable data was collected; otherwise a `partial` 200 |

Error envelope, uniform across the API:

```json
{ "error": { "code": "UPSTREAM_RATE_LIMITED", "message": "Ethereum data provider rate limit reached. Please retry shortly.",
             "details": { "provider": "etherscan", "retry_after_s": 12 }, "request_id": "req_01J…" } }
```

---

## 6. `GET /traces/{id}/graph`

Cytoscape-ready, plus the fields the details panel needs.

```json
{
  "trace_id": "9f1c…",
  "chain": "ethereum",
  "max_hop": 3,
  "nodes": [
    { "id": "0x742d…", "role": "subject", "hop": 0, "display": "0x742d…f44e",
      "label": null, "tx_count": 42, "value_in": "0", "value_out": "15.1",
      "counterparty_count": 6, "risk_indicator_keys": [], "expanded": true,
      "not_expanded_reason": null },
    { "id": "0x28c6…", "role": "vasp", "hop": 2, "label": "Example Exchange",
      "vasp_slug": "example-exchange", "label_tier": "community_verified",
      "verification_status": "verified", "…": "…" }
  ],
  "edges": [
    { "id": "e1", "source": "0x742d…", "target": "0x9ab1…", "tx_hash": "0xabc…",
      "asset": "ETH", "amount": "9.5", "timestamp": "2026-08-14T11:02:00Z",
      "hop_index": 1, "direction": "out", "value_share": 0.82,
      "on_evidence_path": true, "explorer_url": "https://etherscan.io/tx/0xabc…" }
  ],
  "legend": { "roles": { "subject": "Queried wallet", "vasp": "Known VASP address", "…": "…" } },
  "stats": { "node_count": 217, "edge_count": 1184, "rendered_node_cap": 300 }
}
```

If `node_count > rendered_node_cap`, the payload returns the top-N by value share with
`"truncated_for_rendering": true` so the browser stays responsive (brief: lazy graph rendering).

---

## 7. `POST /traces/{id}/review`

Request: `{ "decision": "accepted", "note": "Path verified against Etherscan manually." }`
Decision ∈ `accepted | rejected | deeper_trace_requested`.

Response echoes the review block and updates `next_actions.can_draft_disclosure`. A
`deeper_trace_requested` response includes `suggested_hop_depth` (current + 1, capped at 6).
**Hard gate:** `POST /traces/{id}/disclosure` returns `409 REVIEW_REQUIRED` unless the decision
is `accepted` (DPRD §24, §47(25)).

---

## 8. `GET /traces/{id}/report.json`

The JSON report is the reproducible evidentiary artifact, and the PDF is rendered from exactly
this payload. Sections, in order:

`report_ref` · `generated_at` · `template_version` · `case` · `subject` · `run` ·
`data_sources` (provider + endpoint + fetched_at per chain, plus label dataset version and every
source URL used) · `attribution` (candidate, score, full `ScoreBreakdown`, `matched_labels` with
provenance) · `graph_path` (the evidence path as an ordered hop table) · `evidence`
(transaction table: hash, timestamp, from, to, asset, amount, explorer URL) · `risk_indicators`
· `candidates_considered` (ranked, with the reason each was not primary) · `limitations` ·
`human_review` (decision, reviewer, timestamp, note) · `reproducibility`
(`label_dataset_version`, `scoring_config_version`, `engine_version`, `budget_config`,
`snapshot_ids`) · `legal_notice`.

`legal_notice` is a fixed block containing, verbatim:
> This output is an investigative lead and not legal proof. The attribution score is a heuristic
> investigative score and has not been statistically calibrated. This system does not identify
> the real-world identity of any wallet owner and does not execute any freezing or blocking
> action. Independent investigator verification is required before any action is taken.

`GET /traces/{id}/report.pdf` renders the same payload; every page footer carries the report ref,
the trace id, and "Investigative lead — not legal proof". Mock-data traces additionally carry a
diagonal `DEMO DATA` watermark.

---

## 9. `POST /traces/{id}/disclosure` — MOCK SAHYOG

Request: `{ "attribution_id": "a12…", "requested_information": ["kyc_record","deposit_address_owner","login_ip_logs","linked_bank_accounts"], "investigator": { "name": "…", "designation": "…", "agency": "…", "contact_email": "…", "case_ref": "VT-2026-000123" } }`

```json
{
  "draft_ref": "VT-DISC-000012",
  "mode": "mock_demo",
  "mode_banner": "DEMO / MOCK SAHYOG REQUEST — not transmitted to any portal or VASP.",
  "payload_schema_version": "sahyog-mock-v1",
  "payload": {
    "request_type": "vasp_information_disclosure_request",
    "case": { "case_ref": "VT-2026-000123", "requesting_agency": "…", "investigating_officer": { "…": "…" } },
    "subject_wallet": { "address": "0x742d…", "chain": "ethereum" },
    "suspected_vasp": { "name": "Example Exchange", "slug": "example-exchange",
                        "matched_addresses": ["0x28c6…"], "routing_channel": "https://…" },
    "attribution_summary": { "score": 86, "score_type": "heuristic_investigative_score",
                             "calibrated": false, "hop_distance": 2,
                             "basis": "Labelled deposit address reached in 2 hops over 8 transactions." },
    "transaction_references": [ { "tx_hash": "0xabc…", "timestamp": "…", "asset": "ETH", "amount": "9.5", "explorer_url": "…" } ],
    "evidence_summary": "…generated from the trace, no free-form speculation…",
    "requested_information": ["kyc_record", "deposit_address_owner", "login_ip_logs", "linked_bank_accounts"],
    "legal_basis_placeholder": "To be completed by the investigating officer under the applicable statutory provision.",
    "attached_report_ref": "VT-RPT-000045",
    "notice": "This is a system-generated draft based on a heuristic attribution. It is an investigative lead, not legal proof, and requires officer review and lawful authorisation before submission."
  },
  "created_at": "2026-09-18T08:02:11Z"
}
```

`mode` can only be `mock_demo` in the MVP; there is no code path that sets anything else, and no
outbound network call is made (DPRD §29: no live submission before the real schema is confirmed).

---

## 10. Cross-cutting behaviour

**Rate limiting.** `/traces` is limited per IP (default 10/min, 100/hour) with `X-RateLimit-*`
headers. Other reads are limited generously.

**Caching.** `GET`s that depend on chain data send `ETag` + `Cache-Control: private, max-age=60`.
`POST /traces` reuses cached upstream responses within `CHAIN_CACHE_TTL_S` (default 900) unless
`options.force_refresh` is set; the response's `data_provenance` becomes `cached` or `mixed`
accordingly, so a cached demo is never passed off as a fresh live pull.

**Idempotency.** `POST /traces` accepts an optional `Idempotency-Key` header; a repeat within
10 minutes returns the original trace rather than re-querying the chain — useful protection
against double-clicks on stage.

**Auth.** MVP: a single demo bearer token (`X-Api-Key` header) validated server-side, with the
demo user attached to every audit row. The dependency is written so swapping in SSO/RBAC at
Pilot phase touches one module.

**Versioning.** The path carries `/v1`. Additive changes only within v1; the report and
disclosure payloads carry their own `template_version` / `payload_schema_version` so they can
evolve independently when the real SAHYOG contract arrives (DPRD §47(26)).
