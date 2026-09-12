"use client";

import { useEffect, useState } from "react";

import {
  createApiClient,
  type JsonRecord,
  type RunDetails,
  type RunState,
} from "@/lib/api";
import { subscribeToRun } from "@/lib/stream";

export function stateTone(state: RunState): "ok" | "bad" | "busy" | "idle" {
  if (state === "COMPLETED") {
    return "ok";
  }
  if (state === "FAILED" || state === "CANCELLED" || state === "NEEDS_HUMAN") {
    return "bad";
  }
  if (state === "CREATED") {
    return "idle";
  }
  return "busy";
}

export function StateBadge({ state }: { state: RunState }) {
  return <span className={`badge tone-${stateTone(state)}`}>{state}</span>;
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function list(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function RawJson({ value }: { value: JsonRecord }) {
  return (
    <details className="raw">
      <summary>Raw JSON</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

export function RunDetail({ details }: { details: RunDetails }) {
  const { run, approved_by } = details;
  return (
    <div className="detail">
      <header className="detail-head">
        <div>
          <p className="task">{run.task}</p>
          <p className="meta">
            version {run.version} · updated{" "}
            {new Date(run.updated_at).toLocaleString()}
            {approved_by ? ` · approved by ${approved_by}` : ""}
          </p>
        </div>
        <StateBadge state={run.state} />
      </header>

      <Section title="Timeline">
        {run.steps.length === 0 ? (
          <p className="muted">No steps yet.</p>
        ) : (
          <ol className="timeline">
            {run.steps.map((step) => (
              <li key={step.id}>
                <span className="seq">#{step.sequence}</span>
                <span className="event">{step.event}</span>
                <span className="muted">
                  {step.from_state} → {step.to_state}
                </span>
                {step.approved_by ? (
                  <span className="actor">by {step.approved_by}</span>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </Section>

      {details.analysis ? (
        <Section title="Analysis">
          <p>{str(details.analysis["summary"])}</p>
          <p className="muted">
            Relevant files: {list(details.analysis["relevant_files"]).join(", ") || "—"}
          </p>
          <RawJson value={details.analysis} />
        </Section>
      ) : null}

      {details.plan ? (
        <Section title="Plan">
          <p>{str(details.plan["goal"])}</p>
          <p className="muted">{str(details.plan["approach"])}</p>
          <RawJson value={details.plan} />
        </Section>
      ) : null}

      {details.implementation ? (
        <Section title="Implementation">
          <p>{str(details.implementation["summary"])}</p>
          <p className="muted">
            Changed: {list(details.implementation["files_changed"]).join(", ") || "—"}
          </p>
          <RawJson value={details.implementation} />
        </Section>
      ) : null}

      {details.test_result ? (
        <Section title="Tests">
          <p>
            {`${str(details.test_result["status"]) ?? "?"} · ${Number(details.test_result["passed"] ?? 0)} passed · ${Number(details.test_result["failed"] ?? 0)} failed`}
          </p>
          <RawJson value={details.test_result} />
        </Section>
      ) : null}

      {details.review ? (
        <Section title="Review">
          <p>
            {str(details.review["decision"])} — {str(details.review["summary"])}
          </p>
          <RawJson value={details.review} />
        </Section>
      ) : null}

      {details.diagnosis ? (
        <Section title="Diagnosis">
          <p>{str(details.diagnosis["root_cause"])}</p>
          <RawJson value={details.diagnosis} />
        </Section>
      ) : null}

      {details.memory_candidates.length > 0 ? (
        <Section title="Memory">
          <ul className="memory">
            {details.memory_candidates.map((candidate, index) => (
              <li key={index}>
                <span className="muted">{str(candidate["memory_type"])}:</span>{" "}
                {str(candidate["content"])}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
    </div>
  );
}

export interface RunLiveProps {
  apiBaseUrl: string;
  runId: string;
  initial: RunDetails;
  pollIntervalMs?: number;
}

export function RunLive({ apiBaseUrl, runId, initial, pollIntervalMs }: RunLiveProps) {
  const [details, setDetails] = useState<RunDetails>(initial);

  useEffect(() => {
    const client = createApiClient(apiBaseUrl);
    const options = pollIntervalMs === undefined ? {} : { pollIntervalMs };
    return subscribeToRun(apiBaseUrl, runId, {
      onStateChanged: () => {
        client
          .getRunDetails(runId)
          .then(setDetails)
          .catch(() => {
            // A failed refetch leaves the last known state on screen;
            // the next change retries.
          });
      },
      onStepAdded: (step) => {
        setDetails((prev) => ({
          ...prev,
          run: { ...prev.run, steps: [...prev.run.steps, step] },
        }));
      },
    }, options);
  }, [apiBaseUrl, runId, pollIntervalMs]);

  return <RunDetail details={details} />;
}
