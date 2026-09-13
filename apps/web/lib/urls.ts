/**
 * Server vs browser API base URLs.
 *
 * In Docker Compose the web server reaches the API as `http://api:8000`
 * (compose DNS), but the browser on the laptop reaches it as
 * `http://localhost:8000`. A single `API_BASE_URL` cannot serve both,
 * so server components use `API_BASE_URL` and client components receive
 * the public URL as a prop.
 */
export function serverApiBaseUrl(searchParams: {
  [key: string]: string | string[] | undefined;
}): string {
  if (typeof searchParams.api === "string" && searchParams.api) {
    return searchParams.api;
  }
  return process.env.API_BASE_URL ?? "http://localhost:8000";
}

export function publicApiBaseUrl(serverUrl: string): string {
  return (
    process.env.NEXT_PUBLIC_API_BASE_URL ?? serverUrl ?? "http://localhost:8000"
  );
}
