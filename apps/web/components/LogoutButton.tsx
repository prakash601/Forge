"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { createApiClient } from "@/lib/api";

/**
 * Log out (Issue #022): clears the server session cookie, then returns
 * to the dashboard (which re-renders logged out).
 */
export function LogoutButton({
  apiBaseUrl,
  email,
}: {
  apiBaseUrl: string;
  email: string;
}) {
  const router = useRouter();
  const [pending, setPending] = useState(false);

  const logout = async () => {
    setPending(true);
    try {
      await createApiClient(apiBaseUrl).logout();
    } catch {
      // Clearing failed server-side; still leave the gated UI.
    } finally {
      router.push("/");
      router.refresh();
    }
  };

  return (
    <span className="userbox">
      <span className="muted">{email}</span>{" "}
      <button
        type="button"
        className="btn"
        disabled={pending}
        onClick={() => void logout()}
      >
        {pending ? "Logging out…" : "Log out"}
      </button>
    </span>
  );
}
