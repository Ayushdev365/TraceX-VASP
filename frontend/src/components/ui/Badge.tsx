import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export type BadgeTone = "neutral" | "accent" | "ok" | "warn" | "error" | "muted";

const TONES: Record<BadgeTone, string> = {
  neutral: "border-vt-border-strong bg-vt-surface-raised text-vt-text",
  accent: "border-vt-accent/40 bg-vt-accent/10 text-vt-accent",
  ok: "border-vt-ok/40 bg-vt-ok/10 text-vt-ok",
  warn: "border-vt-warn/40 bg-vt-warn/10 text-vt-warn",
  error: "border-vt-error/40 bg-vt-error/10 text-vt-error",
  muted: "border-vt-border bg-transparent text-vt-text-faint",
};

export function Badge({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: BadgeTone;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Dot({ tone = "neutral" }: { tone?: BadgeTone }) {
  const colour: Record<BadgeTone, string> = {
    neutral: "bg-vt-text-muted",
    accent: "bg-vt-accent",
    ok: "bg-vt-ok",
    warn: "bg-vt-warn",
    error: "bg-vt-error",
    muted: "bg-vt-text-faint",
  };
  return (
    <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", colour[tone])} />
  );
}
