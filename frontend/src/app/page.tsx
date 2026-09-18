"use client";

import { useState } from "react";

import { TraceForm } from "@/components/intake/TraceForm";
import { TraceResultView } from "@/components/result/TraceResultView";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import type { TraceResult } from "@/lib/types";

export default function InvestigationDashboard() {
  const [result, setResult] = useState<TraceResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  return (
    <div className="mx-auto grid max-w-7xl gap-6 xl:grid-cols-[24rem_minmax(0,1fr)]">
      <aside className="space-y-6">
        <TraceForm
          onResult={setResult}
          onError={setError}
          loading={loading}
          setLoading={setLoading}
        />
        {error ? (
          <Card>
            <CardHeader title="Trace error" />
            <CardBody className="text-sm text-vt-error">{error}</CardBody>
          </Card>
        ) : null}
        <Card>
          <CardHeader title="Workflow" />
          <CardBody className="space-y-2 text-xs text-vt-text-muted">
            <p>1. Load a demo wallet or paste an address.</p>
            <p>2. Run the trace in explicit mock mode.</p>
            <p>3. Review attribution, risk indicators and evidence before relying on it.</p>
          </CardBody>
        </Card>
      </aside>
      <main>
        {loading ? (
          <Card>
            <CardHeader title="Tracing wallet" />
            <CardBody className="space-y-3 text-sm text-vt-text-muted">
              <p>Fetching transactions, matching labels, scoring candidates and checking risk.</p>
              <div className="h-2 overflow-hidden rounded bg-vt-bg">
                <div className="h-full w-2/3 animate-pulse rounded bg-vt-accent" />
              </div>
            </CardBody>
          </Card>
        ) : result ? (
          <TraceResultView result={result} />
        ) : (
          <Card>
            <CardHeader title="Ready" />
            <CardBody className="text-sm text-vt-text-muted">
              Start with the clean, mixer or dead-end demo wallet. Results stay labelled as
              mock data and are not legal proof.
            </CardBody>
          </Card>
        )}
      </main>
    </div>
  );
}
