---
name: skylls
description: Find, install and share agent skills, agents and swarms with the skylls CLI (each item lives in its own private GitHub repo; friends share items with each other). Use when a task needs a capability you don't have, the user asks which skills/agents/swarms exist, wants to install one, or wants to publish or share a skill, agent or swarm with other people or agents.
---

# skylls

Every skill, agent and swarm the user publishes is its own private GitHub repo; friends share items with them. Keep output small: use `--json` (one compact JSON object per line on stdout, messages on stderr) and `--limit`.

## 0. Is it installed?
    skylls --version
If not found, ask the user before installing:
    bash -c "$(curl -fsSL https://raw.githubusercontent.com/jcsancho/skylls/main/install.sh)"
If it asks for setup, tell the user to run `skylls setup` (it asks questions).
If results look wrong or a command is missing, check for a newer skylls: `skylls update --check` (`skylls update` installs it; ask first).

## 1. Find (the user's own + what friends shared)
    skylls find <keywords> --json --limit 5          # skills
    skylls agents find <keywords> --json --limit 5   # agents (also: skylls swarms find …)
    skylls find --folder <folder> --json             # everything in a folder
    skylls installed --json                          # installed skills; "newer" = update available
Fields: name, owner, folder, version, summary, updated, installed, published (false = not published yet).

## 2. Install
    skylls add <name> -g -a all                      # skill for Claude, Codex and Gemini, all projects
    skylls add <name>                                # skill for this project only
    skylls add <name> --from <owner> -g -a all       # when several owners have that name
    skylls agents add <name> --from <owner>          # agent → ~/agents/<name>, with its memory
    skylls swarms add <name> --from <owner>          # swarm → ~/swarms/<name>
    skylls pull --update                             # install newer versions of installed skills
Read an installed SKILL.md only when you are about to use it.

## 3. Details
    skylls log <name> --json                         # owner, versions, what changed

## 4. Publish and share (only when the user asks; confirm first)
    skylls push <name> -m "what changed"             # skill → its own private repo (<org>/skill-<name>)
    skylls agents push <name> -m "what changed"      # ~/agents/<name> (also: swarms push)
    skylls share <name> @user                        # one item to one person (agents share …)
    skylls source add <friend>                       # see what a friend shared with the user
    skylls suggest <name> --from <owner> "idea"      # improve someone else's item
- Push scans for API keys and personal data and refuses if it finds any: remove them, never use --skip-scan on your own.
- Sharing access and removing things are the user's decisions; never do them unprompted.

## Rules
- Prefer `--json` and `--limit`; add `--dry-run` before a command to preview it.
- Don't read or edit skylls' cache (~/.cache/skylls) or CHANGELOG.md files; skylls manages them.
- Don't install, publish, share or delete without the user's go-ahead.
