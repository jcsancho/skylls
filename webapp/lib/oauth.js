// GitHub OAuth app: exchanging a sign-in code, and renewing expiring tokens with the refresh token.

const OAUTH = () => process.env.GITHUB_OAUTH_BASE || "https://github.com";

/** POST to GitHub's token endpoint (code exchange or refresh). Throws on failure. */
export async function exchange(params) {
  const res = await fetch(OAUTH() + "/login/oauth/access_token", {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: process.env.GITHUB_CLIENT_ID,
      client_secret: process.env.GITHUB_CLIENT_SECRET,
      ...params,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!data.access_token) throw new Error(data.error_description || "GitHub didn't return a token");
  return data;
}

/** The token part of a session. With "Expire user access tokens" GitHub sends a refresh token too. */
export function tokens(data, previous = {}) {
  return {
    token: data.access_token,
    refresh: data.refresh_token || previous.refresh || "",
    expiresAt: data.expires_in ? Math.floor(Date.now() / 1000) + Number(data.expires_in) : 0,
  };
}

/** A session whose access token expires within 5 minutes needs renewing (if it can be renewed). */
export function needsRefresh(session) {
  return Boolean(session.refresh && session.expiresAt && session.expiresAt - 300 < Date.now() / 1000);
}

export async function refresh(session) {
  const data = await exchange({ grant_type: "refresh_token", refresh_token: session.refresh });
  return { ...session, ...tokens(data, session) };
}
