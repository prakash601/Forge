"use client";

import { useMemo } from "react";

import { ApiError, createApiClient } from "@/lib/api";

/** Inline login hint for expired mid-session calls (401, Issue #022). */
export function SessionExpired({ apiBaseUrl }: { apiBaseUrl: string }) {
  const client = useMemo(() => createApiClient(apiBaseUrl), [apiBaseUrl]);
  return (
    <p role="alert" className="error">
      Session expired.{" "}
      <a href={client.loginUrl("/")}>Log in again</a>.
    </p>
  );
}

export function isUnauthorized(cause: unknown): boolean {
  return cause instanceof ApiError && cause.status === 401;
}
