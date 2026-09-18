# VASPTrace — Project State

Last updated: 2026-09-18

Checkpoint: Phase 9 was committed before this pass. Current working state has Phase 10 backend
orchestration plus the frontend demo investigation dashboard implemented on top of that baseline.

## Completed

- Phases 1-8 were present at takeover: backend/frontend scaffolding, schema and label import,
  Ethereum/Tron/mock adapters, observation storage, graph traversal, VASP label matching and
  deterministic attribution scoring.
- Phase 9 is implemented in `backend/app/risk/`.
- Phase 10 backend orchestration API is implemented.
- The first usable frontend investigation dashboard is implemented.

## Phase 9 Summary

- Deterministic risk indicators now cover mixer interaction, bridge interaction,
  sanctioned/other risk-entity interaction, high fan-in, high fan-out, rapid movement and
  unusual uniform-splitting-style transfer patterns.
- Indicators are explainable and evidence-based: each carries a kind, severity, detection
  basis, neutral summary, evidence addresses, evidence transaction hashes and penalty.
- Risk labels use only existing matched graph-node fields. No VASP labels, risk labels or
  blockchain observations are fabricated.
- Attribution remains separate from risk detection. If an address is both a VASP and a risk
  entity, it can still be a VASP candidate while the risk flag remains available for review.
- Attribution scoring accepts optional risk indicators and applies capped path-scoped penalties
  without redesigning the Phase 8 scorer.

## Reconciled Phase 8 Mismatches

- Minimum primary attribution score is aligned to the architecture policy at `35`.
- Score bands are aligned to the shared policy: insufficient, low, moderate, strong,
  very_strong.
- Path/temporal-strength are documented as not yet separate scoring factors. Phase 9 adds
  rapid-movement as a risk indicator and applies risk penalties to candidate evidence paths.

## Phase 10 Backend Summary

- `POST /traces` runs a complete synchronous investigation pipeline.
- `GET /traces/{trace_id}` returns the stored in-process result for the current app process.
- Explicit `data_mode: "mock"` enables offline/demo tracing with existing MockAdapter data.
- Auto/live mode still requires provider keys and returns `PROVIDER_NOT_CONFIGURED` without
  falling back.
- Result payload includes graph evidence, VASP candidates, attribution scores, risk indicators,
  no-attribution reasons and provenance notes.

## Next Task

Next highest-value tasks are durable trace persistence, report/disclosure exports, and demo
deployment polish. ML remains Phase 14 and is not started.

## Known Gaps

- Trace result storage is in-process only; durable trace persistence is not wired yet.
- No report generation, SAHYOG draft, ML experiment or deployment polish yet.
- Live chain adapters are still unverified without provider keys.
- README status is stale and should be refreshed when the user asks for documentation polish.

## Frontend Demo Summary

- Dashboard can load deterministic demo wallets from the backend and submit mock traces.
- UI renders loading/error states, attribution/no-attribution states, score breakdown,
  risk indicators, provenance note, compact transaction graph and evidence table.
- No extra frontend dependencies were added.
