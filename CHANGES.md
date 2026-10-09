# Changes

Every change to skylls raises its version (`skylls --version`):
fix → 0.2.1, new feature → 0.3.0, breaking change → 1.0.0.

## webapp 1.5.0 — 2026-10-09

- **New `/llms.txt`**: the whole guide as plain Markdown for AI agents (what
  skylls is, installing the skylls skill and the CLI for each kind of agent,
  sharing and using skills, agents and swarms, JSON output, rules, compact
  command reference). Linked from the docs page, its `<head>` and the footers.
- **New `/skill.md`**: the skylls skill, a copy of
  `skylls/skills/skylls/SKILL.md` (a test keeps them identical).
- **Docs: "For LLMs" section on top**, with how to install the skylls skill
  and how to share and use skills.
- `/doc` now redirects to `/docs` (it was a 404).

## 1.3.1 — 2026-10-09

- **Fix:** `--json` and `--dry-run` now work anywhere on the command line
  (`skylls find pdf --json`), as the README and the skylls skill show them.
  Before, they were only accepted before the command, so agents following the
  skill got "unrecognized arguments: --json".

## webapp 1.4.0 — 2026-10-09

- **Cookie consent**: a banner (Accept all / Only necessary / Customize) and a
  settings panel on every page, with "Cookie settings" in each footer to
  change the choice later. Google Fonts, the only optional thing the site
  uses, now loads only after consent; without it the pages use system fonts.
  The choice is kept in the browser for 12 months.
- **New `/cookies` page** (cookie policy) listing each cookie, its purpose and
  duration. The privacy policy now covers the controller, legal bases,
  recipients, international transfers, retention, GDPR rights and
  complaints, and names the controller (Jose Carlos Sancho Pitarch, Spain)
  with a contact address, privacy@skylls.dev. The terms add who provides
  skylls, Spanish governing law, third-party services and consumer rights.

## 1.3.0 and webapp 1.3.1 — 2026-10-08

- **New `skylls update`**: updates skylls itself to the newest release, the
  same way it was installed (uv, pipx or npm), pinned to that version's tag.
  `--check` only says whether a newer one exists; `--dry-run update` shows the
  command. A checkout or editable install is told to `git pull` instead.
  Anyone on 1.2.1 or older should update: their organization items are
  invisible (fixed in 1.2.2).
- webapp: `/docs` shows `skylls update`, and the one-time manual update for
  1.2.2 and older.

## webapp 1.3.0 — 2026-10-08

- **New `/docs` page**: the full user guide on the website, covering install,
  setup, quick start, publishing, versions, agents and swarms with their memory,
  sharing, suggestions, folders, the dashboard, security, `--json` for agents,
  the command reference and an FAQ. It has a sidebar table of contents and copy
  buttons on code blocks. It's linked from the landing page's nav, hero and
  footer.

## webapp 1.2.0 — 2026-10-08

- **Ready for the GitHub Marketplace.**
  - New `/privacy` and `/terms` pages, linked from the footer and the sign-in
    screen.
  - New Marketplace webhook at `/api/marketplace`. It checks GitHub's
    `X-Hub-Signature-256` against `MARKETPLACE_WEBHOOK_SECRET` and acknowledges
    each event. skylls is free and keeps no database, so there is nothing to set
    up per customer.
- The site's home is now `skylls.dev`.

## 1.2.2 and webapp 1.1.1 — 2026-10-08

- **Fix: items in organizations were invisible.** The repo-list query used
  GitHub's default `ownerAffiliations`, which leaves out repos owned by
  organizations.
  - In the CLI, `list`, `find`, `log`, `add` and `share` missed everything
    published to an organization.
  - In the dashboard, "Yours" was empty.
  - Both now ask for organization repos explicitly.
- The test fake GitHubs now behave like GitHub here, so this can't come back
  unnoticed.

## webapp 1.1.0 — 2026-10-08

- **Stay signed in for 30 days.** With "Expire user access tokens" on the
  GitHub OAuth app, the dashboard keeps GitHub's refresh token and renews the
  8-hour access token automatically.
- If the refresh token was revoked, you're signed out with a clear message.

## webapp 1.0.0 — 2026-10-08

The website and dashboard (`webapp/`, deployed on Vercel; the CLI is unchanged):

- **Landing page:** what skylls is, install commands, features, how it works,
  organizations as folders, and examples.
- **Dashboard (sign in with GitHub):**
  - Your skills, agents and swarms, and who can see each one; share or remove
    someone.
  - Accept invitations; answer suggestions; copy install commands for friends'
    items.
- **How it works:** no database; the GitHub token is kept in an encrypted
  HttpOnly cookie, and actions are protected against cross-site requests.
- **Tests:** against a fake GitHub (`node --test test/`), plus a local demo
  (`node test/demo.js`).

## 1.2.1 — 2026-10-08

- The npm package is **`@jcsancho/skylls`** (npm refused the plain name
  `skylls` as too similar to existing packages). Install with
  `npm install -g @jcsancho/skylls` or run `npx @jcsancho/skylls`; the command
  is still `skylls`.

## 1.2.0 — 2026-10-08

- **npm package:** `npm install -g skylls`, or `npx skylls`.
  - `package.json` and `bin/skylls.js`, a small Node launcher that runs the
    bundled Python tool with Python 3.11+ (`SKYLLS_PYTHON` picks one).
  - It explains how to get Python when none is found.
- `tests/e2e.sh` checks that `package.json` and `skylls --version` agree.

## 1.1.0 — 2026-10-08

- **An organization is the recommended home.**
  - Setup lists your organizations first and makes the first one the default.
  - If you have none, it shows how to create one (with the link), can open
    the page, and waits until it exists. Type `account` to use your personal
    account.
  - Non-interactive setup prints the steps and uses your account for now.
- **Shorter repo names in organizations:** `skill-pdf`, `agent-btc`,
  `swarm-apps_ideas`. Personal accounts keep `skylls-skill-pdf` etc.
  - A short-named repo only counts as an item when it carries the `skylls`
    topic, which skylls sets as soon as it creates the repo.
  - Existing repos with the other naming are reused.
- **Base permission check:** setup checks the organization's base permission
  (what members can see on every repo) and offers to set it to "No
  permission", so nothing is visible until you share it item by item.

## 1.0.0 — 2026-10-08

**Breaking: one private GitHub repo per item.**

- **Publishing:** every skill, agent and swarm you publish gets its own
  private repo, `<owner>/skylls-skill-<name>`, `skylls-agent-<name>` or
  `skylls-swarm-<name>`, holding only what friends may see. Versions are tags
  (`v1.2.0`).
- **Where repos live:** setup asks whether to publish to your account or to an
  organization you administer. With an organization, friends get read-only
  access.
- **Sharing is per item:** `skylls share <name> @user` (or `--all`). Friends
  run `skylls source add <you>` once, which accepts your invites, and see
  exactly what you shared. GitHub enforces it.
- **Folders are GitHub topics:** `push --folder`, `move`, `folder rename/remove`,
  and `list`/`find -f`.
- **Finding items:** one catalog (two GitHub GraphQL queries) for `list`,
  `find`, `log`, `installed` and suggestions.
- **Removed:** the shared skills repo, its folders, owner-only permissions and
  the in-place publishing to your `~/agents` / `~/swarms` repos. Those are now
  just your workspaces. Also removed is the `.gitignore` block for downloads,
  which is no longer needed.
- **Setup:** no repos are created at setup; each one is created the first
  time you `push` that item.
- **Upgrading:** an old config runs the new setup once. Your installed skills,
  agents and swarms stay where they are.

## 0.5.0 — 2026-10-08

- `skylls agents remove <name>` and `skylls swarms remove <name>`:
  - Moves the folder to the Trash; `--dry-run` shows what would happen.
  - Asks first, unless you pass `-y`.
  - Memory a download put outside the folder is kept unless you add `--memory`.
- Downloaded agents and swarms were kept out of your own repo with a managed
  `.gitignore` block (removed again in 1.0.0).
- `push` no longer fails when your `.gitignore` excludes a definition file; it
  skips it with a warning.

## 0.4.0 — 2026-10-08

- **The skylls skill** is now a real skill file in the repo
  (`skylls/skills/skylls/SKILL.md`). It teaches any agent (Claude Code, Codex,
  Gemini) to:
  - install skylls if it's missing;
  - find and install skills, agents and swarms;
  - share them, only with your go-ahead.
- **Installing it:** it is the default skill. The last step of `skylls setup`
  asks to install it globally for Claude Code, Codex and Gemini
  (`--no-agent-skill` skips it). It can also be installed from GitHub:
  `skylls add jcsancho/skylls/skylls -g -a all`.
- **Updates:** an installed copy is updated automatically after you upgrade
  skylls.

## 0.3.0 — 2026-10-08

- `install.sh`: one-command installer for new users.
  - Checks git, uv, gh, gitleaks and claude, and offers to install missing
    ones with Homebrew.
  - Installs skylls and puts it on the PATH.
  - Logs in to GitHub and runs `skylls setup`.
  - Optionally teaches your AI agents to use skylls.
  - Options: `-y`, `--no-setup`, `--ref`, and `SKYLLS_SOURCE`.

## 0.2.0 — 2026-10-08

- `skylls --version` / `skylls version`, and the version in `skylls help`.
- This changelog.

## 0.1.0 — 2026-10-08

First public version:

- Skills, agents and swarms shared through each user's own **private**
  GitHub repos, created at first `setup` if missing.
- Friends' repos as sources (`source add`, `--from`), invites with `share`.
- Versions, changelogs and plain summaries for every item.
- Owner permissions and suggestions.
- Folders for skills.
- Obsidian memory for agents and swarms.
- Secret scanning before every push.
- `--json` output for agents, and `agent-skill` to teach agents to use skylls.
