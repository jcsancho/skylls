// POST /api/marketplace ← GitHub Marketplace webhook (ping, marketplace_purchase events).
// skylls is free and has no database, so there is nothing to provision: verify GitHub's signature
// (X-Hub-Signature-256, HMAC-SHA256 of the raw body with MARKETPLACE_WEBHOOK_SECRET) and acknowledge.
import { createHmac, timingSafeEqual } from "node:crypto";
import { json, error } from "../lib/http.js";

export function signature(secret, payload) {
  return "sha256=" + createHmac("sha256", secret).update(payload).digest("hex");
}

export async function POST(request) {
  const secret = process.env.MARKETPLACE_WEBHOOK_SECRET;
  if (!secret) return error("MARKETPLACE_WEBHOOK_SECRET is not set", 503);
  const payload = Buffer.from(await request.arrayBuffer());
  const given = Buffer.from(request.headers.get("x-hub-signature-256") || "");
  const expected = Buffer.from(signature(secret, payload));
  if (given.length !== expected.length || !timingSafeEqual(given, expected)) return error("Bad signature", 401);
  const event = request.headers.get("x-github-event") || "";
  let data = {};
  try {
    data = JSON.parse(payload.toString("utf8"));
  } catch {
    return error("Bad JSON", 400);
  }
  if (event === "marketplace_purchase") {
    const account = data.marketplace_purchase?.account?.login || "?";
    const plan = data.marketplace_purchase?.plan?.name || "?";
    console.log(`marketplace: ${data.action} by ${account} (${plan})`); // shows in Vercel's logs; nothing stored
  }
  return json({ ok: true, event, action: data.action || null });
}
