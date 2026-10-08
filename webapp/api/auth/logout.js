// POST /api/auth/logout → forget the session.
import { clearSessionCookie } from "../../lib/session.js";
import { json } from "../../lib/http.js";

export async function POST(request) {
  return json({ ok: true }, 200, { "Set-Cookie": clearSessionCookie(request) });
}
