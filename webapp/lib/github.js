// GitHub access for the dashboard, with the signed-in user's token. Mirrors the skylls CLI
// (skylls/kinds.py): one private repo per item, named skill-x / agent-x / swarm-x in an organization
// or skylls-skill-x etc. on a personal account; short names only count with the 'skylls' topic.

const API = () => process.env.GITHUB_API || "https://api.github.com";
export const KINDS = { skill: "skills", agent: "agents", swarm: "swarms" };
const USER_RE = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$/;
const REPO_RE = /^[A-Za-z0-9-]+\/[A-Za-z0-9._-]+$/;

export class GitHubError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export async function gh(token, path, { method = "GET", body } = {}) {
  const res = await fetch(path.startsWith("http") ? path : API() + path, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "skylls-webapp",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new GitHubError(data?.message || `GitHub error ${res.status}`, res.status);
  return data;
}

export async function graphql(token, query, variables = {}) {
  const data = await gh(token, "/graphql", { method: "POST", body: { query, variables } });
  if (data?.errors?.length) throw new GitHubError(data.errors[0].message, 502);
  return data.data;
}

/** 'owner/skylls-agent-btc' or 'org/agent-btc' → {kind, name}; null for other repos. */
export function itemOf(repoName, short = true) {
  const base = repoName.split("/").pop();
  const formats = short ? ["skylls-%-", "%-"] : ["skylls-%-"];
  for (const fmt of formats) {
    for (const [one, kind] of Object.entries(KINDS)) {
      const prefix = fmt.replace("%", one);
      if (base.startsWith(prefix) && base.length > prefix.length) return { kind, name: base.slice(prefix.length) };
    }
  }
  return null;
}

const ENTRY_RE = /^## (\d+\.\d+\.\d+) — (\S+)(?: — (.*))?$/;
const CREATED_RE = /^Created by (.+?)(?: \(@([A-Za-z0-9-]+)\))? on (\d{4}-\d{2}-\d{2})\.$/;

/** The skylls CHANGELOG.md: plain summary, creator and versions (newest first). */
export function parseChangelog(text = "") {
  const log = { about: "", createdBy: "", created: "", entries: [] };
  for (const line of text.split("\n")) {
    const m = line.match(ENTRY_RE);
    if (m) log.entries.push({ version: m[1], date: m[2], author: m[3] || "", notes: [] });
    else if (log.entries.length) log.entries.at(-1).notes.push(line);
    else if (line.startsWith("> ") && !log.about) log.about = line.slice(2).trim();
    else {
      const c = line.match(CREATED_RE);
      if (c) [log.createdBy, log.created] = [c[1], c[3]];
    }
  }
  for (const e of log.entries) e.notes = e.notes.join("\n").trim();
  return log;
}

/** Fallback summary: a SKILL.md description, or the first plain line of an instruction file. */
export function summaryFrom(text = "") {
  const lines = text.split("\n");
  const cut = (s) => (s.length > 120 ? s.slice(0, 117) + "..." : s);
  if (lines[0]?.trim() === "---") {
    for (let i = 1; i < lines.length && lines[i].trim() !== "---"; i++) {
      if (lines[i].startsWith("description:")) {
        let desc = lines[i].slice(12).trim().replace(/^["']|["']$/g, "");
        if ([">", "|", ">-", "|-"].includes(desc) && lines[i + 1]) desc = lines[i + 1].trim();
        return cut(desc);
      }
    }
  }
  for (let line of lines) {
    line = line.trim().replace(/^[#>*\-\s]+/, "").trim();
    if (line.length > 15 && !line.startsWith("---") && !line.startsWith("<!--")) return cut(line);
  }
  return "";
}

const LIST_QUERY = `query($endCursor: String) { viewer { login repositories(first: 100, after: $endCursor,
  affiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER],
  ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {
  nodes { name owner { login } } pageInfo { hasNextPage endCursor } } } }`;
const ITEM_FIELDS = `name owner { login __typename } isPrivate url viewerPermission
  repositoryTopics(first: 20) { nodes { topic { name } } }
  changelog: object(expression: "HEAD:CHANGELOG.md") { ... on Blob { text } }
  skillmd: object(expression: "HEAD:SKILL.md") { ... on Blob { text } }
  claudemd: object(expression: "HEAD:CLAUDE.md") { ... on Blob { text } }
  agentsmd: object(expression: "HEAD:AGENTS.md") { ... on Blob { text } }
  issues(states: OPEN, labels: ["suggestion"], first: 50) {
    nodes { number title url createdAt author { login } } }`;

function toItem(node) {
  const topics = (node.repositoryTopics?.nodes || []).map((t) => t.topic.name);
  if (!itemOf(node.name, false) && !topics.includes("skylls")) return null;
  const { kind, name } = itemOf(node.name);
  const log = parseChangelog(node.changelog?.text);
  const text = node.skillmd?.text || node.claudemd?.text || node.agentsmd?.text || "";
  return {
    kind, name,
    owner: node.owner.login,
    ownerIsOrg: node.owner.__typename === "Organization",
    repo: `${node.owner.login}/${node.name}`,
    url: node.url,
    private: node.isPrivate,
    mine: node.viewerPermission === "ADMIN",
    folder: topics.find((t) => !t.startsWith("skylls")) || "",
    version: log.entries[0]?.version || null,
    updated: log.entries[0]?.date || null,
    summary: log.about || summaryFrom(text),
    createdBy: log.createdBy,
    created: log.created,
    versions: log.entries,
    suggestions: (node.issues?.nodes || []).map((s) => ({
      number: s.number, title: s.title, url: s.url, date: s.createdAt.slice(0, 10), by: s.author?.login || "",
    })),
  };
}

/** Every skylls item the user can see: their own (admin) and what friends shared with them. */
export async function catalog(token) {
  const repos = [];
  let cursor = null;
  let login = "";
  do {
    const data = await graphql(token, LIST_QUERY, cursor ? { endCursor: cursor } : {});
    login = data.viewer.login;
    const page = data.viewer.repositories;
    repos.push(...page.nodes.map((n) => `${n.owner.login}/${n.name}`));
    cursor = page.pageInfo.hasNextPage ? page.pageInfo.endCursor : null;
  } while (cursor);
  const wanted = repos.filter((r) => itemOf(r));
  const items = [];
  for (let i = 0; i < wanted.length; i += 40) {
    const chunk = wanted.slice(i, i + 40);
    const aliases = chunk
      .map((r, j) => `r${j}: repository(owner: ${JSON.stringify(r.split("/")[0])}, name: ${JSON.stringify(r.split("/")[1])}) { ${ITEM_FIELDS} }`)
      .join(" ");
    const data = await graphql(token, `query { ${aliases} }`);
    for (const node of Object.values(data)) {
      const item = node && toItem(node);
      if (item) items.push(item);
    }
  }
  items.sort((a, b) => a.kind.localeCompare(b.kind) || a.name.localeCompare(b.name) || a.owner.localeCompare(b.owner));
  return { login, items };
}

/** Pending invitations to skylls repos (friends sharing with you). */
export async function pendingInvites(token) {
  const invites = (await gh(token, "/user/repository_invitations?per_page=100")) || [];
  return invites
    .filter((i) => itemOf(i.repository?.full_name || ""))
    .map((i) => ({
      id: i.id,
      repo: i.repository.full_name,
      ...itemOf(i.repository.full_name),
      owner: i.repository.full_name.split("/")[0],
      from: i.inviter?.login || "",
    }));
}

export async function acceptInvite(token, id) {
  const invite = (await pendingInvites(token)).find((i) => String(i.id) === String(id));
  if (!invite) throw new GitHubError("No such skylls invitation", 404);
  await gh(token, `/user/repository_invitations/${invite.id}`, { method: "PATCH" });
  return invite;
}

export function checkRepo(repo) {
  if (!REPO_RE.test(repo || "") || !itemOf(repo)) throw new GitHubError("Not a skylls repo", 400);
  return repo;
}

export function checkUser(user) {
  const login = String(user || "").replace(/^@/, "");
  if (!USER_RE.test(login)) throw new GitHubError(`'${user}' is not a valid GitHub username`, 400);
  return login;
}

/** Who can see one of your items: collaborators you invited and pending invitations. */
export async function access(token, repo) {
  checkRepo(repo);
  const [collaborators, invites] = await Promise.all([
    gh(token, `/repos/${repo}/collaborators?affiliation=direct&per_page=100`),
    gh(token, `/repos/${repo}/invitations?per_page=100`),
  ]);
  return {
    repo,
    people: (collaborators || []).map((c) => ({ login: c.login, role: c.role_name, avatar: c.avatar_url })),
    pending: (invites || []).map((i) => ({ login: i.invitee?.login, id: i.id })),
  };
}

export async function share(token, repo, user) {
  checkRepo(repo);
  const login = checkUser(user);
  const owner = await gh(token, `/users/${repo.split("/")[0]}`);
  const readOnly = owner?.type === "Organization";
  const res = await gh(token, `/repos/${repo}/collaborators/${login}`, {
    method: "PUT",
    body: readOnly ? { permission: "pull" } : {},
  });
  return { invited: Boolean(res), login, access: readOnly ? "read-only" : "access" };
}

export async function unshare(token, repo, user) {
  checkRepo(repo);
  const login = checkUser(user);
  const invites = (await gh(token, `/repos/${repo}/invitations?per_page=100`)) || [];
  const invite = invites.find((i) => i.invitee?.login?.toLowerCase() === login.toLowerCase());
  if (invite) await gh(token, `/repos/${repo}/invitations/${invite.id}`, { method: "DELETE" });
  await gh(token, `/repos/${repo}/collaborators/${login}`, { method: "DELETE" }).catch((err) => {
    if (err.status !== 404 || !invite) throw err;
  });
  return { removed: login };
}

/** Owner answers a suggestion: a comment, then close as done or not planned. */
export async function answerSuggestion(token, repo, number, accept, note) {
  checkRepo(repo);
  const n = Number(number);
  if (!Number.isInteger(n) || n < 1) throw new GitHubError("Bad suggestion number", 400);
  const comment = String(note || "").trim() || (accept ? "Done, thanks!" : "Thanks, but not planned.");
  await gh(token, `/repos/${repo}/issues/${n}/comments`, { method: "POST", body: { body: comment } });
  await gh(token, `/repos/${repo}/issues/${n}`, {
    method: "PATCH",
    body: { state: "closed", state_reason: accept ? "completed" : "not_planned" },
  });
  return { closed: n, accept };
}
