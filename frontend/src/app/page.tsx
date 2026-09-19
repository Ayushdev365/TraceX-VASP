"use client";

import { useState } from "react";
import { TraceForm } from "@/components/intake/TraceForm";
import { TraceResultView } from "@/components/result/TraceResultView";
import { Card, CardBody } from "@/components/ui/Card";
import type { TraceResult } from "@/lib/types";

const OPERATIONS = ["Validating wallet", "Fetching blockchain data", "Building transaction graph", "Matching VASP entities", "Calculating attribution", "Generating evidence"];

export default function InvestigationDashboard() {
  const [result, setResult] = useState<TraceResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  return (
    <div className="mx-auto max-w-[1600px]"><div className="mb-8 flex items-end justify-between gap-5"><div><div className="text-xs font-semibold uppercase tracking-[.24em] text-vt-accent">Blockchain intelligence</div><h1 className="mt-3 text-4xl font-semibold tracking-[-.04em] md:text-6xl">Investigate. <span className="bg-gradient-to-r from-blue-600 via-indigo-500 to-pink-500 bg-clip-text text-transparent">Trace. Attribute.</span></h1><p className="mt-4 max-w-2xl text-base text-vt-text-muted">Turn blockchain data into actionable intelligence. Identify VASP connections, analyze risk, and generate explainable evidence trails.</p></div></div>
      <div className="mb-6 flex justify-end"><div className="flex items-center gap-2 rounded-full border border-vt-border bg-vt-surface px-3 py-2 text-xs text-vt-text-muted"><span className="size-2 rounded-full bg-vt-ok" /> Workspace ready <span className="text-vt-text-faint">/</span> analyst mode</div></div>
      <div className="grid gap-6 xl:grid-cols-[minmax(20rem,25rem)_minmax(0,1fr)]">
        <aside className="flex flex-col gap-4">
          <TraceForm onResult={setResult} onError={setError} loading={loading} setLoading={setLoading} />
          {loading ? <Card className="overflow-hidden"><CardBody className="p-0"><div className="h-1 animate-pulse bg-vt-accent" /><div className="flex flex-col gap-3 p-5"><div className="text-xs font-semibold uppercase tracking-[0.18em] text-vt-accent">Investigation in progress</div>{OPERATIONS.map((operation, index) => <div key={operation} className="flex items-center gap-3 text-xs text-vt-text-muted"><span className={`grid size-5 place-items-center rounded-full border text-[10px] ${index === 0 ? "border-vt-accent bg-vt-accent/10 text-vt-accent" : "border-vt-border text-vt-text-faint"}`}>{index + 1}</span>{operation}</div>)}</div></CardBody></Card> : null}
          {error ? <Card className="border-vt-error/40"><CardBody><div className="text-xs font-semibold uppercase tracking-wider text-vt-error">Trace request failed</div><p className="mt-2 text-sm text-vt-text-muted">{error}</p><p className="mt-3 text-[11px] text-vt-text-faint">Check the address and backend connection, then retry.</p></CardBody></Card> : null}
          <Card><CardBody className="grid grid-cols-3 gap-2 p-4 text-center"><div><div className="text-lg font-semibold text-vt-accent">01</div><div className="text-[10px] uppercase tracking-wider text-vt-text-faint">Intake</div></div><div className="border-x border-vt-border"><div className="text-lg font-semibold">02</div><div className="text-[10px] uppercase tracking-wider text-vt-text-faint">Analyze</div></div><div><div className="text-lg font-semibold">03</div><div className="text-[10px] uppercase tracking-wider text-vt-text-faint">Review</div></div></CardBody></Card>
        </aside>
        <main className="min-w-0">
          {result ? <TraceResultView result={result} /> : <EmptyWorkspace />}
        </main>
      </div>
    </div>
  );
}

function EmptyWorkspace() {
  return <Card className="relative min-h-[620px] overflow-hidden"><div className="absolute inset-0 bg-[radial-gradient(circle_at_70%_35%,rgba(14,165,233,0.12),transparent_34%),linear-gradient(135deg,transparent_60%,rgba(56,189,248,0.04))]" /><CardBody className="relative flex min-h-[620px] flex-col items-center justify-center text-center"><div className="mb-6 grid size-20 place-items-center rounded-2xl border border-vt-accent/30 bg-vt-accent/10 shadow-[0_0_50px_rgba(56,189,248,0.12)]"><div className="size-8 rounded-full border-2 border-vt-accent border-t-transparent" /></div><div className="text-xs font-semibold uppercase tracking-[0.3em] text-vt-accent">Awaiting subject</div><h2 className="mt-3 text-2xl font-semibold">Start an investigation</h2><p className="mt-3 max-w-md text-sm leading-6 text-vt-text-muted">Enter a wallet address to populate the transaction graph, attribution signals, risk indicators and evidence workspace.</p><div className="mt-8 grid max-w-lg grid-cols-3 gap-3 text-left"><Hint number="01" title="Trace" text="Follow connected activity" /><Hint number="02" title="Attribute" text="Compare labelled entities" /><Hint number="03" title="Preserve" text="Review sourced evidence" /></div></CardBody></Card>;
}
function Hint({ number, title, text }: { number: string; title: string; text: string }) { return <div className="rounded-lg border border-vt-border bg-vt-bg/60 p-3"><div className="text-[10px] text-vt-accent">{number}</div><div className="mt-2 text-xs font-semibold">{title}</div><div className="mt-1 text-[10px] leading-4 text-vt-text-faint">{text}</div></div>; }

// Keep this module's strings deterministic; backend output remains the source of truth for all result data.
export const dynamic = "force-dynamic";


