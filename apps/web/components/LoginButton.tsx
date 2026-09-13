"use client";

import { useEffect, useState } from "react";

import { createApiClient } from "@/lib/api";

/**
 * GitHub login entry (Issue #022) + local dev login.
 *
 * Navigates the browser to the API login endpoint with `next` pointing
 * back here; the API round-trips it through OAuth `state` and redirects
 * back authenticated (session cookie set, httpOnly).
 *
 * Dev login (local only): `POST /api/v1/auth/dev-login` mints a session
 * for any email without GitHub OAuth. The API returns 403 in production.
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

export function DevLoginForm({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [email, setEmail] = useState("dev@local.test");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = email.trim();
    if (!trimmed || pending) return;
    setPending(true);
    setError(null);
    try {
      await createApiClient(apiBaseUrl).devLogin(trimmed);
      window.location.reload();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message.includes("403")
            ? "Dev login is disabled on this server (production)."
            : cause.message
          : String(cause),
      );
      setPending(false);
    }
  };

  return (
    <form className="dev-login" onSubmit={(event) => void submit(event)}>
      <label htmlFor="dev-login-email">Local dev login (no GitHub needed)</label>
      <input
        id="dev-login-email"
        type="email"
        value={email}
        maxLength={320}
        placeholder="you@local.test"
        onChange={(event) => void setEmail(event.target.value)}
      />
      {error ? (
        <p role="alert" className="error">
          {error}
        </p>
      ) : null}
      <button type="submit" className="btn" disabled={email.trim().length === 0 || pending}>
        {pending ? "Logging in…" : "Continue locally"}
      </button>
    </form>
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
        Forge runs are private to your account. Log in with GitHub, or continue
        locally on this machine (no OAuth needed).
      </p>
      <LoginButton apiBaseUrl={apiBaseUrl} />
      <hr />
      <DevLoginForm apiBaseUrl={apiBaseUrl} />
    </div>
  );
}
