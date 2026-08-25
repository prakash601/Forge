import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";

import { ApiError, createApiClient } from "@/lib/api";

async function renderResolved(
  element: ReactElement | Promise<ReactElement>,
) {
  const resolved =
    element instanceof Promise ? await element : (element as ReactElement);
  return render(resolved);
}

describe("createApiClient", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("trims trailing slashes from the base URL", () => {
    const client = createApiClient("http://example.com///");
    expect(client.baseUrl).toBe("http://example.com");
  });

  it("calls /health and returns the JSON body", async () => {
    const mock = vi.mocked(global.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
    );

    const client = createApiClient("http://api");
    const result = await client.getHealth();

    expect(mock).toHaveBeenCalledWith(
      "http://api/health",
      expect.objectContaining({ method: "GET" }),
    );
    expect(result).toEqual({ status: "ok" });
  });

  it("raises an ApiError for non-2xx responses", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      new Response("nope", { status: 503 }),
    );

    const client = createApiClient("http://api");
    await expect(client.getHealth()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("Home page (rendered via async server-component helper)", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", version: "0.1.0" }), {
        status: 200,
      }),
    );
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.resetModules();
  });

  it("renders Forge and a connected-status indicator when the API is reachable", async () => {
    const { default: Home } = await import("@/app/page");
    await renderResolved(Home({ searchParams: {} }));

    expect(
      screen.getByRole("heading", { name: "Forge", level: 1 }),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(
        screen.getByText(/Connected to API \(v0\.1\.0\)/),
      ).toBeInTheDocument();
    });
  });
});
