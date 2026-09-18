import Link from "next/link";

import { BackendStatus } from "@/components/layout/BackendStatus";
import { APP_NAME, PROBLEM_STATEMENT_ID, TEAM_NAME } from "@/lib/constants";

export function AppHeader() {
  return (
    <header className="flex items-center justify-between gap-4 border-b border-vt-border bg-vt-surface px-4 py-3 md:px-6">
      <div className="flex items-center gap-3">
        <Link href="/" className="flex items-center gap-3">
          <span
            aria-hidden
            className="grid size-9 place-items-center rounded-lg bg-vt-accent/15 text-sm font-bold text-vt-accent"
          >
            VT
          </span>
          <span>
            <span className="block text-base font-semibold leading-tight text-vt-text">
              {APP_NAME}
            </span>
            <span className="block text-xs leading-tight text-vt-text-faint">
              VASP Attribution Engine · Team {TEAM_NAME} · {PROBLEM_STATEMENT_ID}
            </span>
          </span>
        </Link>
      </div>
      <BackendStatus />
    </header>
  );
}
