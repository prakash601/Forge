import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { NewRunForm } from "@/components/NewRunForm";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

describe("NewRunForm", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn();
    push.mockClear();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("creates a run and navigates to its detail page", async () => {
    vi.mocked(global.fetch).mockResolvedValue(
      new Response(JSON.stringify({ id: "run-7", state: "CREATED" }), { status: 201 }),
    );
    render(<NewRunForm apiBaseUrl="http://api" />);

    fireEvent.change(screen.getByLabelText("Start a run"), {
      target: { value: "add pagination to /todos" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/runs/run-7"));
    expect(vi.mocked(global.fetch)).toHaveBeenCalledWith(
      "http://api/api/v1/runs",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ task: "add pagination to /todos" }),
      }),
    );
  });

  it("does not submit a blank task", () => {
    render(<NewRunForm apiBaseUrl="http://api" />);
    expect(screen.getByRole("button", { name: "Start run" })).toBeDisabled();
    expect(vi.mocked(global.fetch)).not.toHaveBeenCalled();
  });

  it("shows an error and stays put when creation fails", async () => {
    vi.mocked(global.fetch).mockResolvedValue(new Response("bad", { status: 422 }));
    render(<NewRunForm apiBaseUrl="http://api" />);

    fireEvent.change(screen.getByLabelText("Start a run"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(push).not.toHaveBeenCalled();
  });
});
