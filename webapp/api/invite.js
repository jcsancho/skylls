// POST /api/invite {id} → accept a friend's invitation to one of their skylls items.
import { requireUser, json, body, guarded } from "../lib/http.js";
import { acceptInvite } from "../lib/github.js";

export async function POST(request) {
  const { session, response, finish } = await requireUser(request, { change: true });
  if (response) return response;
  return finish(await guarded(async () => {
    const { id } = await body(request);
    return json({ accepted: await acceptInvite(session.token, id) });
  }));
}
