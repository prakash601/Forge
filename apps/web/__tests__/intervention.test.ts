import { describe, expect, it } from "vitest";

import type { RunDetails, RunStep } from "@/lib/api";
import { describeIntervention } from "@/lib/intervention";

function step(partial: Partial<RunStep> & { sequence: number }): RunStep {
  return {
    id: `s${partial.sequence}`,
    from_state: "TESTING",
    event: "tests_failed",
    approved_by: null,
    to_state: "DEBUGGING",
    created_at: "2026-09-12T00:00:00Z",
    ...partial,
  };
}

function detailsFixture(overrides: Partial<RunDetails> = {}): RunDetails {
  return {
    run: {
      id: "run-1",
      state: "NEEDS_HUMAN",
      is_terminal: false,
      task: "add pagination to /todos",
      version: 9,
      created_at: "2026-09-12T00:00:00Z",
      updated_at: "2026-09-12T00:09:00Z",
      steps: [],
    },
    analysis: null,
    plan: null,
    implementation: null,
    test_result: null,
    diagnosis: null,
    review: null,
    memory_candidates: [],
    approved_by: null,
    ...overrides,
  };
}

describe("describeIntervention", () => {
  it("returns null for healthy or in-flight states", () => {
    for (const state of ["COMPLETED", "TESTING", "AWAITING_APPROVAL", "CREATED"] as const) {
      const details = detailsFixture({
        run: { ...detailsFixture().run, state },
      });
      expect(describeIntervention(details)).toBeNull();
    }
  });

  it("names the exhausted debugging budget after three visits", () => {
    const details = detailsFixture({
      run: {
        ...detailsFixture().run,
        steps: [step({ sequence: 1 }), step({ sequence: 2 }), step({ sequence: 3 })],
      },
    });
    const info = describeIntervention(details);
    expect(info?.reason).toContain("budget exhausted after 3 attempts");
    expect(info?.debugAttempts).toBe(3);
    expect(info?.suggestion).toContain("next event");
  });

  it("reports reviewer rejection with its summary", () => {
    const details = detailsFixture({
      review: { decision: "REJECT", summary: "Scope creep." },
    });
    expect(describeIntervention(details)?.reason).toContain("Scope creep.");
  });

  it("reports failing tests with counts", () => {
    const details = detailsFixture({
      test_result: { status: "FAIL", passed: 11, failed: 1 },
    });
    const info = describeIntervention(details);
    expect(info?.reason).toContain("1 test failing");
    expect(info?.lastTests).toContain("11 passed");
  });

  it("falls back to the last step for failed runs without reports", () => {
    const details = detailsFixture({
      run: {
        ...detailsFixture().run,
        state: "FAILED",
        steps: [
          {
            id: "s9",
            sequence: 9,
            from_state: "IMPLEMENTING",
            event: "unrecoverable_error",
            approved_by: null,
            to_state: "FAILED",
            created_at: "2026-09-12T00:09:00Z",
          },
        ],
      },
    });
    const info = describeIntervention(details);
    expect(info?.reason).toContain("unrecoverable_error");
    expect(info?.suggestion).toContain("new run");
    expect(info?.lastTests).toBeNull();
  });
});
