import { cookies } from "next/headers";

/**
 * Session cookie for server-to-API calls (Issue #022).
 *
 * Server components cannot use the browser jar, so they forward the
 * httpOnly session cookie explicitly. Returns the `name=value` pair
 * (or undefined when logged out) for `createApiClient(baseUrl, { cookie })`.
 */
export async function sessionCookie(): Promise<string | undefined> {
  const jar = await cookies();
  const session = jar.get("forge_session");
  return session === undefined ? undefined : `forge_session=${session.value}`;
}
