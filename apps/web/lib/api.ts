/**
 * Minimal API client foundation.
 *
 * In Phase 0 this only talks to the operational endpoints
 * (`/health`, `/ready`). Application endpoints under `/api/v1` are added
 * in Phase 1 alongside the corresponding server routes.
 *
 * The client intentionally does not use `fetch` features that the rest of
 * the application depends on elsewhere (caching, SSE, idempotency keys).
 * Those are introduced in later phases per `docs/api/OPENAPI_v0.1.md`.
 */

export type HealthStatus = "ok" | "unavailable";

export interface HealthResponse {
  status: HealthStatus;
}

export interface ReadyResponse {
  status: HealthStatus;
  version?: string;
  reason?: string;
}

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

export type RunState =
  | "CREATED"
  | "ANALYZING"
  | "PLANNING"
  | "AWAITING_APPROVAL"
  | "IMPLEMENTING"
  | "TESTING"
  | "DEBUGGING"
  | "REVIEWING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  | "NEEDS_HUMAN";

export interface RunStep {
  id: string;
  sequence: number;
  from_state: RunState;
  event: string;
  approved_by: string | null;
  to_state: RunState;
  created_at: string;
}

export interface Run {
  id: string;
  state: RunState;
  is_terminal: boolean;
  task: string;
  version: number;
  created_at: string;
  updated_at: string;
  steps: RunStep[];
}

export interface RunListResponse {
  runs: Run[];
  total: number;
}

export type JsonRecord = Record<string, unknown>;

export interface RunDetails {
  run: Run;
  analysis: JsonRecord | null;
  plan: JsonRecord | null;
  implementation: JsonRecord | null;
  test_result: JsonRecord | null;
  diagnosis: JsonRecord | null;
  review: JsonRecord | null;
  memory_candidates: JsonRecord[];
  approved_by: string | null;
}

export interface ApiClient {
  baseUrl: string;
  getHealth(): Promise<HealthResponse>;
  getReady(): Promise<ReadyResponse>;
  listRuns(limit?: number, offset?: number): Promise<RunListResponse>;
  getRun(runId: string): Promise<Run>;
  getRunDetails(runId: string): Promise<RunDetails>;
  applyEvent(runId: string, event: "plan_approved" | "plan_rejected"): Promise<Run>;
  createRun(task: string): Promise<Run>;
}

export function createApiClient(baseUrl: string): ApiClient {
  const trimmed = baseUrl.replace(/\/+$/, "");

  async function get<T>(path: string): Promise<T> {
    const response = await fetch(`${trimmed}${path}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
    });

    if (!response.ok) {
      throw new ApiError(
        `Request to ${path} failed with status ${response.status}`,
        response.status,
      );
    }

    return (await response.json()) as T;
  }

  async function post<T>(path: string, body: unknown): Promise<T> {
    const response = await fetch(`${trimmed}${path}`, {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      throw new ApiError(
        `Request to ${path} failed with status ${response.status}`,
        response.status,
      );
    }

    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }

  return {
    baseUrl: trimmed,
    getHealth: () => get<HealthResponse>("/health"),
    getReady: () => get<ReadyResponse>("/ready"),
    listRuns: (limit = 20, offset = 0) =>
      get<RunListResponse>(
        `/api/v1/runs?limit=${encodeURIComponent(String(limit))}&offset=${encodeURIComponent(String(offset))}`,
      ),
    getRun: (runId: string) => get<Run>(`/api/v1/runs/${encodeURIComponent(runId)}`),
    getRunDetails: (runId: string) =>
      get<RunDetails>(`/api/v1/runs/${encodeURIComponent(runId)}/details`),
    applyEvent: (runId: string, event: "plan_approved" | "plan_rejected") =>
      post<Run>(`/api/v1/runs/${encodeURIComponent(runId)}/events`, { event }),
    createRun: (task: string) => post<Run>("/api/v1/runs", { task }),
  };
}
