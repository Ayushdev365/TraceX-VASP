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
