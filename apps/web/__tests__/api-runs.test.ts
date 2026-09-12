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

  it("raises ApiError with the status for run reads", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(new Response("missing", { status: 404 }));
    await expect(createApiClient("http://api").getRun("nope")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
    });
  });
});
