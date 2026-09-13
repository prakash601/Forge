import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { NewRunForm } from "@/components/NewRunForm";
import type { Project } from "@/lib/api";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

const PROJECTS: Project[] = [
  {
    id: "proj-1",
    owner_id: "user-1",
    name: "Website",
    description: null,
    status: "ACTIVE",
    repo_url: null,
    default_branch: "main",
    auto_approve_policy: false,
    created_at: "2026-09-13T00:00:00Z",
    updated_at: "2026-09-13T00:00:00Z",
  },
];

describe("NewRunForm", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn();
    push.mockClear();
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("creates a run in the selected project and navigates to it", async () => {
    vi.mocked(global.fetch).mockResolvedValue(
      new Response(JSON.stringify({ id: "run-7", state: "CREATED" }), { status: 201 }),
    );
    render(<NewRunForm apiBaseUrl="http://api" projects={PROJECTS} />);

    fireEvent.change(screen.getByLabelText("Start a run"), {
      target: { value: "add pagination to /todos" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/runs/run-7"));
    expect(vi.mocked(global.fetch)).toHaveBeenCalledWith(
      "http://api/api/v1/runs",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ task: "add pagination to /todos", project_id: "proj-1" }),
      }),
    );
  });

  it("creates a project inline when the account has none", async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ ...PROJECTS[0], name: "Fresh" }), { status: 201 }),
    );
    render(<NewRunForm apiBaseUrl="http://api" projects={[]} />);

    fireEvent.change(screen.getByLabelText("Create your first project"), {
      target: { value: "Fresh" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create project" }));

    await waitFor(() =>
      expect(vi.mocked(global.fetch)).toHaveBeenCalledWith(
        "http://api/api/v1/projects",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ name: "Fresh" }),
        }),
      ),
    );
    expect(screen.getByLabelText("Project")).toBeInTheDocument();
  });

  it("does not submit a blank task", () => {
    render(<NewRunForm apiBaseUrl="http://api" projects={PROJECTS} />);
    expect(screen.getByRole("button", { name: "Start run" })).toBeDisabled();
    expect(vi.mocked(global.fetch)).not.toHaveBeenCalled();
  });

  it("shows an error and stays put when creation fails", async () => {
    vi.mocked(global.fetch).mockResolvedValue(new Response("bad", { status: 422 }));
    render(<NewRunForm apiBaseUrl="http://api" projects={PROJECTS} />);

    fireEvent.change(screen.getByLabelText("Start a run"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(push).not.toHaveBeenCalled();
  });

  it("offers login again on 401", async () => {
    vi.mocked(global.fetch).mockResolvedValue(new Response("gone", { status: 401 }));
    render(<NewRunForm apiBaseUrl="http://api" projects={PROJECTS} />);

    fireEvent.change(screen.getByLabelText("Start a run"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));

    await waitFor(() => expect(screen.getByText(/Session expired/)).toBeInTheDocument());
    expect(push).not.toHaveBeenCalled();
  });
});
