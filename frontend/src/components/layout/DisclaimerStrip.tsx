import { FALLBACK_DISCLAIMERS } from "@/lib/constants";

/**
 * The "investigative lead, not proof" framing, shown in the UI itself rather than buried in
 * documentation (DPRD §14, §24). It is a fixed part of the layout: there is no prop to hide
 * it and no dismiss control.
 */
export function DisclaimerStrip() {
  return (
    <div className="border-b border-vt-warn/25 bg-vt-warn/10 px-4 py-2 md:px-6">
      <p className="text-center text-xs font-medium text-vt-warn">
        <span className="font-semibold uppercase tracking-wide">Investigative lead</span>
        <span aria-hidden className="mx-2 text-vt-warn/50">
          |
        </span>
        {FALLBACK_DISCLAIMERS.leadNotProof} Attribution scores are heuristic and are not
        calibrated probabilities. Independent investigator verification is required before any
        action.
      </p>
    </div>
  );
}
