import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, createApiClient } from "@/lib/api";

describe("ApiClient runs reads", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("lists runs newest-first with a total", async () => {
    const mock = vi.mocked(global.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ runs: [{ id: "a" }], total: 3 }), { status: 200 }),
    );
    const result = await createApiClient("http://api/").listRuns(10, 5);
    expect(mock).toHaveBeenCalledWith(
      "http://api/api/v1/runs?limit=10&offset=5",
      expect.objectContaining({ method: "GET" }),
    );
    expect(result).toEqual({ runs: [{ id: "a" }], total: 3 });
  });

  it("fetches one run and its details", async () => {
    const mock = vi.mocked(global.fetch)
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: "r1" }), { status: 200 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ run: { id: "r1" }, approved_by: "policy" }), {
          status: 200,
        }),
      );
    const client = createApiClient("http://api");
    expect(await client.getRun("r1")).toEqual({ id: "r1" });
    expect(await client.getRunDetails("r1")).toEqual({
      run: { id: "r1" },
      approved_by: "policy",
    });
    expect(mock).toHaveBeenNthCalledWith(
      1,
      "http://api/api/v1/runs/r1",
      expect.objectContaining({ method: "GET" }),
    );
    expect(mock).toHaveBeenNthCalledWith(
      2,
      "http://api/api/v1/runs/r1/details",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("posts approval events with a JSON body", async () => {
    const mock = vi.mocked(global.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "r1", state: "IMPLEMENTING" }), { status: 200 }),
    );
    const result = await createApiClient("http://api").applyEvent("r1", "plan_approved");
    expect(mock).toHaveBeenCalledWith(
      "http://api/api/v1/runs/r1/events",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ event: "plan_approved" }),
      }),
    );
    expect(result).toEqual({ id: "r1", state: "IMPLEMENTING" });
  });

  it("creates a run with task and project", async () => {
    const mock = vi.mocked(global.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "r2", state: "CREATED" }), { status: 201 }),
    );
    const result = await createApiClient("http://api").createRun("do the thing", "proj-1");
    expect(mock).toHaveBeenCalledWith(
      "http://api/api/v1/runs",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({ task: "do the thing", project_id: "proj-1" }),
      }),
    );
    expect(result).toEqual({ id: "r2", state: "CREATED" });
  });

  it("reads the caller and logs out", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "u1", email: "dev@example.com" }), { status: 200 }),
    );
    const me = await createApiClient("http://api").getMe();
    expect(me.email).toBe("dev@example.com");

    vi.mocked(global.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    await createApiClient("http://api").logout();
    expect(vi.mocked(global.fetch)).toHaveBeenCalledWith(
      "http://api/api/v1/auth/logout",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });

  it("builds the login URL with a next destination", () => {
    expect(createApiClient("http://api").loginUrl("http://web/")).toBe(
      "http://api/api/v1/auth/github/login?next=http%3A%2F%2Fweb%2F",
    );
  });

  it("forwards a session cookie server-side without credentials mode", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "u1", email: "dev@example.com" }), { status: 200 }),
    );
    await createApiClient("http://api", { cookie: "forge_session=abc" }).getMe();
    expect(vi.mocked(global.fetch)).toHaveBeenCalledWith(
      "http://api/api/v1/auth/me",
      expect.objectContaining({
        headers: expect.objectContaining({ Cookie: "forge_session=abc" }),
        credentials: "omit",
      }),
    );
  });

  it("raises ApiError with the status for run reads", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(new Response("missing", { status: 404 }));
    await expect(createApiClient("http://api").getRun("nope")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
    });
  });
});
