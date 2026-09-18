import type { Metadata } from "next";
import { JetBrains_Mono } from "next/font/google";
import type { ReactNode } from "react";

import { AppHeader } from "@/components/layout/AppHeader";
import { AppSidebar } from "@/components/layout/AppSidebar";
import { DisclaimerStrip } from "@/components/layout/DisclaimerStrip";
import { APP_NAME, PROBLEM_STATEMENT_ID, TEAM_NAME } from "@/lib/constants";

import "./globals.css";

// Addresses and transaction hashes are read character by character; a monospace face with
// disambiguated 0/O and 1/l is a correctness feature, not a style choice.
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: `${APP_NAME} — VASP Attribution Engine`,
  description:
    "Traces unknown cryptocurrency wallets to the nearest labelled Virtual Asset Service " +
    "Provider with an explainable heuristic score and a full evidence trail. " +
    `Team ${TEAM_NAME}, ${PROBLEM_STATEMENT_ID}.`,
  robots: { index: false, follow: false },
};

// Typed explicitly rather than via Next's generated `LayoutProps`, so `tsc --noEmit` passes
// in CI without first running a build to emit `.next/types`.
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${jetbrainsMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col bg-vt-bg text-vt-text">
        <AppHeader />
        <DisclaimerStrip />
        <div className="flex flex-1">
          <AppSidebar />
          <main className="flex-1 px-4 py-6 md:px-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
