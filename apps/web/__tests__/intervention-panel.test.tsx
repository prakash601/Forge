import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import type { RunDetails } from "@/lib/api";
import { InterventionPanel } from "@/components/InterventionPanel";
import { RunDetail } from "@/components/RunLive";

function stuckDetails(): RunDetails {
  return {
    run: {
      id: "run-9",
      state: "NEEDS_HUMAN",
      is_terminal: false,
      task: "add pagination to /todos",
      version: 9,
      created_at: "2026-09-12T00:00:00Z",
      updated_at: "2026-09-12T00:09:00Z",
      steps: [1, 2, 3].map((sequence) => ({
        id: `s${sequence}`,
        sequence,
        from_state: "TESTING" as const,
        event: "tests_failed",
        approved_by: null,
        to_state: "DEBUGGING" as const,
        created_at: "2026-09-12T00:00:00Z",
      })),
    },
    analysis: null,
    plan: null,
    implementation: null,
    test_result: { status: "FAIL", passed: 11, failed: 1 },
    diagnosis: null,
    review: null,
    memory_candidates: [],
    approved_by: null,
  };
}

describe("InterventionPanel", () => {
  it("explains a stuck run with a way back", () => {
    render(<InterventionPanel details={stuckDetails()} />);
    expect(screen.getByLabelText("Intervention needed")).toBeInTheDocument();
    expect(screen.getByText(/budget exhausted after 3 attempts/)).toBeInTheDocument();
    expect(screen.getByText(/Debugging attempts: 3/)).toBeInTheDocument();
    expect(screen.getByText(/11 passed/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to runs" })).toHaveAttribute("href", "/");
  });

  it("renders nothing for healthy states", () => {
    const { container } = render(
      <InterventionPanel
        details={{ ...stuckDetails(), run: { ...stuckDetails().run, state: "COMPLETED" } }}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("appears at the top of the run detail for stuck runs", () => {
    render(<RunDetail details={stuckDetails()} />);
    const panel = screen.getByLabelText("Intervention needed");
    const timeline = screen.getByText("Timeline").closest("section");
    expect(panel.compareDocumentPosition(timeline as Element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
