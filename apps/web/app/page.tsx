import { createApiClient, type ReadyResponse } from "@/lib/api";

interface HomePageProps {
  searchParams: { [key: string]: string | string[] | undefined };
}

async function checkBackend(apiBaseUrl: string): Promise<ReadyResponse | null> {
  const client = createApiClient(apiBaseUrl);
  try {
    return await client.getReady();
  } catch {
    return null;
  }
}

export default async function Home({ searchParams }: HomePageProps) {
  const apiBaseUrl =
    typeof searchParams.api === "string" && searchParams.api
      ? searchParams.api
      : (process.env.API_BASE_URL ?? "http://localhost:8000");

  const ready = await checkBackend(apiBaseUrl);

  const isConnected = ready?.status === "ok";
  const statusClass = isConnected ? "connected" : "disconnected";
  const statusText = isConnected
    ? `Connected to API (v${ready?.version ?? "?"})`
    : `Cannot reach API at ${apiBaseUrl}`;

  return (
    <main>
      <span className="phase">
        <span className="dot" />
        Phase 0 — Repository Bootstrap
      </span>
      <h1>Forge</h1>
      <p className="tagline">
        An AI software engineering system that maintains persistent project
        context and owns the engineering loop. The product is not implemented
        yet — this page proves that the web, API, and database stack come up
        locally.
      </p>
      <div className={`status ${statusClass}`}>
        <span className="indicator" />
        <span>{statusText}</span>
      </div>
    </main>
  );
}
