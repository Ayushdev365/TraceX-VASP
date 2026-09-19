import Link from "next/link";
import { BackendStatus } from "@/components/layout/BackendStatus";

const NAV = [
  { href: "/", label: "New investigation", mark: "+", available: true },
  { href: "/cases", label: "Investigations / Cases", mark: "◈", available: false, note: "soon" },
  { href: "/vasps", label: "VASP directory", mark: "◎", available: false, note: "soon" },
  { href: "#", label: "Blockchain explorer", mark: "⌁", available: false, note: "soon" },
  { href: "#", label: "Evidence", mark: "▣", available: true },
  { href: "#", label: "Reports", mark: "≡", available: true },
  { href: "#", label: "Disclosure", mark: "◌", available: true },
] as const;

export function AppSidebar() {
  return <nav aria-label="Main" className="hidden w-60 shrink-0 border-r border-vt-border bg-vt-surface/35 px-3 py-5 md:flex md:flex-col"><div className="mb-5 px-3 text-[10px] font-semibold uppercase tracking-[0.22em] text-vt-text-faint">Investigation workspace</div><ul className="flex flex-col gap-1">{NAV.map((item) => item.available ? <li key={item.label}><Link href={item.href} className="group flex items-center gap-3 rounded-lg px-3 py-2.5 text-xs font-medium text-vt-text-muted transition-colors hover:bg-vt-surface-raised hover:text-vt-text"><span className="grid size-6 place-items-center rounded border border-vt-border text-vt-accent group-hover:border-vt-accent/50">{item.mark}</span>{item.label}</Link></li> : <li key={item.label}><span className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-xs text-vt-text-faint"><span className="grid size-6 place-items-center rounded border border-vt-border/60 text-vt-text-faint">{item.mark}</span><span className="flex-1">{item.label}</span><span className="text-[9px] uppercase">{item.note}</span></span></li>)}</ul><div className="mt-auto flex flex-col gap-3 border-t border-vt-border px-3 pt-5"><div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-vt-text-faint">System status</div><BackendStatus /><div className="mt-2 flex items-center gap-2 text-xs text-vt-text-faint"><span className="grid size-6 place-items-center rounded border border-vt-border">·</span> Settings</div></div></nav>;
}
