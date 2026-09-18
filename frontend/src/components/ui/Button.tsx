import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-vt-accent-strong text-vt-bg hover:bg-vt-accent disabled:bg-vt-border-strong disabled:text-vt-text-faint",
  secondary:
    "border border-vt-border-strong bg-vt-surface-raised text-vt-text hover:border-vt-accent/60 disabled:text-vt-text-faint",
  ghost: "text-vt-text-muted hover:text-vt-text disabled:text-vt-text-faint",
};

export function Button({
  children,
  variant = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  variant?: Variant;
}) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors disabled:cursor-not-allowed",
        VARIANTS[variant],
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
