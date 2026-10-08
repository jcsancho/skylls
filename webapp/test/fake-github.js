// A small fake GitHub (REST + the two GraphQL queries the webapp makes + OAuth token exchange).
// Users are identified by their token: "tok-<login>". Nothing here touches the real GitHub.
import { createServer } from "node:http";

export function fakeGitHub() {
  const state = {
    users: { alice: "User", bob: "User", carol: "User", aliceco: "Organization" },
    orgAdmins: { aliceco: ["alice"] },
    repos: {}, // "owner/name" -> {private, topics, collabs:{login:perm}, files:{}, issues:[]}
    invites: [], // {id, repo, invitee, inviter, permission}
    next: 1,
    calls: [],
    refresh: {}, // refresh token -> login
    refreshed: 0,
  };

  function addRepo(full, { topics = ["skylls"], files = {}, isPrivate = true } = {}) {
    state.repos[full] = { private: isPrivate, topics, collabs: {}, files, issues: [] };
  }

  const login = (req) => (req.headers.authorization || "").replace("Bearer tok-", "");
  const isAdmin = (who, full) => {
    const owner = full.split("/")[0];
    return owner === who || (state.orgAdmins[owner] || []).includes(who);
  };
  const canSee = (who, full) => state.repos[full] && (isAdmin(who, full) || who in state.repos[full].collabs);

  function node(who, full) {
    const r = state.repos[full];
    const [owner, name] = full.split("/");
    const blob = (path) => (path in r.files ? { text: r.files[path] } : null);
    return {
      name, owner: { login: owner, __typename: state.users[owner] }, isPrivate: r.private,
      url: `https://github.com/${full}`, viewerPermission: isAdmin(who, full) ? "ADMIN" : r.collabs[who] === "pull" ? "READ" : "WRITE",
      repositoryTopics: { nodes: r.topics.map((t) => ({ topic: { name: t } })) },
      changelog: blob("CHANGELOG.md"), skillmd: blob("SKILL.md"), claudemd: blob("CLAUDE.md"), agentsmd: blob("AGENTS.md"),
      issues: { nodes: r.issues.filter((i) => i.state === "open").map((i) => ({
        number: i.number, title: i.title, url: `https://github.com/${full}/issues/${i.number}`,
        createdAt: "2026-10-08T10:00:00Z", author: { login: i.author },
      })) },
    };
  }

  async function handle(req, body) {
    const url = new URL(req.url, "http://x");
    const who = login(req);
    const send = (status, data) => ({ status, data });
    state.calls.push(`${req.method} ${url.pathname}`);
    if (url.pathname === "/login/oauth/authorize") { // the user "approves" at once
      const back = new URL(url.searchParams.get("redirect_uri"));
      back.searchParams.set("code", "good-code");
      back.searchParams.set("state", url.searchParams.get("state"));
      return { status: 302, location: back.toString() };
    }
    if (url.pathname === "/login/oauth/access_token") { // expiring tokens: 8 h + a one-time refresh token
      const issue = (owner) => {
        const refresh = `rt-${owner}-${state.next++}`;
        state.refresh[refresh] = owner;
        return send(200, { access_token: `tok-${owner}`, refresh_token: refresh, expires_in: 28800 }); // gitleaks:allow (fake)
      };
      if (body.grant_type === "refresh_token") {
        const owner = state.refresh[body.refresh_token];
        if (!owner) return send(200, { error: "bad_refresh_token", error_description: "The refresh token passed is incorrect or expired." });
        delete state.refresh[body.refresh_token];
        state.refreshed++;
        return issue(owner);
      }
      return body.code === "good-code" ? issue("alice") : send(200, { error: "bad_verification_code", error_description: "The code is incorrect" });
    }
    if (!state.users[who]) return send(401, { message: "Bad credentials" });
    if (url.pathname === "/user") return send(200, { login: who, avatar_url: `https://avatars/${who}` });
    let m;
    if ((m = url.pathname.match(/^\/users\/([^/]+)$/))) return send(200, { login: m[1], type: state.users[m[1]] || "User" });
    if (url.pathname === "/graphql") {
      const q = body.query;
      if (/\bviewer \{/.test(q)) {
        const orgsToo = /ownerAffiliations:[^)]*ORGANIZATION_MEMBER/.test(q); // GitHub's default leaves org repos out
        const nodes = Object.keys(state.repos)
          .filter((f) => canSee(who, f) && (orgsToo || state.users[f.split("/")[0]] !== "Organization")).map((f) => ({ name: f.split("/")[1], owner: { login: f.split("/")[0] } }));
        return send(200, { data: { viewer: { login: who, repositories: { nodes, pageInfo: { hasNextPage: false, endCursor: null } } } } });
      }
      const data = {};
      for (const [, alias, owner, name] of q.matchAll(/(r\d+): repository\(owner: "([^"]+)", name: "([^"]+)"\)/g)) {
        data[alias] = canSee(who, `${owner}/${name}`) ? node(who, `${owner}/${name}`) : null;
      }
      return send(200, { data });
    }
    if (url.pathname === "/user/repository_invitations") {
      return send(200, state.invites.filter((i) => i.invitee === who).map((i) => ({ id: i.id, repository: { full_name: i.repo }, inviter: { login: i.inviter } })));
    }
    if ((m = url.pathname.match(/^\/user\/repository_invitations\/(\d+)$/)) && req.method === "PATCH") {
      const inv = state.invites.find((i) => i.id === Number(m[1]) && i.invitee === who);
      if (!inv) return send(404, { message: "Not Found" });
      state.repos[inv.repo].collabs[who] = inv.permission;
      state.invites = state.invites.filter((i) => i !== inv);
      return send(204, null);
    }
    if ((m = url.pathname.match(/^\/repos\/([^/]+\/[^/]+)\/(.*)$/))) {
      const [, full, rest] = m;
      const r = state.repos[full];
      if (!r || !canSee(who, full)) return send(404, { message: "Not Found" });
      const admin = isAdmin(who, full);
      if (rest === "collaborators") {
        return send(200, Object.entries(r.collabs).map(([l, p]) => ({ login: l, role_name: p === "pull" ? "read" : "write", avatar_url: "" })));
      }
      if (rest === "invitations") return send(200, state.invites.filter((i) => i.repo === full).map((i) => ({ id: i.id, invitee: { login: i.invitee } })));
      let n;
      if ((n = rest.match(/^invitations\/(\d+)$/)) && req.method === "DELETE") {
        if (!admin) return send(403, { message: "Must have admin rights" });
        state.invites = state.invites.filter((i) => i.id !== Number(n[1]));
        return send(204, null);
      }
      if ((n = rest.match(/^collaborators\/([^/]+)$/))) {
        if (!admin) return send(403, { message: "Must have admin rights to Repository." });
        const user = n[1];
        if (req.method === "PUT") {
          if (user in r.collabs) return send(204, null);
          const inv = { id: state.next++, repo: full, invitee: user, inviter: who, permission: body.permission || "push" };
          state.invites.push(inv);
          return send(201, { id: inv.id });
        }
        if (req.method === "DELETE") {
          if (!(user in r.collabs)) return send(404, { message: "Not Found" });
          delete r.collabs[user];
          return send(204, null);
        }
      }
      if ((n = rest.match(/^issues\/(\d+)(\/comments)?$/))) {
        const issue = r.issues.find((i) => i.number === Number(n[1]));
        if (!issue) return send(404, { message: "Not Found" });
        if (!admin) return send(403, { message: "Must have admin rights" });
        if (n[2]) { issue.comments.push(body.body); return send(201, { id: 1 }); }
        Object.assign(issue, { state: body.state, reason: body.state_reason });
        return send(200, { number: issue.number, state: issue.state });
      }
    }
    return send(404, { message: `fake: no route ${req.method} ${url.pathname}` });
  }

  const server = createServer(async (req, res) => {
    const chunks = [];
    for await (const c of req) chunks.push(c);
    const text = Buffer.concat(chunks).toString();
    const { status, data, location } = await handle(req, text ? JSON.parse(text) : {});
    res.writeHead(status, location ? { Location: location } : { "Content-Type": "application/json" });
    res.end(status === 204 ? "" : JSON.stringify(data));
  });

  return {
    state, addRepo,
    start: () => new Promise((resolve) => server.listen(0, () => resolve(`http://127.0.0.1:${server.address().port}`))),
    stop: () => new Promise((resolve) => server.close(resolve)),
  };
}
