import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import type { RunDetails } from "@/lib/api";
import { RunDetail, RunLive } from "@/components/RunLive";

function detailsFixture(): RunDetails {
  return {
    run: {
      id: "run-1",
      state: "REVIEWING",
      is_terminal: false,
      task: "add pagination to /todos",
      version: 6,
      created_at: "2026-09-12T00:00:00Z",
      updated_at: "2026-09-12T00:05:00Z",
      steps: [
        {
          id: "s1",
          sequence: 1,
          from_state: "CREATED",
          event: "repository_ready",
          approved_by: null,
          to_state: "ANALYZING",
          created_at: "2026-09-12T00:00:01Z",
        },
        {
          id: "s4",
          sequence: 4,
          from_state: "AWAITING_APPROVAL",
          event: "plan_approved",
          approved_by: "policy",
          to_state: "IMPLEMENTING",
          created_at: "2026-09-12T00:03:00Z",
        },
      ],
    },
    analysis: { summary: "Todo fixture.", relevant_files: ["app/main.py"] },
    plan: { goal: "Add pagination.", approach: "Slice." },
    implementation: { summary: "Sliced.", files_changed: ["app/main.py"] },
    test_result: { status: "PASS", passed: 12, failed: 0 },
    diagnosis: null,
    review: { decision: "APPROVE", summary: "Minimal change." },
    memory_candidates: [{ memory_type: "SUCCESSFUL_FIX", content: "Paginate." }],
    approved_by: "policy",
  };
}

describe("RunDetail", () => {
  it("renders task, state, timeline, and Phase 2 sections", () => {
    render(<RunDetail details={detailsFixture()} />);

    expect(screen.getByText("add pagination to /todos")).toBeInTheDocument();
    expect(screen.getByText("REVIEWING")).toBeInTheDocument();
    expect(screen.getByText("repository_ready")).toBeInTheDocument();
    expect(screen.getByText("plan_approved")).toBeInTheDocument();
    const sectionText = (heading: string) =>
      screen.getByText(heading).closest("section")?.textContent ?? "";
    expect(sectionText("Timeline")).toContain("by policy");
    expect(sectionText("Plan")).toContain("Add pagination.");
    expect(sectionText("Tests")).toContain("12 passed");
    expect(sectionText("Review")).toContain("Minimal change.");
    expect(sectionText("Memory")).toContain("Paginate.");
  });

  it("omits sections that have not run yet", () => {
    const fresh: RunDetails = {
      ...detailsFixture(),
      run: { ...detailsFixture().run, steps: [] },
      analysis: null,
      plan: null,
      implementation: null,
      test_result: null,
      review: null,
      memory_candidates: [],
      approved_by: null,
    };
    render(<RunDetail details={fresh} />);

    expect(screen.queryByText("Analysis")).not.toBeInTheDocument();
    expect(screen.queryByText("Review")).not.toBeInTheDocument();
    expect(screen.getByText("No steps yet.")).toBeInTheDocument();
  });
});

describe("RunLive", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("appends streamed steps to the timeline", async () => {
    // Polling fallback (no EventSource in jsdom) keeps returning the
    // initial run: no refetch storms, no duplicate steps.
    vi.mocked(global.fetch).mockResolvedValue(
      new Response(
        JSON.stringify({ ...detailsFixture().run, steps: detailsFixture().run.steps }),
        { status: 200 },
      ),
    );
    render(
      <RunLive apiBaseUrl="http://api" runId="run-1" initial={detailsFixture()} pollIntervalMs={10} />,
    );

    await waitFor(() => {
      expect(screen.getByText("repository_ready")).toBeInTheDocument();
    });
    expect(vi.mocked(global.fetch)).toHaveBeenCalledWith(
      "http://api/api/v1/runs/run-1",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("refetches details when the polled state changes", async () => {
    const base = detailsFixture().run;
    const completedRun = { ...base, state: "COMPLETED", version: 7 };
    const completedDetails = { ...detailsFixture(), run: completedRun };
    let polls = 0;
    vi.mocked(global.fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/details")) {
        return new Response(JSON.stringify(completedDetails), { status: 200 });
      }
      polls += 1;
      const run = polls === 1 ? base : completedRun;
      return new Response(JSON.stringify(run), { status: 200 });
    });
    render(
      <RunLive apiBaseUrl="http://api" runId="run-1" initial={detailsFixture()} pollIntervalMs={10} />,
    );

    await waitFor(() => {
      expect(
        vi.mocked(global.fetch),
      ).toHaveBeenCalledWith(
        "http://api/api/v1/runs/run-1/details",
        expect.objectContaining({ method: "GET" }),
      );
    });
    await waitFor(() => {
      expect(screen.getByText("COMPLETED")).toBeInTheDocument();
    });
  });
});
