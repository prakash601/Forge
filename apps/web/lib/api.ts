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
  project_id?: string | null;
  branch?: string | null;
  base_commit?: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  steps: RunStep[];
}

export interface Project {
  id: string;
  owner_id: string;
  name: string;
  description: string | null;
  status: string;
  repo_url: string | null;
  default_branch: string;
  auto_approve_policy: boolean;
  created_at: string;
  updated_at: string;
}

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  created_at: string;
  updated_at: string;
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
  pull_request?: JsonRecord | null;
}

export interface ApiClientOptions {
  /** Forwarded session cookie (server components). Browser calls use the jar. */
  cookie?: string;
}

export interface ApiClient {
  baseUrl: string;
  getHealth(): Promise<HealthResponse>;
  getReady(): Promise<ReadyResponse>;
  getMe(): Promise<User>;
  devLogin(email: string, displayName?: string): Promise<User>;
  logout(): Promise<void>;
  loginUrl(next: string): string;
  listProjects(): Promise<Project[]>;
  createProject(name: string): Promise<Project>;
  listRuns(limit?: number, offset?: number): Promise<RunListResponse>;
  getRun(runId: string): Promise<Run>;
  getRunDetails(runId: string): Promise<RunDetails>;
  applyEvent(runId: string, event: "plan_approved" | "plan_rejected"): Promise<Run>;
  createRun(task: string, projectId: string): Promise<Run>;
}

export function createApiClient(baseUrl: string, options: ApiClientOptions = {}): ApiClient {
  const trimmed = baseUrl.replace(/\/+$/, "");
  // Server components forward the session explicitly; browser calls
  // ride the cookie jar (session is httpOnly, never in JS state).
  const extraHeaders: Record<string, string> = {};
  if (options.cookie !== undefined) {
    extraHeaders.Cookie = options.cookie;
  }
  const credentials: RequestCredentials = options.cookie === undefined ? "include" : "omit";

  async function get<T>(path: string): Promise<T> {
    const response = await fetch(`${trimmed}${path}`, {
      method: "GET",
      headers: { Accept: "application/json", ...extraHeaders },
      credentials,
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
      headers: { Accept: "application/json", "Content-Type": "application/json", ...extraHeaders },
      credentials,
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
    getMe: () => get<User>("/api/v1/auth/me"),
    devLogin: (email: string, displayName?: string) =>
      post<User>("/api/v1/auth/dev-login", { email, display_name: displayName ?? null }),
    logout: () => post<{ ok: boolean }>("/api/v1/auth/logout", {}).then(() => {}),
    loginUrl: (next: string) =>
      `${trimmed}/api/v1/auth/github/login?next=${encodeURIComponent(next)}`,
    listProjects: () => get<Project[]>("/api/v1/projects?limit=200"),
    createProject: (name: string) => post<Project>("/api/v1/projects", { name }),
    listRuns: (limit = 20, offset = 0) =>
      get<RunListResponse>(
        `/api/v1/runs?limit=${encodeURIComponent(String(limit))}&offset=${encodeURIComponent(String(offset))}`,
      ),
    getRun: (runId: string) => get<Run>(`/api/v1/runs/${encodeURIComponent(runId)}`),
    getRunDetails: (runId: string) =>
      get<RunDetails>(`/api/v1/runs/${encodeURIComponent(runId)}/details`),
    applyEvent: (runId: string, event: "plan_approved" | "plan_rejected") =>
      post<Run>(`/api/v1/runs/${encodeURIComponent(runId)}/events`, { event }),
    createRun: (task: string, projectId: string) =>
      post<Run>("/api/v1/runs", { task, project_id: projectId }),
  };
}
