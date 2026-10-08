// POST /api/share {repo, user} → invite a GitHub user to one of your items (read-only in organizations).
import { requireUser, json, body, guarded } from "../lib/http.js";
import { share } from "../lib/github.js";

export async function POST(request) {
  const { session, response, finish } = await requireUser(request, { change: true });
  if (response) return response;
  return finish(await guarded(async () => {
    const { repo, user } = await body(request);
    return json(await share(session.token, repo, user));
  }));
}
