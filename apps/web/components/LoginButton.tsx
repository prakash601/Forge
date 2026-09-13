"use client";

import { useEffect, useState } from "react";

import { createApiClient } from "@/lib/api";

/**
 * GitHub login entry (Issue #022).
 *
 * Navigates the browser to the API login endpoint with `next` pointing
 * back here; the API round-trips it through OAuth `state` and redirects
 * back authenticated (session cookie set, httpOnly).
 */
export function LoginButton({ apiBaseUrl }: { apiBaseUrl: string }) {
  // Client-only href (SSR renders "/" to avoid a hydration mismatch).
  const [href, setHref] = useState(createApiClient(apiBaseUrl).loginUrl("/"));
  useEffect(() => {
    setHref(createApiClient(apiBaseUrl).loginUrl(`${window.location.origin}/`));
  }, [apiBaseUrl]);

  return (
    <a className="btn primary" href={href}>
      Log in with GitHub
    </a>
  );
}

/**
 * Static login prompt for logged-out screens (server-renderable).
 */
export function LoginPrompt({ apiBaseUrl }: { apiBaseUrl: string }) {
  return (
    <div className="panel login-prompt">
      <h2>Log in</h2>
      <p className="muted">
        Forge runs are private to your account. Log in with GitHub to see your
        projects and runs.
      </p>
      <LoginButton apiBaseUrl={apiBaseUrl} />
    </div>
  );
}
