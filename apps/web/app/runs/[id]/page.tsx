import Link from "next/link";
import { notFound } from "next/navigation";

import { ApiError, createApiClient } from "@/lib/api";
import { RunLive } from "@/components/RunLive";

interface RunPageProps {
  params: Promise<{ id: string }>;
  searchParams: { [key: string]: string | string[] | undefined };
}

export default async function RunPage({ params, searchParams }: RunPageProps) {
  const { id } = await params;
  const baseUrl =
    typeof searchParams.api === "string" && searchParams.api
      ? searchParams.api
      : (process.env.API_BASE_URL ?? "http://localhost:8000");

  let details = null;
  try {
    details = await createApiClient(baseUrl).getRunDetails(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    throw error;
  }

  return (
    <main className="dashboard">
      <nav className="crumbs">
        <Link href="/">Runs</Link>
        <span className="muted">/</span>
        <span className="mono">{id.slice(0, 8)}</span>
      </nav>
      <h1 className="detail-title">Run</h1>
      <RunLive apiBaseUrl={baseUrl} runId={id} initial={details} />
    </main>
  );
}
