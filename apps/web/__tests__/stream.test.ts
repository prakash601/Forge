import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { subscribeToRun } from "@/lib/stream";
import type { Run } from "@/lib/api";

function runFixture(overrides: Partial<Run> = {}): Run {
  return {
    id: "run-1",
    state: "CREATED",
    is_terminal: false,
    task: "add pagination to /todos",
    version: 0,
    created_at: "2026-09-12T00:00:00Z",
    updated_at: "2026-09-12T00:00:00Z",
    steps: [],
    ...overrides,
  };
}

describe("subscribeToRun polling fallback (no EventSource in jsdom)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn();
    expect(typeof EventSource).toBe("undefined");
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.useRealTimers();
  });

  it("emits snapshot, then state changes and new steps", async () => {
    const states = [
      runFixture(),
      runFixture({
        state: "ANALYZING",
        version: 1,
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
        ],
      }),
    ];
    let calls = 0;
    vi.mocked(global.fetch).mockImplementation(async () => {
      const body = states[Math.min(calls, states.length - 1)];
      calls += 1;
      return new Response(JSON.stringify(body), { status: 200 });
    });

    const seen: string[] = [];
    const unsubscribe = subscribeToRun("http://api", "run-1", {
      onSnapshot: (run) => seen.push(`snapshot:${run.state}`),
      onStateChanged: (state) => seen.push(`state:${state}`),
      onStepAdded: (step) => seen.push(`step:${step.event}`),
    }, { pollIntervalMs: 5 });

    await vi.waitFor(() => expect(seen).toContain("snapshot:CREATED"));
    await vi.waitFor(() => expect(seen).toContain("state:ANALYZING"));
    await vi.waitFor(() => expect(seen).toContain("step:repository_ready"));
    unsubscribe();
    const frozen = seen.length;
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(seen.length).toBe(frozen);
  });

  it("reports fetch failures through onError", async () => {
    vi.mocked(global.fetch).mockRejectedValue(new Error("down"));
    const errors: string[] = [];
    const unsubscribe = subscribeToRun("http://api", "run-1", {
      onError: (message) => errors.push(message),
    }, { pollIntervalMs: 50 });
    await vi.waitFor(() => expect(errors).toContain("down"));
    unsubscribe();
  });
});

describe("subscribeToRun EventSource path", () => {
  const originalEventSource = global.EventSource;
  const originalFetch = global.fetch;

  class FakeEventSource {
    static instances: FakeEventSource[] = [];
    url: string;
    init: object | undefined;
    listeners = new Map<string, Array<(event: object) => void>>();
    onerror: (() => void) | null = null;
    closed = false;
    constructor(url: string, init?: object) {
      this.url = url;
      this.init = init;
      FakeEventSource.instances.push(this);
    }
    addEventListener(type: string, listener: (event: object) => void) {
      const list = this.listeners.get(type) ?? [];
      list.push(listener);
      this.listeners.set(type, list);
    }
    emit(type: string, payload: unknown) {
      for (const listener of this.listeners.get(type) ?? []) {
        listener({ data: JSON.stringify(payload) });
      }
    }
    fail() {
      this.onerror?.();
    }
    close() {
      this.closed = true;
    }
  }

  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
    global.fetch = vi.fn();
  });

  afterEach(() => {
    if (originalEventSource === undefined) {
      vi.unstubAllGlobals();
    } else {
      global.EventSource = originalEventSource;
    }
    global.fetch = originalFetch;
  });

  it("routes snapshot/state/step frames to handlers", () => {
    const seen: string[] = [];
    const unsubscribe = subscribeToRun("http://api", "run-9", {
      onSnapshot: (run) => seen.push(`snapshot:${run.state}`),
      onStateChanged: (state) => seen.push(`state:${state}`),
      onStepAdded: (step) => seen.push(`step:${step.event}`),
    });
    const source = FakeEventSource.instances[0];
    expect(source.url).toBe("http://api/api/v1/runs/run-9/stream");
    expect(source.init).toEqual({ withCredentials: true });
    source.emit("snapshot", runFixture({ state: "CREATED" }));
    source.emit("state_changed", { state: "ANALYZING", version: 1 });
    source.emit("step_added", {
      id: "s1",
      sequence: 1,
      from_state: "CREATED",
      event: "repository_ready",
      approved_by: null,
      to_state: "ANALYZING",
      created_at: "2026-09-12T00:00:01Z",
    });
    expect(seen).toEqual(["snapshot:CREATED", "state:ANALYZING", "step:repository_ready"]);
    unsubscribe();
    expect(source.closed).toBe(true);
  });

  it("falls back to polling when the stream errors before data", async () => {
    vi.mocked(global.fetch).mockResolvedValue(
      new Response(JSON.stringify(runFixture()), { status: 200 }),
    );
    const seen: string[] = [];
    const unsubscribe = subscribeToRun("http://api", "run-9", {
      onSnapshot: (run) => seen.push(`snapshot:${run.state}`),
    }, { pollIntervalMs: 5 });
    FakeEventSource.instances[0].fail();
    await vi.waitFor(() => expect(seen).toEqual(["snapshot:CREATED"]));
    expect(vi.mocked(global.fetch)).toHaveBeenCalledWith(
      "http://api/api/v1/runs/run-9",
      expect.objectContaining({ method: "GET" }),
    );
    unsubscribe();
  });
});
