// GET /api/auth/callback?code&state → exchange the code for a token, keep it in the session cookie.
// With "Expire user access tokens" on the OAuth app, GitHub also sends a refresh token: the session
// keeps it and renews the 8-hour access token automatically (see lib/http.js requireUser).
import { clearStateCookie, readState, sessionCookie } from "../../lib/session.js";
import { gh } from "../../lib/github.js";
import { exchange, tokens } from "../../lib/oauth.js";
import { origin } from "./login.js";

function back(request, query, cookies) {
  const headers = new Headers({ Location: origin(request) + "/dashboard" + query, "Cache-Control": "no-store" });
  for (const c of cookies) headers.append("Set-Cookie", c);
  return new Response(null, { status: 302, headers });
}

export async function GET(request) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const clear = clearStateCookie(request);
  if (!code || !state || state !== readState(request)) {
    return back(request, "?error=" + encodeURIComponent("Sign-in expired, please try again."), [clear]);
  }
  try {
    const data = await exchange({ code, redirect_uri: origin(request) + "/api/auth/callback" });
    const session = tokens(data);
    const user = await gh(session.token, "/user");
    const cookie = await sessionCookie(request, { ...session, login: user.login, avatar: user.avatar_url });
    return back(request, "", [clear, cookie]);
  } catch (err) {
    return back(request, "?error=" + encodeURIComponent(err.message), [clear]);
  }
}
