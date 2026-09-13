import Link from "next/link";

import { createApiClient } from "@/lib/api";
import { sessionCookie } from "@/lib/session";
import { publicApiBaseUrl, serverApiBaseUrl } from "@/lib/urls";
import { LoginPrompt } from "@/components/LoginButton";
import { LogoutButton } from "@/components/LogoutButton";
import { NewRunForm } from "@/components/NewRunForm";
import { StateBadge } from "@/components/RunLive";

interface HomePageProps {
  searchParams: { [key: string]: string | string[] | undefined };
}

function apiBaseUrl(searchParams: HomePageProps["searchParams"]): string {
  return serverApiBaseUrl(searchParams);
}

export default async function Home({ searchParams }: HomePageProps) {
  const baseUrl = apiBaseUrl(searchParams);
  // Browser-facing fetches (forms, SSE, login) must use the public URL:
  // inside Docker `API_BASE_URL=http://api:8000` is unreachable from the laptop.
  const browserBaseUrl = publicApiBaseUrl(baseUrl);
  const cookie = await sessionCookie();
  const client = createApiClient(baseUrl, { cookie });

  let ready = null;
  try {
    ready = await client.getReady();
  } catch {
    ready = null;
  }
  const isConnected = ready?.status === "ok";

  let me = null;
  try {
    me = await client.getMe();
  } catch {
    // Logged out or unreachable: the login prompt covers both (the
    // status indicator above tells them apart).
    me = null;
  }

  if (me === null) {
    return (
      <main className="dashboard">
        <span className="phase">
          <span className="dot" />
          Phase 4 — Public MVP
        </span>
        <h1>Forge</h1>
        <div className={`status ${isConnected ? "connected" : "disconnected"}`}>
          <span className="indicator" />
          <span>
            {isConnected
              ? `Connected to API (v${ready?.version ?? "?"})`
              : `Cannot reach API at ${baseUrl}`}
          </span>
        </div>
        <LoginPrompt apiBaseUrl={browserBaseUrl} />
      </main>
    );
  }

  const [projects, listing] = await Promise.all([
    client.listProjects().catch(() => null),
    client.listRuns(20, 0).catch(() => null),
  ]);

  return (
    <main className="dashboard">
      <span className="phase">
        <span className="dot" />
        Phase 4 — Public MVP
      </span>
      <h1>Forge</h1>
      <div className={`status ${isConnected ? "connected" : "disconnected"}`}>
        <span className="indicator" />
        <span>
          {isConnected
            ? `Connected to API (v${ready?.version ?? "?"})`
            : `Cannot reach API at ${baseUrl}`}
        </span>{" "}
        <LogoutButton apiBaseUrl={browserBaseUrl} email={me.email} />
      </div>

      <section className="panel">
        <h2>New run</h2>
        <NewRunForm apiBaseUrl={browserBaseUrl} projects={projects ?? []} />
      </section>

      <section className="panel runs">
        <h2>Runs{listing ? ` (${listing.total})` : ""}</h2>
        {!listing ? (
          <p className="muted">Could not load runs from the API.</p>
        ) : listing.runs.length === 0 ? (
          <p className="muted">No runs yet. Describe a task above to start one.</p>
        ) : (
          <ul className="run-list">
            {listing.runs.map((run) => (
              <li key={run.id}>
                <Link href={`/runs/${run.id}`}>
                  <span className="run-task">{run.task}</span>
                  <span className="run-meta">
                    <StateBadge state={run.state} />
                    <span className="muted">
                      {new Date(run.updated_at).toLocaleString()}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
