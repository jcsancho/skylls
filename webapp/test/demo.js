// Try the webapp locally with sample data and no real GitHub: node test/demo.js → http://localhost:3901
// "Sign in with GitHub" goes to the fake GitHub, which signs you in as alice at once.
import { fakeGitHub } from "./fake-github.js";

const gh = fakeGitHub();
const base = await gh.start();
Object.assign(process.env, {
  GITHUB_API: base, GITHUB_OAUTH_BASE: base, SESSION_SECRET: "demo-".repeat(8),
  GITHUB_CLIENT_ID: "demo", GITHUB_CLIENT_SECRET: "demo",
});

const log = (about, versions) =>
  `# x\n\n> ${about}\n\nCreated by Alice (@alice) on 2026-09-20.\n\n` +
  versions.map(([v, d, n]) => `## ${v} — ${d} — Alice\n\n${n}\n`).join("\n");

gh.addRepo("aliceco/skill-pdf", { topics: ["skylls", "skylls-skill", "docs"], files: { "CHANGELOG.md": log("Fills in PDF forms and reads scanned documents for you.", [["1.2.0", "2026-10-07", "Handles scans"], ["1.0.0", "2026-09-20", "First version"]]), "SKILL.md": "x" } });
gh.addRepo("aliceco/skill-invoices", { topics: ["skylls", "skylls-skill", "work"], files: { "CHANGELOG.md": log("Turns receipts into tidy monthly invoices.", [["1.0.3", "2026-10-02", "Fixes VAT"]]), "SKILL.md": "x" } });
gh.addRepo("aliceco/agent-btc", { topics: ["skylls", "skylls-agent"], files: { "CHANGELOG.md": log("Watches bitcoin prices and writes a daily note.", [["1.1.0", "2026-10-05", "Adds ETH"]]), "CLAUDE.md": "x" } });
gh.addRepo("aliceco/swarm-app-ideas", { topics: ["skylls", "skylls-swarm"], files: { "CHANGELOG.md": log("A team of agents that finds and scores app ideas.", [["1.0.0", "2026-09-30", "First version"]]), "CLAUDE.md": "x" } });
gh.addRepo("bob/skylls-skill-slides", { topics: ["skylls", "skylls-skill"], files: { "CHANGELOG.md": log("Builds slide decks from your notes.", [["2.0.1", "2026-10-06", "New themes"]]), "SKILL.md": "x" } });
gh.addRepo("carol/skylls-agent-gmail", { topics: ["skylls", "skylls-agent"], files: { "CLAUDE.md": "# gmail agent that sorts your inbox and drafts replies\n" } });
gh.state.repos["aliceco/skill-pdf"].collabs.bob = "pull";
gh.state.repos["bob/skylls-skill-slides"].collabs.alice = "push";
gh.state.repos["aliceco/skill-pdf"].issues.push({ number: 3, title: "Support Excel files too", state: "open", author: "bob", comments: [] });
gh.state.invites.push({ id: 7, repo: "carol/skylls-agent-gmail", invitee: "alice", inviter: "carol", permission: "push" });
gh.state.invites.push({ id: 8, repo: "aliceco/skill-pdf", invitee: "dave", inviter: "alice", permission: "pull" });

const { serve } = await import("../dev.js");
serve(Number(process.env.PORT) || 3901);
console.log(`fake GitHub on ${base}`);
