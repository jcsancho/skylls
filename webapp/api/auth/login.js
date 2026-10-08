// GET /api/auth/login → GitHub's sign-in page (OAuth app), with a state cookie against CSRF.
import { stateCookie } from "../../lib/session.js";

export const SCOPES = "repo read:org"; // read your skylls repos (private) and manage who they're shared with

export function origin(request) {
  return process.env.APP_URL || new URL(request.url).origin;
}

export async function GET(request) {
  const clientId = process.env.GITHUB_CLIENT_ID;
  if (!clientId) return new Response("GITHUB_CLIENT_ID is not set", { status: 500 });
  const state = Buffer.from(crypto.getRandomValues(new Uint8Array(16))).toString("hex");
  const url = new URL((process.env.GITHUB_OAUTH_BASE || "https://github.com") + "/login/oauth/authorize");
  url.searchParams.set("client_id", clientId);
  url.searchParams.set("redirect_uri", origin(request) + "/api/auth/callback");
  url.searchParams.set("scope", SCOPES);
  url.searchParams.set("state", state);
  url.searchParams.set("allow_signup", "true");
  return new Response(null, {
    status: 302,
    headers: { Location: url.toString(), "Set-Cookie": stateCookie(request, state), "Cache-Control": "no-store" },
  });
}
