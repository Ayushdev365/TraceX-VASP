"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { CHAIN_OPTIONS, HOP_DEPTH_FALLBACK, type ChainValue } from "@/lib/constants";

/**
 * Case intake — wallet address, chain, trace depth (DPRD §22).
 *
 * Phase 1 is the shell: the fields, the constraints and the copy are real, but submission is
 * disabled because `POST /traces` does not exist until Phase 6. It is disabled with a stated
 * reason rather than wired to a placeholder, so nothing here can be mistaken for a working
 * trace.
 */
export function TraceForm() {
  const [address, setAddress] = useState("");
  const [chain, setChain] = useState<ChainValue>("ethereum");
  const [hopDepth, setHopDepth] = useState<number>(HOP_DEPTH_FALLBACK.default);
  const [caseRef, setCaseRef] = useState("");

  const chainOption = CHAIN_OPTIONS.find((option) => option.value === chain);
  const chainAvailable = chainOption?.mvp ?? false;

  return (
    <Card>
      <CardHeader
        title="New trace"
        subtitle="Enter a suspect wallet address and select its blockchain."
      />
      <CardBody className="space-y-5">
        <div>
          <label
            htmlFor="wallet-address"
            className="mb-1.5 block text-sm font-medium text-vt-text"
          >
            Wallet address
          </label>
          <input
            id="wallet-address"
            value={address}
            onChange={(event) => setAddress(event.target.value.trim())}
            spellCheck={false}
            autoComplete="off"
            placeholder="0x… (Ethereum) or T… (Tron)"
            className="vt-mono w-full rounded-lg border border-vt-border bg-vt-bg px-3 py-2.5 text-sm text-vt-text placeholder:text-vt-text-faint focus:border-vt-accent focus:outline-none"
          />
          <p className="mt-1.5 text-xs text-vt-text-faint">
            Validated against the selected chain&rsquo;s format and checksum before any data
            request is made.
          </p>
        </div>

        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <label htmlFor="chain" className="mb-1.5 block text-sm font-medium text-vt-text">
              Blockchain
            </label>
            <select
              id="chain"
              value={chain}
              onChange={(event) => setChain(event.target.value as ChainValue)}
              className="w-full rounded-lg border border-vt-border bg-vt-bg px-3 py-2.5 text-sm text-vt-text focus:border-vt-accent focus:outline-none"
            >
              {CHAIN_OPTIONS.map((option) => (
                <option key={option.value} value={option.value} disabled={!option.mvp}>
                  {option.label}
                  {option.mvp ? "" : " — not supported yet"}
                </option>
              ))}
            </select>
            {!chainAvailable ? (
              <p className="mt-1.5 text-xs text-vt-warn">
                This chain is on the roadmap. Ethereum and Tron are supported.
              </p>
            ) : null}
          </div>

          <div>
            <label
              htmlFor="case-ref"
              className="mb-1.5 block text-sm font-medium text-vt-text"
            >
              Case reference <span className="text-vt-text-faint">(optional)</span>
            </label>
            <input
              id="case-ref"
              value={caseRef}
              onChange={(event) => setCaseRef(event.target.value)}
              autoComplete="off"
              placeholder="VT-2026-000123"
              className="vt-mono w-full rounded-lg border border-vt-border bg-vt-bg px-3 py-2.5 text-sm text-vt-text placeholder:text-vt-text-faint focus:border-vt-accent focus:outline-none"
            />
          </div>
        </div>

        <div>
          <div className="mb-1.5 flex items-baseline justify-between">
            <label htmlFor="hop-depth" className="text-sm font-medium text-vt-text">
              Trace depth
            </label>
            <span className="vt-mono text-sm text-vt-accent">
              {hopDepth} {hopDepth === 1 ? "hop" : "hops"}
            </span>
          </div>
          <input
            id="hop-depth"
            type="range"
            min={HOP_DEPTH_FALLBACK.min}
            max={HOP_DEPTH_FALLBACK.max}
            step={1}
            value={hopDepth}
            onChange={(event) => setHopDepth(Number(event.target.value))}
            className="w-full accent-vt-accent"
          />
          <p className="mt-1.5 text-xs text-vt-text-faint">
            Deeper traces cover longer laundering chains but cost more time and API calls. A
            trace that reaches the depth limit without finding a VASP reports that outcome
            rather than guessing.
          </p>
        </div>

        <div className="flex items-center justify-between gap-4 border-t border-vt-border pt-4">
          <p className="text-xs text-vt-text-faint">
            Tracing is not available yet — the traversal engine lands in Phase 6.
          </p>
          <Button type="button" disabled title="Available from Phase 6">
            Analyze wallet
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}
