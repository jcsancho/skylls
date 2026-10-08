// POST /api/unshare {repo, user} → revoke access (or cancel a pending invitation).
import { requireUser, json, body, guarded } from "../lib/http.js";
import { unshare } from "../lib/github.js";

export async function POST(request) {
  const { session, response, finish } = await requireUser(request, { change: true });
  if (response) return response;
  return finish(await guarded(async () => {
    const { repo, user } = await body(request);
    return json(await unshare(session.token, repo, user));
  }));
}
