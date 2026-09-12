"use client";

import { useState } from "react";

import { createApiClient, type RunState } from "@/lib/api";

export type ApprovalEvent = "plan_approved" | "plan_rejected";

export interface PlanApprovalProps {
  apiBaseUrl: string;
  runId: string;
  state: RunState;
  onChanged: () => void;
}

/**
 * Human plan approval (Issue #012).
 *
 * Renders only while the run awaits approval. Approving or rejecting
 * posts the event (recorded server-side as approved_by=human) and asks
 * the parent to refresh; the stream then carries the new state.
 */
export function PlanApproval({ apiBaseUrl, runId, state, onChanged }: PlanApprovalProps) {
  const [pending, setPending] = useState<ApprovalEvent | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (state !== "AWAITING_APPROVAL") {
    return null;
  }

  const act = async (event: ApprovalEvent) => {
    setPending(event);
    setError(null);
    try {
      await createApiClient(apiBaseUrl).applyEvent(runId, event);
      onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setPending(null);
    }
  };

  const busy = pending !== null;
  return (
    <div className="approval">
      <button
        type="button"
        className="btn primary"
        disabled={busy}
        onClick={() => void act("plan_approved")}
      >
        {pending === "plan_approved" ? "Approving…" : "Approve plan"}
      </button>
      <button
        type="button"
        className="btn danger"
        disabled={busy}
        onClick={() => void act("plan_rejected")}
      >
        {pending === "plan_rejected" ? "Rejecting…" : "Reject plan"}
      </button>
      {error ? (
        <p role="alert" className="error">
          {error}
        </p>
      ) : null}
      <p className="muted">Your decision is recorded as a human approval.</p>
    </div>
  );
}
