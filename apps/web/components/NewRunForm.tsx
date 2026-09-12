"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { createApiClient } from "@/lib/api";

export interface NewRunFormProps {
  apiBaseUrl: string;
}

/**
 * Start a run from the dashboard (Issue #014).
 *
 * Posts the task to the existing create endpoint and navigates to the
 * live detail page. Empty tasks never leave the browser.
 */
export function NewRunForm({ apiBaseUrl }: NewRunFormProps) {
  const router = useRouter();
  const [task, setTask] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submittable = task.trim().length > 0 && !pending;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = task.trim();
    if (trimmed.length === 0 || pending) {
      return;
    }
    setPending(true);
    setError(null);
    try {
      const run = await createApiClient(apiBaseUrl).createRun(trimmed);
      router.push(`/runs/${run.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setPending(false);
    }
  };

  return (
    <form className="new-run" onSubmit={(event) => void submit(event)}>
      <label htmlFor="new-run-task">Start a run</label>
      <textarea
        id="new-run-task"
        value={task}
        maxLength={10000}
        rows={3}
        placeholder="Describe the engineering task, e.g. add pagination to /todos"
        onChange={(event) => setTask(event.target.value)}
      />
      {error ? (
        <p role="alert" className="error">
          {error}
        </p>
      ) : null}
      <button type="submit" className="btn primary" disabled={!submittable}>
        {pending ? "Starting…" : "Start run"}
      </button>
    </form>
  );
}
