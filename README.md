# skylls

**Share agent skills, agents and swarms with friends through GitHub, one item at a time.**

Every skill, agent and swarm you publish gets **its own private GitHub repo**.
You decide, item by item, who may install it. Friends do the same with
theirs. skylls installs what you were given: skills for Claude Code, Codex or
Gemini CLI (in one project or globally), and agents and swarms together with
their Obsidian memory.

skylls is a layer on top of GitHub. GitHub stores everything and enforces
who can see what (repo access). skylls adds versions, changelogs, plain
summaries, folders, suggestions and a secret scan.

## Install

One command (macOS / Linux):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/jcsancho/skylls/main/install.sh)"
```

The installer:
1. Checks `git`, `uv`, `gh` and `gitleaks`, and offers to install missing ones
   with Homebrew.
2. Installs skylls and puts it on your PATH.
3. Logs you in to GitHub.
4. Runs `skylls setup`.

Options: `-y` answers yes to everything, `--no-setup` only installs, and
`--ref v1.0.0` installs a specific version. Pass them after the command:
`bash -c "$(curl …)" _ -y`.

With npm (needs Node 18+ and Python 3.11+; the package runs the Python tool):

```bash
npm install -g @jcsancho/skylls && skylls setup      # or try it: npx @jcsancho/skylls --version
```

Or by hand: `uv tool install git+https://github.com/jcsancho/skylls` (or
`pipx install …`), then `skylls setup`.

Update with `skylls update` (`--check` only looks), which reinstalls the newest
release the way you installed it (uv, pipx or npm). Check your
version with `skylls --version`; [CHANGES.md](CHANGES.md) lists what changed
in each.

### Setup

`skylls setup` (any command runs it the first time) asks:

1. **Where to publish.** Recommended: a GitHub **organization** you
   administer. It is listed first and is the default, and it works like a
   folder holding one independent private repo per item:

   ```
   github.com/<you>-skylls          ← your organization
   ├── skill-pdf                    ← one private repo per skill
   ├── agent-btc                    ← one per agent (definition + memory)
   └── swarm-apps_ideas             ← one per swarm
   ```

   It keeps them apart from your other repos and lets friends have
   **read-only** access. If you don't have one yet, setup shows how to create
   it (free, about a minute, at
   [github.com/account/organizations/new](https://github.com/account/organizations/new?plan=free)),
   can open that page for you, and waits until it exists. Type `account` to
   use your personal account instead; there repos are named
   `skylls-skill-pdf` etc., so they stand apart from your other projects.
   Setup also checks the organization's base permission (what members can
   see) and offers to set it to "No permission", so nothing is visible until
   you share it.
2. **Your agent CLIs**: `claude`, `codex`, `gemini` or `all`.
3. **Your folders** for agents and swarms (default `~/agents`, `~/swarms`).
4. **The skylls skill**: install it globally so Claude Code, Codex and Gemini
   can use skylls themselves (default: all three; `--no-agent-skill` skips).

Non-interactive: `skylls setup --owner <you-or-org> --agents all
--agents-dir D --swarms-dir D`.

## Quick start

```bash
# you
skylls push pdf -m "First version"        # publishes ~/.claude/skills/pdf → <org>/skill-pdf (private)
skylls share pdf @bob                     # Bob may install it

# Bob
skylls source add <you>                   # once: accepts your shares, shows what you shared
skylls add pdf -g -a all                  # installs it for Claude Code, Codex and Gemini
```

## Find and install

```bash
skylls list                         # your skills and what friends shared, grouped by folder
skylls find invoice                 # search name, folder, summary and SKILL.md text
skylls find --folder docs           # one folder
skylls add pdf                      # this project: ./.claude/skills/pdf (+ ./.agents, ./.gemini)
skylls add pdf -g -a all            # global: ~/.claude/skills/pdf, Codex/Gemini link to it
skylls add pdf --from alice         # when several people have a "pdf"
skylls add pdf@1.2.0                # an older version
skylls log pdf                      # who made it, every version, what changed
skylls installed                    # installed skills, flags newer versions
skylls pull --update                # install newer versions
skylls remove pdf                   # remove your local copy (never touches GitHub)
```

Where skills go:

| | Claude Code | Codex | Gemini |
|---|---|---|---|
| `skylls add pdf` (this project) | `./.claude/skills/pdf/` | `./.agents/skills/pdf/` | `./.gemini/skills/pdf/` |
| `skylls add pdf -g` (global) | `~/.claude/skills/pdf/` | `~/.agents/skills/pdf/` | `~/.gemini/skills/pdf/` |

A global install for several agents keeps one real copy (Claude's) and links
the others to it. `-a` picks the agents (default: those chosen at setup).

## Publish

```bash
skylls push pdf -m "Handles scans"          # 1.2.0 → 1.2.1 (default)
skylls push pdf -m "New option" --minor     # 1.2.1 → 1.3.0
skylls push pdf -m "Rewrite" --major        # 1.3.0 → 2.0.0
skylls push pdf --folder docs               # also put it in a folder
skylls push ./path/to/skill                 # or a folder path
```

- **The repo:** the first push creates the private repo
  `<org>/skill-<name>` (`<you>/skylls-skill-<name>` on a personal account). Each version is a git tag (`v1.3.0`), and
  without `-m` push asks what changed.
- **Secret scan:** before anything goes up, push scans for API keys, tokens,
  passwords, private keys and personal data (emails, phone numbers…) with
  [gitleaks](https://github.com/gitleaks/gitleaks), and publishes nothing if it
  finds any. `--skip-scan` is for false positives.
- **`CHANGELOG.md`:** each item has one, written by skylls (don't edit it).
  It holds a **plain one-sentence summary** (written by Claude through
  `claude -p`, or yours with `--about "…"`), who created it, and one entry per
  version: what changed, when and by whom. The summary is also the repo's
  description on GitHub.

## Agents and swarms

The same commands, under `skylls agents …` and `skylls swarms …`:

```bash
skylls agents                                # yours (published or not) + friends'
skylls agents push btc -m "Adds ETH"         # ~/agents/btc → <org>/agent-btc
skylls agents share btc @bob
skylls agents add btc --from alice           # → ~/agents/btc
skylls agents add btc@1.0.0 --from alice --as btc-old
skylls agents remove btc                     # local folder → the Trash (repos untouched)
skylls swarms push apps_ideas                # ~/swarms/apps_ideas → <org>/swarm-apps_ideas
```

**What is published** is the *definition*, never runtime state:

| | published | not published |
|---|---|---|
| agent | `CLAUDE.md`/`AGENTS.md`/`GEMINI.md`, `.claude/` (settings, skills, commands), scripts and other files, **its memory folder** | `logs/`, `data/`, `reports/`, `scratch/`, `state/`, caches and venvs, `*.log`, `*.jsonl`, `*_state.json`, databases, `.claude/settings.local.json`, `.env*`, keys, files over 5 MB |
| swarm | top-level and per-role `CLAUDE.md`/`AGENTS.md`/`GEMINI.md` and `.claude/`, `.swarm/agents.json`, `.swarm/schedules.json`, **its memory folder** | the roles' work files, reports, `.swarm/bus.jsonl` and other state |

A `.skyllsignore` in the folder adjusts this (one pattern per line,
`!pattern` to include something).

**Memory (Obsidian) travels with them.**
- **Where it should live:** inside the agent's or swarm's folder (e.g.
  `~/agents/btc/wiki/`). A subfolder counts as memory if it is an Obsidian
  vault (has `.obsidian/`), or is named `memory`, `wiki`, `obsidian` or
  `*-wiki`. All of it is published, except Obsidian's per-user window layout,
  the trash and files over 5 MB.
- **Memory elsewhere in `~/Obsidian`** still works:
  - Found from the instructions: a `<x>-wiki` vault they mention, or
    `<vault>/AGENTS/<name>/` for the item's own name.
  - Snapshotted into `.skylls-memory/`, and restored to the same place under a
    friend's home.
  - A `.skyllsmemory` file lists memory folders yourself.

**Installing a friend's agent or swarm:**
- **Where it goes:** your agents or swarms folder (`~/agents/btc/`).
- **Paths:** absolute paths from their machine are rewritten to yours, and
  missing ones are listed.
- **Updates:** running `add` again updates the definition. Your runtime data
  stays, and so does your memory unless you pass `--update-memory`.
- **Where it came from** is recorded in its `CHANGELOG.md`.

## Friends and sharing

```bash
skylls share pdf @bob @carol        # invite to one item
skylls share --all @bob             # every skill you published (agents/swarms: skylls agents share --all @bob)
skylls share pdf                    # who has access
skylls unshare pdf @bob             # revoke (what Bob installed stays on his machine)

skylls source add alice             # see what alice shared with you (accepts her invites)
skylls source                       # your friends and how many items each shared
skylls source remove alice
```

- **Who sees what:** nothing is shared by default. Your friends see **only
  the items you shared with them**, and GitHub enforces it. skylls invites
  them to single repos as *outside collaborators*, who can't see your other
  repos, even in the same organization. Don't make friends *members* of your
  organization: members get its base permission on every repo, which setup
  offers to set to "No permission". New shares from a friend you added are
  accepted automatically. If someone else shares with you, `list` says so and
  you decide whether to add them.
- **Access level:** on a personal account, GitHub gives everyone you invite
  write access to that repo. skylls never pushes to friends' repos, but plain
  git could. With an **organization**, skylls invites friends **read-only**.

## Folders

GitHub has no folders for repos, so skylls uses **topics**:

```bash
skylls push pdf --folder docs       # or later: skylls move pdf docs   ('.' = no folder)
skylls folder                       # your folders and how many items each has
skylls folder rename docs office
skylls folder remove office         # items stay, just without a folder
skylls list -f docs                 # filter (also find -f docs)
```

On GitHub, filter your repos by topic:
`github.com/<owner>?tab=repositories&q=topic:docs`. Every skylls repo also
carries the topics `skylls` and `skylls-skill` / `skylls-agent` /
`skylls-swarm`. In an organization repos are named `skill-…`, `agent-…`,
`swarm-…`; on a personal account `skylls-skill-…` and so on. A repo only
counts as a skylls item if it carries the `skylls` topic (skylls sets it), so
other repos with similar names are ignored.

## Suggestions

```bash
skylls suggest pdf --from alice "Also handle scanned PDFs"   # a GitHub issue in alice's repo, assigned to her
skylls suggestions                                           # open suggestions for yours
skylls accept pdf#3 -m "Done in 1.3.0"                       # closes it as done
skylls decline pdf#4 -m "Out of scope"                       # closes it as not planned
```

## For agents: few tokens

Setup installs **the skylls skill**
([`skylls/skills/skylls/SKILL.md`](skylls/skills/skylls/SKILL.md)), which
teaches Claude Code, Codex and Gemini to use skylls:

- **What it covers:** installing skylls if it's missing; finding and
  installing skills, agents and swarms; asking you before publishing or
  sharing anything.
- **Installing it later:** `skylls agent-skill -g -a all`, or from GitHub:
  `skylls add jcsancho/skylls/skylls -g -a all`.
- **Updates:** after an upgrade, the next skylls command updates your
  installed copy.

With `--json`, the read commands print one compact JSON object per line on
stdout, without empty fields. Messages and errors go to stderr.

```bash
skylls find pdf --json --limit 5
{"name":"pdf","owner":"alice","folder":"docs","version":"1.3.0","summary":"Fills in PDF forms for you.","updated":"2026-10-07","repo":"alice-skylls/skill-pdf"}
skylls installed --json             # "newer" when an update exists
skylls log pdf --json               # details + version history
skylls agents list --json           # "published":false for ones not published yet
```

`find --json` returns at most 10 results unless you pass `--limit`.

## Website and dashboard

[`webapp/`](webapp/) holds the skylls website and dashboard, deployed on
Vercel. **Sign in with GitHub** to manage everything from the browser:

- **Your items:** see your skills, agents and swarms (version, folder,
  summary), and who can see each one. Share with a user, or remove someone.
- **Invitations:** accept what friends shared with you.
- **Suggestions:** accept or decline them, with a note.
- **Friends' items:** copy the install command for anything friends shared.

It has no database: it works directly on your GitHub with your own access, and
keeps your token in an encrypted cookie. Deployment and local testing are
described in [webapp/README.md](webapp/README.md).

## Public skills from skills.sh

```bash
skylls search pdf                          # top matches with install counts
skylls add anthropics/skills/pdf -g        # install straight from that public GitHub repo
```

Add `--dry-run` before any command to see what it would do without changing anything.

## How it works

```
<org>/skill-pdf      ┐  one private repo per item, only what friends may see
<org>/agent-btc      │  + CHANGELOG.md, tags v1.0.0…, topics (folder)
<org>/swarm-apps     ┘  (personal account: skylls-skill-pdf, …)
        ▲ push (copy, commit, tag)        │ add (copy the version you want)
        │                                 ▼
~/.claude/skills/pdf   ~/agents/btc   ~/swarms/apps       ← your copies / workspaces
```

- **Config:** `~/.config/skylls/config.json` holds your login, where you
  publish, your agent CLIs, your folders and your friends.
- **Finding items:** two GitHub GraphQL queries (the repos you can access,
  then the skylls repos' changelogs and instructions).
- **Publishing and installing:** small clones in `~/.cache/skylls/repos/`.
- **Your own folders:** `~/agents` and `~/swarms` are just your workspaces.
  skylls never commits there. If they are git repos of your own (backups),
  that's up to you.

## Command reference

| Command | What it does |
|---------|--------------|
| `setup [--owner O] [--agents A] [--agents-dir D] [--swarms-dir D] [--no-agent-skill]` | Your account or organization, agent CLIs, folders, the skylls skill |
| `list [query] [--from O] [-f F]` | Your items and what friends shared, grouped by folder |
| `find <words> [--from O] [-f F] [-n N]` | Search; shows summary, version, owner, folder |
| `add <name[@ver]> [--from O] [-g] [-a A] [-y]` | Install a skill (`owner/repo/skill`: from a public repo) |
| `log <name> [--from O]` | Who made it, versions, what changed |
| `installed [-g] [-a A]` | Installed skills and newer versions |
| `pull [--update]` | Check for (and install) newer versions |
| `remove <name> [-g] [-a A]` | Remove a local skill copy |
| `push <name\|path> [-m msg] [--minor\|--major] [--about text] [--folder F] [--skip-scan]` | Publish a new version to its private repo |
| `share <name> @user… \| --all @user` | Let friends install it (no users: who has access) |
| `unshare <name> @user… \| --all @user` | Revoke access |
| `move <name> <folder>` | Put it in a folder (`.` = none) |
| `folder [rename old new \| remove F]` | Your folders |
| `source [add\|remove] <login>` | Friends whose shares you see |
| `suggest <name> [--from O] "text"` | Suggest an improvement to the owner |
| `suggestions [name]` / `accept <name>#<n>` / `decline <name>#<n>` | Your open suggestions, and answering them |
| `agents …` / `swarms …` | The same commands for agents and swarms, plus `add --as N --update-memory` and `remove [--memory] [-y]` |
| `agent-skill [-g] [-a A]` | (Re)install the skylls skill for your agents |
| `search <query>` | Public skills on skills.sh |
| `version` / `--version` | The skylls version |
| `update [--check]` | Update skylls itself to the newest version |
| `--json` / `--dry-run` (before the command) | Compact output for agents / preview only |

## Requirements

- **Required:** Python 3.11+, `git`, and the GitHub CLI `gh` logged in
  (`gh auth login`).
- **For publishing:** [gitleaks](https://github.com/gitleaks/gitleaks)
  (`brew install gitleaks`).
- **Optional:** the `claude` CLI, for the automatic plain summaries.
- No Python dependencies.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
