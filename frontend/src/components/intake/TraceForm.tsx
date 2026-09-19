"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { api } from "@/lib/api-client";
import { CHAIN_OPTIONS, HOP_DEPTH_FALLBACK, type ChainValue } from "@/lib/constants";
import type { Chain, TraceResult } from "@/lib/types";

export function TraceForm({ onResult, onError, loading, setLoading }: { onResult: (result: TraceResult) => void; onError: (message: string) => void; loading: boolean; setLoading: (value: boolean) => void }) {
  const [address, setAddress] = useState("");
  const [chain, setChain] = useState<ChainValue>("ethereum");
  const [hopDepth, setHopDepth] = useState<number>(HOP_DEPTH_FALLBACK.default);
  const [caseRef, setCaseRef] = useState("");
  const [demoSubjects, setDemoSubjects] = useState<Record<string, string>>({});
  const [touched, setTouched] = useState(false);
  useEffect(() => { api.demoSubjects().then((payload) => setDemoSubjects(payload.subjects[chain] ?? {})).catch(() => setDemoSubjects({})); }, [chain]);
  const isValid = address.trim().length > 0;
  async function submit() { setTouched(true); if (!isValid) return; onError(""); setLoading(true); try { onResult(await api.createTrace({ address: address.trim(), chain: chain as Chain, hop_depth: hopDepth, direction: "out", data_mode: "mock", case_ref: caseRef.trim() || null })); } catch (error) { onError(error instanceof Error ? error.message : "Trace failed."); } finally { setLoading(false); } }
  return <Card className="overflow-hidden"><div className="h-1 bg-gradient-to-r from-vt-accent-strong via-vt-accent to-transparent" /><CardHeader title="Start investigation" subtitle="Define a subject and trace parameters." /><CardBody className="flex flex-col gap-5">
    <div><div className="mb-2 flex items-center justify-between"><label htmlFor="wallet-address" className="text-xs font-semibold uppercase tracking-wider text-vt-text-muted">Wallet address</label><span className="text-[10px] text-vt-text-faint">Required</span></div><div className="relative"><input id="wallet-address" value={address} onChange={(event) => setAddress(event.target.value)} onBlur={() => setTouched(true)} spellCheck={false} autoComplete="off" placeholder="0x... or TR..." aria-invalid={touched && !isValid} className="vt-mono w-full rounded-lg border border-vt-border bg-vt-bg px-3 py-3 pr-16 text-xs text-vt-text placeholder:text-vt-text-faint focus:border-vt-accent focus:outline-none" />{address ? <button type="button" onClick={() => setAddress("")} className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] uppercase tracking-wider text-vt-text-faint hover:text-vt-text">Clear</button> : null}</div>{touched && !isValid ? <p className="mt-2 text-xs text-vt-error">Enter a wallet address to continue.</p> : null}<div className="mt-3 flex flex-wrap gap-2">{Object.entries(demoSubjects).map(([name, value]) => <Button key={name} type="button" variant="secondary" className="px-2.5 py-1.5 text-[11px]" onClick={() => setAddress(value)}>Load {name.replaceAll("_", " ")}</Button>)}</div></div>
    <div className="grid gap-4 sm:grid-cols-2"><div><label htmlFor="chain" className="mb-2 block text-xs font-semibold uppercase tracking-wider text-vt-text-muted">Network</label><select id="chain" value={chain} onChange={(event) => setChain(event.target.value as ChainValue)} className="w-full rounded-lg border border-vt-border bg-vt-bg px-3 py-3 text-sm text-vt-text focus:border-vt-accent focus:outline-none">{CHAIN_OPTIONS.map((option) => <option key={option.value} value={option.value} disabled={!option.mvp}>{option.label}{option.mvp ? "" : " · roadmap"}</option>)}</select></div><div><label htmlFor="case-ref" className="mb-2 block text-xs font-semibold uppercase tracking-wider text-vt-text-muted">Case reference</label><input id="case-ref" value={caseRef} onChange={(event) => setCaseRef(event.target.value)} placeholder="Optional" className="vt-mono w-full rounded-lg border border-vt-border bg-vt-bg px-3 py-3 text-xs focus:border-vt-accent focus:outline-none" /></div></div>
    <div><div className="mb-2 flex items-center justify-between"><label htmlFor="hop-depth" className="text-xs font-semibold uppercase tracking-wider text-vt-text-muted">Trace depth</label><span className="vt-mono rounded bg-vt-accent/10 px-2 py-1 text-xs text-vt-accent">{hopDepth} hops</span></div><input id="hop-depth" type="range" min={HOP_DEPTH_FALLBACK.min} max={HOP_DEPTH_FALLBACK.max} value={hopDepth} onChange={(event) => setHopDepth(Number(event.target.value))} className="w-full accent-vt-accent" /><div className="mt-1 flex justify-between text-[10px] text-vt-text-faint"><span>Focused</span><span>Extended network</span></div></div>
    <div className="flex items-center justify-between gap-3 border-t border-vt-border pt-4"><div><div className="text-xs font-medium text-vt-text">Explicit demo mode</div><div className="mt-1 text-[10px] text-vt-text-faint">Results are labelled as mock data.</div></div><Button type="button" disabled={!isValid || loading} onClick={submit}>{loading ? "Analyzing..." : "Analyze wallet"}<span aria-hidden>→</span></Button></div>
  </CardBody></Card>;
}
