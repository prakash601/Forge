import Link from "next/link";
import { notFound } from "next/navigation";

import { ApiError, createApiClient } from "@/lib/api";
import { sessionCookie } from "@/lib/session";
import { publicApiBaseUrl, serverApiBaseUrl } from "@/lib/urls";
import { LoginPrompt } from "@/components/LoginButton";
import { RunLive } from "@/components/RunLive";

interface RunPageProps {
  params: Promise<{ id: string }>;
  searchParams: { [key: string]: string | string[] | undefined };
}

export default async function RunPage({ params, searchParams }: RunPageProps) {
  const { id } = await params;
  const baseUrl = serverApiBaseUrl(searchParams);
  const browserBaseUrl = publicApiBaseUrl(baseUrl);
  const cookie = await sessionCookie();
  const client = createApiClient(baseUrl, { cookie });

  let details = null;
  try {
    details = await client.getRunDetails(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    if (error instanceof ApiError && error.status === 401) {
      return (
        <main className="dashboard">
          <nav className="crumbs">
            <Link href="/">Runs</Link>
          </nav>
          <LoginPrompt apiBaseUrl={browserBaseUrl} />
        </main>
      );
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
      <RunLive apiBaseUrl={browserBaseUrl} runId={id} initial={details} />
    </main>
  );
}
