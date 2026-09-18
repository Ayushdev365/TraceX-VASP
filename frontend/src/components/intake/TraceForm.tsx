"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { api } from "@/lib/api-client";
import { CHAIN_OPTIONS, HOP_DEPTH_FALLBACK, type ChainValue } from "@/lib/constants";
import type { Chain, TraceResult } from "@/lib/types";

export function TraceForm({
  onResult,
  onError,
  loading,
  setLoading,
}: {
  onResult: (result: TraceResult) => void;
  onError: (message: string) => void;
  loading: boolean;
  setLoading: (value: boolean) => void;
}) {
  const [address, setAddress] = useState("");
  const [chain, setChain] = useState<ChainValue>("ethereum");
  const [hopDepth, setHopDepth] = useState<number>(HOP_DEPTH_FALLBACK.default);
  const [caseRef, setCaseRef] = useState("");
  const [demoSubjects, setDemoSubjects] = useState<Record<string, string>>({});

  useEffect(() => {
    api
      .demoSubjects()
      .then((payload) => setDemoSubjects(payload.subjects.ethereum ?? {}))
      .catch(() => setDemoSubjects({}));
  }, []);

  async function submit() {
    onError("");
    setLoading(true);
    try {
      const result = await api.createTrace({
        address,
        chain: chain as Chain,
        hop_depth: hopDepth,
        direction: "out",
        data_mode: "mock",
        case_ref: caseRef || null,
      });
      onResult(result);
    } catch (error) {
      onError(error instanceof Error ? error.message : "Trace failed.");
    } finally {
      setLoading(false);
    }
  }

  const canSubmit = address.trim().length > 0 && !loading;

  return (
    <Card>
      <CardHeader title="New trace" subtitle="Run an offline mock investigation." />
      <CardBody className="space-y-5">
        <div>
          <label htmlFor="wallet-address" className="mb-1.5 block text-sm font-medium">
            Wallet address
          </label>
          <input
            id="wallet-address"
            value={address}
            onChange={(event) => setAddress(event.target.value.trim())}
            spellCheck={false}
            autoComplete="off"
            placeholder="Paste address or load a demo wallet"
            className="vt-mono w-full rounded-lg border border-vt-border bg-vt-bg px-3 py-2.5 text-sm"
          />
          <div className="mt-2 flex flex-wrap gap-2">
            {Object.entries(demoSubjects).map(([name, value]) => (
              <Button
                key={name}
                type="button"
                variant="secondary"
                className="px-3 py-1.5 text-xs"
                onClick={() => setAddress(value)}
              >
                {name.replace("_", " ")}
              </Button>
            ))}
          </div>
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <label htmlFor="chain" className="mb-1.5 block text-sm font-medium">
              Blockchain
            </label>
            <select
              id="chain"
              value={chain}
              onChange={(event) => setChain(event.target.value as ChainValue)}
              className="w-full rounded-lg border border-vt-border bg-vt-bg px-3 py-2.5 text-sm"
            >
              {CHAIN_OPTIONS.map((option) => (
                <option key={option.value} value={option.value} disabled={!option.mvp}>
                  {option.label}
                  {option.mvp ? "" : " - roadmap"}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="case-ref" className="mb-1.5 block text-sm font-medium">
              Case reference
            </label>
            <input
              id="case-ref"
              value={caseRef}
              onChange={(event) => setCaseRef(event.target.value)}
              placeholder="Optional"
              className="vt-mono w-full rounded-lg border border-vt-border bg-vt-bg px-3 py-2.5 text-sm"
            />
          </div>
        </div>

        <div>
          <div className="mb-1.5 flex items-baseline justify-between">
            <label htmlFor="hop-depth" className="text-sm font-medium">
              Trace depth
            </label>
            <span className="vt-mono text-sm text-vt-accent">{hopDepth} hops</span>
          </div>
          <input
            id="hop-depth"
            type="range"
            min={HOP_DEPTH_FALLBACK.min}
            max={HOP_DEPTH_FALLBACK.max}
            value={hopDepth}
            onChange={(event) => setHopDepth(Number(event.target.value))}
            className="w-full accent-vt-accent"
          />
        </div>

        <div className="flex items-center justify-between gap-4 border-t border-vt-border pt-4">
          <p className="text-xs text-vt-text-faint">Mock mode is explicit and labelled.</p>
          <Button type="button" disabled={!canSubmit} onClick={submit}>
            {loading ? "Tracing..." : "Analyze wallet"}
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}
