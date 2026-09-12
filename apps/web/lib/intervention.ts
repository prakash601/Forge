/**
 * Intervention descriptor for stuck or failed runs (Issue #013).
 *
 * Pure derivation from the details read: why the run needs a human,
 * how many debugging attempts it took, the last test summary, and the
 * suggested next step. Returns null for states that need no panel.
 */

import type { RunDetails } from "./api";

export interface InterventionInfo {
  reason: string;
  debugAttempts: number;
  lastTests: string | null;
  suggestion: string;
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

export function describeIntervention(details: RunDetails): InterventionInfo | null {
  const { run } = details;
  if (run.state !== "NEEDS_HUMAN" && run.state !== "FAILED") {
    return null;
  }

  const debugAttempts = run.steps.filter((step) => step.to_state === "DEBUGGING").length;
  const failed = Number(details.test_result?.["failed"] ?? 0);
  const passed = Number(details.test_result?.["passed"] ?? 0);
  const lastTests =
    details.test_result === null
      ? null
      : `${str(details.test_result["status"]) ?? "?"} · ${passed} passed · ${failed} failed`;

  const reviewDecision = str(details.review?.["decision"]);
  const reviewSummary = str(details.review?.["summary"]);
  const lastStep = run.steps[run.steps.length - 1];

  let reason: string;
  if (run.state === "NEEDS_HUMAN" && debugAttempts >= 3) {
    reason = `Debugging budget exhausted after ${debugAttempts} attempts.`;
  } else if (reviewDecision !== null && reviewDecision !== "APPROVE") {
    reason = `Reviewer did not approve the change${reviewSummary ? `: ${reviewSummary}` : "."}`;
  } else if (failed > 0) {
    reason = `${failed} test${failed === 1 ? "" : "s"} failing with no fix ready.`;
  } else if (lastStep !== undefined) {
    reason = `Run stopped on ${lastStep.event} (${lastStep.from_state} → ${lastStep.to_state}).`;
  } else {
    reason = "Run needs attention before it can continue.";
  }

  const suggestion =
    run.state === "NEEDS_HUMAN"
      ? "Inspect the timeline and test output below, then drive the next event via the API."
      : "This run cannot continue automatically. Start a new run from the runs list.";

  return { reason, debugAttempts, lastTests, suggestion };
}
