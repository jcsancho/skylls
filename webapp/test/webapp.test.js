// End-to-end tests of the webapp against a fake GitHub (node --test test/). No real GitHub, no network.
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { fakeGitHub } from "./fake-github.js";
import { seal, unseal } from "../lib/session.js";
import { parseChangelog, summaryFrom, itemOf } from "../lib/github.js";

const gh = fakeGitHub();
let app;

const CHANGELOG = `# pdf

> Fills in PDF forms for you.

Created by Alice (@alice) on 2026-10-01.

## 1.1.0 — 2026-10-07 — Alice

Handles scans

## 1.0.0 — 2026-10-01 — Alice

First version
`;

before(async () => {
  const base = await gh.start();
  Object.assign(process.env, {
    GITHUB_API: base, GITHUB_OAUTH_BASE: base, SESSION_SECRET: "x".repeat(40),
    GITHUB_CLIENT_ID: "cid", GITHUB_CLIENT_SECRET: "secret",
  });
  delete process.env.APP_URL;
  gh.addRepo("alice/skylls-skill-pdf", { topics: ["skylls", "skylls-skill", "docs"], files: { "CHANGELOG.md": CHANGELOG, "SKILL.md": "---\nname: pdf\ndescription: PDF forms\n---\n" } });
  gh.addRepo("alice/skylls-agent-btc", { topics: ["skylls", "skylls-agent"], files: { "CLAUDE.md": "# btc agent that tracks bitcoin prices\n" } });
  gh.addRepo("aliceco/skill-tax", { topics: ["skylls", "skylls-skill"], files: { "SKILL.md": "---\ndescription: Tax helper for invoices\n---\n" } });
  gh.addRepo("aliceco/agent-foo", { topics: [] }); // short name without the skylls topic: not an item
  gh.addRepo("alice/random-repo", { topics: [] }); // not a skylls repo
  gh.addRepo("carol/skylls-skill-notes", { topics: ["skylls", "skylls-skill"], files: { "SKILL.md": "---\ndescription: Notes\n---\n" } });
  gh.state.repos["carol/skylls-skill-notes"].collabs.bob = "push";
  gh.state.repos["alice/skylls-skill-pdf"].issues.push({ number: 1, title: "Support Excel", state: "open", author: "bob", comments: [] });
  gh.state.invites.push({ id: 99, repo: "alice/skylls-skill-pdf", invitee: "bob", inviter: "alice", permission: "push" });
  ({ app } = await import("../dev.js"));
});

after(() => gh.stop());

async function call(path, { user, method = "GET", body, header = true, cookie } = {}) {
  const headers = new Headers();
  if (user) headers.set("cookie", `skylls_session=${encodeURIComponent(await seal({ token: `tok-${user}`, login: user }))}`);
  if (cookie) headers.set("cookie", cookie);
  if (body !== undefined) headers.set("content-type", "application/json");
  if (body !== undefined && header) headers.set("x-skylls", "1");
  const res = await app(new Request("http://localhost" + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) }));
  const text = await res.text();
  let data = text;
  try { data = JSON.parse(text); } catch {}
  return { status: res.status, data, headers: res.headers };
}

test("changelog, summary and repo names parse like the CLI", () => {
  const log = parseChangelog(CHANGELOG);
  assert.equal(log.about, "Fills in PDF forms for you.");
  assert.equal(log.createdBy, "Alice");
  assert.deepEqual(log.entries.map((e) => e.version), ["1.1.0", "1.0.0"]);
  assert.equal(log.entries[0].notes, "Handles scans");
  assert.equal(summaryFrom("---\nname: x\ndescription: Does a thing\n---\n"), "Does a thing");
  assert.equal(summaryFrom("# Title\n\nThis agent tracks prices every day.\n"), "This agent tracks prices every day.");
  assert.deepEqual(itemOf("o/skylls-agent-btc"), { kind: "agents", name: "btc" });
  assert.deepEqual(itemOf("org/swarm-app-ideas"), { kind: "swarms", name: "app-ideas" });
  assert.equal(itemOf("o/skill-x", false), null);
  assert.equal(itemOf("o/random"), null);
});

test("pages, 404 and 405", async () => {
  assert.match((await call("/")).data, /one private repo at a time/);
  assert.match((await call("/dashboard")).data, /Sign in with GitHub/);
  assert.equal((await call("/nope")).status, 404);
  assert.equal((await call("/api/nope")).status, 404);
  assert.equal((await call("/api/share")).status, 405);
  assert.equal((await call("/api/../lib/session")).status, 404);
});

test("sign in: redirect to GitHub with state, then the callback sets the session", async () => {
  const login = await call("/api/auth/login");
  assert.equal(login.status, 302);
  const loc = new URL(login.headers.get("location"));
  assert.equal(loc.pathname, "/login/oauth/authorize");
  assert.equal(loc.searchParams.get("client_id"), "cid");
  assert.equal(loc.searchParams.get("scope"), "repo read:org");
  assert.equal(loc.searchParams.get("redirect_uri"), "http://localhost/api/auth/callback");
  const state = loc.searchParams.get("state");
  assert.match(login.headers.get("set-cookie"), new RegExp(`skylls_oauth_state=${state}; Path=/; HttpOnly; SameSite=Lax`));

  const bad = await call(`/api/auth/callback?code=good-code&state=wrong`, { cookie: `skylls_oauth_state=${state}` });
  assert.match(bad.headers.get("location"), /\/dashboard\?error=/);

  const badCode = await call(`/api/auth/callback?code=nope&state=${state}`, { cookie: `skylls_oauth_state=${state}` });
  assert.match(decodeURIComponent(badCode.headers.get("location")), /The code is incorrect/);

  const ok = await call(`/api/auth/callback?code=good-code&state=${state}`, { cookie: `skylls_oauth_state=${state}` });
  assert.equal(ok.headers.get("location"), "http://localhost/dashboard");
  const session = ok.headers.getSetCookie().find((c) => c.startsWith("skylls_session="));
  assert.ok(session && session.includes("HttpOnly") && session.includes("SameSite=Lax"));
  assert.ok(!session.includes("tok-alice"), "the token must not be readable in the cookie");
  const me = await call("/api/me", { cookie: session.split(";")[0] });
  assert.equal(me.data.login, "alice");
});

test("no session or a tampered one: 401", async () => {
  assert.equal((await call("/api/items")).status, 401);
  assert.equal((await call("/api/items", { cookie: "skylls_session=abc.def" })).status, 401);
});

test("alice sees her own items (account + organization), not other repos", async () => {
  const { status, data } = await call("/api/items", { user: "alice" });
  assert.equal(status, 200);
  const mine = data.items.filter((i) => i.mine).map((i) => `${i.kind}:${i.repo}`);
  assert.deepEqual(mine.sort(), ["agents:alice/skylls-agent-btc", "skills:alice/skylls-skill-pdf", "skills:aliceco/skill-tax"]);
  const pdf = data.items.find((i) => i.name === "pdf");
  assert.equal(pdf.version, "1.1.0");
  assert.equal(pdf.folder, "docs");
  assert.equal(pdf.summary, "Fills in PDF forms for you.");
  assert.equal(pdf.suggestions[0].title, "Support Excel");
  assert.equal(data.items.find((i) => i.name === "btc").summary, "btc agent that tracks bitcoin prices");
  assert.equal(data.items.find((i) => i.name === "tax").ownerIsOrg, true);
});

test("bob: pending invite, shared items, accepting", async () => {
  let { data } = await call("/api/items", { user: "bob" });
  assert.deepEqual(data.invites.map((i) => [i.id, i.name, i.from]), [[99, "pdf", "alice"]]);
  assert.deepEqual(data.items.map((i) => [i.repo, i.mine]), [["carol/skylls-skill-notes", false]]);
  assert.equal((await call("/api/invite", { user: "bob", method: "POST", body: { id: 12345 } })).status, 404);
  const ok = await call("/api/invite", { user: "bob", method: "POST", body: { id: 99 } });
  assert.equal(ok.data.accepted.name, "pdf");
  ({ data } = await call("/api/items", { user: "bob" }));
  assert.ok(data.items.some((i) => i.repo === "alice/skylls-skill-pdf" && !i.mine));
  assert.equal(data.invites.length, 0);
});

test("share: CSRF header required, validation, personal vs organization access", async () => {
  assert.equal((await call("/api/share", { user: "alice", method: "POST", body: { repo: "alice/skylls-skill-pdf", user: "carol" }, header: false })).status, 403);
  assert.equal((await call("/api/share", { user: "alice", method: "POST", body: { repo: "alice/skylls-skill-pdf", user: "bad user!" } })).status, 400);
  assert.equal((await call("/api/share", { user: "alice", method: "POST", body: { repo: "alice/random-repo", user: "carol" } })).status, 400);
  const personal = await call("/api/share", { user: "alice", method: "POST", body: { repo: "alice/skylls-skill-pdf", user: "@carol" } });
  assert.deepEqual(personal.data, { invited: true, login: "carol", access: "access" });
  const org = await call("/api/share", { user: "alice", method: "POST", body: { repo: "aliceco/skill-tax", user: "bob" } });
  assert.equal(org.data.access, "read-only");
  assert.equal(gh.state.invites.find((i) => i.repo === "aliceco/skill-tax").permission, "pull");
  const again = await call("/api/share", { user: "alice", method: "POST", body: { repo: "alice/skylls-skill-pdf", user: "bob" } });
  assert.equal(again.data.invited, false); // bob already has access
  const notOwner = await call("/api/share", { user: "bob", method: "POST", body: { repo: "alice/skylls-skill-pdf", user: "carol" } });
  assert.equal(notOwner.status, 403);
});

test("access and unshare", async () => {
  let { data } = await call("/api/access?repo=alice/skylls-skill-pdf", { user: "alice" });
  assert.deepEqual(data.people.map((p) => p.login), ["bob"]);
  assert.deepEqual(data.pending.map((p) => p.login), ["carol"]);
  await call("/api/unshare", { user: "alice", method: "POST", body: { repo: "alice/skylls-skill-pdf", user: "carol" } });
  await call("/api/unshare", { user: "alice", method: "POST", body: { repo: "alice/skylls-skill-pdf", user: "bob" } });
  ({ data } = await call("/api/access?repo=alice/skylls-skill-pdf", { user: "alice" }));
  assert.deepEqual([data.people, data.pending], [[], []]);
  const items = await call("/api/items", { user: "bob" });
  assert.ok(!items.data.items.some((i) => i.repo === "alice/skylls-skill-pdf"), "bob lost access");
});

test("answering a suggestion closes it with a comment; others can't", async () => {
  const denied = await call("/api/suggestion", { user: "bob", method: "POST", body: { repo: "alice/skylls-skill-pdf", number: 1, accept: true } });
  assert.equal(denied.status, 404); // bob can't even see the repo any more
  const ok = await call("/api/suggestion", { user: "alice", method: "POST", body: { repo: "alice/skylls-skill-pdf", number: 1, accept: true, note: "Done in 1.2.0" } });
  assert.deepEqual(ok.data, { closed: 1, accept: true });
  const issue = gh.state.repos["alice/skylls-skill-pdf"].issues[0];
  assert.deepEqual([issue.state, issue.reason, issue.comments], ["closed", "completed", ["Done in 1.2.0"]]);
  assert.equal((await call("/api/items", { user: "alice" })).data.items.find((i) => i.name === "pdf").suggestions.length, 0);
});

test("sessions last 30 days and keep GitHub's refresh token", async () => {
  const login = await call("/api/auth/login");
  const state = new URL(login.headers.get("location")).searchParams.get("state");
  const ok = await call(`/api/auth/callback?code=good-code&state=${state}`, { cookie: `skylls_oauth_state=${state}` });
  const cookie = ok.headers.getSetCookie().find((c) => c.startsWith("skylls_session="));
  assert.match(cookie, /Max-Age=2592000/);
  const session = await unseal(decodeURIComponent(cookie.split(";")[0].split("=")[1]));
  assert.ok(session.refresh.startsWith("rt-alice-"));
  assert.ok(Math.abs(session.expiresAt - (Date.now() / 1000 + 28800)) < 60);
});

test("an expired GitHub token is renewed automatically (and the cookie updated)", async () => {
  gh.state.refresh["rt-old"] = "alice";
  const before = gh.state.refreshed;
  const expired = await seal({ token: "tok-alice", login: "alice", refresh: "rt-old", expiresAt: Math.floor(Date.now() / 1000) - 10 }); // gitleaks:allow (fake test token)
  const res = await call("/api/items", { cookie: `skylls_session=${encodeURIComponent(expired)}` });
  assert.equal(res.status, 200);
  assert.equal(gh.state.refreshed, before + 1);
  const renewed = await unseal(decodeURIComponent(res.headers.get("set-cookie").split(";")[0].split("=")[1]));
  assert.notEqual(renewed.refresh, "rt-old");
  assert.ok(renewed.expiresAt > Date.now() / 1000 + 28000);
  assert.ok(!("rt-old" in gh.state.refresh), "refresh tokens are single-use");
});

test("a revoked refresh token signs you out; non-expiring tokens are left alone", async () => {
  const revoked = await seal({ token: "tok-alice", login: "alice", refresh: "rt-revoked", expiresAt: 1 }); // gitleaks:allow (fake test token)
  const res = await call("/api/me", { cookie: `skylls_session=${encodeURIComponent(revoked)}` });
  assert.equal(res.status, 401);
  assert.match(res.data.error, /sign in again/);
  assert.match(res.headers.get("set-cookie"), /skylls_session=; .*Max-Age=0/);
  const plain = await call("/api/me", { user: "alice" }); // no refresh token: nothing to renew
  assert.equal(plain.status, 200);
  assert.equal(plain.headers.get("set-cookie"), null);
});

test("docs page", async () => {
  const res = await call("/docs");
  assert.equal(res.status, 200);
  assert.match(res.data, /How to use skylls/);
  assert.match(res.data, /id="reference"/);
});

test("privacy and terms pages", async () => {
  assert.match((await call("/privacy")).data, /has no database and doesn't store your data/);
  assert.match((await call("/terms")).data, /Apache License 2\.0/);
});

test("Marketplace webhook: signature checked, events acknowledged", async () => {
  const { signature } = await import("../api/marketplace.js");
  const hook = async (payload, sig, event = "marketplace_purchase") => {
    const res = await app(new Request("http://localhost/api/marketplace", {
      method: "POST", body: payload,
      headers: { "x-github-event": event, ...(sig ? { "x-hub-signature-256": sig } : {}) },
    }));
    return { status: res.status, data: await res.json() };
  };
  const payload = JSON.stringify({ action: "purchased", marketplace_purchase: { account: { login: "bob" }, plan: { name: "Free" } } });
  delete process.env.MARKETPLACE_WEBHOOK_SECRET;
  assert.equal((await hook(payload, "sha256=x")).status, 503);
  process.env.MARKETPLACE_WEBHOOK_SECRET = "hook-secret-for-tests"; // gitleaks:allow (test value)
  assert.equal((await hook(payload)).status, 401);
  assert.equal((await hook(payload, signature("wrong", payload))).status, 401);
  const ok = await hook(payload, signature("hook-secret-for-tests", payload));
  assert.deepEqual(ok.data, { ok: true, event: "marketplace_purchase", action: "purchased" });
  const ping = await hook("{}", signature("hook-secret-for-tests", "{}"), "ping");
  assert.equal(ping.data.event, "ping");
});

test("logout clears the cookie", async () => {
  const res = await call("/api/auth/logout", { user: "alice", method: "POST", body: {} });
  assert.match(res.headers.get("set-cookie"), /skylls_session=; Path=\/; HttpOnly; SameSite=Lax; Max-Age=0/);
});
