/**
 * Live run subscription (Issue #011).
 *
 * Prefers server-sent events (`GET /api/v1/runs/{id}/stream`) and falls
 * back to polling `GET /api/v1/runs/{id}` when EventSource is unavailable
 * or the stream errors before delivering anything. Both paths funnel
 * into the same handlers so the UI never branches on transport.
 */

import { createApiClient, type Run, type RunState, type RunStep } from "./api";

export interface RunStreamHandlers {
  onSnapshot?: (run: Run) => void;
  onStateChanged?: (state: RunState, version: number) => void;
  onStepAdded?: (step: RunStep) => void;
  onError?: (message: string) => void;
}

export interface SubscribeOptions {
  pollIntervalMs?: number;
}

type EventSourceFactory = new (url: string) => EventSource;

function getEventSourceFactory(): EventSourceFactory | null {
  if (typeof EventSource === "undefined") {
    return null;
  }
  return EventSource as unknown as EventSourceFactory;
}

export function subscribeToRun(
  baseUrl: string,
  runId: string,
  handlers: RunStreamHandlers,
  options: SubscribeOptions = {},
): () => void {
  const trimmed = baseUrl.replace(/\/+$/, "");
  const factory = getEventSourceFactory();
  if (factory === null) {
    return startPolling(trimmed, runId, handlers, options.pollIntervalMs ?? 2000);
  }
  return startEventStream(trimmed, runId, handlers, factory, options.pollIntervalMs ?? 2000);
}

function startEventStream(
  baseUrl: string,
  runId: string,
  handlers: RunStreamHandlers,
  factory: EventSourceFactory,
  pollIntervalMs: number,
): () => void {
  let settled = false;
  const source = new factory(
    `${baseUrl}/api/v1/runs/${encodeURIComponent(runId)}/stream`,
  );

  const markSettled = () => {
    settled = true;
  };
  const onMessage = (type: "snapshot" | "state_changed" | "step_added") => {
    return (event: MessageEvent) => {
      markSettled();
      try {
        const data = JSON.parse((event as MessageEvent).data as string) as
          | Run
          | { state: RunState; version: number }
          | RunStep;
        if (type === "snapshot") {
          handlers.onSnapshot?.(data as Run);
        } else if (type === "state_changed") {
          const { state, version } = data as { state: RunState; version: number };
          handlers.onStateChanged?.(state, version);
        } else {
          handlers.onStepAdded?.(data as RunStep);
        }
      } catch (error) {
        handlers.onError?.(error instanceof Error ? error.message : String(error));
      }
    };
  };

  source.addEventListener("snapshot", onMessage("snapshot") as EventListener);
  source.addEventListener("state_changed", onMessage("state_changed") as EventListener);
  source.addEventListener("step_added", onMessage("step_added") as EventListener);
  source.addEventListener("error", (() => {
    handlers.onError?.("stream error payload");
  }) as EventListener);

  let fallback: (() => void) | null = null;
  source.onerror = () => {
    // If the stream died before delivering anything, poll instead of
    // leaving the UI frozen. A mid-stream error just closes: the UI
    // already has data and the next navigation refetches.
    if (!settled) {
      source.close();
      fallback = startPolling(baseUrl, runId, handlers, pollIntervalMs);
    } else {
      source.close();
    }
  };

  return () => {
    source.close();
    fallback?.();
  };
}

function startPolling(
  baseUrl: string,
  runId: string,
  handlers: RunStreamHandlers,
  pollIntervalMs: number,
): () => void {
  const client = createApiClient(baseUrl);
  let stopped = false;
  let lastState: RunState | null = null;
  let lastSequence = 0;

  const poll = async () => {
    if (stopped) {
      return;
    }
    try {
      const run = await client.getRun(runId);
      if (stopped) {
        return;
      }
      if (lastState === null) {
        handlers.onSnapshot?.(run);
      } else {
        if (run.state !== lastState) {
          handlers.onStateChanged?.(run.state, run.version);
        }
        for (const step of run.steps) {
          if (step.sequence > lastSequence) {
            handlers.onStepAdded?.(step);
          }
        }
      }
      lastState = run.state;
      for (const step of run.steps) {
        lastSequence = Math.max(lastSequence, step.sequence);
      }
    } catch (error) {
      handlers.onError?.(error instanceof Error ? error.message : String(error));
    }
  };

  void poll();
  const timer = setInterval(() => {
    void poll();
  }, pollIntervalMs);
  return () => {
    stopped = true;
    clearInterval(timer);
  };
}
