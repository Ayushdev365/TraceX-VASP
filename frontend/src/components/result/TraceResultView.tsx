"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { api } from "@/lib/api-client";
import { cn } from "@/lib/cn";
import type { TraceResult } from "@/lib/types";

const bandTone = {
  insufficient: "muted",
  low: "neutral",
  moderate: "accent",
  strong: "ok",
  very_strong: "ok",
} as const;

const roleColor = {
  subject: "bg-vt-subject",
  intermediate: "bg-vt-intermediate",
  vasp: "bg-vt-vasp",
  risk_entity: "bg-vt-risk-entity",
  contract: "bg-vt-text-faint",
} as const;

export function TraceResultView({ result }: { result: TraceResult }) {
  const primary = result.primary_attribution;
  const [actionMessage, setActionMessage] = useState("");
  async function exportReport() {
    const report = await api.getReport(result.trace_id);
    setActionMessage(`JSON report ${report.report_ref} ready, sha256 ${report.content_sha256.slice(0, 12)}...`);
  }
  async function draftDisclosure() {
    await api.reviewTrace(result.trace_id);
    const disclosure = await api.createDisclosure(result.trace_id);
    setActionMessage(`${disclosure.disclosure_ref}: ${disclosure.banner}`);
  }
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title="Investigation result"
          action={
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="secondary" className="px-3 py-1.5 text-xs" onClick={exportReport}>
                JSON report
              </Button>
              <Button type="button" variant="secondary" className="px-3 py-1.5 text-xs" onClick={draftDisclosure}>
                Mock disclosure
              </Button>
              <Badge tone={result.data_provenance === "mock_demo" ? "warn" : "ok"}>{result.data_provenance}</Badge>
            </div>
          }
        />
        <CardBody className="grid gap-4 md:grid-cols-4">
          <Metric label="Trace ID" value={result.trace_id.slice(0, 8)} mono />
          <Metric label="Addresses" value={String(result.discovered_addresses.length)} />
          <Metric label="Transactions" value={String(result.edges.length)} />
          <Metric label="Risk indicators" value={String(result.risk_indicators.length)} />
          <div className="md:col-span-4 text-sm text-vt-text-muted">{result.evidence_summary}</div>
          <div className="md:col-span-4 text-xs text-vt-warn">{result.provenance_note}</div>
          {actionMessage ? <div className="md:col-span-4 text-xs text-vt-accent">{actionMessage}</div> : null}
        </CardBody>
      </Card>

      {primary ? <AttributionCard candidate={primary} /> : <NoAttribution reason={result.no_attribution_reason} />}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(22rem,0.8fr)]">
        <TraceGraph result={result} />
        <RiskPanel result={result} />
      </div>

      <EvidenceTable result={result} />
    </div>
  );
}

function Metric({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div className="text-xs text-vt-text-faint">{label}</div>
      <div className={cn("mt-1 text-sm font-semibold", mono && "vt-mono")}>{value}</div>
    </div>
  );
}

function AttributionCard({ candidate }: { candidate: TraceResult["primary_attribution"] & {} }) {
  const contributionEntries = Object.entries(candidate.score_breakdown.contributions);
  return (
    <Card>
      <CardHeader
        title="Primary VASP attribution"
        action={<Badge tone={bandTone[candidate.score_band]}>{candidate.score_band}</Badge>}
      />
      <CardBody className="grid gap-5 lg:grid-cols-[10rem_minmax(0,1fr)]">
        <div className="grid size-32 place-items-center rounded-full border-8 border-vt-accent/30 bg-vt-surface-raised">
          <span className="text-3xl font-bold">{candidate.score}</span>
        </div>
        <div className="space-y-3">
          <h3 className="text-xl font-semibold">{candidate.vasp_name}</h3>
          <p className="text-sm text-vt-text-muted">{candidate.score_breakdown.why_summary}</p>
          <div className="grid gap-2 sm:grid-cols-3">
            {contributionEntries.map(([name, value]) => (
              <Metric key={name} label={name.replace("_", " ")} value={value.toFixed(1)} />
            ))}
          </div>
        </div>
      </CardBody>
    </Card>
  );
}

function NoAttribution({ reason }: { reason: string | null }) {
  return (
    <Card>
      <CardHeader title="No reliable VASP attribution found" />
      <CardBody className="text-sm text-vt-text-muted">
        The trace completed without a primary attribution. Reason:{" "}
        <span className="vt-mono text-vt-text">{reason ?? "inconclusive"}</span>
      </CardBody>
    </Card>
  );
}

function TraceGraph({ result }: { result: TraceResult }) {
  const nodes = result.nodes.slice(0, 24);
  const width = 720;
  const height = 360;
  const positions = new Map(
    nodes.map((node, index) => {
      const sameHop = nodes.filter((item) => item.hop_distance === node.hop_distance);
      const row = sameHop.findIndex((item) => item.address === node.address);
      return [
        node.address,
        {
          x: 80 + node.hop_distance * 150,
          y: 60 + row * 70 + (index % 2) * 8,
        },
      ];
    }),
  );
  return (
    <Card>
      <CardHeader title="Transaction graph" />
      <CardBody>
        <svg viewBox={`0 0 ${width} ${height}`} className="h-80 w-full rounded bg-vt-bg">
          {result.edges.map((edge) => {
            const a = positions.get(edge.from_address);
            const b = positions.get(edge.to_address);
            if (!a || !b) return null;
            return <line key={edge.tx_hash} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#33415c" strokeWidth="2" />;
          })}
          {nodes.map((node) => {
            const p = positions.get(node.address);
            if (!p) return null;
            return (
              <g key={node.address}>
                <circle cx={p.x} cy={p.y} r="13" className={roleColor[node.role]} />
                <text x={p.x + 18} y={p.y + 4} fill="#e8edf7" fontSize="11">
                  {node.role === "vasp" ? node.matched_vasp_name : `${node.address.slice(0, 8)}...`}
                </text>
              </g>
            );
          })}
        </svg>
      </CardBody>
    </Card>
  );
}

function RiskPanel({ result }: { result: TraceResult }) {
  return (
    <Card>
      <CardHeader title="Risk indicators" />
      <CardBody className="space-y-3">
        {result.risk_indicators.length === 0 ? (
          <p className="text-sm text-vt-text-muted">No risk indicators fired on this trace.</p>
        ) : (
          result.risk_indicators.map((item) => (
            <div key={`${item.kind}-${item.evidence_addresses.join("-")}`} className="rounded border border-vt-border bg-vt-bg p-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-semibold">{item.kind.replaceAll("_", " ")}</span>
                <Badge tone={item.severity === "high" ? "error" : item.severity === "medium" ? "warn" : "neutral"}>{item.severity}</Badge>
              </div>
              <p className="mt-2 text-xs text-vt-text-muted">{item.summary}</p>
            </div>
          ))
        )}
      </CardBody>
    </Card>
  );
}

function EvidenceTable({ result }: { result: TraceResult }) {
  return (
    <Card>
      <CardHeader title="Evidence" subtitle="Observed transaction edges returned by the trace." />
      <CardBody className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-xs">
          <thead className="text-vt-text-faint">
            <tr><th className="py-2">Hop</th><th>From</th><th>To</th><th>Asset</th><th>Amount</th><th>Tx</th></tr>
          </thead>
          <tbody>
            {result.edges.slice(0, 30).map((edge) => (
              <tr key={edge.tx_hash} className="border-t border-vt-border">
                <td className="py-2">{edge.hop_index}</td>
                <td className="vt-mono">{edge.from_address.slice(0, 12)}...</td>
                <td className="vt-mono">{edge.to_address.slice(0, 12)}...</td>
                <td>{edge.asset_symbol}</td>
                <td className="vt-mono">{edge.amount}</td>
                <td className="vt-mono">{edge.tx_hash.slice(0, 14)}...</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardBody>
    </Card>
  );
}
