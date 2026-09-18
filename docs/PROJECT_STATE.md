# VASPTrace — Project State

Last updated: 2026-09-18

Checkpoint: `8905ded` was the takeover baseline. Current working state has Phase 9 implemented
on top of that baseline.

## Completed

- Phases 1-8 were present at takeover: backend/frontend scaffolding, schema and label import,
  Ethereum/Tron/mock adapters, observation storage, graph traversal, VASP label matching and
  deterministic attribution scoring.
- Phase 9 is now implemented in `backend/app/risk/`.

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

## Next Task

Phase 10: frontend investigation workflow, including intake submission, loading states,
result rendering, attribution cards, score breakdowns, risk chips, provenance banners and
review gate. Do not start until instructed.

## Known Gaps

- No frontend trace workflow yet.
- No report generation, SAHYOG draft, ML experiment or deployment polish yet.
- Live chain adapters are still unverified without provider keys.
- README status is stale and should be refreshed when the user asks for documentation polish.
