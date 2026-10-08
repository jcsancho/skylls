// GET /api/items → your skills/agents/swarms, what friends shared with you, and pending invitations.
import { requireUser, json, guarded } from "../lib/http.js";
import { catalog, pendingInvites } from "../lib/github.js";

export async function GET(request) {
  const { session, response, finish } = await requireUser(request);
  if (response) return response;
  return finish(await guarded(async () => {
    const [{ login, items }, invites] = await Promise.all([catalog(session.token), pendingInvites(session.token)]);
    return json({ login, items, invites });
  }));
}
