// GET /api/access?repo=owner/name → who can see one of your items.
import { requireUser, json, guarded } from "../lib/http.js";
import { access } from "../lib/github.js";

export async function GET(request) {
  const { session, response, finish } = await requireUser(request);
  if (response) return response;
  return finish(await guarded(async () => json(await access(session.token, new URL(request.url).searchParams.get("repo")))));
}
