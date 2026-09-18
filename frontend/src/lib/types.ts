/**
 * API types, mirroring `docs/API_CONTRACT.md`.
 *
 * Hand-written in Phase 1 for the meta endpoints only. From Phase 10 these are generated
 * from the backend's OpenAPI schema so the two sides cannot drift.
 *
 * Monetary amounts are always `string` — never `number`. An 18-decimal token amount does
 * not survive a JavaScript float, and no arithmetic on amounts happens in the browser.
 */

export type Chain = "ethereum" | "tron" | "bitcoin" | "bnb" | "solana" | "polygon";
export type ChainStatus = "supported" | "degraded" | "roadmap";
export type DataProvenance = "live_api" | "cached" | "mock_demo" | "mixed";
export type NodeRole = "subject" | "intermediate" | "vasp" | "risk_entity" | "contract";
export type ScoreBand = "insufficient" | "low" | "moderate" | "strong" | "very_strong";
export type Severity = "info" | "low" | "medium" | "high";
export type DependencyStatus = "ok" | "not_configured" | "degraded" | "unavailable";
export type Direction = "in" | "out";
export type TraceDataMode = "auto" | "mock";

export interface ApiError {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
    request_id: string | null;
  };
}

export interface DependencyHealth {
  name: string;
  status: DependencyStatus;
  detail: string | null;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  engine_version: string;
  app_env: string;
  time: string;
  dependencies: DependencyHealth[];
}

export interface PublicConfig {
  engine_version: string;
  app_env: string;
  hop_depth: { default: number; min: number; max: number };
  attribution: {
    min_attribution_score: number;
    score_type: "heuristic_investigative_score";
    calibrated: false;
    bands: { min_score: number; band: ScoreBand }[];
  };
  labels: { stale_label_days: number };
  disclaimers: {
    lead_not_proof: string;
    score: string;
    risk: string;
    mock_sahyog: string;
  };
}

export interface TraceRequest {
  address: string;
  chain: Chain;
  hop_depth: number;
  direction: Direction;
  data_mode: TraceDataMode;
  case_ref?: string | null;
}

export interface TraceNodeResult {
  address: string;
  role: NodeRole;
  hop_distance: number;
  expanded: boolean;
  not_expanded_reason: string | null;
  matched_vasp_name: string | null;
  matched_vasp_slug: string | null;
  matched_risk_entity_kind: string | null;
}

export interface TraceEdgeResult {
  from_address: string;
  to_address: string;
  tx_hash: string;
  chain: Chain;
  direction: Direction;
  asset_symbol: string;
  amount: string;
  block_timestamp: string;
  hop_index: number;
}

export interface ScoreBreakdown {
  base_score: number;
  hop_penalty: number;
  tx_count_factor: number;
  volume_factor: number;
  final_score: number;
  score_band: ScoreBand;
  why_summary: string;
  contributions: Record<string, number>;
  risk_penalties: { kind: string; penalty: number }[];
  penalty_total: number;
}

export interface ScoredCandidate {
  vasp_name: string;
  vasp_slug: string;
  rank: number;
  is_primary: boolean;
  score: number;
  score_band: ScoreBand;
  min_hop_distance: number;
  matched_addresses: string[];
  interaction_tx_count: number;
  interaction_value_usd: number | null;
  score_breakdown: ScoreBreakdown;
  evidence_paths: string[][];
}

export interface RiskIndicator {
  kind: string;
  severity: Severity;
  detection_basis: string;
  summary: string;
  evidence_addresses: string[];
  evidence_tx_hashes: string[];
  penalty: number;
  details: Record<string, string | number>;
}

export interface VaspCandidate {
  address: string;
  vasp_name: string;
  vasp_slug: string;
  hop_distance: number;
  path: string[];
}

export interface TraceResult {
  trace_id: string;
  status: string;
  queried_address: string;
  canonical_address: string;
  chain: Chain;
  hop_depth: number;
  direction: Direction;
  data_provenance: DataProvenance;
  data_mode: TraceDataMode;
  case_ref: string | null;
  truncated: boolean;
  truncation_reason: string | null;
  nodes_expanded: number;
  api_calls_made: number;
  tx_analyzed_count: number;
  duration_ms: number | null;
  discovered_addresses: string[];
  nodes: TraceNodeResult[];
  edges: TraceEdgeResult[];
  paths: Record<string, string[]>;
  vasp_candidates: VaspCandidate[];
  attributions: ScoredCandidate[];
  primary_attribution: ScoredCandidate | null;
  no_attribution_reason: string | null;
  risk_indicators: RiskIndicator[];
  evidence_summary: string;
  provenance_note: string;
  score_type: "heuristic_investigative_score";
  calibrated: false;
}

export interface DemoSubjectsResponse {
  subjects: Partial<Record<Chain, Record<string, string>>>;
}

export interface TraceReport {
  report_ref: string;
  trace_id: string;
  format: "json";
  content_sha256: string;
  payload: Record<string, unknown>;
}

export interface DisclosureDraft {
  disclosure_ref: string;
  trace_id: string;
  mode: "mock_demo";
  payload_schema_version: string;
  banner: string;
  payload: Record<string, unknown>;
}
