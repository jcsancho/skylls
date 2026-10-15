# Changes

Every change to skylls raises its version (`skylls --version`):
fix → 0.2.1, new feature → 0.3.0, breaking change → 1.0.0.

## 1.8.0 — 2026-10-15

- **Pull requests for agents and swarms:** `skylls swarms propose <name> --from
  <owner> -m "what"` (also `agents`) sends the changes you made to your copy of
  a friend's item as a real GitHub pull request: it compares your copy with the
  version you installed, puts the owner's paths back, scans for secrets, forks
  the repo (private, named `<repo>-from-<owner>`) and opens the pull request.
  `--skip FILE` leaves files out.
- **The owner answers it like a suggestion:** `suggestions` lists pull requests
  too, `review <name>#<n>` shows the diff, `accept <name>#<n>` applies it to
  their own copy, publishes a new version and closes it (it stops when they
  changed the same files since; `--force` takes the proposal), `decline` closes
  it.
- **`allow-prs <name> | --all [--off]`:** friends can only fork once the owner
  allows it (for an organization this also allows private forks in it).

## 1.7.4 — 2026-10-15

- **Swarms share the scripts their instructions run:** a swarm was published
  as its instructions and settings only, so a script next to them that the
  instructions call (`python3 check_cards.py <n>`, `~/swarms/x/set_goal.sh`)
  was silently left out and a friend's copy broke at that step. Scripts
  (`.py`, `.sh`, `.js`, `.ts`, `.rb`, `.pl`) mentioned in the top-level or a
  role's `CLAUDE.md` / `AGENTS.md` / `GEMINI.md` are now published with it;
  other files still stay home (runtime folders like `scratch/` too).

## 1.7.3 — 2026-10-15

- **`sync` shows progress right away:** the bar now also covers reading your
  items from GitHub (invites, the repo list, item details), which is where a
  sync spends its first seconds, and the final count (`40/40 checked`) stays
  on screen instead of flashing by.

## 1.7.2 — 2026-10-15

- **Progress bar in `sync`:** while it checks your published items it shows
  a bar on the terminal (`█████░░░ 12/40 skill foo`). Only on a terminal,
  never with `--json` or when output is piped.

## 1.7.1 — 2026-10-15

- **Faster `sync` when little changed:** an item whose files match its
  latest published version (checked offline against the cached clone, at the
  commit GitHub reports) is skipped without the secret scan, `git fetch` or
  `gh` calls. With many items a no-change sync goes from minutes to seconds.

## 1.7.0 — 2026-10-15

- **Private memory notes:** a note in an agent's or swarm's memory whose
  frontmatter says `private: true` is never published (also for memory kept
  in `~/Obsidian`). Mixed memory can now live in one vault: lessons travel,
  client names and other private facts stay home.
- **Memory review before publishing:** `push` and `sync` list the memory
  notes that are new or changed since the last version and ask before
  publishing them. `-y` (new on agents/swarms `push` and on `sync`) skips the
  question; `--dry-run` only lists them; without a terminal they are listed
  and published.

## 1.6.1 — 2026-10-13

- A friend who shares from their organization (`<org>/swarm-…`) now shows up:
  when you accept an invite a friend sent from a repo their organization owns,
  that organization is added to your sources, so its items appear in `list`.
  Before, the invite was accepted but the item stayed hidden.
- `list` and the other catalog commands point out skylls repos you can already
  see from someone who isn't a source yet (`skylls source add <owner>`).

## 1.6.0 — 2026-10-13

- **Skills inside an agent or swarm** (`.claude/skills/<name>/`, also per
  role) that are one of your skylls skills are published as a reference
  (`.skylls-skills`) instead of a copy; installing the agent or swarm puts the
  latest version of each in place from skylls (or says to ask the owner to
  share it). Fewer files to scan and no stale copies.
- Obsidian's downloaded plugins and themes (`.obsidian/plugins/`,
  `.obsidian/themes/`) are no longer shared with an agent's or swarm's memory.
- `skylls sync` no longer prints "Skill '…' not found" for every published
  skill that isn't installed on this computer; it skips them quietly.
- `skylls sync` no longer asks "What changed?" for each item: without `-m`
  the log entry lists the files that changed (e.g. "Updated SKILL.md,
  scripts/run.py").

## 1.5.0 — 2026-10-13

- **`skylls sync`** keeps everything in step with GitHub in one go: it
  publishes a new version of each skill, agent and swarm you already
  published and changed since (each one scanned for secrets; one refused item
  doesn't stop the rest), then installs the newer versions of the skills,
  agents and swarms friends shared with you (your memory copies are kept).
  `-m` gives the log entry for every new version; `--dry-run` shows what it
  would do.
- **`skylls revoke @user`** takes back everything you shared with someone:
  every skill, agent and swarm they can use and the invites they haven't
  accepted. It lists them and asks first (`-y` doesn't ask; `--dry-run`
  only lists). One item is still `skylls unshare <name> @user`.
- **`skylls people`**: one line per person you share with or who shares
  with you (or whom you added as a source), with what you share with them,
  what they share with you and what waits for you to accept.
- **`skylls shared`** shows in one place which skills, agents and swarms you
  shared and with whom (pending invites included), and which ones friends
  shared with you, grouped by friend. `skylls shared @bob` shows only what
  you and Bob share with each other. Works with `--json`.
- It also lists what isn't accepted yet: your invites a friend hasn't
  accepted (with the date sent), and items people shared with you that wait
  for you, with the `skylls source add <owner>` that accepts them.

## webapp 1.8.0 — 2026-10-13

- `/docs`, `/llms.txt` and `/skill.md` cover `skylls sync`, `shared`,
  `people` and `revoke`.

## 1.4.0 — 2026-10-11

- **New npm name: `@skylls/cli`** (`npm install -g @skylls/cli`). `skylls
  update` moves installs of the old `@jcsancho/skylls` package to it (it
  uninstalls the old package first, since both own the `skylls` command, and
  puts it back if the new install fails).
- **The installer now lives at `https://skylls.dev/install.sh`**:
  `curl -fsSL https://skylls.dev/install.sh | bash` (options after
  `bash -s --`). The old GitHub URL keeps working.

## webapp 1.7.0 — 2026-10-11

- Serves `/install.sh` (a copy of the repo's installer; a test keeps them
  identical) as plain text.
- Install commands on the landing page, `/docs`, `/llms.txt` and `/skill.md`
  use `@skylls/cli` and `curl -fsSL https://skylls.dev/install.sh | bash`;
  the docs explain how to move from `@jcsancho/skylls`.

## webapp 1.6.2 — 2026-10-11

- The landing page loads `network.svg?v=<version>` so browsers fetch the new
  graphic after a change instead of showing a cached one.

## webapp 1.6.1 — 2026-10-11

- Examples on the website now use generic business names (`seo-audit`,
  `lead-generator`, `marketing-team`, `x-marketing`, `tiktok-creator`, …)
  in the graphics, the docs and `/llms.txt`, instead of personal ones.
- Long share commands in the "Share anything" cards wrap instead of being cut.

## webapp 1.6.0 — 2026-10-10

- **Landing page graphics** that show what skylls shares and with whom:
  an animated share map under the hero (your skill, agent and swarm go
  through private repos and a secret scan to friends and to agents), a new
  "From one skill to a whole swarm" section with an illustration per kind,
  and a "Friends or agents" section (per-friend access map and an agent
  finding and installing a skill on its own). Inline SVG and CSS only, no
  new files or dependencies; animations stop with reduced motion.
- **New `/network.svg`** and a "People and agents, sharing with each other"
  section: an animated network of people and AI agents (Claude Code, Codex,
  Gemini, a swarm) around skylls, with skills, agents and swarms travelling
  between them through private repos. A standalone SVG, usable in the README
  or on social posts too.
- Title now reads "Share skills, agents and whole swarms, one private repo
  at a time"; new "Network" and "Share" links in the nav.

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
