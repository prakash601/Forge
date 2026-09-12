import Link from "next/link";

import { createApiClient, type ReadyResponse, type Run } from "@/lib/api";
import { StateBadge } from "@/components/RunLive";

interface HomePageProps {
  searchParams: { [key: string]: string | string[] | undefined };
}

function apiBaseUrl(searchParams: HomePageProps["searchParams"]): string {
  return typeof searchParams.api === "string" && searchParams.api
    ? searchParams.api
    : (process.env.API_BASE_URL ?? "http://localhost:8000");
}

async function checkBackend(baseUrl: string): Promise<ReadyResponse | null> {
  try {
    return await createApiClient(baseUrl).getReady();
  } catch {
    return null;
  }
}

async function loadRuns(baseUrl: string): Promise<{ runs: Run[]; total: number } | null> {
  try {
    const { runs, total } = await createApiClient(baseUrl).listRuns(20, 0);
    return { runs, total };
  } catch {
    return null;
  }
}

export default async function Home({ searchParams }: HomePageProps) {
  const baseUrl = apiBaseUrl(searchParams);
  const ready = await checkBackend(baseUrl);
  const listing = await loadRuns(baseUrl);

  const isConnected = ready?.status === "ok";
  const statusClass = isConnected ? "connected" : "disconnected";
  const statusText = isConnected
    ? `Connected to API (v${ready?.version ?? "?"})`
    : `Cannot reach API at ${baseUrl}`;

  return (
    <main className="dashboard">
      <span className="phase">
        <span className="dot" />
        Phase 3 — MVP Polish &amp; UX
      </span>
      <h1>Forge</h1>
      <div className={`status ${statusClass}`}>
        <span className="indicator" />
        <span>{statusText}</span>
      </div>

      <section className="panel runs">
        <h2>Runs{listing ? ` (${listing.total})` : ""}</h2>
        {!listing ? (
          <p className="muted">Could not load runs from the API.</p>
        ) : listing.runs.length === 0 ? (
          <p className="muted">No runs yet. Create one via POST /api/v1/runs.</p>
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
