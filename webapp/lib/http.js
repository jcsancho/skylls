import { clearSessionCookie, getSession, sessionCookie } from "./session.js";
import { needsRefresh, refresh } from "./oauth.js";

export function json(data, status = 200, headers = {}) {
  return Response.json(data, { status, headers: { "Cache-Control": "no-store", ...headers } });
}

export function error(message, status) {
  return json({ error: message }, status);
}

/** The session for an API call, or an error Response. An expiring GitHub token is renewed with the
 *  refresh token; `finish(response)` then attaches the updated session cookie.
 *  Changes also need the X-Skylls header (a custom header can't be sent cross-site without CORS,
 *  so this blocks CSRF). */
export async function requireUser(request, { change = false } = {}) {
  let session = await getSession(request);
  if (!session) return { response: error("Sign in first", 401) };
  if (change && request.headers.get("x-skylls") !== "1") return { response: error("Missing X-Skylls header", 403) };
  let cookie = null;
  if (needsRefresh(session)) {
    try {
      session = await refresh(session);
      cookie = await sessionCookie(request, session);
    } catch {
      return { response: json({ error: "Your GitHub sign-in expired. Please sign in again." }, 401,
                               { "Set-Cookie": clearSessionCookie(request) }) };
    }
  }
  const finish = (response) => {
    if (cookie) response.headers.append("Set-Cookie", cookie);
    return response;
  };
  return { session, finish };
}

export async function body(request) {
  try {
    return await request.json();
  } catch {
    return {};
  }
}

/** Run a handler, turning thrown errors into JSON (GitHub errors keep their status). */
export async function guarded(fn) {
  try {
    return await fn();
  } catch (err) {
    return error(err.message || "Something went wrong", err.status && err.status < 600 ? err.status : 500);
  }
}
