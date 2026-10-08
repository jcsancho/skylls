// GET /api/me → who is signed in.
import { requireUser, json } from "../lib/http.js";

export async function GET(request) {
  const { session, response, finish } = await requireUser(request);
  if (response) return response;
  return finish(json({ login: session.login, avatar: session.avatar }));
}
