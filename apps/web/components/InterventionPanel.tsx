import Link from "next/link";

import type { RunDetails } from "@/lib/api";
import { describeIntervention } from "@/lib/intervention";

/**
 * Intervention panel for NEEDS_HUMAN / FAILED runs (Issue #013).
 *
 * Explains why the run is stuck, what was tried, and what to do next —
 * always with a way back to the runs list, so no state is a dead end.
 */
export function InterventionPanel({ details }: { details: RunDetails }) {
  const info = describeIntervention(details);
  if (info === null) {
    return null;
  }
  return (
    <section className="panel intervention" aria-label="Intervention needed">
      <h2>Intervention needed</h2>
      <p>{info.reason}</p>
      <p className="muted">Debugging attempts: {info.debugAttempts}</p>
      {info.lastTests ? <p className="muted">Last tests: {info.lastTests}</p> : null}
      <p>{info.suggestion}</p>
      <p>
        <Link href="/">Back to runs</Link>
      </p>
    </section>
  );
}
