---
name: skylls
description: Find, install and share agent skills, agents and swarms with the skylls CLI (each item lives in its own private GitHub repo; friends share items with each other). Use when a task needs a capability you don't have, the user asks which skills/agents/swarms exist, wants to install one, or wants to publish or share a skill, agent or swarm with other people or agents.
---

# skylls

Every skill, agent and swarm the user publishes is its own private GitHub repo; friends share items with them. Keep output small: use `--json` (one compact JSON object per line on stdout, messages on stderr) and `--limit`.

## 0. Is it installed?
    skylls --version
If not found, ask the user before installing:
    curl -fsSL https://skylls.dev/install.sh | bash
If it asks for setup, tell the user to run `skylls setup` (it asks questions).
If results look wrong or a command is missing, check for a newer skylls: `skylls update --check` (`skylls update` installs it; ask first).

## 1. Find (the user's own + what friends shared)
    skylls find <keywords> --json --limit 5          # skills
    skylls agents find <keywords> --json --limit 5   # agents (also: skylls swarms find …)
    skylls find --folder <folder> --json             # everything in a folder
    skylls installed --json                          # installed skills; "newer" = update available
    skylls shared --json [@user]                     # shared by the user ("with", "pending") / with the user ("pending" = not accepted yet)
    skylls people --json                             # per person: you_share, they_share, waiting (+ accept command)
Fields: name, owner, folder, version, summary, updated, installed, published (false = not published yet).

## 2. Install
    skylls add <name> -g -a all                      # skill for Claude, Codex and Gemini, all projects
    skylls add <name>                                # skill for this project only
    skylls add <name> --from <owner> -g -a all       # when several owners have that name
    skylls agents add <name> --from <owner>          # agent → ~/agents/<name>, with its memory
    (updates and sync refresh its memory to the owner's; --keep-memory keeps the user's, theirs goes to <owner>-<wiki>/)
    skylls swarms add <name> --from <owner>          # swarm → ~/swarms/<name>
    skylls pull --update                             # install newer versions of installed skills
Read an installed SKILL.md only when you are about to use it.

## 3. Details
    skylls log <name> --json                         # owner, versions, what changed

## 4. Publish and share (only when the user asks; confirm first)
    skylls push <name> -m "what changed"             # skill → its own private repo (<org>/skill-<name>)
    skylls agents push <name> -m "what changed"      # ~/agents/<name> (also: swarms push)
    skylls share <name> @user                        # one item to one person (agents share …)
    skylls swarms share <name> @user --prs|--no-prs  # agents/swarms: ask the user whether they may send pull requests
    skylls unshare <name> @user                      # take one item back; skylls revoke @user = everything
    skylls source add <friend>                       # see what a friend shared with the user
    skylls sync -m "what changed"                    # take changes others pushed to the user's items, publish the user's changes, install friends' new versions
    skylls view                                      # first: what sync would publish/install + what isn't installed (changes nothing)
    skylls suggest <name> --from <owner> "idea"      # improve someone else's item
    skylls swarms propose <name> --from <owner> -m "what"   # your changes to a friend's agent/swarm copy → pull request
    skylls swarms allow-prs <name> | --all           # owner: let the people you share with send pull requests
    skylls suggestions / review <name>#<n> / accept <name>#<n> / decline <name>#<n>   # owner: answer (accept merges + publishes)
- Push scans for API keys and personal data and refuses if it finds any: remove them, never use --skip-scan on your own.
- Agent/swarm memory notes go with them, except notes with `private: true` in their frontmatter: write private facts (clients, people, money) there.
- Agents/swarms push lists new memory notes and asks; show the user that list, use -y only after they agree. sync publishes them without asking: run view first when the user wants to check them.
- Sharing access and removing things are the user's decisions; never do them unprompted.

## Rules
- Prefer `--json` and `--limit`; add `--dry-run` to a command to preview it.
- Don't read or edit skylls' cache (~/.cache/skylls) or CHANGELOG.md files; skylls manages them.
- Don't install, publish, share or delete without the user's go-ahead.
