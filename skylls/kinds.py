"""
One private GitHub repo per item: skills, agents and swarms.

Every item you publish lives in its own private repo, in your account or an
organization chosen at setup:

    <owner>/skylls-skill-<name>   <owner>/skylls-agent-<name>   <owner>/skylls-swarm-<name>

The repo holds only what friends may see (a skill's files; an agent's or
swarm's definition and memory) plus CHANGELOG.md. Versions are tags (v1.2.0).
Folders are GitHub topics. You share item by item (GitHub invites); friends
add you once (`skylls source add <owner>`), which accepts your invites, and
from then on they see exactly what you shared with them.

The catalog (what you and your friends have) comes from two GitHub GraphQL
queries: one lists the repos you can access, one reads the skylls repos'
changelogs and instruction files. Downloads and publishing use small clones
in ~/.cache/skylls/repos/<owner>/<repo>.

Agents and swarms: only the definition is shared (instructions, .claude/,
scripts, swarm config), never runtime state, plus the item's Obsidian memory
(a memory folder inside it, or legacy memory elsewhere in ~/Obsidian that is
snapshotted into .skylls-memory/).
"""

import argparse
import fnmatch
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple

from skylls import cli as core
from skylls.cli import BLUE, CYAN, GREEN, NC, YELLOW, die, emit, fail, git, info, ok, say, section, warn

REPOS_CACHE = Path.home() / ".cache" / "skylls" / "repos"
MAX_FILE = 5 * 1024 * 1024  # files bigger than this are not shared (agents/swarms/memory)
KINDS = {
    "skills": {"one": "skill", "main": ("SKILL.md",)},
    "agents": {"one": "agent", "main": ("CLAUDE.md", "AGENTS.md", "GEMINI.md")},
    "swarms": {"one": "swarm", "main": ("CLAUDE.md", "AGENTS.md", "GEMINI.md")},
}
SUGGESTION = "suggestion"  # issue label for suggestions
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}")
# Runtime state of agents and swarms: never shared.
RUNTIME_DIRS = {"logs", "data", "reports", "scratch", "state", "output", "outputs", "tmp", "temp", "cache",
                ".cache", "node_modules", ".venv", "venv", "env", "__pycache__", ".git",
                ".pytest_cache", ".mypy_cache", "dist", "build"}
RUNTIME_FILES = ["*.log", "*.jsonl", "*_state.json", "*.bak", "*.bak-*", "*.db", "*.sqlite", "*.sqlite3",
                 "*.pyc", ".DS_Store", "settings.local.json", ".env", ".env.*", "*.env", "*.pem", "*.key"]
# A swarm is shared as its configuration only: instructions and settings, top level and per role.
SWARM_KEEP = ["CLAUDE.md", "AGENTS.md", "GEMINI.md", "README.md", "CHANGELOG.md", ".skyllsignore", ".skyllsmemory",
              ".skylls-skills",
              ".claude/*", ".swarm/agents.json", ".swarm/schedules.json", "*/CLAUDE.md", "*/AGENTS.md",
              "*/GEMINI.md", "*/.claude/*"]
# ... plus the scripts those instructions run (`python3 check_cards.py`, `~/swarms/x/set_goal.sh`): without them
# a friend's copy of the swarm breaks at the first step that calls one.
INSTRUCTION_FILES = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")
SCRIPT_REF_RE = re.compile(r"[\w.~/-]*[\w-]\.(?:py|sh|js|mjs|cjs|ts|rb|pl)\b")
MEMORY_NAMES = {"memory", "wiki", "obsidian"}  # in-folder memory, besides any Obsidian vault or *-wiki
MEMORY_DIR = ".skylls-memory"  # snapshot of memory kept outside the item, by path under the owner's home
# Obsidian's per-user state and downloaded plugins/themes (third-party code) are not shared.
MEMORY_SKIP = [".obsidian/workspace*", ".obsidian/plugins/*", ".obsidian/themes/*", ".trash/*", ".DS_Store", "*.tmp"]
# Skills copied into an agent/swarm that are your skylls skills are shared as a reference, not a copy:
# one '<folder> <owner>/<repo>' line per skill in this file; installs fetch them from skylls.
SKILLS_MANIFEST = ".skylls-skills"
BUNDLED_RE = re.compile(r"((?:[^/]+/)?\.(?:claude|agents|gemini)/skills/([^/]+))/")
OBSIDIAN_RE = re.compile(r"(?:~|\$HOME|\$\{HOME\}|\bHOME|/Users/[^/\s\"'`]+|/home/[^/\s\"'`]+)"
                         r"/(Obsidian/[^\s\"'`)\]>,;*]+)")


# ── Names, repos, folders ──────────────────────────────────────────────────
def one(kind: str) -> str:
    return KINDS[kind]["one"]


def an(word: str) -> str:
    return f"{'an' if word[0] in 'aeiou' else 'a'} {word}"


def repo_name(kind: str, name: str, org: bool) -> str:
    """In an organization the org already groups everything: 'skill-pdf'. In a personal account the
    prefix keeps skylls repos apart from your other projects: 'skylls-skill-pdf'."""
    return f"{one(kind)}-{name}" if org else f"skylls-{one(kind)}-{name}"


def item_of(repo: str, short: bool = True) -> Optional[Tuple[str, str]]:
    """'owner/skylls-agent-btc' or 'org/agent-btc' → ('agents', 'btc'); None for other repos.
    Short names only count once the repo carries the 'skylls' topic (checked by the caller)."""
    base = repo.rsplit("/", 1)[-1]
    for prefix_fmt in ("skylls-{}-", "{}-") if short else ("skylls-{}-",):
        for kind, spec in KINDS.items():
            prefix = prefix_fmt.format(spec["one"])
            if base.startswith(prefix) and len(base) > len(prefix):
                return kind, base[len(prefix):]
    return None


def item_repo(cfg: dict, kind: str, name: str) -> str:
    """Your repo for an item: <owner>/skill-<name> in an organization, <owner>/skylls-skill-<name> otherwise
    (an existing repo with the other naming is reused)."""
    org = cfg.get("owner_is_org", False)
    preferred = f"{cfg['owner']}/{repo_name(kind, name, org)}"
    other = f"{cfg['owner']}/{repo_name(kind, name, not org)}"
    if core.gh("repo", "view", preferred).returncode != 0 and core.gh("repo", "view", other).returncode == 0:
        return other
    return preferred


def check_name(name: str) -> str:
    if not NAME_RE.fullmatch(name):
        die(f"'{name}' can't be a repo name: use letters, digits, '.', '_' and '-'.")
    return name


def folder_topic(folder: str) -> str:
    """A folder is a GitHub topic: lowercase letters, digits and dashes."""
    topic = re.sub(r"[^a-z0-9-]+", "-", folder.lower()).strip("-")[:50]
    if not topic or topic.startswith("skylls"):
        die(f"'{folder}' can't be a folder name.")
    return topic


def system_topics(kind: str) -> List[str]:
    return ["skylls", f"skylls-{one(kind)}"]


def mine(cfg: dict, owner: str) -> bool:
    return owner.lower() in {cfg["owner"].lower(), cfg["login"].lower()}


def is_org(owner: str) -> bool:
    res = core.gh_api(f"users/{owner}")
    return res.returncode == 0 and (gh_json(res) or {}).get("type") == "Organization"


def gh_json(res: subprocess.CompletedProcess):
    """Parse gh output; --paginate prints one JSON document per page, so list pages are joined."""
    text, out, docs, pos = res.stdout.strip(), [], 0, 0
    decoder = json.JSONDecoder()
    while pos < len(text):
        doc, end = decoder.raw_decode(text, pos)
        docs += 1
        if isinstance(doc, list):
            out += doc
        elif docs == 1:
            out = doc
        pos = end
        while pos < len(text) and text[pos].isspace():
            pos += 1
    return out if docs else None


def gh_ok(*args: str, what: str) -> subprocess.CompletedProcess:
    res = core.gh(*args)
    if res.returncode != 0:
        die(f"{what}: {(res.stderr or res.stdout).strip()}")
    return res


ORG_NEW_URL = "https://github.com/account/organizations/new?plan=free"


def admin_orgs() -> List[str]:
    """Organizations where you can create repos."""
    return [m["organization"]["login"] for m in (gh_json(core.gh_api("user/memberships/orgs")) or [])
            if m.get("role") == "admin" and m.get("state", "active") == "active"]


def org_howto(login: str) -> None:
    say(f"""
  {CYAN}Recommended: a GitHub organization for your skylls repos{NC}
  An organization is a free GitHub account that holds repos for you, like a folder. It keeps every
  skill, agent and swarm repo together and apart from your other repos, and lets friends you share
  with have read-only access. To create one (about a minute):
    1. Open {ORG_NEW_URL}
       (logged in to GitHub as {login})
    2. Pick a name, e.g. {login}-skylls, and enter your email.
    3. "This organization belongs to": My personal account.
    4. Click Next; skip adding members. Don't add friends as members: you share with them item by
       item with skylls, and members can see every repo the organization's base permission allows.
""")


def ensure_org_private(org: str) -> None:
    """Members of an organization get its base permission on every repo (GitHub's default: read).
    skylls shares item by item, so the base permission should be 'none'."""
    res = core.gh_api(f"orgs/{org}")
    base = (gh_json(res) or {}).get("default_repository_permission") if res.returncode == 0 else None
    if base in (None, "none"):
        return
    warn(f"Members of {org} can {base} every repo in it (its base permission). skylls shares item by item, "
         "so nothing should be visible by default.")
    if not sys.stdin.isatty():
        info(f"Fix it: gh api -X PATCH orgs/{org} -f default_repository_permission=none  "
             f"(or github.com/organizations/{org}/settings/member_privileges)")
        return
    if input(f"  {YELLOW}?{NC} Set {org}'s base permission to 'No permission'? (Y/n): ").strip().lower() != "n":
        res = core.gh_api("-X", "PATCH", f"orgs/{org}", "-f", "default_repository_permission=none")
        if res.returncode == 0:
            ok(f"Members of {org} now only see the repos shared with them.")
        else:
            warn(f"Could not change it ({res.stderr.strip()}); do it at "
                 f"github.com/organizations/{org}/settings/member_privileges")


def choose_owner(login: str, given: Optional[str], current: Optional[str]) -> str:
    """Where your skylls repos live: an organization you administer (recommended) or your account."""
    orgs = admin_orgs()
    if given:
        if given.lower() != login.lower() and given.lower() not in {o.lower() for o in orgs}:
            die(f"You can't create repos in '{given}': use your account ({login}) or an organization you administer.")
        return given
    interactive = sys.stdin.isatty()
    if not orgs and current in (None, "", login):
        warn("You don't have a GitHub organization yet.")
        org_howto(login)
        if not interactive:
            info(f"Using your account ({login}) for now. After creating an organization, run: skylls setup")
            return login
        if input(f"  {YELLOW}?{NC} Open that page in your browser now? (Y/n): ").strip().lower() != "n":
            import webbrowser
            webbrowser.open(ORG_NEW_URL)
        while not orgs:
            answer = input(f"  {YELLOW}?{NC} Press Enter once it's created (or type 'account' to use your "
                           f"account {login} for now): ").strip().lower()
            if answer == "account":
                info("Using your account. Switch to an organization any time with: skylls setup")
                return login
            orgs = admin_orgs()
            if not orgs:
                warn("No organization found yet (it can take a few seconds). Try again, or type 'account'.")
        ok(f"Found your organization: {orgs[0]}")
    # An organization is the recommended home: it groups every skill/agent/swarm repo, keeps them apart
    # from your other repos, and lets friends have read-only access.
    default = current if current and (current == login or current in orgs) else (orgs[0] if orgs else login)
    if not interactive:
        return default
    say("  Where should your skills, agents and swarms be published (each in its own private repo)?")
    choices = orgs + [login]
    for i, choice in enumerate(choices, 1):
        tag = "your account" if choice == login else \
            "organization, recommended" if choice == orgs[0] else "organization"
        say(f"    {i}. {choice}  ({tag})")
    answer = input(f"  {YELLOW}?{NC} Choose 1-{len(choices)} [{choices.index(default) + 1}]: ").strip()
    if not answer:
        return default
    if answer.isdigit() and 1 <= int(answer) <= len(choices):
        return choices[int(answer) - 1]
    return choose_owner(login, answer, current)


def ensure_private(repo: str) -> None:
    res = core.gh("repo", "view", repo, "--json", "visibility")
    if res.returncode != 0 or (gh_json(res) or {}).get("visibility") != "PUBLIC":
        return
    warn(f"{repo} is PUBLIC: everyone can see it.")
    if sys.stdin.isatty() and input(f"  {YELLOW}?{NC} Make it private? (Y/n): ").strip().lower() != "n":
        res = core.gh("repo", "edit", repo, "--visibility", "private", "--accept-visibility-change-consequences")
        if res.returncode == 0:
            ok(f"{repo} is now private.")
        else:
            warn(f"Could not change it: {res.stderr.strip()}")


# ── Catalog: what you and your friends have ────────────────────────────────
LIST_QUERY = """query($endCursor: String) { viewer { repositories(first: 100, after: $endCursor,
  affiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER],
  ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {
  nodes { name owner { login } } pageInfo { hasNextPage endCursor } } } }"""
ITEM_FIELDS = """name owner { login } isPrivate pushedAt url
  defaultBranchRef { target { oid } }
  repositoryTopics(first: 20) { nodes { topic { name } } }
  changelog: object(expression: "HEAD:CHANGELOG.md") { ... on Blob { text } }
  skillmd: object(expression: "HEAD:SKILL.md") { ... on Blob { text } }
  claudemd: object(expression: "HEAD:CLAUDE.md") { ... on Blob { text } }
  agentsmd: object(expression: "HEAD:AGENTS.md") { ... on Blob { text } }
  issues(states: OPEN, labels: ["suggestion"], first: 50) {
    nodes { number title url createdAt author { login } } }
  pullRequests(states: OPEN, first: 50) { nodes { number title url createdAt author { login } } }"""
_catalog: Dict[str, List[dict]] = {}


def graphql(query: str, fail: bool = True, **variables: str) -> Optional[dict]:
    """Run a GraphQL query, retrying once (GitHub answers 502/504 when a query takes too long).
    fail=False returns None instead of stopping."""
    args = ["graphql", "-f", f"query={query}"] + [f"-f{k}={v}" for k, v in variables.items()]
    for _ in range(2):
        res = core.gh_api(*args)
        if res.returncode == 0:
            return gh_json(res)["data"]
    if fail:
        die(f"GitHub query failed: {res.stderr.strip()}")
    return None


def read_items(chunk: List[str]) -> dict:
    """The ITEM_FIELDS of these repos; a batch GitHub can't answer in time is split in halves."""
    aliases = " ".join(f'r{i}: repository(owner: "{r.split("/")[0]}", name: "{r.split("/")[1]}") '
                       f'{{ {ITEM_FIELDS} }}' for i, r in enumerate(chunk))
    data = graphql(f"query {{ {aliases} }}", fail=len(chunk) == 1)
    if data is not None:
        return data
    half = len(chunk) // 2
    return {**{f"a{k}": v for k, v in read_items(chunk[:half]).items()},
            **{f"b{k}": v for k, v in read_items(chunk[half:]).items()}}


def accept_invites(owners: set) -> Tuple[int, Dict[str, List[dict]], set]:
    """Accept pending invites to skylls repos from these owners (or sent by them); list the others by owner.
    Also returns the new owners (a friend's organization) of repos accepted because a friend sent the invite."""
    invites = gh_json(core.gh_api("user/repository_invitations", "--paginate")) or []
    accepted, waiting, new_owners = 0, {}, set()
    for inv in invites:
        repo = (inv.get("repository") or {}).get("full_name", "")
        if not item_of(repo):
            continue
        owner = repo.split("/")[0]
        inviter = (inv.get("inviter") or {}).get("login", "")
        if owner.lower() in owners or inviter.lower() in owners:
            if core.gh_api("-X", "PATCH", f"user/repository_invitations/{inv['id']}").returncode == 0:
                accepted += 1
                if owner.lower() not in owners:
                    new_owners.add(owner)
        else:
            kind, name = item_of(repo)
            waiting.setdefault(owner, []).append({"kind": kind, "name": name, "repo": repo, "inviter": inviter,
                                                  "invited": (inv.get("created_at") or "")[:10]})
    return accepted, waiting, new_owners


def catalog(cfg: dict, kind: Optional[str] = None, owner: Optional[str] = None, quiet: bool = False) -> List[dict]:
    """Items you and your friends published (that you can see), fresh from GitHub once per run.
    Invites from people who aren't your friends yet are kept in _catalog["waiting"] (quiet: don't mention them)."""
    if "all" not in _catalog:
        owners = {cfg["owner"].lower(), cfg["login"].lower()} | {f.lower() for f in cfg.get("friends", [])}
        core.progress(0, 1, "GitHub: checking invites")
        accepted, waiting, new_owners = accept_invites(owners)
        if new_owners:  # a friend shares from their organization: list its items too
            cfg.setdefault("friends", []).extend(sorted(new_owners))
            core.save_config(cfg)
            owners |= {o.lower() for o in new_owners}
        if accepted:
            ok(f"Accepted {accepted} new share{'s' if accepted != 1 else ''} from your friends.")
        _catalog["waiting"] = waiting
        for who, n in ((w, len(items)) for w, items in waiting.items() if not quiet):
            info(f"@{who} shared {n} item{'s' if n != 1 else ''} with you: skylls source add {who}")
        repos, cursor = [], ""
        while True:
            core.progress(0, 1, f"GitHub: listing your repos ({len(repos)} so far)")
            page = graphql(LIST_QUERY, **({"endCursor": cursor} if cursor else {}))["viewer"]["repositories"]
            repos += [f"{n['owner']['login']}/{n['name']}" for n in page["nodes"]]
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]
        wanted = [r for r in repos if item_of(r) and r.split("/")[0].lower() in owners]
        unknown = sorted({r.split("/")[0] for r in repos if item_of(r)} - {r.split("/")[0] for r in wanted})
        for who in ([] if quiet else unknown):  # shared earlier (already accepted) by someone not a source
            info(f"{who} may have shared skylls items with you: skylls source add {who}")
        records_ = []
        for start in range(0, len(wanted), 20):  # 40 big items can take GitHub over its 10 s limit
            chunk = wanted[start:start + 20]
            core.progress(start, len(wanted), f"GitHub: reading items {start + 1}-{start + len(chunk)}")
            data = read_items(chunk)
            records_ += [rec for node in data.values() if node and (rec := to_record(cfg, node))]
        core.progress_clear()
        _catalog["all"] = sorted(records_, key=lambda r: (r["kind"], r["name"].lower(), r["owner"].lower()))
    return [r for r in _catalog["all"] if (not kind or r["kind"] == kind)
            and (not owner or r["owner"].lower() == owner.lower())]


def to_record(cfg: dict, node: dict) -> Optional[dict]:
    """A catalog record; None for a short-named repo ('agent-x') without the 'skylls' topic."""
    topics = [t["topic"]["name"] for t in (node.get("repositoryTopics") or {}).get("nodes", [])]
    if not item_of(node["name"], short=False) and "skylls" not in topics:
        return None
    kind, name = item_of(node["name"])
    owner = node["owner"]["login"]
    log = core.parse_changelog((node.get("changelog") or {}).get("text", ""))
    text = next(((node.get(k) or {}).get("text", "") for k in ("skillmd", "claudemd", "agentsmd")
                 if node.get(k)), "")
    return {"kind": kind, "name": name, "owner": owner, "mine": mine(cfg, owner),
            "repo": f"{owner}/{node['name']}", "folder": next((t for t in topics if not t.startswith("skylls")), ""),
            "version": log["entries"][0]["version"] if log["entries"] else None,
            "summary": log["about"] or summary_from(text),
            "updated": log["entries"][0]["date"] if log["entries"] else None,
            "created": log["created"], "by": log["created_by"], "log": log, "text": text,
            "suggestions": (node.get("issues") or {}).get("nodes", [])
            + [{**pr, "pr": True} for pr in (node.get("pullRequests") or {}).get("nodes", [])],
            "private": node.get("isPrivate", True),
            "head": ((node.get("defaultBranchRef") or {}).get("target") or {}).get("oid", "")}


def summary_from(text: str) -> str:
    """Fallback summary: a SKILL.md description, or the first plain line of an instruction file."""
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                break
            if line.startswith("description:"):
                desc = line[len("description:"):].strip().strip("\"'")
                if desc in (">", "|", ">-", "|-") and i + 1 < len(lines):
                    desc = lines[i + 1].strip()
                return desc[:117] + "..." if len(desc) > 120 else desc
    for line in lines:
        line = line.strip().lstrip("#>*- ").strip()
        if len(line) > 15 and not line.startswith(("---", "<!--")):
            return line[:117] + "..." if len(line) > 120 else line
    return ""


def resolve(cfg: dict, kind: str, name: str, owner: Optional[str]) -> dict:
    """The catalog record for <name> (from <owner>, if given)."""
    hits = [r for r in catalog(cfg, kind, owner) if r["name"].lower() == name.lower()]
    if not hits:
        where = f" from {owner}" if owner else ""
        die(f"No {one(kind)} '{name}'{where} that you can see. Try: skylls{cmd_prefix(kind)} find {name}")
    if len(hits) > 1:
        mine_hits = [r for r in hits if r["mine"]]
        if len(mine_hits) == 1:
            return mine_hits[0]
        die(f"'{name}' exists for {', '.join(r['owner'] for r in hits)}; add --from <owner>.")
    return hits[0]


def cmd_prefix(kind: str) -> str:
    return "" if kind == "skills" else f" {kind}"


# ── Local clones of item repos ─────────────────────────────────────────────
def sync_item(repo: str) -> Path:
    """A clone of an item repo in the cache, up to date with GitHub."""
    path = REPOS_CACHE / repo
    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        res = git("clone", "--quiet", core.repo_url(repo), str(path), cwd=path.parent, check=False)
        if res.returncode != 0:
            die(f"Could not get {repo}: {res.stderr.strip()}")
    else:
        git("fetch", "--quiet", "--tags", "--force", "--prune", "origin", cwd=path)
    if git("rev-parse", "--verify", "--quiet", "origin/main", cwd=path, check=False).returncode == 0:
        git("checkout", "--quiet", "-B", "main", "origin/main", cwd=path)
        git("reset", "--quiet", "--hard", "origin/main", cwd=path)
        git("clean", "-fdq", cwd=path)
    return path


def versions(path: Path) -> List[str]:
    tags = git("tag", "-l", "v*", cwd=path).stdout.split()
    return sorted((t[1:] for t in tags if re.fullmatch(r"v\d+\.\d+\.\d+", t)), key=core.version_key)


def extract(kind: str, rec: dict, version: Optional[str], tmp: Path) -> Tuple[Path, List[str], dict]:
    """Unpack an item at a version (default: latest) into tmp; returns (folder, shareable files, changelog)."""
    path = sync_item(rec["repo"])
    ref = "HEAD"
    if version:
        version = version.lstrip("v")
        if version not in versions(path):
            die(f"No version {version} of {rec['repo']}. Available: {', '.join(versions(path)) or 'none'}")
        ref = f"v{version}"
    res = subprocess.run(["git", "archive", "--format=tar", ref], cwd=path, capture_output=True)
    if res.returncode != 0:
        die(f"Could not read {rec['repo']} at {ref}: {res.stderr.decode(errors='ignore').strip()}")
    out = tmp / rec["name"]
    out.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(res.stdout)) as tar:
        tar.extractall(out, filter="data")
    rels = local_files(kind, out)
    keep = set(rels) | {core.CHANGELOG}
    for extra in [p for p in out.rglob("*") if p.is_file() and p.relative_to(out).as_posix() not in keep]:
        extra.unlink()  # defence in depth: never install what wouldn't be shared
    return out, [r for r in rels if r != core.CHANGELOG], core.read_changelog(out)


# ── What gets shared ───────────────────────────────────────────────────────
def parse_rules(text: str) -> List[str]:
    """.skyllsignore: one pattern per line; 'pattern' excludes, '!pattern' includes; last match wins."""
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]


def rule_matches(rel: str, pattern: str) -> bool:
    pattern = pattern.strip("/")
    return fnmatch.fnmatch(rel, pattern) or rel.startswith(pattern + "/") or \
        fnmatch.fnmatch(rel.rsplit("/", 1)[-1], pattern)


def is_memory_name(name: str) -> bool:
    return name.lower() in MEMORY_NAMES or name.lower().endswith("-wiki")


def memory_dirs_in(rels: List[str]) -> List[str]:
    """Top-level subfolders of an item that are its memory (from its file list)."""
    found = set()
    for rel in rels:
        parts = rel.split("/")
        if len(parts) > 1 and not parts[0].startswith(".") and (is_memory_name(parts[0]) or parts[1] == ".obsidian"):
            found.add(parts[0])
    return sorted(found)


def local_memory_dirs(item: Path) -> List[str]:
    if not item.is_dir():
        return []
    return sorted(d.name for d in item.iterdir() if d.is_dir() and not d.name.startswith(".")
                  and (is_memory_name(d.name) or (d / ".obsidian").is_dir()))


def memory_file_ok(inner: str, size: int) -> bool:
    """Inside a memory folder: everything but Obsidian's per-user state, the trash and big files."""
    return size <= MAX_FILE and ".trash/" not in inner and \
        not any(fnmatch.fnmatch(inner, pat) or fnmatch.fnmatch(inner.rsplit("/", 1)[-1], pat) for pat in MEMORY_SKIP)


PRIVATE_RE = re.compile(r"^private:\s*(?:true|yes)\s*$", re.I | re.M)


def private_note(path: Path) -> bool:
    """A memory note whose frontmatter says 'private: true' stays home."""
    if path.suffix.lower() != ".md":
        return False
    try:
        with path.open(errors="ignore") as f:
            head = f.read(4096)
    except OSError:
        return False
    if not head.startswith("---"):
        return False
    end = head.find("\n---", 3)
    return bool(PRIVATE_RE.search(head[3:end if end > 0 else len(head)]))


def referenced_scripts(item: Path) -> FrozenSet[str]:
    """Scripts inside a swarm that its instruction files (top level and per role) mention, as paths relative to it.
    A mention may be relative to the instruction file, to the swarm, or a longer path ending in one of those."""
    found = set()
    docs = [item / n for n in INSTRUCTION_FILES] + [d for n in INSTRUCTION_FILES for d in item.glob(f"*/{n}")]
    for doc in docs:
        if not doc.is_file():
            continue
        for ref in set(SCRIPT_REF_RE.findall(doc.read_text(errors="ignore"))):
            parts = [x for x in ref.split("/") if x not in ("", ".", "~")]
            for i in range(len(parts)):  # longest suffix first: '~/swarms/x/check_cards.py' → 'check_cards.py'
                tail = "/".join(parts[i:])
                for base in (doc.parent, item):
                    cand = base / tail
                    if cand.is_file() and not cand.is_symlink():
                        try:
                            found.add(cand.resolve().relative_to(item.resolve()).as_posix())
                        except ValueError:
                            pass
                        break
                else:
                    continue
                break
    return frozenset(found)


def shareable(kind: str, rel: str, rules: List[str], size: int = 0, memory: Tuple[str, ...] = (),
              scripts: FrozenSet[str] = frozenset()) -> bool:
    """Is this file (path relative to the item) part of what is published and downloaded?"""
    parts = rel.split("/")
    if kind != "skills" and len(parts) > 1 and (parts[0] in memory or parts[0] == MEMORY_DIR):
        keep = memory_file_ok("/".join(parts[1:]), size)
    elif kind == "skills":
        keep = not any(p in (".git", "__pycache__") for p in parts) and parts[-1] != ".DS_Store"
    else:
        keep = (size <= MAX_FILE and not any(p in RUNTIME_DIRS for p in parts[:-1])
                and not any(fnmatch.fnmatch(parts[-1], pat) for pat in RUNTIME_FILES)
                and not rel.startswith(".agent/state/"))
        if kind == "swarms":
            keep = keep and (any(fnmatch.fnmatch(rel, pat) for pat in SWARM_KEEP) or rel in scripts)
    for rule in rules:
        negate = rule.startswith("!")
        if rule_matches(rel, rule[1:] if negate else rule):
            keep = negate
    return keep


def local_files(kind: str, item: Path) -> List[str]:
    """Shareable files of a local item, as paths relative to it."""
    ignore = item / ".skyllsignore"
    rules = parse_rules(ignore.read_text(errors="ignore")) if ignore.is_file() else []
    prune = {".git", "node_modules", ".venv", "venv", "__pycache__"}
    if kind != "skills" and not any(r.startswith("!") for r in rules):
        prune |= RUNTIME_DIRS
    memory = tuple(local_memory_dirs(item)) if kind != "skills" else ()
    scripts = referenced_scripts(item) if kind == "swarms" else frozenset()
    out = []
    for dirpath, dirnames, filenames in os.walk(item):
        top = Path(dirpath).relative_to(item).parts[:1]
        in_memory = bool(top) and (top[0] == MEMORY_DIR or top[0] in memory)
        dirnames[:] = [d for d in dirnames if d not in ({".git", ".trash"} if in_memory else prune)]
        for f in filenames:
            path = Path(dirpath) / f
            if path.is_symlink():
                continue
            rel = path.relative_to(item).as_posix()
            if in_memory and private_note(path):
                continue
            if shareable(kind, rel, rules, path.stat().st_size, memory, scripts):
                out.append(rel)
    return sorted(out)


def bundled_skills(cfg: dict, files: List[str]) -> Dict[str, str]:
    """Skill folders copied into an agent/swarm that are your published skills: {folder: repo}."""
    mine = {r["name"].lower(): r["repo"] for r in catalog(cfg, "skills") if r["mine"]}
    found = {}
    for rel in files:
        m = BUNDLED_RE.match(rel)
        if m and m.group(2).lower() in mine:
            found[m.group(1)] = mine[m.group(2).lower()]
    return found


def read_manifest(item: Path) -> Dict[str, str]:
    path = item / SKILLS_MANIFEST
    lines = path.read_text(errors="ignore").splitlines() if path.is_file() else []
    pairs = [line.split() for line in lines]
    return {p[0]: p[1] for p in pairs if len(p) == 2 and BUNDLED_RE.match(p[0] + "/") and ".." not in p[0]}


def install_bundled(cfg: dict, item: Path, folder: str, repo: str) -> None:
    """Put the latest version of a referenced skill into the agent/swarm (a copy)."""
    name = folder.rsplit("/", 1)[-1]
    r = next((x for x in catalog(cfg, "skills") if x["repo"].lower() == repo.lower()), None)
    if not r:
        warn(f"Skill {name} ({folder}/) is {repo}, which isn't shared with you. "
             f"Ask its owner: skylls share {name} @{cfg['login']}, then install this again.")
        return
    with tempfile.TemporaryDirectory() as tmp:
        src, _, log = extract("skills", r, None, Path(tmp))
        got = log["entries"][0]["version"] if log["entries"] else "latest"
        log["source"] = f"{r['repo']} v{got}"
        core.write_changelog(src, r["name"], log)
        core.remove_path(item / folder)
        shutil.copytree(src, item / folder)
    ok(f"Skill {name} v{got} → {folder}/")


def is_item(kind: str, path: Path) -> bool:
    if not path.is_dir() or path.name.startswith("."):
        return False
    return any((path / m).is_file() for m in KINDS[kind]["main"]) or \
        (kind == "swarms" and (path / ".swarm").is_dir())


def main_file(kind: str, path: Path) -> Optional[Path]:
    return next((path / m for m in KINDS[kind]["main"] if (path / m).is_file()), None)


# ── Obsidian memory kept outside the item (legacy) ─────────────────────────
def memory_roots(kind: str, item: Path) -> List[str]:
    """Memory folders outside the item, as paths under your home ('Obsidian/btc-wiki').

    `.skyllsmemory` (one path per line) decides if present. Otherwise they are
    found in the instructions: `<x>-wiki` vaults they mention, and
    `<vault>/AGENTS/<name>` when <name> is this item."""
    home = Path.home()
    listed = item / ".skyllsmemory"
    if listed.is_file():
        roots = []
        for line in parse_rules(listed.read_text(errors="ignore")):
            path = Path(os.path.expanduser(line.replace("$HOME", "~"))).absolute()
            try:
                roots.append(path.relative_to(home).as_posix())
            except ValueError:
                warn(f".skyllsmemory: {line} is not inside your home folder; skipped")
        return sorted(r for r in roots if (home / r).is_dir() and not (home / r).is_relative_to(item))
    found = set()
    for rel in local_files(kind, item):
        if rel.startswith(MEMORY_DIR + "/") or not rel.endswith((".md", ".json", ".yaml", ".yml", ".toml", ".txt")):
            continue
        for m in OBSIDIAN_RE.finditer((item / rel).read_text(errors="ignore")):
            parts = m[1].rstrip("/.").split("/")
            if len(parts) >= 2 and parts[1].endswith("-wiki"):
                found.add("/".join(parts[:2]))
            elif len(parts) >= 4 and parts[2] == "AGENTS" and parts[3].lower() == item.name.lower():
                found.add("/".join(parts[:4]))
    return sorted(r for r in found if (home / r).is_dir())


def snapshot_memory(item: Path, roots: List[str]) -> int:
    """Mirror outside memory folders into <item>/.skylls-memory/; returns the number of files."""
    snap = item / MEMORY_DIR
    wanted: Dict[str, Path] = {}
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(Path.home() / root):
            dirnames[:] = [d for d in dirnames if d not in (".git", ".trash")]
            for f in filenames:
                src = Path(dirpath) / f
                inner = src.relative_to(Path.home() / root).as_posix()
                if not src.is_symlink() and memory_file_ok(inner, src.stat().st_size) and not private_note(src):
                    wanted[f"{root}/{inner}"] = src
    if snap.exists():
        for old in [p for p in snap.rglob("*") if p.is_file()]:
            if old.relative_to(snap).as_posix() not in wanted:
                old.unlink()
    for rel, src in wanted.items():
        dst = snap / rel
        if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime or dst.stat().st_size != src.stat().st_size:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    if not wanted and snap.exists():
        shutil.rmtree(snap)
    return len(wanted)


def snapshot_root(rel: str) -> str:
    """'.skylls-memory/Obsidian/btc-wiki/wiki/a.md' → 'Obsidian/btc-wiki' (the memory folder under home)."""
    parts = rel[len(MEMORY_DIR) + 1:].split("/")
    return "/".join(parts[:4 if len(parts) > 4 and parts[2] == "AGENTS" else 2])


def owner_copy_name(owner: str, name: str) -> str:
    """Folder for the owner's latest memory next to yours (--keep-memory); always named like a memory folder."""
    copy = f"{owner}-{name}"
    return copy if is_memory_name(copy) else copy + "-wiki"


def drop_stale(folder: Path, keep: set, base: Path) -> None:
    """Delete the files in an owner's copy of a memory that their latest version no longer has
    (Obsidian's per-user state, which is never shared, stays)."""
    for path in [p for p in folder.rglob("*") if p.is_file() and not p.is_symlink()] if folder.is_dir() else []:
        if path.relative_to(base).as_posix() not in keep and memory_file_ok(path.relative_to(folder).as_posix(), 0):
            path.unlink()


def install_memory(src: Path, rels: List[str], keep_owner: Optional[str] = None) -> List[str]:
    """Copy a downloaded memory snapshot to the same place under your home; returns the folders written.
    With keep_owner (--keep-memory) a folder you already have stays as it is and theirs goes next to it."""
    by_root: Dict[str, List[str]] = {}
    for rel in rels:
        by_root.setdefault(snapshot_root(rel), []).append(rel[len(MEMORY_DIR) + 1:])
    done = []
    for root, files in by_root.items():
        target = root
        if keep_owner and (Path.home() / root).exists():
            parent, _, leaf = root.rpartition("/")
            target = f"{parent}/{owner_copy_name(keep_owner, leaf)}"
            info(f"Kept your memory at ~/{root}; {keep_owner}'s latest goes to ~/{target}")
        places = {inner: target + inner[len(root):] for inner in files}
        if target != root:
            drop_stale(Path.home() / target, set(places.values()), Path.home())
        for inner, place in places.items():
            dst = Path.home() / place
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / MEMORY_DIR / inner, dst)
        done.append(target)
    return done


def rewrite_paths(dest: Path, rels: List[str], origin: str, home: str) -> None:
    """Point the owner's absolute paths (their copy, their home) at yours; report paths that don't exist here."""
    mine_home = str(Path.home())
    left = []
    for rel in rels:
        path = dest / rel
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        new = text.replace(origin, str(dest)) if origin else text
        if home and home != mine_home:
            new = new.replace(home + "/", mine_home + "/")
        if new != text:
            path.write_text(new)
        for m in re.finditer(re.escape(mine_home) + r"/[^\s\"'`)\]>,;*]+", new):
            target = m[0].rstrip("/.:")
            if "YYYY" not in target and "<" not in target and not Path(target).exists():
                left.append(f"{rel}: {target}")
    if left:
        warn("Paths that don't exist on this machine (check them):\n    " + "\n    ".join(sorted(set(left))[:10])
             + (" …" if len(set(left)) > 10 else ""))


def to_trash(path: Path) -> str:
    """Move to the Trash when there is one (macOS), else delete. Returns where it went."""
    trash = Path.home() / ".Trash"
    if trash.is_dir():
        shutil.move(str(path), str(trash / f"{path.name}-{datetime.now():%Y%m%d-%H%M%S}"))
        return "moved to the Trash"
    shutil.rmtree(path)
    return "deleted"


# ── Publishing ─────────────────────────────────────────────────────────────
def local_item(cfg: dict, kind: str, name: str) -> Path:
    """Where your copy of an agent/swarm lives."""
    return Path(cfg["dirs"][kind]).expanduser() / name


def blob_id(data: bytes) -> str:
    """The id git gives a file with this content."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def unchanged(cfg: dict, rec: dict, src: Path, dry_run: bool) -> bool:
    """True when the local item matches its latest published version (checked offline against the clone
    in the cache, which must be at the commit GitHub has): sync then skips the scan, fetch and gh calls."""
    path = REPOS_CACHE / rec["repo"]
    if not rec.get("head") or not rec.get("private") or not (path / ".git").exists():
        return False
    res = git("ls-tree", "-r", "-z", rec["head"], cwd=path, check=False)
    if res.returncode != 0:  # the clone doesn't have that commit yet
        return False
    kind = rec["kind"]
    if kind != "skills" and not dry_run and (roots := memory_roots(kind, src)):
        snapshot_memory(src, roots)
    files = [f for f in local_files(kind, src) if f not in (core.CHANGELOG, SKILLS_MANIFEST)]
    bundled = bundled_skills(cfg, files) if kind != "skills" else {}
    want = {f: blob_id((src / f).read_bytes()) for f in files if not any(f.startswith(d + "/") for d in bundled)}
    if bundled:
        want[SKILLS_MANIFEST] = blob_id("".join(f"{d} {r}\n" for d, r in sorted(bundled.items())).encode())
    have = {}
    for line in filter(None, res.stdout.split("\0")):
        meta, _, rel = line.partition("\t")
        if rel != core.CHANGELOG:
            have[rel] = meta.split()[2]
    return want == have


def publish(cfg: dict, kind: str, src: Path, message: Optional[str], part: str, about: Optional[str],
            folder: Optional[str], skip_scan: bool, dry_run: bool, ask: bool = True, yes: bool = False) -> None:
    """Publish a new version of one of your items to its own private repo (created if needed)."""
    src = src.resolve()
    name = check_name(src.name)
    if not is_item(kind, src):
        die(f"{src} is not a{'n' if kind == 'agents' else ''} {one(kind)} (no {' / '.join(KINDS[kind]['main'])}).")
    repo = item_repo(cfg, kind, name)
    section(f"Publishing {one(kind)} {name} → {repo}")
    if kind != "skills":
        roots = memory_roots(kind, src)
        if roots:
            count = snapshot_memory(src, roots) if not dry_run else 0
            info(f"Memory outside the folder: {', '.join('~/' + r for r in roots)}"
                 f"{f' ({count} files)' if count else ''}")
        inner = local_memory_dirs(src)
        if inner:
            info(f"Memory in the folder: {', '.join(d + '/' for d in inner)}")
    files = [f for f in local_files(kind, src) if f not in (core.CHANGELOG, SKILLS_MANIFEST)]
    bundled = bundled_skills(cfg, files) if kind != "skills" else {}
    if bundled:
        files = [f for f in files if not any(f.startswith(d + "/") for d in bundled)] + [SKILLS_MANIFEST]
        info(f"Skills from skylls, shared as a reference (friends get them from skylls): "
             f"{', '.join(sorted({d.rsplit('/', 1)[-1] for d in bundled}))}")

    if kind != "skills":
        review_memory(kind, src, repo, files, dry_run, yes)

    def place(rel: str, root: Path) -> None:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        if rel == SKILLS_MANIFEST:
            (root / rel).write_text("".join(f"{d} {repo}\n" for d, repo in sorted(bundled.items())))
        else:
            shutil.copy2(src / rel, root / rel)
    if skip_scan:
        warn("Skipping the secret scan (--skip-scan).")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            for rel in files:
                place(rel, Path(tmp) / name)
            core.scan_secrets(Path(tmp) / name)
    exists = core.gh("repo", "view", repo).returncode == 0
    if dry_run:
        info(f"Would publish {len(files)} files to {'' if exists else 'a new private repo '}{repo}")
        return
    if not exists:
        gh_ok("repo", "create", repo, "--private", "--description", f"skylls {one(kind)}: {name}",
              what=f"Could not create {repo}")
        core.gh("repo", "edit", repo, "--add-topic", ",".join(system_topics(kind)))  # marks it as a skylls item
        ok(f"Created private repo {repo}")
    else:
        ensure_private(repo)
    path = sync_item(repo)
    old_log = core.read_changelog(path)
    has_head = git("rev-parse", "--verify", "--quiet", "HEAD", cwd=path, check=False).returncode == 0
    for existing in [p for p in path.rglob("*") if p.is_file() and ".git" not in p.relative_to(path).parts]:
        rel = existing.relative_to(path).as_posix()
        if rel not in files and rel != core.CHANGELOG:
            existing.unlink()
    for rel in files:
        place(rel, path)
    git("add", "-A", cwd=path)
    status = git("status", "--porcelain", cwd=path).stdout.splitlines()
    changed = bool(status)
    last = old_log["entries"][0]["version"] if old_log["entries"] else None
    if not changed and not about:
        ok(f"{name} v{last} is already up to date.")
        set_folder(repo, folder)
        return
    version = core.bump(last, part)
    while version in versions(path):
        version = core.bump(version, "patch")
    if not message and ask and sys.stdin.isatty():
        message = input(f"  {YELLOW}?{NC} What changed in v{version}? ").strip()
    if not message and not ask and last:
        files = [line[3:].split(" -> ")[-1] for line in status if line[3:] != "CHANGELOG.md"]
        message = "Updated " + ", ".join(files[:5]) + (f" and {len(files) - 5} more" if len(files) > 5 else "")
    notes = message or ("First version" if not last else "Updated")
    main = main_file(kind, path)
    log = old_log
    if about:
        log["about"] = about
    elif not log["about"] or not has_head or git("diff", "--cached", "--quiet", "HEAD", "--", main.name,
                                                 cwd=path, check=False).returncode != 0:
        what = "AI agent skill" if kind == "skills" else f"AI {one(kind)} definition"
        log["about"] = core.ai_summary(path, main.name, what) or log["about"]
    me, today = core.my_name(), date.today().isoformat()
    if not log["created_by"]:
        log["created_by"], log["owner_login"], log["created"] = me or cfg["login"], cfg["login"], today
    if kind != "skills":
        log["origin"], log["home"] = str(src), str(Path.home())
    log["source"] = log["memory"] = ""
    log["entries"] = [{"version": version, "date": today, "author": me, "notes": notes}] + log["entries"]
    core.write_changelog(path, name, log)
    git("add", "-A", cwd=path)
    res = git("commit", "--quiet", "-m", f"{name} {version}: {notes.splitlines()[0]}", cwd=path, check=False)
    if res.returncode != 0:
        die("Could not commit. Set your git name and email:\n"
            "    git config --global user.name 'Your Name'; git config --global user.email you@example.com")
    git("tag", f"v{version}", cwd=path)
    res = git("push", "--quiet", "--atomic", "origin", "HEAD:refs/heads/main", f"refs/tags/v{version}",
              cwd=path, check=False)
    if res.returncode != 0:
        shutil.rmtree(path, ignore_errors=True)  # the next run starts from GitHub again
        die(f"Push failed; nothing was published:\n{res.stderr.strip()}")
    if log["about"]:
        core.gh("repo", "edit", repo, "--description", log["about"][:340])
    core.gh("repo", "edit", repo, "--add-topic", ",".join(system_topics(kind)))
    set_folder(repo, folder)
    shutil.copy2(path / core.CHANGELOG, src / core.CHANGELOG)  # your copy now knows its version
    ok(f"Published {name} v{version} → https://github.com/{repo}")
    if log["about"]:
        info(log["about"])


def review_memory(kind: str, src: Path, repo: str, files: List[str], dry_run: bool, yes: bool) -> None:
    """List the memory notes this publish adds or changes; ask before sending them (unless -y or no terminal)."""
    memory = set(local_memory_dirs(src)) | {MEMORY_DIR}
    notes = [f for f in files if "/" in f and f.split("/", 1)[0] in memory]
    if not notes:
        return
    path = sync_item(repo) if core.gh("repo", "view", repo).returncode == 0 else None
    new = [f for f in notes if not path or not (path / f).is_file()
           or (path / f).read_bytes() != (src / f).read_bytes()]
    if not new:
        return
    shown = ["~/" + f[len(MEMORY_DIR) + 1:] if f.startswith(MEMORY_DIR + "/") else f for f in new]
    warn(f"Memory notes friends will get ({len(new)} new or changed):\n    " + "\n    ".join(shown[:20])
         + (f"\n    … and {len(new) - 20} more" if len(new) > 20 else ""))
    info("Keep a note home: put 'private: true' in its frontmatter, or list it in .skyllsignore.")
    if dry_run or yes or not sys.stdin.isatty():
        return
    answer = input(f"  {YELLOW}?{NC} Publish these memory notes? (y/N): ").strip().lower()
    if answer not in ("y", "yes"):
        die(f"Nothing published for {src.name}.")


def set_folder(repo: str, folder: Optional[str]) -> None:
    """Put an item in a folder (a GitHub topic); '' or '.' takes it out of any folder."""
    if folder is None:
        return
    res = core.gh("repo", "view", repo, "--json", "repositoryTopics")
    data = (gh_json(res) or {}) if res.returncode == 0 else {}
    current = [t["name"] for t in (data.get("repositoryTopics") or [])]
    old = [t for t in current if not t.startswith("skylls")]
    new = "" if folder.strip() in ("", ".") else folder_topic(folder)
    if old:
        core.gh("repo", "edit", repo, "--remove-topic", ",".join(old))
    if new:
        core.gh("repo", "edit", repo, "--add-topic", new)
    ok(f"{repo.split('/')[1]}: {'folder ' + new if new else 'no folder'}")


# ── Commands ───────────────────────────────────────────────────────────────
def cmd_push(cfg: dict, kind: str, args) -> None:
    if kind == "skills":
        src = core.find_installed(cfg, args.name, args.agent, args.is_global)
    else:
        src = local_item(cfg, kind, args.name)
        given = Path(args.name).expanduser()
        if not src.is_dir() and given.is_dir():
            src = given
    if not src.is_dir():
        die(f"No {one(kind)} '{args.name}' in {src.parent}.")
    publish(cfg, kind, src, args.message, args.part, args.about, args.folder, args.skip_scan, args.dry_run,
            yes=getattr(args, "yes", False))


def print_record(r: dict, indent: int = 2) -> None:
    pad = " " * indent
    label = f" {BLUE}v{r['version']}{NC}" if r.get("version") else ""
    if r.get("newer"):
        label += f" {YELLOW}(v{r['newer']} available){NC}"
    if r.get("folder"):
        label += f"  [{r['folder']}]"
    if r.get("installed"):
        label += f"  {GREEN}(installed){NC}"
    if r.get("published") is False:
        label += f"  {YELLOW}(not published){NC}"
    say(f"{pad}{GREEN}•{NC} {CYAN}{r['name']}{NC}{label}")
    if r.get("summary"):
        say(f"{pad}  {r['summary']}")
    extra = [x for x in (f"by {r['by']}" if r.get("by") else "", f"updated {r['updated']}" if r.get("updated") else "",
                         f"copy of {r['source']}" if r.get("source") else "") if x]
    if extra:
        say(f"{pad}  {' · '.join(extra)}")


def public(r: dict) -> dict:
    """The fields shown to agents (--json)."""
    return {k: r.get(k) for k in ("name", "owner", "folder", "version", "newer", "summary", "updated",
                                   "installed", "published", "source", "repo")}


def mark_installed(cfg: dict, kind: str, r: dict) -> dict:
    if kind == "skills":
        r["installed"] = core.installed_scope(cfg, r["name"])
    else:
        r["installed"] = local_item(cfg, kind, r["name"]).is_dir() and not r["mine"]
    return r


def records(cfg: dict, kind: str, owner: Optional[str] = None, folder: Optional[str] = None) -> List[dict]:
    """Catalog + (agents/swarms) your local items that aren't published yet."""
    rows = [mark_installed(cfg, kind, dict(r)) for r in catalog(cfg, kind, owner)]
    if kind != "skills" and (not owner or mine(cfg, owner)):
        published = {r["name"].lower() for r in rows if r["mine"]}
        root = Path(cfg["dirs"][kind]).expanduser()
        for item in sorted(root.iterdir()) if root.is_dir() else []:
            if is_item(kind, item) and item.name.lower() not in published:
                log = core.read_changelog(item)
                main = main_file(kind, item)
                rows.append({"kind": kind, "name": item.name, "owner": cfg["owner"], "mine": True,
                             "published": False, "folder": "", "text": "", "source": log["source"],
                             "summary": log["about"] or summary_from(main.read_text(errors="ignore") if main else "")})
    if folder is not None:
        want = "" if folder.strip() in ("", ".") else folder_topic(folder)
        rows = [r for r in rows if r.get("folder", "") == want]
    return rows


def cmd_list(cfg: dict, kind: str, query: Optional[str], owner: Optional[str], folder: Optional[str]) -> None:
    q = (query or "").lower()
    rows = [r for r in records(cfg, kind, owner, folder)
            if not q or q in f"{r['name']} {r.get('summary') or ''} {r.get('folder', '')}".lower()]
    if core.JSON_MODE:
        for r in rows:
            emit(public(r))
        return
    groups: Dict[str, List[dict]] = {}
    for r in rows:
        groups.setdefault("" if r["mine"] else r["owner"], []).append(r)
    for who in sorted(groups, key=lambda w: (w != "", w.lower())):
        section(f"From {who}" if who else f"Your {kind} ({cfg['owner']})")
        by_folder: Dict[str, List[dict]] = {}
        for r in groups[who]:
            by_folder.setdefault(r.get("folder", ""), []).append(r)
        nested = len(by_folder) > 1 or "" not in by_folder
        for f in sorted(by_folder, key=lambda x: (x != "", x)):
            if nested:
                say(f"  {BLUE}{f or '(no folder)'}{NC}")
            for r in by_folder[f]:
                print_record(r, 4 if nested else 2)
    if not rows:
        warn(f"No {kind} yet. Publish one with: skylls{cmd_prefix(kind)} push <name>"
             f"{'' if cfg.get('friends') else ', or add a friend: skylls source add <their-login>'}")


def cmd_find(cfg: dict, kind: str, words: List[str], owner: Optional[str], folder: Optional[str],
             limit: Optional[int]) -> None:
    if not words and folder is None:
        die(f"Give keywords and/or --folder, e.g. skylls{cmd_prefix(kind)} find pdf")
    terms = [w.lower() for w in words]
    scored = []
    for r in records(cfg, kind, owner, folder):
        fields = [(r["name"], 5), (r.get("folder", ""), 3), (r.get("summary") or "", 3), (r.get("text", ""), 1)]
        if all(any(t in text.lower() for text, _ in fields) for t in terms):
            scored.append((-sum(w for t in terms for text, w in fields if t in text.lower()), r["name"].lower(), r))
    scored.sort(key=lambda s: (s[0], s[1]))
    limit = limit if limit is not None else (10 if core.JSON_MODE else None)
    shown = [r for _, _, r in (scored[:limit] if limit else scored)]
    if core.JSON_MODE:
        for r in shown:
            emit(public(r))
        if len(scored) > len(shown):
            warn(f"{len(scored) - len(shown)} more; raise --limit")
        return
    section(f"{kind.capitalize()} matching '{' '.join(words)}'{f' in folder {folder}' if folder else ''}")
    for r in shown:
        print_record(r)
        if not r["mine"]:
            say(f"    from {r['owner']}")
    folders = {r.get("folder") for r in shown if r.get("folder")}
    related = sorted({r["name"] for r in records(cfg, kind) if r.get("folder") in folders} - {r["name"] for r in shown})
    if terms and related:
        info(f"Related (same folder): {', '.join(related)}")
    if not shown:
        warn("No matches." + (" Try 'skylls search <words>' for public skills on skills.sh." if kind == "skills" else ""))


def cmd_log(cfg: dict, kind: str, name: str, owner: Optional[str]) -> None:
    r = resolve(cfg, kind, name, owner)
    log = r["log"]
    if core.JSON_MODE:
        emit({**public(r), "created": log["created"], "by": log["created_by"],
              "versions": [{"v": e["version"], "date": e["date"], "by": e["author"], "notes": e["notes"]}
                           for e in log["entries"]]})
        return
    section(f"{r['name']}  ({r['repo']})")
    if r["summary"]:
        say(f"  {r['summary']}")
    if log["created_by"]:
        say(f"  Created by {core.owner_label(log)} on {log['created']}")
    if r.get("folder"):
        say(f"  Folder: {r['folder']}")
    for e in log["entries"]:
        say(f"\n  {CYAN}v{e['version']}{NC}  {e['date']}  {BLUE}{e['author']}{NC}")
        for line in e["notes"].splitlines():
            say(f"    {line}")
    if not log["entries"]:
        warn("No versions yet.")
    elif len(log["entries"]) > 1:
        say("")
        info(f"Install an older version with: skylls{cmd_prefix(kind)} add {r['name']}@<version>"
             f"{'' if r['mine'] else ' --from ' + r['owner']}")


def install_skill_copy(cfg: dict, src: Path, name: str, agent: Optional[str], is_global: bool, force: bool,
                       dry_run: bool) -> None:
    dests = core.target_dirs(cfg, agent, is_global)
    core.copy_skill(src, dests[0], name, dry_run, force)
    for dest_root in dests[1:]:
        if is_global:
            core.link_skill(dests[0] / name, dest_root, name, dry_run)
        else:
            core.copy_skill(src, dest_root, name, dry_run, force)


def cmd_add_skill(cfg: dict, spec: str, owner: Optional[str], agent: Optional[str], is_global: bool,
                  force: bool, dry_run: bool) -> None:
    """Install a skill you or a friend published (latest, or name@version)."""
    name, _, version = spec.partition("@")
    r = resolve(cfg, "skills", name, owner)
    section(f"Installing skill {r['name']}{'' if r['mine'] else ' from ' + r['owner']}")
    with tempfile.TemporaryDirectory() as tmp:
        src, _, log = extract("skills", r, version, Path(tmp))
        got = log["entries"][0]["version"] if log["entries"] else "latest"
        log["source"] = f"{r['repo']} v{got}"
        core.write_changelog(src, r["name"], log)
        install_skill_copy(cfg, src, r["name"], agent, is_global, force, dry_run)


def cmd_add_item(cfg: dict, kind: str, spec: str, owner: Optional[str], as_name: Optional[str], force: bool,
                 keep_memory: bool, dry_run: bool) -> None:
    """Download an agent/swarm into your folder. Updates keep your runtime data and refresh its memory
    to the owner's; with keep_memory your memory stays and theirs goes next to it."""
    name, _, version = spec.partition("@")
    r = resolve(cfg, kind, name, owner)
    dest = local_item(cfg, kind, check_name(as_name or r["name"]))
    section(f"Installing {r['owner']}'s {one(kind)} {r['name']} → {dest}")
    restored: List[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        src, fetched, log = extract(kind, r, version, Path(tmp))
        got = log["entries"][0]["version"] if log["entries"] else "latest"
        rels = [f for f in fetched if not f.startswith(MEMORY_DIR + "/")]
        outside = [f for f in fetched if f.startswith(MEMORY_DIR + "/")]
        if dry_run:
            info(f"Would install {len(rels)} files of {r['name']} v{got} into {dest}"
                 f"{f' and {len(outside)} memory files under ~/' if outside else ''}"
                 f"{', keeping your memory (theirs gets its own folder)' if keep_memory else ''}")
            return
        existed = dest.exists()
        if existed:
            if r["mine"] and not core.read_changelog(dest)["source"]:
                die(f"{dest} is your own {one(kind)}, the original of {r['repo']}. Use --as <other-name> for a copy.")
            if not force and not core.read_changelog(dest)["source"].startswith(r["repo"] + " ") and \
                    input(f"  {YELLOW}?{NC} {dest} exists and isn't a copy of {r['repo']}. Replace its files? "
                          "(y/N): ").strip().lower() != "y":
                die("Nothing was changed.")
        bundled = read_manifest(src)
        theirs = {d: owner_copy_name(r["owner"], d) for d in memory_dirs_in(rels) if (dest / d).is_dir()} \
            if keep_memory else {}
        for d, copy in theirs.items():
            info(f"Kept your memory in {d}/; {r['owner']}'s latest goes to {copy}/")
        place = {}  # downloaded file → where it goes in your copy
        for f in rels:
            top, _, rest = f.partition("/")
            place[f] = f"{theirs[top]}/{rest}" if top in theirs else f
        wanted = set(place.values())
        if existed:
            mine_memory = local_memory_dirs(dest)
            for rel in local_files(kind, dest):  # drop definition files the new version no longer has
                if rel not in wanted and rel != core.CHANGELOG and not rel.startswith(MEMORY_DIR + "/") \
                        and rel.split("/", 1)[0] not in mine_memory \
                        and not any(rel.startswith(d + "/") for d in bundled):
                    (dest / rel).unlink()
            for copy in theirs.values():  # the owner's copy mirrors their latest version
                drop_stale(dest / copy, wanted, dest)
        for f, rel in place.items():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / f, dest / rel)
        restored = install_memory(src, outside, r["owner"] if keep_memory else None)
        rewrite_paths(dest, sorted(wanted), log["origin"], log["home"])
        for folder, repo in sorted(bundled.items()):
            install_bundled(cfg, dest, folder, repo)
        log["source"] = f"{r['repo']} v{got}"
        log["origin"] = log["home"] = ""
        log["memory"] = ", ".join(sorted({snapshot_root(f) for f in outside}))
        core.write_changelog(dest, dest.name, log)
    ok(f"Installed {r['name']} v{got} from {r['repo']} → {dest} ({len(rels)} files)")
    for folder in restored:
        ok(f"Memory → ~/{folder}")


def cmd_remove_item(cfg: dict, kind: str, name: str, memory: bool, force: bool, dry_run: bool) -> None:
    """Remove an agent/swarm folder from this computer (to the Trash). Published repos are not touched."""
    item = local_item(cfg, kind, name)
    if not is_item(kind, item):
        die(f"No {one(kind)} '{name}' in {item.parent}.")
    log = core.read_changelog(item)
    outside = [r for r in log["memory"].split(", ") if r] if log["source"] else []
    section(f"Removing {one(kind)} {name}")
    if log["source"]:
        info(f"A copy of {log['source']}; the original stays with its owner.")
    elif log["entries"]:
        info(f"Your published repo ({cfg['owner']}/{repo_name(kind, name, cfg.get('owner_is_org', False))}) "
             "stays on GitHub.")
    else:
        warn(f"'{name}' was never published: this removes the only copy (it goes to the Trash).")
    if memory and not log["source"]:
        warn("--memory only removes memory that came with a downloaded copy; your own memory is kept.")
    targets = [item] + ([Path.home() / r for r in outside if (Path.home() / r).is_dir()] if memory else [])
    if dry_run:
        info(f"Would remove: {', '.join(str(t) for t in targets)}")
        return
    if not force:
        if not sys.stdin.isatty():
            die("Add -y to remove without being asked.")
        if input(f"  {YELLOW}?{NC} Remove {', '.join(str(t) for t in targets)}? (y/N): ").strip().lower() != "y":
            die("Nothing was removed.")
    for target in targets:
        ok(f"{target}: {to_trash(target)}")
    kept = [r for r in outside if (Path.home() / r).is_dir()]
    if kept:
        info(f"Kept its memory at {', '.join('~/' + r for r in kept)} (add --memory to remove it too)")


def installed_skills(cfg: dict, agent: Optional[str], is_global: Optional[bool]) -> List[dict]:
    scopes = [is_global] if is_global is not None else [False, True]
    rows = []
    for scope in scopes:
        for root in core.target_dirs(cfg, agent, scope):
            if not root.is_dir():
                continue
            agent_name = next((a for a, d in core.AGENT_DIRS.items() if root.as_posix().endswith(d)), None)
            for p in sorted(root.iterdir()):
                if (p / "SKILL.md").is_file():
                    log = core.read_changelog(p)
                    rows.append({"name": p.name, "scope": "global" if scope else "project", "agent": agent_name,
                                 "dir": root, "link": p.is_symlink(),
                                 "version": log["entries"][0]["version"] if log["entries"] else None,
                                 "summary": log["about"] or core.get_skill_description(p),
                                 "source": log["source"].split(" ")[0] if log["source"] else ""})
    return rows


def latest_for(cfg: dict, row: dict) -> Optional[dict]:
    """The catalog record an installed skill came from (its Source, or your own repo of that name)."""
    for r in catalog(cfg, "skills"):
        if (row["source"] and r["repo"].lower() == row["source"].lower()) or \
                (not row["source"] and r["mine"] and r["name"] == row["name"]):
            return r
    return None


def newer(row: dict, r: Optional[dict]) -> Optional[str]:
    if r and r["version"] and (not row["version"] or core.version_key(r["version"]) > core.version_key(row["version"])):
        return r["version"]
    return None


def cmd_installed(cfg: dict, agent: Optional[str], is_global: Optional[bool]) -> None:
    rows = installed_skills(cfg, agent, is_global)
    for row in rows:
        if not row["link"]:
            row["newer"] = newer(row, latest_for(cfg, row))
    if core.JSON_MODE:
        for row in rows:
            emit({k: row.get(k) for k in ("name", "scope", "agent", "version", "newer", "link", "source")})
        return
    current = None
    for row in rows:
        if row["dir"] != current:
            current = row["dir"]
            section(f"{row['scope'].capitalize()}: {current}")
        if row["link"]:
            say(f"  {GREEN}•{NC} {CYAN}{row['name']}{NC} → {os.readlink(current / row['name'])}")
        else:
            print_record(row)
    if not rows:
        info("No skills installed here. Find some with: skylls list")


def cmd_pull(cfg: dict, update: bool, agent: Optional[str], is_global: Optional[bool], dry_run: bool) -> List[str]:
    """Check for new versions; with update, install them for installed skills (returns what was updated)."""
    section("Checking for new versions")
    items = catalog(cfg)
    ok(f"{len(items)} items you can install ({sum(1 for r in items if r['mine'])} yours)")
    done: List[str] = []
    if not update:
        return done
    seen = set()
    for row in installed_skills(cfg, agent, is_global):
        r = latest_for(cfg, row) if not row["link"] else None
        where = (row["dir"] / row["name"]).resolve()  # run from ~, the project and global folders are one
        if newer(row, r) and where not in seen:
            seen.add(where)
            info(f"{row['name']}: v{row['version'] or '-'} → v{r['version']}")
            with tempfile.TemporaryDirectory() as tmp:
                src, _, log = extract("skills", r, None, Path(tmp))
                log["source"] = f"{r['repo']} v{r['version']}"
                core.write_changelog(src, r["name"], log)
                core.copy_skill(src, row["dir"], row["name"], dry_run, force=True)
            done.append(f"skill {row['name']} v{r['version']}")
    return done


def local_original(cfg: dict, kind: str, name: str) -> Optional[Path]:
    """Your own local copy of one of your published items (not a download), if it is on this computer."""
    src = core.locate_installed(cfg, name, None, None) if kind == "skills" else local_item(cfg, kind, name)
    return src if src and is_item(kind, src) and not src.is_symlink() and not core.read_changelog(src)["source"] else None


def installed_version(path: Path) -> Optional[str]:
    log = core.read_changelog(path)
    return log["entries"][0]["version"] if log["entries"] else None


def cmd_sync(cfg: dict, message: Optional[str], skip_scan: bool, dry_run: bool, yes: bool = False,
             keep_memory: bool = False) -> None:
    """Publish what changed in your published items, then install newer versions of what friends shared."""
    published, updated, failed, unchanged_ = [], [], [], 0
    section("Reading your items and your friends' from GitHub")
    mine_ = [r for r in catalog(cfg) if r["mine"]]
    section(f"Publishing your changes ({len(mine_)} published items)")
    for i, r in enumerate(mine_):
        core.progress(i, len(mine_), f"{one(r['kind'])} {r['name']}")
        src = local_original(cfg, r["kind"], r["name"])
        if not src:
            continue
        if unchanged(cfg, r, src, dry_run):
            unchanged_ += 1
            continue
        core.progress_clear()  # publish prints and runs git/gitleaks
        before = installed_version(src)
        try:
            publish(cfg, r["kind"], src, message, "patch", None, None, skip_scan, dry_run, ask=False, yes=yes)
        except SystemExit:  # e.g. the secret scan found something: the others still go
            failed.append(f"{one(r['kind'])} {r['name']}")
            continue
        if installed_version(src) != before:
            published.append(f"{one(r['kind'])} {r['name']} v{installed_version(src)}")
    core.progress(len(mine_), len(mine_), "checked")
    core.progress_done()
    if unchanged_:
        ok(f"Unchanged since the last version: {unchanged_} item{'s' if unchanged_ != 1 else ''}.")
    section("Getting newer versions of what friends shared with you")
    updated += cmd_pull(cfg, True, None, None, dry_run)  # skills
    by_repo = {r["repo"].lower(): r for r in catalog(cfg) if not r["mine"]}
    for kind in ("agents", "swarms"):
        root = Path(cfg["dirs"][kind]).expanduser()
        for item in sorted(root.iterdir()) if root.is_dir() else []:
            source = core.read_changelog(item)["source"] if is_item(kind, item) else ""
            r = by_repo.get(source.split(" ")[0].lower()) if source else None
            if r and newer({"version": installed_version(item)}, r):
                info(f"{one(kind)} {item.name}: v{installed_version(item) or '-'} → v{r['version']}")
                try:
                    cmd_add_item(cfg, kind, r["name"], r["owner"], item.name, True, keep_memory, dry_run)
                except SystemExit:
                    failed.append(f"{one(kind)} {item.name}")
                    continue
                updated.append(f"{one(kind)} {item.name} v{r['version']}")
    section("Sync done" + (" (dry run)" if dry_run else ""))
    if not dry_run:
        ok(f"Published: {', '.join(published) or 'nothing changed'}")
    ok(f"Updated from friends: {', '.join(updated) or 'everything is up to date'}")
    if failed:
        warn(f"Not synced (see above): {', '.join(failed)}")
    if core.JSON_MODE:
        emit({"published": published, "updated": updated, "failed": failed})


# ── Sharing ────────────────────────────────────────────────────────────────
def my_repos(cfg: dict, kind: str, name: Optional[str], all_: bool) -> List[str]:
    if all_:
        repos = [r["repo"] for r in catalog(cfg, kind) if r["mine"]]
        if not repos:
            die(f"You haven't published any {kind} yet.")
        return repos
    if not name:
        die(f"Which {one(kind)}? skylls{cmd_prefix(kind)} share <name> @user (or --all @user)")
    return [resolve(cfg, kind, name, cfg["owner"])["repo"]]


def pending_invites(repo: str) -> dict:
    invites = gh_json(core.gh_api(f"repos/{repo}/invitations", "--paginate")) or []
    return {i["invitee"]["login"].lower(): i["id"] for i in invites if i.get("invitee")}


def cmd_share(cfg: dict, kind: str, name: Optional[str], users: List[str], all_: bool, dry_run: bool,
              prs: Optional[bool] = None) -> None:
    repos = my_repos(cfg, kind, name, all_)
    if not users:
        for repo in repos:
            section(f"Who can use {repo}")
            for c in gh_json(core.gh_api(f"repos/{repo}/collaborators", "--paginate")) or []:
                say(f"  {GREEN}•{NC} {CYAN}@{c['login']}{NC} ({c.get('role_name', '')})")
            for login in pending_invites(repo):
                say(f"  {YELLOW}•{NC} {CYAN}@{login}{NC} (invite pending)")
        return
    org = is_org(cfg["owner"])
    permission = ["-f", "permission=pull"] if org else []
    access = "read-only" if org else "access"
    users = core.github_users(users)
    for repo in repos:
        section(f"Sharing {repo}")
        for user in users:
            if dry_run:
                info(f"Would invite @{user} ({access})")
                continue
            res = core.gh_api("-X", "PUT", f"repos/{repo}/collaborators/{user}", *permission)
            if res.returncode != 0:
                fail(f"@{user}: {(res.stderr or res.stdout).strip()}")
            else:
                ok(f"Invited @{user} ({access})" if res.stdout.strip() else f"@{user} already has {access}")
    if not dry_run:
        info(f"They add you once with: skylls source add {cfg['owner']}"
             + ("" if org else "  (on personal repos GitHub gives collaborators write access; "
                               "skylls only ever reads friends' repos)"))
    if kind != "skills":
        share_prs(cfg, kind, repos, prs, dry_run)


def forks_allowed(repo: str) -> bool:
    return bool((gh_json(core.gh_api(f"repos/{repo}")) or {}).get("allow_forking"))


def share_prs(cfg: dict, kind: str, repos: List[str], prs: Optional[bool], dry_run: bool) -> None:
    """When sharing an agent/swarm: may the people you share it with send pull requests (--prs / --no-prs)?
    Asked when it isn't on yet and you're at a terminal; agents must pass the user's answer as a flag."""
    p = cmd_prefix(kind)
    if prs is None:
        off = [r for r in repos if not forks_allowed(r)]
        if not off:
            info("Pull requests from the people you share with: on (turn off: skylls"
                 f"{p} allow-prs <name> --off)")
            return
        if not sys.stdin.isatty():
            info(f"Pull requests from them are off. Allow them with --prs (or later: skylls{p} allow-prs <name>)")
            return
        prs = input(f"  {YELLOW}?{NC} Let the people you share it with send their changes as pull requests "
                    "(you review and accept each one)? (y/N) ").strip().lower() in ("y", "yes")
        repos = off
    set_prs(cfg, repos, prs, dry_run)


def set_prs(cfg: dict, repos: List[str], on: bool, dry_run: bool) -> None:
    """Turn forking (= pull requests from the people you share with) on or off for your item repos."""
    org = cfg["owner"] if cfg.get("owner_is_org") else None
    if dry_run:
        info(f"Would turn pull requests {'on' if on else 'off'} for {', '.join(repos)}")
        return
    if org and on:
        res = core.gh_api("-X", "PATCH", f"orgs/{org}", "-F", "members_can_fork_private_repositories=true")
        if res.returncode != 0:
            warn(f"Could not allow private forks in {org} (you must own it): {res.stderr.strip()}")
    for repo in repos:
        gh_ok("api", "-X", "PATCH", f"repos/{repo}", "-F", f"allow_forking={'true' if on else 'false'}",
              what=f"Could not change pull requests for {repo}")
        ok(f"{repo}: pull requests from the people you share it with are {'on' if on else 'off'}")


def cmd_unshare(cfg: dict, kind: str, name: Optional[str], users: List[str], all_: bool, dry_run: bool) -> None:
    for repo in my_repos(cfg, kind, name, all_):
        section(f"Revoking access to {repo}")
        invites = pending_invites(repo)
        for user in core.github_users(users):
            invite_id = invites.get(user.lower())
            member = core.gh_api(f"repos/{repo}/collaborators/{user}").returncode == 0
            if user.lower() in {cfg["owner"].lower(), cfg["login"].lower()}:
                fail(f"@{user} owns {repo}.")
            elif not invite_id and not member:
                warn(f"@{user} has no access.")
            elif dry_run:
                info(f"Would revoke @{user}")
            else:
                if invite_id:
                    core.gh_api("-X", "DELETE", f"repos/{repo}/invitations/{invite_id}")
                if member:
                    core.gh_api("-X", "DELETE", f"repos/{repo}/collaborators/{user}")
                ok(f"Revoked @{user} (copies they installed stay on their machine)")


def shared_with(cfg: dict, repo: str) -> List[dict]:
    """Who besides you can use one of your repos: collaborators and pending invites."""
    me = {cfg["owner"].lower(), cfg["login"].lower()}
    people = [{"login": c["login"], "role": c.get("role_name", "")}
              for c in gh_json(core.gh_api(f"repos/{repo}/collaborators", "--paginate")) or []
              if c["login"].lower() not in me]
    invites = gh_json(core.gh_api(f"repos/{repo}/invitations", "--paginate")) or []
    return people + [{"login": i["invitee"]["login"], "pending": True, "invite_id": i["id"],
                      "invited": (i.get("created_at") or "")[:10]}
                     for i in invites if i.get("invitee")]


def sharing(cfg: dict, only: set) -> Tuple[List[Tuple[dict, List[dict]]], List[dict], List[dict]]:
    """(your items with who can use them, items shared with you, invites to you not accepted yet)."""
    rows = catalog(cfg, quiet=True)
    mine_ = [r for r in rows if r["mine"]]
    with ThreadPoolExecutor(max_workers=8) as pool:  # two GitHub calls per item: do them side by side
        access = list(pool.map(lambda r: shared_with(cfg, r["repo"]), mine_))
    by_you = [(r, [p for p in people if not only or p["login"].lower() in only]) for r, people in zip(mine_, access)]
    by_you = [(r, people) for r, people in by_you if people or not only]
    with_you = [mark_installed(cfg, r["kind"], dict(r)) for r in rows
                if not r["mine"] and (not only or r["owner"].lower() in only)]
    waiting = [w for who, items in _catalog.get("waiting", {}).items() for w in items
               if not only or {who.lower(), w["inviter"].lower()} & only]
    return by_you, with_you, waiting


def cmd_shared(cfg: dict, users: List[str]) -> None:
    """Skills, agents and swarms you shared (and with whom), and those friends shared with you."""
    only = {u.lower() for u in core.github_users(users)}
    by_you, with_you, waiting = sharing(cfg, only)
    if core.JSON_MODE:
        for r, people in by_you:
            emit({"shared": "by_you", "kind": one(r["kind"]), "name": r["name"], "repo": r["repo"],
                  "with": [p["login"] for p in people if not p.get("pending")],
                  "pending": [p["login"] for p in people if p.get("pending")]})
        for r in with_you:
            emit({"shared": "with_you", "kind": one(r["kind"]), **public(r)})
        for w in waiting:
            emit({"shared": "with_you", "pending": True, **w, "kind": one(w["kind"]),
                  "accept": f"skylls source add {w['repo'].split('/')[0]}"})
        return
    section("Shared by you" + (f" with {', '.join('@' + u for u in sorted(only))}" if only else ""))
    for r, people in by_you:
        if people:
            who = ", ".join(f"{CYAN}@{p['login']}{NC}" + (f" {YELLOW}(invite pending"
                            f"{', sent ' + p['invited'] if p.get('invited') else ''}){NC}" if p.get("pending") else "")
                            for p in people)
            say(f"  {GREEN}•{NC} {one(r['kind'])} {CYAN}{r['name']}{NC} → {who}")
    private = [f"{one(r['kind'])} {r['name']}" for r, people in by_you if not people]
    if private:
        say(f"  {BLUE}Not shared with anyone ({len(private)}):{NC} {', '.join(private)}")
    if not by_you:
        info("Nothing yet. Share with: skylls share <name> @user")
    section("Shared with you" + (f" by {', '.join('@' + u for u in sorted(only))}" if only else ""))
    owners: Dict[str, List[dict]] = {}
    for r in with_you:
        owners.setdefault(r["owner"], []).append(r)
    for who in sorted(owners, key=str.lower):
        say(f"  {BLUE}From {who}{NC}")
        for r in owners[who]:
            print_record({**r, "name": f"{one(r['kind'])} {r['name']}"}, 4)
    if not with_you and not waiting:
        info("Nothing yet. When a friend shares with you: skylls source add <their-login>")
    if waiting:
        section("Waiting for you (shared with you, not accepted yet)")
        for w in waiting:
            owner = w["repo"].split("/")[0]
            when = f", {w['invited']}" if w.get("invited") else ""
            say(f"  {YELLOW}•{NC} {one(w['kind'])} {CYAN}{w['name']}{NC} from {CYAN}@{w['inviter'] or owner}{NC}{when}"
                f"  → accept: skylls source add {owner}")


def cmd_revoke(cfg: dict, users: List[str], force: bool, dry_run: bool) -> None:
    """Take back everything you shared with these users: every skill, agent and swarm, and pending invites."""
    logins = core.github_users(users)
    if not logins:
        die("Whose access? skylls revoke @user… (one item only: skylls unshare <name> @user)")
    if {u.lower() for u in logins} & {cfg["owner"].lower(), cfg["login"].lower()}:
        die("You can't revoke your own access.")
    items = [(r, people) for r, people in sharing(cfg, {u.lower() for u in logins})[0] if people]
    if not items:
        ok(f"You share nothing with {', '.join('@' + u for u in logins)}.")
        return
    section(f"Revoking {', '.join('@' + u for u in logins)}: {len(items)} item{'s' if len(items) != 1 else ''}")
    for r, people in items:
        say(f"  {GREEN}•{NC} {one(r['kind'])} {CYAN}{r['name']}{NC} → "
            + ", ".join(f"@{p['login']}" + (" (invite pending)" if p.get("pending") else "") for p in people))
    if dry_run:
        info("Would revoke all of the above.")
        return
    if not force:
        if not sys.stdin.isatty():
            die("Add -y to revoke without being asked.")
        if input(f"  {YELLOW}?{NC} Revoke all of these? (y/N): ").strip().lower() != "y":
            die("Nothing was changed.")
    for r, people in items:
        for p in people:
            res = core.gh_api("-X", "DELETE", f"repos/{r['repo']}/invitations/{p['invite_id']}" if p.get("pending")
                              else f"repos/{r['repo']}/collaborators/{p['login']}")
            if res.returncode != 0:
                fail(f"{r['name']} @{p['login']}: {(res.stderr or res.stdout).strip()}")
    ok("Revoked (copies they installed stay on their machine)")
    if core.JSON_MODE:
        emit({"revoked": [f"{one(r['kind'])} {r['name']}" for r, _ in items], "users": logins})


def cmd_people(cfg: dict) -> None:
    """Everyone you share with or who shares with you, and what goes each way."""
    by_you, with_you, waiting = sharing(cfg, set())
    friends = {f.lower() for f in cfg.get("friends", [])}
    people: Dict[str, dict] = {}

    def person(login: str) -> dict:
        return people.setdefault(login.lower(), {"login": login, "you_share": [], "pending_from_you": [],
                                                 "they_share": [], "waiting": [], "accept": ""})
    for r, who in by_you:
        for p in who:
            person(p["login"])["pending_from_you" if p.get("pending") else "you_share"].append(
                f"{one(r['kind'])} {r['name']}")
    for r in with_you:
        person(r["owner"])["they_share"].append(f"{one(r['kind'])} {r['name']}")
    for w in waiting:
        p = person(w["inviter"] or w["repo"].split("/")[0])
        p["waiting"].append(f"{one(w['kind'])} {w['name']}")
        p["accept"] = f"skylls source add {w['repo'].split('/')[0]}"
    for f in cfg.get("friends", []):
        person(f)
    rows = sorted(people.values(), key=lambda p: p["login"].lower())
    for p in rows:
        p["source"] = p["login"].lower() in friends
    if core.JSON_MODE:
        for p in rows:
            emit(p)
        return
    section("People you share with, and who share with you")
    for p in rows:
        say(f"  {GREEN}•{NC} {CYAN}@{p['login']}{NC}" + (f"  {BLUE}(your source){NC}" if p["source"] else ""))
        if p["you_share"] or p["pending_from_you"]:
            pending = f"  {YELLOW}+ {len(p['pending_from_you'])} not accepted yet: " \
                      f"{', '.join(p['pending_from_you'])}{NC}" if p["pending_from_you"] else ""
            say(f"      you share {len(p['you_share'])}: {', '.join(p['you_share']) or '-'}{pending}")
        if p["they_share"]:
            say(f"      they share {len(p['they_share'])} with you: {', '.join(p['they_share'])}")
        if p["waiting"]:
            say(f"      {YELLOW}waiting for you ({len(p['waiting'])}): {', '.join(p['waiting'])}{NC}"
                f"  → accept: {p['accept']}")
        if p["source"] and not p["they_share"]:
            say("      nothing shared with you yet")
    if not rows:
        info("Nobody yet. Share with: skylls share <name> @user; a friend's shares: skylls source add <login>")


def cmd_source(cfg: dict, action: Optional[str], owner: Optional[str], dry_run: bool) -> None:
    """Friends whose shared skills, agents and swarms you see."""
    friends = cfg.setdefault("friends", [])
    if not action:
        section("Friends (sources)")
        for f in friends:
            counts: Dict[str, int] = {}
            for r in catalog(cfg, owner=f):
                counts[r["kind"]] = counts.get(r["kind"], 0) + 1
            say(f"  {GREEN}•{NC} {CYAN}{f}{NC}  "
                + (", ".join(f"{n} {k}" for k, n in counts.items()) or "nothing shared with you yet"))
        if not friends:
            info("None yet. When a friend shares with you: skylls source add <their-login>")
        return
    owner = (owner or "").lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", owner):
        die(f"Usage: skylls source {action} <github-login-or-organization>")
    if action == "add":
        if dry_run:
            info(f"Would add {owner} and accept their pending shares")
            return
        if owner.lower() not in {f.lower() for f in friends}:
            friends.append(owner)
            core.save_config(cfg)
        _catalog.clear()
        before = {f.lower() for f in friends}
        items = catalog(cfg)
        added = {owner.lower()} | {f.lower() for f in cfg["friends"]} - before  # + their organization
        counts = {}
        for r in items:
            if r["owner"].lower() in added:
                counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        ok(f"Added {owner}: " + (", ".join(f"{n} {k}" for k, n in counts.items()) or
                                  "nothing shared with you yet (it appears once they share)"))
    else:
        if owner.lower() not in {f.lower() for f in friends}:
            die(f"{owner} is not one of your sources.")
        if dry_run:
            info(f"Would stop listing {owner}'s items")
            return
        cfg["friends"] = [f for f in friends if f.lower() != owner.lower()]
        core.save_config(cfg)
        ok(f"Removed {owner} (what you installed stays)")


# ── Folders (GitHub topics) ────────────────────────────────────────────────
def cmd_move(cfg: dict, kind: str, name: str, folder: str, dry_run: bool) -> None:
    r = resolve(cfg, kind, name, cfg["owner"])
    if dry_run:
        info(f"Would put {r['repo']} in folder '{folder}'")
        return
    set_folder(r["repo"], folder)


def cmd_folder(cfg: dict, action: Optional[str], names: List[str], dry_run: bool) -> None:
    items = [r for r in catalog(cfg) if r["mine"]]
    if not action:
        section("Your folders (GitHub topics)")
        counts: Dict[str, int] = {}
        for r in items:
            counts[r["folder"] or "(no folder)"] = counts.get(r["folder"] or "(no folder)", 0) + 1
        for f, n in sorted(counts.items()):
            say(f"  {GREEN}•{NC} {CYAN}{f}{NC}  {n} item{'s' if n != 1 else ''}")
        say(f"  On GitHub: https://github.com/{cfg['owner']}?tab=repositories&q=topic:<folder>")
        return
    if len(names) != (2 if action == "rename" else 1):
        die("Usage: skylls folder rename <old> <new>  |  skylls folder remove <folder>")
    old = folder_topic(names[0])
    inside = [r for r in items if r["folder"] == old]
    if not inside:
        die(f"No items in folder '{old}'.")
    new = folder_topic(names[1]) if action == "rename" else "."
    for r in inside:
        if dry_run:
            info(f"Would move {r['repo']} → {new}")
        else:
            set_folder(r["repo"], new)


# ── Suggestions ────────────────────────────────────────────────────────────
def cmd_suggest(cfg: dict, kind: str, name: str, owner: Optional[str], text: Optional[str], dry_run: bool) -> None:
    r = resolve(cfg, kind, name, owner)
    section(f"Suggesting an improvement to {r['owner']}'s {one(kind)} {r['name']}")
    if not text and sys.stdin.isatty():
        text = input(f"  {YELLOW}?{NC} What should be improved? ").strip()
    if not text:
        die(f'Describe it: skylls{cmd_prefix(kind)} suggest {r["name"]} --from {r["owner"]} "what to improve"')
    title = text.splitlines()[0][:80]
    body = f"{text}\n\n---\nSuggestion for {r['name']} v{r['version'] or '-'}, sent with skylls."
    if dry_run:
        info(f"Would open an issue in {r['repo']}: {title}")
        return
    core.gh("label", "create", SUGGESTION, "-R", r["repo"], "--force", "--color", "1D76DB",
            "--description", "Suggestions sent with skylls")
    args = ["issue", "create", "-R", r["repo"], "--title", title, "--body", body, "--label", SUGGESTION]
    res = core.gh(*args, "--assignee", r["owner"])
    if res.returncode != 0:
        res = core.gh(*args)
    if res.returncode != 0:
        die(f"Could not send it: {res.stderr.strip()}")
    ok(f"Sent to {r['owner']}: {res.stdout.strip()}")


def cmd_suggestions(cfg: dict, kind: str, name: Optional[str]) -> None:
    rows = []
    for r in catalog(cfg, kind):
        if r["mine"] and (not name or r["name"].lower() == name.lower()):
            for s in r["suggestions"]:
                rows.append({"id": f"{r['name']}#{s['number']}", "title": s["title"],
                             "type": "pull request" if s.get("pr") else "idea",
                             "by": (s.get("author") or {}).get("login", ""), "date": s["createdAt"][:10],
                             "url": s["url"]})
    if core.JSON_MODE:
        for row in rows:
            emit(row)
        return
    section(f"Open suggestions for your {kind}")
    for row in rows:
        say(f"  {YELLOW}{row['id']}{NC}  {row['title']}" + (f"  {CYAN}(pull request){NC}" if row["type"] != "idea" else ""))
        say(f"      by @{row['by']} on {row['date']}  {BLUE}{row['url']}{NC}")
    if rows:
        info(f"See one: skylls{cmd_prefix(kind)} review <name>#<n> · answer: accept <name>#<n> or decline <name>#<n> "
             "[-m note] (accepting a pull request merges it and publishes a new version)")
    else:
        info("None.")


def cmd_decide(cfg: dict, kind: str, ref: str, accept: bool, note: Optional[str], dry_run: bool,
               force: bool = False) -> None:
    name, number = split_ref(kind, ref)
    r = resolve(cfg, kind, name, cfg["owner"])
    pr = pr_of(r["repo"], number)
    if pr:
        if accept:
            accept_pr(cfg, kind, r, number, pr, note, force, dry_run)
        elif dry_run:
            info(f"Would close pull request {r['repo']}#{number} without merging")
        else:
            gh_ok("pr", "close", number, "-R", r["repo"], "--comment", note or "Thanks, but not planned.",
                  what=f"Could not close {r['repo']}#{number}")
            ok(f"Declined {r['name']}#{number}")
        return
    note = note or ("Done, thanks!" if accept else "Thanks, but not planned.")
    if dry_run:
        info(f"Would close {r['repo']}#{number} as {'done' if accept else 'not planned'}: {note}")
        return
    gh_ok("issue", "close", number, "-R", r["repo"], "--reason", "completed" if accept else "not planned",
          "--comment", note, what=f"Could not close {r['repo']}#{number}")
    ok(f"{'Accepted' if accept else 'Declined'} {r['name']}#{number}")


# ── Proposals: your changes to a friend's agent/swarm as a pull request ──────
def fork_name(repo: str) -> str:
    """Your fork of a friend's item repo: named after them, so it never clashes with your own item."""
    owner, name = repo.split("/")
    return f"{name}-from-{owner}"[:100]


def cmd_allow_prs(cfg: dict, kind: str, name: Optional[str], all_: bool, off: bool, dry_run: bool) -> None:
    """Let the people you share with fork your items, so they can send changes as pull requests."""
    set_prs(cfg, my_repos(cfg, kind, name, all_), not off, dry_run)
    if not off and not dry_run:
        info(f"They send changes with: skylls{cmd_prefix(kind)} propose <name> --from {cfg['owner']} -m \"what\"")


def copy_of(cfg: dict, kind: str, r: dict) -> Tuple[Path, str]:
    """Your downloaded copy of a friend's agent/swarm, and the version it came from."""
    item = local_item(cfg, kind, r["name"])
    source = core.read_changelog(item)["source"] if item.is_dir() else ""
    if not source.startswith(r["repo"] + " v"):
        die(f"{item} isn't a copy of {r['repo']}. Install it first: "
            f"skylls{cmd_prefix(kind)} add {r['name']} --from {r['owner']}, then change it and propose.")
    return item, source.rsplit(" v", 1)[1]


def definition_files(kind: str, item: Path) -> List[str]:
    """The files a proposal can change: shareable, not memory, not skills shared by reference."""
    skip_dirs = set(local_memory_dirs(item)) | {MEMORY_DIR}
    bundled = read_manifest(item)
    return [f for f in local_files(kind, item)
            if f not in (core.CHANGELOG, SKILLS_MANIFEST) and f.split("/", 1)[0] not in skip_dirs
            and not any(f.startswith(d + "/") for d in bundled)]


def stage_proposal(kind: str, item: Path, work: Path, skip: List[str]) -> List[str]:
    """Put your copy's files into a checkout of the version you installed, with the owner's paths put back
    (an install points their paths at yours). Returns `git status` lines of what changed."""
    log = core.read_changelog(work)  # the owner's paths, as published in that version
    origin, home, mine_home = log["origin"], log["home"], str(Path.home())
    skipped = lambda rel: any(fnmatch.fnmatch(rel, pat) for pat in skip)  # noqa: E731
    mine = [f for f in definition_files(kind, item) if not skipped(f)]
    for rel in definition_files(kind, work):
        if rel not in mine and not skipped(rel):
            (work / rel).unlink()  # you deleted it
    for rel in mine:
        data = (item / rel).read_bytes()
        try:
            text = data.decode()
            if origin:
                text = text.replace(str(item), origin)
            if home and home != mine_home:
                text = text.replace(mine_home + "/", home + "/")
            data = text.encode()
        except UnicodeDecodeError:
            pass
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_bytes(data)
    git("add", "-A", cwd=work)
    return git("status", "--porcelain", cwd=work).stdout.splitlines()


def ensure_fork(cfg: dict, kind: str, r: dict) -> str:
    """Your fork of the item repo (created the first time; GitHub needs a few seconds)."""
    fork = f"{cfg['owner']}/{fork_name(r['repo'])}"
    found = gh_json(core.gh_api(f"repos/{fork}")) if core.gh_api(f"repos/{fork}").returncode == 0 else None
    if found:
        if (found.get("parent") or {}).get("full_name", "").lower() != r["repo"].lower():
            die(f"{fork} exists but isn't a fork of {r['repo']}; rename or delete it.")
        return fork
    args = ["-X", "POST", f"repos/{r['repo']}/forks", "-f", f"name={fork_name(r['repo'])}",
            "-F", "default_branch_only=true"]
    if cfg.get("owner_is_org"):
        args += ["-f", f"organization={cfg['owner']}"]
    res = core.gh_api(*args)
    if res.returncode != 0:
        die(f"Could not fork {r['repo']}: {(res.stderr or res.stdout).strip()}\n"
            f"  {r['owner']} hasn't turned on pull requests for it. Ask them to run once:\n"
            f"      skylls{cmd_prefix(kind)} allow-prs {r['name']}")
    for _ in range(30):
        if git("ls-remote", "--heads", core.repo_url(fork), cwd=REPOS_CACHE, check=False).returncode == 0:
            ok(f"Forked {r['repo']} → {fork} (private)")
            return fork
        time.sleep(2)
    die(f"GitHub is still creating {fork}; run the same command again in a minute.")


def cmd_propose(cfg: dict, kind: str, name: str, owner: Optional[str], message: Optional[str], skip: List[str],
                skip_scan: bool, dry_run: bool) -> None:
    """Send the changes you made to your copy of a friend's agent/swarm as a pull request in their repo."""
    r = resolve(cfg, kind, name, owner)
    p = cmd_prefix(kind)
    if r["mine"]:
        die(f"{r['name']} is yours: publish changes with skylls{p} push {r['name']}")
    item, base = copy_of(cfg, kind, r)
    section(f"Proposing your changes to {r['owner']}'s {one(kind)} {r['name']} (you have v{base})")
    if not message and sys.stdin.isatty():
        message = input(f"  {YELLOW}?{NC} What do your changes do? ").strip()
    if not message:
        die(f'Describe them: skylls{p} propose {r["name"]} --from {r["owner"]} -m "what and why"')
    cache = sync_item(r["repo"])
    if base not in versions(cache):
        die(f"{r['repo']} has no v{base} any more; update your copy first (skylls{p} add {r['name']} -y).")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / r["name"]
        git("clone", "--quiet", str(cache), str(work), cwd=Path(tmp))
        slug = re.sub(r"[^a-z0-9]+", "-", message.lower()).strip("-")[:40] or "changes"
        branch = f"skylls/{slug}-{datetime.now():%Y%m%d-%H%M}"
        git("checkout", "--quiet", "-b", branch, f"v{base}", cwd=work)
        status = stage_proposal(kind, item, work, skip)
        if not status:
            ok(f"Your copy matches v{base}: nothing to propose.")
            return
        info(f"{len(status)} file(s) changed vs v{base}:")
        for line in status:
            say(f"    {line[:2].strip() or 'M'}  {line[3:]}")
        if skip:
            info(f"Left out: {', '.join(skip)}")
        if not skip_scan:
            scan = Path(tmp) / "scan" / r["name"]
            for line in status:
                rel = line[3:].split(" -> ")[-1]
                if (work / rel).is_file():
                    (scan / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(work / rel, scan / rel)
            if scan.exists():
                core.scan_secrets(scan)
        else:
            warn("Skipping the secret scan (--skip-scan).")
        if dry_run:
            info(f"Would fork {r['repo']}, push branch {branch} and open a pull request in {r['repo']}")
            return
        fork = ensure_fork(cfg, kind, r)
        res = git("commit", "--quiet", "-m", message, cwd=work, check=False)
        if res.returncode != 0:
            die("Could not commit. Set your git name and email:\n"
                "    git config --global user.name 'Your Name'; git config --global user.email you@example.com")
        git("push", "--quiet", core.repo_url(fork), f"HEAD:refs/heads/{branch}", cwd=work)
        files = "\n".join(f"- `{line[3:]}`" for line in status)
        body = (f"{message}\n\nChanged files (from v{base}):\n{files}\n\n---\n"
                f"Proposed with skylls by @{cfg['login']}. Review: `skylls{p} review {r['name']}#<n>` · "
                f"merge and publish: `skylls{p} accept {r['name']}#<n>` · `skylls{p} decline {r['name']}#<n>`.")
        res = core.gh("pr", "create", "-R", r["repo"], "--head", f"{fork.split('/')[0]}:{branch}", "--base", "main",
                      "--title", message.splitlines()[0][:80], "--body", body)
        if res.returncode != 0:
            die(f"Pushed {branch} to {fork}, but the pull request failed: {(res.stderr or res.stdout).strip()}")
    ok(f"Pull request for {r['owner']}: {res.stdout.strip()}")
    info(f"When they accept it you get it with: skylls{p} add {r['name']} --from {r['owner']} -y")


def pr_of(repo: str, number: str) -> Optional[dict]:
    """The pull request #number of repo, or None when #number is a plain suggestion (issue)."""
    issue = gh_json(core.gh_api(f"repos/{repo}/issues/{number}")) or {}
    if "pull_request" not in issue:
        return None
    return {"title": issue.get("title", ""), "author": (issue.get("user") or {}).get("login", ""),
            "state": issue.get("state", "")}


def cmd_review(cfg: dict, kind: str, ref: str) -> None:
    """Show a suggestion; for a pull request, its changes and whether they apply to your copy."""
    name, number = split_ref(kind, ref)
    r = resolve(cfg, kind, name, cfg["owner"])
    p = cmd_prefix(kind)
    pr = pr_of(r["repo"], number)
    if not pr:
        res = gh_ok("issue", "view", number, "-R", r["repo"], what=f"No suggestion {r['repo']}#{number}")
        say(res.stdout.rstrip())
        info(f"Answer with: skylls{p} accept {name}#{number}  or  decline {name}#{number} [-m note]")
        return
    section(f"Pull request {name}#{number} by @{pr['author']}: {pr['title']}")
    say(gh_ok("pr", "diff", number, "-R", r["repo"], what="Could not read the pull request").stdout.rstrip())
    src = local_original(cfg, kind, r["name"])
    if src:
        _, conflicts = pr_changes(r["repo"], number, src)
        if conflicts:
            warn("You changed these files since that version too; accept would stop (or use --force to take theirs):\n"
                 "    " + "\n    ".join(conflicts))
    info(f"Merge and publish: skylls{p} accept {name}#{number} [-m note]   ·   skylls{p} decline {name}#{number}")


def pr_changes(repo: str, number: str, src: Path) -> Tuple[List[Tuple[str, Optional[bytes]]], List[str]]:
    """What the pull request changes, as (file, new content or None = deleted), and the files you also
    changed locally since the version it started from (conflicts)."""
    path = sync_item(repo)
    ref = f"refs/skylls/pr-{number}"
    git("fetch", "--quiet", "origin", f"+refs/pull/{number}/head:{ref}", cwd=path)
    base = git("merge-base", "HEAD", ref, cwd=path).stdout.strip()
    changes, conflicts = [], []
    for line in git("diff", "--name-only", "--no-renames", base, ref, cwd=path).stdout.splitlines():
        rel = line.strip()
        if not rel or rel == core.CHANGELOG or ".." in rel.split("/"):
            continue
        theirs = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=path, capture_output=True)
        before = subprocess.run(["git", "show", f"{base}:{rel}"], cwd=path, capture_output=True)
        new = theirs.stdout if theirs.returncode == 0 else None
        old = before.stdout if before.returncode == 0 else None
        current = (src / rel).read_bytes() if (src / rel).is_file() else None
        if current not in (old, new):
            conflicts.append(rel)
        changes.append((rel, new))
    return changes, conflicts


def accept_pr(cfg: dict, kind: str, r: dict, number: str, pr: dict, note: Optional[str], force: bool,
              dry_run: bool) -> None:
    """Merge a pull request the skylls way: into your own copy, then publish a new version and close it."""
    p = cmd_prefix(kind)
    src = local_original(cfg, kind, r["name"])
    if not src:
        die(f"Your own copy of {r['name']} isn't on this computer; accept it where you publish it from.")
    changes, conflicts = pr_changes(r["repo"], number, src)
    if conflicts and not force:
        die("You changed these files since that version too:\n    " + "\n    ".join(conflicts) +
            f"\n  See the changes with skylls{p} review {r['name']}#{number}; merge them by hand and decline, "
            "or accept with --force to take theirs.")
    if dry_run:
        info(f"Would apply {len(changes)} file(s) from #{number} to {src}, publish a new version and close it")
        return
    for rel, data in changes:
        target = src / rel
        if data is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    ok(f"Applied {len(changes)} file(s) from @{pr['author']} to {src}")
    publish(cfg, kind, src, f"Merged #{number} from @{pr['author']}: {pr['title']}", "minor", None, None,
            False, False, ask=False)
    version = installed_version(src)
    core.gh("pr", "close", number, "-R", r["repo"], "--comment",
            (note + "\n\n" if note else "") + f"Merged into v{version} with skylls. Thanks!")
    ok(f"Closed {r['name']}#{number}; @{pr['author']} gets v{version} with: skylls{p} add {r['name']} -y")


def split_ref(kind: str, ref: str) -> Tuple[str, str]:
    name, _, number = ref.partition("#")
    if not number.isdigit():
        die(f"Use <name>#<number>, e.g. skylls{cmd_prefix(kind)} accept {name or 'pdf'}#3")
    return name, number


# ── Command line: the same subcommands for skills (top level), agents and swarms ──
def add_item_parsers(sub, kind: str, scoped) -> None:
    """Subcommands shared by skills (top level), `skylls agents …` and `skylls swarms …`."""
    o = one(kind)
    sp = sub.add_parser("list", help=f"Yours and your friends' {kind}.")
    sp.add_argument("query", nargs="?")
    sp.add_argument("--from", dest="owner")
    sp.add_argument("-f", "--folder")
    sp = sub.add_parser("find", help=f"Search {kind} by keyword and/or folder.")
    sp.add_argument("words", nargs="*")
    sp.add_argument("--from", dest="owner")
    sp.add_argument("-f", "--folder")
    sp.add_argument("-n", "--limit", type=int, help="At most N results (default 10 with --json).")
    sp = sub.add_parser("add", help=f"Install {an(o)} (name or name@version).")
    sp.add_argument("name")
    sp.add_argument("--from", dest="owner", help="Whose (when several people have one with that name).")
    sp.add_argument("-y", "--yes", action="store_true", help="Replace without asking.")
    if kind == "skills":
        scoped(sp)
    else:
        sp.add_argument("--as", dest="as_name", help="Install under another folder name.")
        sp.add_argument("--keep-memory", action="store_true",
                        help="Keep your copy of its memory; the owner's latest goes next to it in its own folder.")
        sp.add_argument("--update-memory", action="store_true", help=argparse.SUPPRESS)  # the default since 1.10
    for cmd in ("push",) + (("save",) if kind == "skills" else ()):
        sp = sub.add_parser(cmd, help=f"Publish a new version of your {o} to its private repo.")
        sp.add_argument("name", help=f"{o} name or folder")
        sp.add_argument("-m", "--message", help="What changed (logged with the new version).")
        group = sp.add_mutually_exclusive_group()
        group.add_argument("--minor", dest="part", action="store_const", const="minor", default="patch")
        group.add_argument("--major", dest="part", action="store_const", const="major")
        sp.add_argument("--about", help="Plain one-sentence summary (default: written by Claude).")
        sp.add_argument("--folder", help="Put it in this folder (a GitHub topic); '.' = none.")
        sp.add_argument("--skip-scan", action="store_true", help="Publish without the secret scan.")
        if kind == "skills":
            scoped(sp)
        else:
            sp.add_argument("-y", "--yes", action="store_true", help="Publish new memory notes without asking.")
    sp = sub.add_parser("log", help="Who made it, versions and what changed.")
    sp.add_argument("name")
    sp.add_argument("--from", dest="owner")
    sp = sub.add_parser("move", help=f"Put your {o} in a folder ('.' = no folder).")
    sp.add_argument("name")
    sp.add_argument("folder")
    sp = sub.add_parser("share", help=f"Let GitHub users install your {o} (no users: who has access).")
    sp.add_argument("name", nargs="?")
    sp.add_argument("users", nargs="*", metavar="@user")
    sp.add_argument("--all", dest="all_", action="store_true", help=f"Every {o} you published.")
    if kind != "skills":
        g = sp.add_mutually_exclusive_group()
        g.add_argument("--prs", dest="prs", action="store_const", const=True, default=None,
                       help="Also let them send pull requests with their changes (asked if not given).")
        g.add_argument("--no-prs", dest="prs", action="store_const", const=False, help="Don't (turns it off).")
    sp = sub.add_parser("unshare", help="Revoke access.")
    sp.add_argument("name", nargs="?")
    sp.add_argument("users", nargs="*", metavar="@user")
    sp.add_argument("--all", dest="all_", action="store_true")
    sp = sub.add_parser("suggest", help=f"Suggest an improvement to someone's {o}.")
    sp.add_argument("name")
    sp.add_argument("text", nargs="?")
    sp.add_argument("--from", dest="owner")
    sub.add_parser("suggestions", help=f"Open suggestions for your {kind}.").add_argument("name", nargs="?")
    for verb in ("accept", "decline"):
        sp = sub.add_parser(verb, help="Answer a suggestion or pull request (<name>#<n>).")
        sp.add_argument("ref", metavar="name#n")
        sp.add_argument("-m", "--message")
        if verb == "accept":
            sp.add_argument("--force", action="store_true",
                            help="Pull request: take their version of files you also changed.")
    sub.add_parser("review", help="Show a suggestion or a pull request's changes (<name>#<n>).").add_argument(
        "ref", metavar="name#n")
    if kind != "skills":
        sp = sub.add_parser("propose", help=f"Send your changes to a friend's {o} as a pull request.")
        sp.add_argument("name")
        sp.add_argument("--from", dest="owner")
        sp.add_argument("-m", "--message", help="What the changes do (the pull request's title).")
        sp.add_argument("--skip", action="append", default=[], metavar="FILE",
                        help="Leave out this file (pattern; repeatable), e.g. --skip scout/CLAUDE.md")
        sp.add_argument("--skip-scan", action="store_true", help="Send without the secret scan.")
        sp = sub.add_parser("allow-prs", help=f"Let people you share {an(o)} with send pull requests.")
        sp.add_argument("name", nargs="?")
        sp.add_argument("--all", dest="all_", action="store_true", help=f"Every {o} you published.")
        sp.add_argument("--off", action="store_true", help="Turn it off again.")
    if kind != "skills":
        sp = sub.add_parser("remove", help=f"Remove {an(o)} folder from this computer (to the Trash).")
        sp.add_argument("name")
        sp.add_argument("--memory", action="store_true", help="Also remove memory a download put outside it.")
        sp.add_argument("-y", "--yes", action="store_true")


def fix_share_args(args) -> None:
    """`share --all @bob` parses '@bob' as the name; move it to the users."""
    if getattr(args, "name", None) and args.name.startswith("@"):
        args.users = [args.name] + list(args.users or [])
        args.name = None


def run(cfg: dict, kind: str, cmd: str, args) -> None:
    if cmd == "list":
        cmd_list(cfg, kind, args.query, args.owner, args.folder)
    elif cmd == "find":
        cmd_find(cfg, kind, args.words, args.owner, args.folder, args.limit)
    elif cmd == "add":
        if kind == "skills":
            cmd_add_skill(cfg, args.name, args.owner, args.agent, bool(args.is_global), args.yes, args.dry_run)
        else:
            cmd_add_item(cfg, kind, args.name, args.owner, args.as_name, args.yes, args.keep_memory, args.dry_run)
    elif cmd in ("push", "save"):
        cmd_push(cfg, kind, args)
    elif cmd == "log":
        cmd_log(cfg, kind, args.name, args.owner)
    elif cmd == "move":
        cmd_move(cfg, kind, args.name, args.folder, args.dry_run)
    elif cmd in ("share", "unshare"):
        fix_share_args(args)
        if cmd == "unshare" and not args.users:
            die(f"Who? skylls{cmd_prefix(kind)} unshare <name> @user")
        if cmd == "share":
            cmd_share(cfg, kind, args.name, args.users, args.all_, args.dry_run, getattr(args, "prs", None))
        else:
            cmd_unshare(cfg, kind, args.name, args.users, args.all_, args.dry_run)
    elif cmd == "suggest":
        cmd_suggest(cfg, kind, args.name, args.owner, args.text, args.dry_run)
    elif cmd == "suggestions":
        cmd_suggestions(cfg, kind, args.name)
    elif cmd in ("accept", "decline"):
        cmd_decide(cfg, kind, args.ref, cmd == "accept", args.message, args.dry_run, getattr(args, "force", False))
    elif cmd == "review":
        cmd_review(cfg, kind, args.ref)
    elif cmd == "propose":
        cmd_propose(cfg, kind, args.name, args.owner, args.message, args.skip, args.skip_scan, args.dry_run)
    elif cmd == "allow-prs":
        cmd_allow_prs(cfg, kind, args.name, args.all_, args.off, args.dry_run)
    elif cmd == "remove":
        cmd_remove_item(cfg, kind, args.name, args.memory, args.yes, args.dry_run)
