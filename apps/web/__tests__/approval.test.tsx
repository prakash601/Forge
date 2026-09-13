import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { PlanApproval } from "@/components/PlanApproval";
import { RunDetail } from "@/components/RunLive";
import type { RunDetails } from "@/lib/api";

const DETAILS_AWAITING: RunDetails = {
  run: {
    id: "run-1",
    state: "AWAITING_APPROVAL",
    is_terminal: false,
    task: "add pagination to /todos",
    version: 3,
    created_at: "2026-09-12T00:00:00Z",
    updated_at: "2026-09-12T00:02:00Z",
    steps: [],
  },
  analysis: null,
  plan: { goal: "Add pagination.", approach: "Slice." },
  implementation: null,
  test_result: null,
  diagnosis: null,
  review: null,
  memory_candidates: [],
  approved_by: null,
};

describe("PlanApproval", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("renders nothing when the run is not awaiting approval", () => {
    const { container } = render(
      <PlanApproval apiBaseUrl="http://api" runId="run-1" state="PLANNING" onChanged={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("approves the plan and notifies the parent", async () => {
    vi.mocked(global.fetch).mockResolvedValue(
      new Response(JSON.stringify({ id: "run-1", state: "IMPLEMENTING" }), { status: 200 }),
    );
    const onChanged = vi.fn();
    render(
      <PlanApproval apiBaseUrl="http://api" runId="run-1" state="AWAITING_APPROVAL" onChanged={onChanged} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Approve plan" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(vi.mocked(global.fetch)).toHaveBeenCalledWith(
      "http://api/api/v1/runs/run-1/events",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ event: "plan_approved" }),
      }),
    );
  });

  it("rejects the plan", async () => {
    vi.mocked(global.fetch).mockResolvedValue(
      new Response(JSON.stringify({ id: "run-1", state: "PLANNING" }), { status: 200 }),
    );
    const onChanged = vi.fn();
    render(
      <PlanApproval apiBaseUrl="http://api" runId="run-1" state="AWAITING_APPROVAL" onChanged={onChanged} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Reject plan" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(vi.mocked(global.fetch)).toHaveBeenCalledWith(
      "http://api/api/v1/runs/run-1/events",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ event: "plan_rejected" }),
      }),
    );
  });

  it("shows an error and stays put when the request fails", async () => {
    vi.mocked(global.fetch).mockResolvedValue(new Response("conflict", { status: 409 }));
    const onChanged = vi.fn();
    render(
      <PlanApproval apiBaseUrl="http://api" runId="run-1" state="AWAITING_APPROVAL" onChanged={onChanged} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Approve plan" }));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(onChanged).not.toHaveBeenCalled();
  });
});

describe("RunDetail approval slot", () => {
  it("renders the injected approval node inside the Plan section", () => {
    render(<RunDetail details={DETAILS_AWAITING} approval={<div>approval-node</div>} />);
    const plan = screen.getByText("Plan").closest("section");
    expect(plan?.textContent).toContain("approval-node");
  });

  it("labels policy-approved runs as such", () => {
    render(<RunDetail details={{ ...DETAILS_AWAITING, approved_by: "policy" }} />);
    expect(screen.getByText(/approved by policy/)).toBeInTheDocument();
  });
});
