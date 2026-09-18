/**
 * Shared constants.
 *
 * Disclaimer text is fetched from the backend's `/meta/config` at runtime so one policy
 * governs the UI, the JSON report, the PDF and the disclosure draft (DPRD §48 task 36).
 * The values here are fallbacks used only before that request resolves — they must stay
 * character-identical to `backend/app/config.py`.
 */

export const APP_NAME = "VASPTrace";
export const TEAM_NAME = "TraceX";
export const PROBLEM_STATEMENT_ID = "SIH26182";

export const FALLBACK_DISCLAIMERS = {
  leadNotProof: "This output is an investigative lead and not legal proof.",
  score: "Heuristic investigative score — not a calibrated probability.",
  risk:
    "Risk indicators are attention markers for investigator review. They are not evidence " +
    "of criminal activity, and detection is limited to known labelled addresses plus simple " +
    "heuristics.",
  mockSahyog: "DEMO / MOCK SAHYOG REQUEST — not transmitted to any portal or VASP.",
} as const;

export const HOP_DEPTH_FALLBACK = { default: 3, min: 1, max: 6 } as const;

/** Chains offered in the intake form. `supported` is confirmed against `/meta/chains`. */
export const CHAIN_OPTIONS = [
  { value: "ethereum", label: "Ethereum", nativeAsset: "ETH", mvp: true },
  { value: "tron", label: "Tron", nativeAsset: "TRX", mvp: true },
  { value: "bitcoin", label: "Bitcoin", nativeAsset: "BTC", mvp: false },
  { value: "bnb", label: "BNB Chain", nativeAsset: "BNB", mvp: false },
  { value: "solana", label: "Solana", nativeAsset: "SOL", mvp: false },
  { value: "polygon", label: "Polygon", nativeAsset: "POL", mvp: false },
] as const;

export type ChainValue = (typeof CHAIN_OPTIONS)[number]["value"];
