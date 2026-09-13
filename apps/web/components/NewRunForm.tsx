"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { createApiClient, type Project } from "@/lib/api";
import { SessionExpired, isUnauthorized } from "@/components/SessionExpired";

export interface NewRunFormProps {
  apiBaseUrl: string;
  projects: Project[];
}

/**
 * Start a run from the dashboard (Issues #014, #022).
 *
 * Runs belong to a project (required since #016): pick one, or create
 * one inline when the account has none yet. A 401 surfaces the login
 * hint instead of a dead form.
 */
export function NewRunForm({ apiBaseUrl, projects: initial }: NewRunFormProps) {
  const router = useRouter();
  const [task, setTask] = useState("");
  const [projects, setProjects] = useState<Project[]>(initial);
  const [projectId, setProjectId] = useState(initial[0]?.id ?? "");
  const [newName, setNewName] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unauthorized, setUnauthorized] = useState(false);

  const submittable = task.trim().length > 0 && projectId !== "" && !pending;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = task.trim();
    if (trimmed.length === 0 || projectId === "" || pending) {
      return;
    }
    setPending(true);
    setError(null);
    setUnauthorized(false);
    try {
      const run = await createApiClient(apiBaseUrl).createRun(trimmed, projectId);
      router.push(`/runs/${run.id}`);
    } catch (cause) {
      if (isUnauthorized(cause)) {
        setUnauthorized(true);
      } else {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
      setPending(false);
    }
  };

  const createProject = async (event: React.FormEvent) => {
    event.preventDefault();
    const name = newName.trim();
    if (name.length === 0 || pending) {
      return;
    }
    setPending(true);
    setError(null);
    setUnauthorized(false);
    try {
      const project = await createApiClient(apiBaseUrl).createProject(name);
      setProjects((prev) => [...prev, project]);
      setProjectId(project.id);
      setNewName("");
    } catch (cause) {
      if (isUnauthorized(cause)) {
        setUnauthorized(true);
      } else {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    } finally {
      setPending(false);
    }
  };

  return (
    <form className="new-run" onSubmit={(event) => void submit(event)}>
      <label htmlFor="new-run-task">Start a run</label>
      <textarea
        id="new-run-task"
        value={task}
        maxLength={10000}
        rows={3}
        placeholder="Describe the engineering task, e.g. add pagination to /todos"
        onChange={(event) => void setTask(event.target.value)}
      />
      {projects.length > 0 ? (
        <label htmlFor="new-run-project">
          Project
          <select
            id="new-run-project"
            value={projectId}
            onChange={(event) => void setProjectId(event.target.value)}
          >
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <div className="new-project">
          <label htmlFor="new-project-name">Create your first project</label>
          <input
            id="new-project-name"
            value={newName}
            maxLength={255}
            placeholder="Project name"
            onChange={(event) => void setNewName(event.target.value)}
          />
          <button
            type="button"
            className="btn"
            disabled={newName.trim().length === 0 || pending}
            onClick={(event) => void createProject(event)}
          >
            Create project
          </button>
        </div>
      )}
      {error ? (
        <p role="alert" className="error">
          {error}
        </p>
      ) : null}
      {unauthorized ? <SessionExpired apiBaseUrl={apiBaseUrl} /> : null}
      <button type="submit" className="btn primary" disabled={!submittable}>
        {pending ? "Starting…" : "Start run"}
      </button>
    </form>
  );
}
