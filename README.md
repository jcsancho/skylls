# skylls

**Share your agent skills, agents and swarms through GitHub.** Everyone keeps
their own GitHub repos: one for skills, one for agents (`~/agents`), one for
swarms (`~/swarms`). You share yours with friends, they share theirs with you,
and skylls installs what you were given access to: skills for Claude Code,
Codex or Gemini CLI (in one project or globally), agents and swarms with their
Obsidian memory.

skylls is a layer on top of GitHub: GitHub stores the skills and handles
access to the repo, and skylls adds per-skill rules on top: who owns each
skill, who may update it, and suggestions the owner accepts or declines.

## Why

Skills (folders with a `SKILL.md`) tend to end up scattered: copied by hand
between projects, different versions on different machines, separate copies
for each agent. skylls fixes that:

- **GitHub is the source of truth.** Your skills live in one repo.
- **Install where you need them.** Into the current project, or globally in
  your home folder.
- **Every agent.** The same skill can be installed for Claude Code, Codex and
  Gemini at once.
- **Share both ways.** Upload a skill you made or improved, and teammates (or
  your other computers) pull it down.
- **Versions and a changelog.** Every upload is a new version (1.0.0, 1.0.1…)
  with a note of what changed, when and by whom, plus a plain one-sentence
  summary of what the skill does. Older versions stay installable.
- **Folders.** Group skills into folders (`work/`, `writing/`…) and move them
  around; find skills by keyword or folder.
- **Owners and suggestions.** Whoever first uploads a skill owns it and decides
  whether anyone may update it, or whether others send suggestions the owner
  accepts or declines.
- **Find more.** Search the public [skills.sh](https://skills.sh) directory and
  install any skill from GitHub.

## Install

```bash
uv tool install git+https://github.com/jcsancho/skylls   # puts `skylls` on your PATH
skylls setup        # first run: your private repos for skills, agents and swarms
```

(`pipx install git+https://github.com/jcsancho/skylls` works too. Needs
Python 3.11+, `git`, and the GitHub CLI `gh` logged in with `gh auth login`.)

**skylls is public; your repos are private.** The first run (any command runs
it if needed) sets up **your own private GitHub repos**:

1. **Skills**: do you already have a repo? Give its `owner/name`, or press
   Enter and skylls creates a private `<your-login>/skylls-skills`.
2. **Your default agent CLIs**, e.g. `claude`, `claude,codex` or `all`.
3. **Agents**: the folder (default `~/agents`) and its repo, detected from the
   folder's git remote, or a new private `<your-login>/skylls-agents`.
4. **Swarms**: the folder (default `~/swarms`) and its repo, or a new private
   `<your-login>/skylls-swarms`.

- **New repos** get a first commit (a README, plus a protective `.gitignore`
  for agents and swarms).
- **A public repo**, if you name one, gets a warning and an offer to make it
  private.
- **An existing folder** that isn't a git repo yet is connected to the new
  repo without uploading anything. Only what you publish with
  `skylls agents push` goes up.
- **Skipping:** type `-` to skip agents or swarms.
- **Non-interactive:** `skylls setup --create --agents claude` creates whatever
  is missing, or give repos with `--repo R --agents-repo R --agents-dir D
  --swarms-repo R --swarms-dir D`.

Then share with friends and add theirs (see *Friends' repos*).

## Everyday use

```bash
skylls list                       # what's in the shared repo
skylls list video                 # filter by name/description
skylls add youtube-transcribe     # install into this project (default agents)
skylls add youtube-transcribe -g  # install globally (home folder)
skylls add youtube-transcribe -g -a all   # globally for Claude, Codex and Gemini
skylls installed                  # what's installed here and globally
skylls remove youtube-transcribe  # remove the local copy (repo is untouched)
```

### Share a skill

```bash
skylls push my-new-skill -m "Handles PDFs too"   # finds it in your installed folders, commits + pushes
skylls push ./path/to/skill -m "Better prompts"  # or give a folder path
```

Uploads go **straight to the repo's main branch**.

### Versions and the changelog

Every `push` publishes a **new version** of the skill and records it:

```bash
skylls push my-skill -m "Fix typo"           # 1.2.0 → 1.2.1 (default)
skylls push my-skill -m "New option" --minor # 1.2.1 → 1.3.0
skylls push my-skill -m "Rewrite" --major    # 1.3.0 → 2.0.0
skylls log my-skill                          # summary + every version: what, when, who
skylls add my-skill@1.2.0                    # install an older version
```

- The first push of a skill is `1.0.0`. Without `-m`, push asks what changed.
- The log lives in the skill's own `CHANGELOG.md` (in the repo and in your
  installed copy). skylls writes it, so don't edit it by hand:

  ```markdown
  # my-skill

  > Turns meeting recordings into short written summaries.

  Created by Alice (@alice) on 2026-09-30.

  Updates: owner only — others suggest changes with 'skylls suggest'.

  ## 1.3.0 — 2026-10-07 — Alice
  New option

  ## 1.2.1 — 2026-10-05 — Bob
  Fix typo
  ```

- The quoted line is a **plain, one-sentence summary** of what the skill does.
  Claude writes it (`claude -p`, Haiku) on the first push, and again whenever
  `SKILL.md` changes. Use `--about "..."` to write it yourself. Without the
  `claude` CLI, push still works; the summary just stays as it was.
- Each version is also a git tag (`my-skill@1.3.0`), which is what
  `add my-skill@<version>` installs. `pull --update` moves such pinned copies
  to the latest version.
- `list` and `installed` show each skill's version and summary; `installed`
  marks copies that have a newer version (`v1.2.1 (v1.3.0 available)`).
- If someone pushed a newer version since your copy, push warns and asks
  before replacing it (`-y` to skip the question). Get theirs with
  `skylls add my-skill -y`, redo your change, and push again.

Before anything is committed, `push` scans the skill with
[gitleaks](https://github.com/gitleaks/gitleaks) for API keys, tokens,
passwords, private keys, credential URLs and personal data (emails, phone
numbers, card numbers…). It uses the rules of the `git-scan-secrets` skill
(`~/.claude/skills/git-scan-secrets/gitleaks.toml` or `~/SKILLS/…`), or
gitleaks' defaults if that skill isn't installed. If anything is found, it lists
the file, line and rule (with the value redacted) and **pushes nothing**. Fix
the skill, or use `--skip-scan` if the findings are false positives.

### Find skills

```bash
skylls find pdf                    # keyword: name, folder, summary, description and SKILL.md text
skylls find deploy --folder work   # only inside one folder
skylls find --folder work          # everything in a folder
```

Best matches come first. Each result shows the version, folder, plain summary,
owner, who may update it, and when it was created and last updated, plus
related skills from the same folder. `list` and `installed` show the same
details. (`search` is different: it searches public skills on skills.sh.)

### For agents: find and share skills with few tokens

Teach your agents to use skylls once:

```bash
skylls agent-skill -g -a all     # installs a small 'skylls' skill for Claude Code, Codex and Gemini
```

That skill (~1.5 KB) tells agents to look things up with `--json`, which
prints one compact JSON object per line on stdout. Progress and errors go to
stderr, and empty fields are left out:

```bash
skylls find pdf --json --limit 5
{"name":"pdf-forms","folder":"docs","version":"1.3.0","summary":"Fills in PDF forms for you.","owner":"alice","updated":"2026-10-07"}
skylls installed --json
{"name":"pdf-forms","scope":"global","agent":"claude","version":"1.2.0","newer":"1.3.0"}
skylls log pdf-forms --json      # one line: details + version history
skylls list --json [query]       # every skill, one line each
```

- `find --json` returns at most 10 results unless you pass `--limit`; when
  more exist it says so on stderr.
- Fields: `name`, `folder`, `version`, `summary`, `owner`, `updated`,
  `installed` (`project`/`global`), and `updates: "owner"` for owner-only skills.
- The agent installs what it needs (`skylls add <name> -g -a all`) and shares
  only when you ask (`skylls push …`, or `skylls suggest …` for owner-only
  skills). The same permissions, secret scan and changelog apply.

### Folders

Skills can be grouped into folders in the shared repo (one level deep):

```bash
skylls folder                          # list folders and how many skills each has
skylls folder create work              # new folder (adds work/README.md)
skylls push my-skill --folder work     # a new skill goes straight into work/
skylls move my-skill work              # move a skill; '.' moves it back to the top level
skylls folder rename work job
skylls folder remove job               # only if empty; otherwise choose:
skylls folder remove job --keep-skills     # move its skills to the top level
skylls folder remove job --delete-skills   # delete them from the repo too (asks first)
```

- Skill names stay unique across folders, and installs are not affected by
  folders (`.claude/skills/my-skill`). Use `folder/name` (e.g.
  `skylls add work/my-skill`) only if two folders hold the same name.
- Deleted skills can still be installed by version (`skylls add my-skill@1.0.0`).
- Sharing gives friends the **whole repo**; GitHub can't share a single folder.

### Owners, permissions and suggestions

The person who **first uploads a skill is its owner** (for skills that were in
the repo before, whoever first committed them). When uploading a new skill,
the owner decides who may push updates:

```bash
skylls push my-skill --updates anyone   # default: any collaborator can push new versions
skylls push my-skill --updates owner    # only the owner; others must suggest
```

Without `--updates`, the first push asks. Only the owner can change it later.

| Who may…                                   | open skill (`anyone`) | owner-only skill |
|--------------------------------------------|-----------------------|------------------|
| push a new version                         | anyone                | owner            |
| move it to another folder                  | anyone                | owner            |
| rename / remove a folder that contains it  | anyone                | owner            |
| delete it (`folder remove --delete-skills`)| anyone (asks first)   | owner            |
| suggest an improvement                     | anyone                | anyone           |
| accept / decline suggestions               | owner                 | owner            |

**skylls never makes a commit that changes someone else's owner-only skill.**
Commands refuse up front, and as a last check every commit skylls makes is
inspected: if it touches an owner-only skill and you aren't its owner, nothing
is committed or pushed.

Everyone else can suggest improvements, and the owner decides:

```bash
skylls suggest my-skill "Also handle scanned PDFs"   # anyone (alias: comment)
skylls suggestions                                   # open suggestions, all skills
skylls suggestions my-skill                          # ...or one skill
skylls accept 12 -m "Done in 1.3.0"                  # owner: mark as done
skylls decline 13 -m "Out of scope"                  # owner: not planned
```

- Suggestions are GitHub issues in the shared repo, labelled `skill:<name>` and
  assigned to the owner, so the owner gets GitHub's notification and anyone
  can discuss them on GitHub. They need the `gh` CLI and a GitHub-hosted repo.
- Owners are identified by GitHub login (`gh`), or by git user name when that
  isn't available. Skills from before owners existed are decided by the repo
  owner.
- **Owner-only is enforced by skylls, not by GitHub.** Collaborators can still
  push with plain `git` or the GitHub website. It stops accidental overwrites
  between friends, not a determined collaborator.

### Get other people's changes

```bash
skylls pull                       # refresh the local copy of the repo
skylls pull --update -g           # ...and refresh your installed global skills
```

### Share the repo with friends

```bash
skylls share @alice @bob          # invite GitHub users as collaborators (needs gh auth login)
skylls share @carol --read-only   # add/pull only, no push — organization-owned repos only
skylls share                      # who has access, and who hasn't accepted yet
skylls unshare @bob               # revoke access (also cancels a pending invite)
```

`adduser` and `revoke` work as aliases for `share` and `unshare`. Revoking
removes access to the repo; skills a friend already installed stay on their
machine.

Each friend accepts the invite (GitHub emails it, or
`https://github.com/<owner>/<repo>/invitations`), installs skylls, and runs
`skylls setup --repo <owner>/<repo>`.

On a repo owned by a **personal account**, GitHub gives every collaborator push
access, so `--read-only` is refused there. For friends who should only read,
make the skills repo public (anyone can `add`/`pull`, only collaborators can
`push`), or move it to an organization.

### Friends' repos (sources)

Each person shares their own repos; you install from the ones you were invited to:

```bash
skylls share @bob                        # you: let bob install your skills
skylls agents share @bob                 # ...your agents
skylls swarms share @bob                 # ...your swarms

skylls source add alice/skills           # bob: after alice shared hers
skylls agents source add alice/agents
skylls swarms source add alice/Swarms
skylls source                            # list your sources (also: agents source, swarms source)
```

- `source add` only works if the owner invited you. **GitHub enforces who may
  download**: no invite, no access. `unshare` takes it away again.
- Sources are fetched as partial clones: listing a big repo downloads no file
  contents, and installing fetches only the files needed.
- Skills from a source: `skylls add pdf --from alice [-g -a all]`,
  `skylls add pdf@1.2.0 --from alice`, `skylls log pdf --from alice`,
  `skylls suggest pdf --from alice "…"`. `list` and `find` include your
  sources' skills too (`--from alice` for just one friend).

### Agents and swarms

Agents (`~/agents/<name>`) and swarms (`~/swarms/<name>`) work like skills,
with the commands under `skylls agents …` and `skylls swarms …`:

```bash
skylls agents                                # yours + your sources' (also: agents list [query])
skylls agents find bitcoin --json --limit 5
skylls agents push btc -m "Adds ETH" --minor # publish a version of YOUR agent
skylls agents add btc --from alice           # install alice's btc into ~/agents/btc
skylls agents add btc@1.0.0 --from alice --as btc-old
skylls agents log btc --from alice
skylls agents suggest btc --from alice "Also track SOL"
skylls agents suggestions / accept 3 / decline 4   # suggestions for yours
skylls swarms add apps_ideas --from alice    # same for swarms
```

**What is shared** is the *definition* of an agent or swarm, never its
runtime state:

| | shared | not shared |
|---|---|---|
| agent | `CLAUDE.md`/`AGENTS.md`/`GEMINI.md`, `.claude/` (settings, skills, commands), scripts and other files, **its memory folder** | `logs/`, `data/`, `reports/`, `scratch/`, `state/`, caches and venvs, `*.log`, `*.jsonl`, `*_state.json`, databases, `.claude/settings.local.json`, `.env*`, keys, files over 5 MB |
| swarm | top-level and per-role `CLAUDE.md`/`AGENTS.md`/`GEMINI.md` and `.claude/`, `.swarm/agents.json`, `.swarm/schedules.json`, **its memory folder** | the roles' work files, reports, `.swarm/bus.jsonl` and other state |

A `.skyllsignore` in the folder adjusts this (one pattern per line,
`!pattern` to include something).

**Memory (Obsidian) travels with them.** Keep each agent's or swarm's memory
**inside its own folder**, next to its `CLAUDE.md` (e.g. `~/agents/btc/wiki/`).
A subfolder counts as memory if it is an Obsidian vault (has `.obsidian/`) or
is named `memory`, `wiki`, `obsidian` or `*-wiki`. All of it is shared,
including its own `raw/`, `data/` or `reports/`, except Obsidian's per-user
window layout (`.obsidian/workspace*.json`), the trash and files over 5 MB.

Memory still kept elsewhere in `~/Obsidian` also works, for now:
- On `push`, skylls finds it in the instructions: a `~/Obsidian/<x>-wiki`
  vault they mention, or `~/Obsidian/<vault>/AGENTS/<name>/` for the item's own
  name. Other agents' folders and personal notes don't count.
- It snapshots that memory into `<item>/.skylls-memory/`, and friends get it
  restored to the same place under their home.
- A `.skyllsmemory` file (one path per line) chooses the folders yourself.
- Once the memory is inside the folder, no snapshot is made.

**Publishing** (`push`) works in your real `~/agents` / `~/swarms` clone:
1. It scans for secrets and personal data, including the memory.
2. It commits **only** that item's definition and memory snapshot (runtime
   files stay for your own commits).
3. It tags the commit `<name>@<version>` and pushes.

The changelog, plain summary and versions work as for skills. Each repo has one
owner, so friends download and suggest rather than push into yours.

**Installing** (`add`) fetches just the definition and memory:
- Memory inside the folder comes with it; memory from outside goes to the same
  place under your home (`~/Obsidian/btc-wiki/`).
- Absolute paths from the owner's machine (`/Users/alice/…`) are rewritten to
  yours, and any path that doesn't exist on your machine is listed.
- Running `add` again updates the definition. Your runtime data stays, and so
  does your memory unless you pass `--update-memory`.
- The copy records where it came from (`Source:` in its `CHANGELOG.md`), and
  you can publish your own version of it to your repo.

### Public skills from skills.sh

```bash
skylls search pdf                          # top matches with install counts
skylls add anthropics/skills/pdf -g        # install straight from that GitHub repo
```

Add `--dry-run` before any command to see what it would do without changing anything.

## Where skills get installed

| Agent       | `-a` name | Project (default)  | Global (`-g`)      |
|-------------|-----------|--------------------|--------------------|
| Claude Code | `claude`  | `./.claude/skills` | `~/.claude/skills` |
| Codex       | `codex`   | `./.agents/skills` | `~/.agents/skills` |
| Gemini CLI  | `gemini`  | `./.gemini/skills` | `~/.gemini/skills` |

**Global installs for several agents share one copy.** The real folder goes in
the first agent's directory (Claude when selected) and the other agents get a
**symlink** to it. Edit or update it once, and every agent sees the change.
Project installs are plain copies, so they're safe to commit into a project.

## How it works

```
GitHub repo (shared)  ⇄  ~/.cache/skylls/repo (local clone)
                             │ add (copy)             ▲ push (copy + commit + push)
                             ▼                        │
      ./.claude/skills   ~/.claude/skills ← real copy
      ./.agents/skills   ~/.agents/skills → symlink
      ./.gemini/skills   ~/.gemini/skills → symlink
```

- Config: `~/.config/skylls/config.json` (`repo`, default `agents`).
- The cache clone is refreshed automatically before `list`, `add`, `push` and `pull`.
- In the repo, skills are folders with a `SKILL.md`, at the top level or one
  folder down (`work/my-skill/`), under `skills/` if the repo has one.
- `remove` never deletes anything from GitHub. If you remove the real global
  copy while other agents still link to it, skylls warns you.

## Command reference

| Command | What it does |
|---------|--------------|
| `setup [--repo R] [--agents A] [--agents-repo R --agents-dir D] [--swarms-repo R --swarms-dir D]` | First run: your repos for skills, agents and swarms, and default agent CLIs |
| `list [query]` | List skills in the shared repo, grouped by folder |
| `find [words] [--folder F]` | Search the shared repo; shows summary, owner, permission, dates and related skills |
| `search <query> [--limit N]` | Search public skills on skills.sh |
| `add <name[@version]\|owner/repo/skill> [-g] [-a A] [-y]` | Install a skill, optionally an older version (`-y` overwrites without asking) |
| `remove <name> [-g] [-a A]` | Remove an installed copy |
| `installed [-g] [-a A]` | Show installed skills (project + global by default) |
| `push <name\|path> [-g] [-a A] [-m msg] [--minor\|--major] [--about text] [--folder F] [--updates anyone\|owner] [-y] [--skip-scan]` | Scan for secrets, then upload a new version to the shared repo |
| `log <name>` | Owner, permission and version history: what changed, when and by whom |
| `folder [create\|rename\|remove] …` | List, create, rename or remove folders (`remove --keep-skills\|--delete-skills [-y]`) |
| `move <name> <folder>` | Move a skill to a folder (`.` = top level) |
| `suggest <name> "text"` | Suggest an improvement to the skill's owner (GitHub issue) |
| `suggestions [name]` | List open suggestions |
| `accept <#> [-m note]` / `decline <#> [-m note]` | Owner: close a suggestion as done / not planned |
| `pull [--update] [-g] [-a A]` | Refresh the cache; `--update` refreshes installed copies |
| `share [@user...] [--read-only]` | Invite friends as collaborators (`--read-only`: org repos only); no names lists who has access |
| `unshare @user...` | Revoke a friend's access or cancel their pending invite |
| `agent-skill [-g] [-a A]` | Install the `skylls` skill that teaches agents to find, install and share skills |
| `--json` (before the command) | Compact JSON lines for `find`, `list`, `installed`, `log`; messages on stderr |
| `source [add\|remove] <owner/repo>` | Friends' skills repos you can install from (they must share first) |
| `add/list/find/log/suggest … --from OWNER` | Use a friend's skills repo |
| `agents …` / `swarms …` | `list`, `find`, `push`, `add [--from O] [--as N] [--update-memory]`, `log`, `source`, `share`, `unshare`, `suggest`, `suggestions`, `accept`, `decline` |
| `help` | Detailed help |

`-a` accepts `claude`, `codex`, `gemini`, a comma list, or `all`.

## Requirements

Python 3.11+, `git`, and GitHub access to the shared repo (SSH key or `gh auth
login`). [gitleaks](https://github.com/gitleaks/gitleaks) (`brew install
gitleaks`) for `push`. The GitHub CLI (`gh`, logged in) for setup (creating
your private repos), `share`/`unshare` and suggestions. The `claude` CLI for
the automatic plain summaries (optional). No Python dependencies.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
