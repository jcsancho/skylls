// POST /api/suggestion {repo, number, accept, note} → answer a suggestion on one of your items.
import { requireUser, json, body, guarded } from "../lib/http.js";
import { answerSuggestion } from "../lib/github.js";

export async function POST(request) {
  const { session, response, finish } = await requireUser(request, { change: true });
  if (response) return response;
  return finish(await guarded(async () => {
    const { repo, number, accept, note } = await body(request);
    return json(await answerSuggestion(session.token, repo, number, Boolean(accept), note));
  }));
}
