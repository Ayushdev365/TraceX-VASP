import { TraceForm } from "@/components/intake/TraceForm";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";

/** The pipeline, in the investigator's own terms rather than in engineering terms. */
const PIPELINE = [
  { step: "Trace", detail: "Follow the wallet's outbound transactions across the chain." },
  { step: "Match", detail: "Check every address against labelled VASP and risk datasets." },
  { step: "Score", detail: "Produce an explainable, factor-by-factor attribution score." },
  { step: "Report", detail: "Export the evidence trail and a draft disclosure request." },
] as const;

export default function CaseIntakePage() {
  return (
    <div className="mx-auto grid max-w-6xl gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="space-y-6">
        <div>
          <h1 className="text-xl font-semibold text-vt-text">Wallet attribution</h1>
          <p className="mt-1 max-w-2xl text-sm text-vt-text-muted">
            Trace an unknown cryptocurrency wallet to the nearest labelled Virtual Asset
            Service Provider, with a hop-by-hop evidence trail an investigator can verify
            independently.
          </p>
        </div>

        <TraceForm />
      </div>

      <aside className="space-y-6">
        <Card>
          <CardHeader title="How it works" />
          <CardBody>
            <ol className="space-y-3">
              {PIPELINE.map((item, index) => (
                <li key={item.step} className="flex gap-3">
                  <span
                    aria-hidden
                    className="vt-mono mt-0.5 grid size-5 shrink-0 place-items-center rounded bg-vt-surface-raised text-[11px] text-vt-accent"
                  >
                    {index + 1}
                  </span>
                  <span>
                    <span className="block text-sm font-medium text-vt-text">{item.step}</span>
                    <span className="block text-xs text-vt-text-muted">{item.detail}</span>
                  </span>
                </li>
              ))}
            </ol>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Scope" />
          <CardBody className="space-y-2 text-xs text-vt-text-muted">
            <p>
              This system identifies a wallet-to-VASP relationship only. It does not identify
              any wallet owner&rsquo;s real-world identity.
            </p>
            <p>
              It performs no freezing, blocking or account action, and submits nothing to any
              portal. Disclosure requests are drafts for an officer to review.
            </p>
            <p>
              Label coverage is partial. A result of &ldquo;no attribution found&rdquo; does not
              mean the wallet has no VASP relationship.
            </p>
          </CardBody>
        </Card>
      </aside>
    </div>
  );
}
