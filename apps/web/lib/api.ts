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

export interface ApiClient {
  baseUrl: string;
  getHealth(): Promise<HealthResponse>;
  getReady(): Promise<ReadyResponse>;
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

  return {
    baseUrl: trimmed,
    getHealth: () => get<HealthResponse>("/health"),
    getReady: () => get<ReadyResponse>("/ready"),
  };
}
