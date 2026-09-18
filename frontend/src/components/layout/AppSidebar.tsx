import Link from "next/link";

/**
 * Navigation shell. Items whose phase has not landed yet are rendered as disabled with the
 * phase noted, so the dashboard never offers a control that silently does nothing.
 */
const NAV = [
  { href: "/", label: "New trace", available: true },
  { href: "/cases", label: "Cases", available: false, note: "Phase 10" },
  { href: "/vasps", label: "VASP directory", available: false, note: "Phase 2" },
] as const;

export function AppSidebar() {
  return (
    <nav
      aria-label="Main"
      className="hidden w-56 shrink-0 border-r border-vt-border bg-vt-surface/50 px-3 py-5 md:block"
    >
      <ul className="space-y-1">
        {NAV.map((item) =>
          item.available ? (
            <li key={item.href}>
              <Link
                href={item.href}
                className="block rounded-lg px-3 py-2 text-sm font-medium text-vt-text hover:bg-vt-surface-raised"
              >
                {item.label}
              </Link>
            </li>
          ) : (
            <li key={item.href}>
              {/* Not a link and not a button: there is nothing to navigate to yet, so the
                  unavailability is conveyed in text rather than as a dead control. */}
              <span className="flex items-center justify-between rounded-lg px-3 py-2 text-sm text-vt-text-faint">
                <span>{item.label}</span>
                <span className="text-[10px] uppercase tracking-wide">
                  <span className="sr-only">Not available until </span>
                  {item.note}
                </span>
              </span>
            </li>
          ),
        )}
      </ul>
    </nav>
  );
}
