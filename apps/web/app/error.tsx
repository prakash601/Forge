"use client";

import Link from "next/link";

/**
 * Root error boundary (Issue #022): no dead screens on unexpected
 * failures — retry in place or return to the dashboard.
 */
export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="dashboard">
      <h1>Something went wrong</h1>
      <p className="muted">{error.message}</p>
      <p>
        <button type="button" className="btn primary" onClick={() => reset()}>
          Try again
        </button>{" "}
        <Link className="btn" href="/">
          Back to runs
        </Link>
      </p>
    </main>
  );
}
