"use client";

import { useEffect, useState } from "react";

import { Badge, Dot } from "@/components/ui/Badge";
import { api, ApiRequestError } from "@/lib/api-client";
import type { HealthResponse } from "@/lib/types";

type State =
  | { kind: "loading" }
  | { kind: "ok"; health: HealthResponse }
  | { kind: "error"; message: string };

/**
 * Live backend health indicator in the header.
 *
 * Shows *which* dependency is missing rather than a single green/red light — during a demo
 * "engine up, Ethereum key absent" is a completely different situation from "engine down",
 * and the operator needs to tell them apart at a glance.
 */
export function BackendStatus() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();

    const poll = async () => {
      try {
        const health = await api.health(controller.signal);
        setState({ kind: "ok", health });
      } catch (error) {
        if (controller.signal.aborted) return;
        setState({
          kind: "error",
          message:
            error instanceof ApiRequestError
              ? error.message
              : "The attribution engine is not reachable.",
        });
      }
    };

    void poll();
    const timer = setInterval(() => void poll(), 30_000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, []);

  if (state.kind === "loading") {
    return (
      <Badge tone="muted">
        <Dot tone="muted" />
        Checking engine…
      </Badge>
    );
  }

  if (state.kind === "error") {
    return (
      <Badge tone="error" className="max-w-xs">
        <Dot tone="error" />
        Engine offline
      </Badge>
    );
  }

  const unconfigured = state.health.dependencies.filter((d) => d.status !== "ok");

  return (
    <div className="flex items-center gap-2">
      <Badge tone="ok">
        <Dot tone="ok" />
        Engine v{state.health.engine_version}
      </Badge>
      {unconfigured.length > 0 ? (
        <Badge
          tone="warn"
          className="cursor-help"
          // Names only — the detail strings never contain key values.
        >
          <span title={unconfigured.map((d) => `${d.name}: ${d.status}`).join("\n")}>
            {unconfigured.length} not configured
          </span>
        </Badge>
      ) : null}
    </div>
  );
}
