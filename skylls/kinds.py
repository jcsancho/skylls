"""
Per-owner sharing for skills, agents and swarms.

Everyone keeps their own GitHub repos (one each for skills, agents and swarms)
and invites friends to them (`share`). A friend's repo you were invited to is a
*source*: you can list, find and download what is in it. GitHub enforces who may
download (repo access); skylls adds versions, changelogs and suggestions on top.

- skills: your own repo is the shared skills repo from cli.py (cache clone).
- agents / swarms: your own repo is the git clone you work in (~/agents,
  ~/swarms). `push` versions one folder in place: commits only that folder,
  tags it and pushes. Friends download only the *definition* of an agent or
  swarm (instructions, .claude/, scripts, swarm config), never runtime state.

Memory: an agent's or swarm's Obsidian memory lives in its own folder by default
(a subfolder that is an Obsidian vault, or is named memory / wiki / obsidian /
*-wiki). It is shared with the item; on updates a friend's own copy of it is kept
unless they ask for --update-memory. Memory still kept elsewhere in ~/Obsidian
(a `<x>-wiki` vault or `<vault>/AGENTS/<name>/` mentioned in the instructions)
is snapshotted into `<item>/.skylls-memory/` on push and restored to the same
place under the friend's home.

Sources are partial clones (--filter=blob:none) under ~/.cache/skylls/sources,
so listing a large repo downloads no file contents and a download fetches only
the files it needs.
"""

import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from skylls import cli as core
from skylls.cli import BLUE, CYAN, GREEN, NC, YELLOW, die, emit, git, info, ok, say, section, warn

SOURCES_CACHE = Path.home() / ".cache" / "skylls" / "sources"
MAX_FILE = 5 * 1024 * 1024  # definition files bigger than this are not shared
KINDS = {
    "skills": {"one": "skill", "main": ("SKILL.md",)},
    "agents": {"one": "agent", "main": ("CLAUDE.md", "AGENTS.md", "GEMINI.md")},
    "swarms": {"one": "swarm", "main": ("CLAUDE.md", "AGENTS.md", "GEMINI.md")},
}
# Runtime state of agents and swarms: never shared.
RUNTIME_DIRS = {"logs", "data", "reports", "scratch", "state", "output", "outputs", "tmp", "temp", "cache",
                ".cache", "node_modules", ".venv", "venv", "env", "__pycache__", ".git",
                ".pytest_cache", ".mypy_cache", "dist", "build"}
RUNTIME_FILES = ["*.log", "*.jsonl", "*_state.json", "*.bak", "*.bak-*", "*.db", "*.sqlite", "*.sqlite3",
                 "*.pyc", ".DS_Store", "settings.local.json", ".env", ".env.*", "*.env", "*.pem", "*.key"]
# A swarm is shared as its configuration only: instructions and settings, top level and per role.
SWARM_KEEP = ["CLAUDE.md", "AGENTS.md", "GEMINI.md", "README.md", "CHANGELOG.md", ".skyllsignore", ".skyllsmemory",
              ".claude/*", ".swarm/agents.json", ".swarm/schedules.json", "*/CLAUDE.md", "*/AGENTS.md",
              "*/GEMINI.md", "*/.claude/*"]
MEMORY_NAMES = {"memory", "wiki", "obsidian"}  # in-folder memory, besides any Obsidian vault or *-wiki
MEMORY_DIR = ".skylls-memory"  # snapshot of the item's Obsidian memory, by path under the owner's home
MEMORY_SKIP = [".obsidian/workspace*", ".trash/*", ".DS_Store", "*.tmp"]
OBSIDIAN_RE = re.compile(r"(?:~|\$HOME|\$\{HOME\}|\bHOME|/Users/[^/\s\"'`]+|/home/[^/\s\"'`]+)"
                         r"/(Obsidian/[^\s\"'`)\]>,;*]+)")


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


def shareable(kind: str, rel: str, rules: List[str], size: int = 0, memory: Tuple[str, ...] = ()) -> bool:
    """Is this file (path relative to the item) part of what friends download?"""
    parts = rel.split("/")
    if kind != "skills" and len(parts) > 1 and parts[0] in memory:
        keep = memory_file_ok("/".join(parts[1:]), size)
        for rule in rules:
            negate = rule.startswith("!")
            if rule_matches(rel, rule[1:] if negate else rule):
                keep = negate
        return keep
    if rel.startswith(MEMORY_DIR + "/") and kind != "skills":
        keep = memory_file_ok(rel[len(MEMORY_DIR) + 1:], size)
        for rule in rules:
            negate = rule.startswith("!")
            if rule_matches(rel, rule[1:] if negate else rule):
                keep = negate
        return keep
    if kind == "skills":
        keep = not any(p in (".git", "__pycache__") for p in parts) and parts[-1] != ".DS_Store"
    else:
        keep = (size <= MAX_FILE and not any(p in RUNTIME_DIRS for p in parts[:-1])
                and not any(fnmatch.fnmatch(parts[-1], pat) for pat in RUNTIME_FILES)
                and not rel.startswith(".agent/state/"))
        if kind == "swarms":
            keep = keep and any(fnmatch.fnmatch(rel, pat) for pat in SWARM_KEEP)
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
            if shareable(kind, rel, rules, path.stat().st_size, memory):
                out.append(rel)
    return sorted(out)


def is_item(kind: str, path: Path) -> bool:
    if not path.is_dir() or path.name.startswith("."):
        return False
    return any((path / m).is_file() for m in KINDS[kind]["main"]) or \
        (kind == "swarms" and (path / ".swarm").is_dir())


def main_file(kind: str, path: Path) -> Optional[Path]:
    return next((path / m for m in KINDS[kind]["main"] if (path / m).is_file()), None)


def first_line(path: Optional[Path]) -> str:
    """A fallback description: the first plain line of an instruction file."""
    if not path:
        return ""
    if path.name == "SKILL.md":
        return core.get_skill_description(path.parent) or ""
    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip().lstrip("#>*- ").strip()
        if len(line) > 15 and not line.startswith(("---", "<!--")):
            return line[:77] + "..." if len(line) > 80 else line
    return ""


# ── Obsidian memory ────────────────────────────────────────────────────────
def memory_roots(kind: str, item: Path) -> List[str]:
    """The item's memory folders, as paths under your home ('Obsidian/btc-wiki').

    `.skyllsmemory` (one path per line) decides if present. Otherwise they are
    found in the instructions: `<x>-wiki` vaults they mention, and
    `<vault>/AGENTS/<name>` when <name> is this item (other agents' folders and
    personal notes are not memory)."""
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
        return sorted(r for r in roots if (home / r).is_dir())
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
    """Mirror the memory folders into <item>/.skylls-memory/; returns the number of files."""
    snap = item / MEMORY_DIR
    wanted: Dict[str, Path] = {}
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(Path.home() / root):
            dirnames[:] = [d for d in dirnames if d not in (".git", ".trash")]
            for f in filenames:
                src = Path(dirpath) / f
                inner = src.relative_to(Path.home() / root).as_posix()
                if src.is_symlink() or src.stat().st_size > MAX_FILE or \
                        any(fnmatch.fnmatch(inner, pat) for pat in MEMORY_SKIP):
                    continue
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


def install_memory(cache_item: Path, rels: List[str], update: bool) -> List[str]:
    """Copy a downloaded memory snapshot to the same place under your home; returns the folders."""
    by_root: Dict[str, List[str]] = {}
    for rel in rels:
        inner = rel[len(MEMORY_DIR) + 1:]
        parts = inner.split("/")
        depth = 4 if len(parts) > 4 and parts[2] == "AGENTS" else 2
        by_root.setdefault("/".join(parts[:depth]), []).append(inner)
    done = []
    for root, files in by_root.items():
        target = Path.home() / root
        if target.exists() and not update:
            info(f"Kept your memory at ~/{root} (refresh it from the source with --update-memory)")
            continue
        for inner in files:
            dst = Path.home() / inner
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cache_item / MEMORY_DIR / inner, dst)
        done.append(root)
    return done


# ── Configuration ──────────────────────────────────────────────────────────
def kind_cfg(cfg: dict, kind: str) -> dict:
    """{'repo', 'dir'} of your own repo for this kind."""
    if kind == "skills":
        return {"repo": cfg["repo"]}
    kc = cfg.get("kinds", {}).get(kind) or {}
    if not kc.get("repo"):
        die(f"No {kind} repo set up yet. Run: skylls setup")
    return kc


def sources(cfg: dict, kind: str) -> List[str]:
    return cfg.get("sources", {}).get(kind, [])


def owner_of(repo: str) -> str:
    """GitHub owner of a repo; for a local path (tests), its parent folder name."""
    slug = core.github_slug(repo)
    return slug.split("/")[0] if slug else Path(repo.rstrip("/")).parent.name


REPO_GITIGNORE = """# Written by skylls. skylls itself only commits what you publish with `push`;
# this protects the repo if you also commit by hand.
# Runtime state of each agent/swarm (top-level folders of an item only):
/*/logs/
/*/data/
/*/reports/
/*/scratch/
/*/state/
/*/tmp/
/*/.agent/state/
/*/.swarm/bus.jsonl
# Secrets and personal settings
.env
.env.*
*.env
*.pem
*.key
**/.claude/settings.local.json
# Obsidian per-user window layout
**/.obsidian/workspace*.json
# Caches
__pycache__/
.venv/
venv/
node_modules/
.DS_Store
*.log
"""


def ensure_private(repo: str) -> None:
    """Your repos should be private: warn about a public one and offer to fix it."""
    slug = core.github_slug(repo)
    if not slug or not shutil.which("gh"):
        return
    res = core.gh("repo", "view", slug, "--json", "visibility", "--jq", ".visibility")
    if res.returncode != 0 or res.stdout.strip() != "PUBLIC":
        return
    warn(f"{slug} is PUBLIC: everything you publish there is visible to everyone.")
    if sys.stdin.isatty() and input(f"  {YELLOW}?{NC} Make it private? (Y/n): ").strip().lower() != "n":
        res = core.gh("repo", "edit", slug, "--visibility", "private", "--accept-visibility-change-consequences")
        if res.returncode == 0:
            ok(f"{slug} is now private.")
        else:
            warn(f"Could not make {slug} private: {res.stderr.strip()}")


def create_private_repo(kind: str) -> str:
    """Create <your-login>/skylls-<kind> as a private GitHub repo (or reuse it if it exists)."""
    if not shutil.which("gh"):
        die(f"To create your {kind} repo, install the GitHub CLI and log in (brew install gh; gh auth login), "
            "or create a private repo yourself and give its owner/name.")
    login = core.my_login() or die("The GitHub CLI isn't logged in. Run: gh auth login")
    slug = f"{login}/skylls-{kind}"
    if core.gh("repo", "view", slug).returncode == 0:
        info(f"Using your existing {slug}.")
        ensure_private(slug)
        return slug
    res = core.gh("repo", "create", slug, "--private", "--description", f"My {kind}, shared with skylls")
    if res.returncode != 0:
        die(f"Could not create {slug}: {res.stderr.strip()}")
    ok(f"Created private repo {slug}")
    return slug


def choose_repo(kind: str, given: Optional[str], current: str, detected: str, create: bool) -> Optional[str]:
    """Your existing GitHub repo for this kind, or a new private one (None = skip)."""
    if given:
        return given
    default = current or detected
    if sys.stdin.isatty():
        hint = f"Enter = {default}" if default else "Enter = create a new private repo"
        skip = "" if kind == "skills" else ", '-' = skip"
        answer = input(f"  {YELLOW}?{NC} Do you already have a GitHub repo for your {kind}? "
                       f"owner/name ({hint}{skip}): ").strip()
        if answer == "-" and kind != "skills":
            return None
        if answer:
            return answer
        return default or create_private_repo(kind)
    if default:
        return default
    return create_private_repo(kind) if create else None


def init_empty_repo(path: Path, kind: str) -> None:
    """A brand-new repo has no commits: give it a README (+ .gitignore) so it has a main branch."""
    if git("rev-parse", "--verify", "--quiet", "HEAD", cwd=path, check=False).returncode == 0:
        return
    created = []
    if not (path / "README.md").exists():
        (path / "README.md").write_text(f"# My {kind}\n\nShared with skylls: friends you invite can install "
                                        f"them with `skylls{'' if kind == 'skills' else ' ' + kind} source add`.\n")
        created.append("README.md")
    if kind != "skills" and not (path / ".gitignore").exists():
        (path / ".gitignore").write_text(REPO_GITIGNORE)
        created.append(".gitignore")
    git("add", "--", *created, cwd=path)
    res = git("commit", "--quiet", "-m", f"skylls: start my {kind} repo", cwd=path, check=False)
    if res.returncode != 0:
        die("Could not make the first commit. Set your git name and email:\n"
            "    git config --global user.name 'Your Name'; git config --global user.email you@example.com\n"
            f"{res.stderr.strip()}")
    git("branch", "-M", "main", cwd=path)
    res = git("push", "--quiet", "-u", "origin", "main", cwd=path, check=False)
    if res.returncode != 0:
        die(f"Could not push the first commit: {res.stderr.strip()}")


def setup_kind(cfg: dict, kind: str, repo: Optional[str], folder: Optional[str], create: bool = False) -> None:
    """Your agents/swarms: the folder where they live and your private GitHub repo for them."""
    current = cfg.get("kinds", {}).get(kind, {})
    interactive = sys.stdin.isatty()
    default_dir = current.get("dir") or str(Path.home() / kind)
    if not folder:
        folder = (input(f"  {YELLOW}?{NC} Folder for your {kind} [{default_dir}]: ").strip() if interactive
                  else "") or default_dir
    path = Path(folder).expanduser()
    detected = ""
    if (path / ".git").exists():
        origin = git("remote", "get-url", "origin", cwd=path, check=False).stdout.strip()
        detected = core.github_slug(origin) or origin
    repo = choose_repo(kind, repo, current.get("repo", ""), detected, create)
    if not repo:
        info(f"No {kind} repo; skipped (run 'skylls setup' again to add it).")
        return
    ensure_private(repo)
    url = core.repo_url(repo)
    if not (path / ".git").exists():
        if path.exists() and any(path.iterdir()):
            # An existing folder that isn't a clone yet: connect it to a new, empty repo without uploading it.
            if git("ls-remote", "--heads", url, cwd=Path.home(), check=False).stdout.strip():
                die(f"{path} has files but isn't a clone of {repo}, which already has content. "
                    f"Move the folder away and run setup again (it will clone {repo} there).")
            if interactive and input(f"  {YELLOW}?{NC} Connect {path} to {repo}? Nothing is uploaded until you "
                                     f"publish with 'skylls {kind} push'. (Y/n): ").strip().lower() == "n":
                die("Setup stopped.")
            git("init", "--quiet", "-b", "main", cwd=path)
            git("remote", "add", "origin", url, cwd=path)
        else:
            info(f"Cloning {repo} into {path} …")
            res = git("clone", "--quiet", url, str(path), cwd=Path.home(), check=False)
            slug = core.github_slug(repo)
            if res.returncode != 0 and slug and (create or (interactive and input(
                    f"  {YELLOW}?{NC} {slug} doesn't exist. Create it as a private repo? (Y/n): ")
                    .strip().lower() != "n")):
                created = core.gh("repo", "create", slug, "--private", "--description",
                                  f"My {kind}, shared with skylls")
                if created.returncode != 0:
                    die(f"Could not create {slug}: {created.stderr.strip()}")
                res = git("clone", "--quiet", url, str(path), cwd=Path.home(), check=False)
            if res.returncode != 0:
                die(f"Could not clone {repo}: {res.stderr.strip()}")
        init_empty_repo(path, kind)
    elif detected and core.github_slug(repo) != core.github_slug(detected) and repo != detected:
        warn(f"{path} is a clone of {detected}, not {repo}.")
    cfg.setdefault("kinds", {})[kind] = {"repo": repo, "dir": str(path)}
    ok(f"{kind}: {repo} ↔ {path}")


# ── Sources (friends' repos) ───────────────────────────────────────────────
def source_cache(kind: str, repo: str) -> Path:
    key = re.sub(r"[^\w.-]+", "_", core.github_slug(repo) or repo).strip("_")
    return SOURCES_CACHE / kind / key


def sync_source(kind: str, repo: str) -> Path:
    """Partial clone (no file contents) of a friend's repo, refreshed."""
    path = source_cache(kind, repo)
    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        info(f"Connecting to {repo} …")
        res = git("clone", "--quiet", "--filter=blob:none", "--no-checkout", core.repo_url(repo), str(path),
                  cwd=path.parent, check=False)
    else:
        res = git("fetch", "--quiet", "--tags", "--force", "--prune", "origin", cwd=path, check=False)
    if res.returncode != 0:
        die(f"No access to {repo}. Ask its owner to run: skylls{'' if kind == 'skills' else ' ' + kind} "
            f"share @<your-github-user>\n{res.stderr.strip()}")
    return path


def tree(cache: Path, ref: str) -> List[str]:
    """All file paths at ref (no file contents are downloaded)."""
    return git("ls-tree", "-r", "--name-only", ref, cwd=cache).stdout.splitlines()


def restore(cache: Path, ref: str, paths: List[str]) -> None:
    """Fetch just these files (one batch) into the cache's working tree."""
    if paths:
        res = subprocess.run(["git", "restore", f"--source={ref}", "--worktree", "--pathspec-from-file=-"],
                             cwd=cache, input="\n".join(paths), capture_output=True, text=True)
        if res.returncode != 0:
            die(f"Could not fetch files from {ref}: {res.stderr.strip()}")


def items_in_tree(kind: str, paths: List[str]) -> Dict[str, str]:
    """{item name: its path in the repo}."""
    found: Dict[str, str] = {}
    for p in paths:
        parts = p.split("/")
        if kind == "skills":
            if parts[-1] == "SKILL.md" and 2 <= len(parts) <= 4 and not any(x.startswith(".") for x in parts):
                found.setdefault(parts[-2], "/".join(parts[:-1]))
        elif len(parts) >= 2 and not parts[0].startswith("."):
            if (len(parts) == 2 and parts[1] in KINDS[kind]["main"]) or \
                    (kind == "swarms" and parts[1] == ".swarm"):
                found.setdefault(parts[0], parts[0])
    return found


def source_items(kind: str, repo: str) -> Tuple[Path, Dict[str, str]]:
    """Sync a source and fetch its items' changelogs + instruction files (small, one batch)."""
    cache = sync_source(kind, repo)
    paths = tree(cache, "origin/HEAD")
    items = items_in_tree(kind, paths)
    present = set(paths)
    wanted = [f"{d}/{f}" for d in items.values() for f in (core.CHANGELOG, *KINDS[kind]["main"])
              if f"{d}/{f}" in present]
    restore(cache, "origin/HEAD", wanted)
    return cache, items


def record(kind: str, name: str, path: Path, owner: Optional[str] = None, repo: Optional[str] = None) -> dict:
    log = core.read_changelog(path)
    return {"name": name, "from": owner, "repo": repo,
            "version": log["entries"][0]["version"] if log["entries"] else None,
            "summary": log["about"] or first_line(main_file(kind, path)),
            "updated": log["entries"][0]["date"] if log["entries"] else None,
            "source": log["source"] or None}


def pick_source(cfg: dict, kind: str, name: str, owner: Optional[str]) -> Tuple[str, Path, str]:
    """(repo, cache, path in repo) of an item in your sources; --from narrows it to one owner."""
    repos = [r for r in sources(cfg, kind) if not owner or owner.lower() in (owner_of(r).lower(), r.lower())]
    if not repos:
        die(f"No {kind} source{f' from {owner}' if owner else ''}. Add one: "
            f"skylls{'' if kind == 'skills' else ' ' + kind} source add <owner>/<repo>")
    hits = []
    for repo in repos:
        cache = sync_source(kind, repo)
        where = items_in_tree(kind, tree(cache, "origin/HEAD")).get(name)
        if where:
            hits.append((repo, cache, where))
    if not hits:
        die(f"No {KINDS[kind]['one']} '{name}' in {', '.join(repos)}.")
    if len(hits) > 1:
        die(f"'{name}' is in several sources ({', '.join(h[0] for h in hits)}); add --from <owner>.")
    return hits[0]


def resolve_ref(cache: Path, name: str, version: str) -> str:
    if not version:
        return "origin/HEAD"
    tag = f"{name}@{version.lstrip('v')}"
    if not git("tag", "-l", tag, cwd=cache).stdout.strip():
        known = sorted((t.split("@", 1)[1] for t in git("tag", "-l", f"{name}@*", cwd=cache).stdout.split()),
                       key=core.version_key)
        die(f"No version {version} of '{name}'. Available: {', '.join(known) or 'none'}")
    return tag


def fetch_item(kind: str, cache: Path, ref: str, where: str) -> List[str]:
    """Fetch the shareable files of one item at ref into the cache; returns them relative to the item."""
    paths = [p for p in tree(cache, ref) if p.startswith(where + "/")]
    ignore = f"{where}/.skyllsignore"
    rules = []
    if ignore in paths:
        restore(cache, ref, [ignore])
        rules = parse_rules((cache / ignore).read_text(errors="ignore"))
    all_rels = [p[len(where) + 1:] for p in paths]
    memory = tuple(memory_dirs_in(all_rels)) if kind != "skills" else ()
    rels = [r for r in all_rels if shareable(kind, r, rules, 0, memory)]
    restore(cache, ref, [f"{where}/{r}" for r in rels])
    big = [r for r in rels if (cache / where / r).stat().st_size > MAX_FILE and kind != "skills"]
    if big:
        warn(f"Skipped files over 5 MB: {', '.join(big)}")
    return [r for r in rels if r not in big]


def fetch_source_skill(cfg: dict, spec: str, owner: Optional[str]) -> Tuple[Path, str]:
    """For 'skylls add <skill> --from <owner>': (folder to install from, skill name)."""
    name, _, version = spec.partition("@")
    repo, cache, where = pick_source(cfg, "skills", name, owner)
    ref = resolve_ref(cache, name, version)
    fetch_item("skills", cache, ref, where)
    info(f"From {repo} ({ref.replace('origin/HEAD', 'latest')})")
    return cache / where, name


def cmd_source(cfg: dict, kind: str, action: Optional[str], repo: Optional[str], dry_run: bool) -> None:
    listed = cfg.setdefault("sources", {}).setdefault(kind, [])
    if not action:
        section(f"{kind.capitalize()} sources (friends' repos you can install from)")
        for r in listed:
            say(f"  {GREEN}•{NC} {CYAN}{owner_of(r)}{NC}  {r}")
        if not listed:
            info(f"None yet. Add one: skylls{'' if kind == 'skills' else ' ' + kind} source add <owner>/<repo>")
        return
    if not repo:
        die(f"Usage: skylls{'' if kind == 'skills' else ' ' + kind} source {action} <owner>/<repo>")
    if action == "add":
        if repo in listed:
            ok(f"{repo} is already a source.")
            return
        if dry_run:
            info(f"Would add {repo} as a {kind} source")
            return
        cache = sync_source(kind, repo)  # fails here if the owner hasn't shared it with you
        count = len(items_in_tree(kind, tree(cache, "origin/HEAD")))
        listed.append(repo)
        core.save_config(cfg)
        ok(f"Added {repo}: {count} {kind} from {owner_of(repo)}")
    else:
        if repo not in listed:
            die(f"{repo} is not a source.")
        if dry_run:
            info(f"Would remove the source {repo}")
            return
        listed.remove(repo)
        core.save_config(cfg)
        shutil.rmtree(source_cache(kind, repo), ignore_errors=True)
        ok(f"Removed source {repo} (what you already installed stays)")


# ── Your own agents / swarms ───────────────────────────────────────────────
def own_root(cfg: dict, kind: str) -> Path:
    root = Path(kind_cfg(cfg, kind)["dir"]).expanduser()
    if not (root / ".git").exists():
        die(f"{root} is not a git clone of {kind_cfg(cfg, kind)['repo']}. Run: skylls setup")
    return root


def own_items(cfg: dict, kind: str) -> Dict[str, Path]:
    root = own_root(cfg, kind)
    return {p.name: p for p in sorted(root.iterdir()) if is_item(kind, p)}


def tagged_files(root: Path, kind: str, name: str, tag: str) -> List[str]:
    paths = [p[len(name) + 1:] for p in tree(root, tag) if p.startswith(name + "/")]
    return [r for r in paths if shareable(kind, r, [])]


def cmd_push(cfg: dict, kind: str, name: str, message: Optional[str], part: str, about: Optional[str],
             skip_scan: bool, dry_run: bool) -> None:
    """Publish a new version of one of your agents/swarms: commit only its folder, tag and push."""
    root = own_root(cfg, kind)
    item = root / name
    if not is_item(kind, item):
        die(f"No {KINDS[kind]['one']} '{name}' in {root}.")
    section(f"Publishing {KINDS[kind]['one']}: {name}")
    roots = memory_roots(kind, item)
    if dry_run:
        info(f"Memory: {', '.join('~/' + r for r in roots) or 'none found'}")
    else:
        count = snapshot_memory(item, roots)
        if roots:
            info(f"Memory outside the folder: {', '.join('~/' + r for r in roots)} ({count} files, snapshotted)")
    inner = local_memory_dirs(item)
    if inner:
        info(f"Memory in the folder: {', '.join(d + '/' for d in inner)}")
    files = local_files(kind, item)
    if skip_scan:
        warn("Skipping the secret scan (--skip-scan).")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            for rel in files:
                (Path(tmp) / name / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item / rel, Path(tmp) / name / rel)
            core.scan_secrets(Path(tmp) / name)
    log = core.read_changelog(item)
    last = log["entries"][0]["version"] if log["entries"] else None
    last_tag = f"{name}@{last}" if last and git("tag", "-l", f"{name}@{last}", cwd=root).stdout.strip() else None
    defs = [f for f in files if f != core.CHANGELOG]
    if last_tag and not about:
        old = [f for f in tagged_files(root, kind, name, last_tag) if f != core.CHANGELOG]
        same = set(old) == set(defs) and git("diff", "--quiet", last_tag, "--", *[f"{name}/{f}" for f in defs],
                                              cwd=root, check=False).returncode == 0
        if same:
            ok(f"'{name}' v{last} is already up to date (no changes to its definition).")
            return
    version = core.bump(last, part)
    while git("tag", "-l", f"{name}@{version}", cwd=root).stdout.strip():
        version = core.bump(version, "patch")
    if dry_run:
        info(f"Would publish {name} v{last or '-'} → v{version} ({len(defs)} definition files) to "
             f"{kind_cfg(cfg, kind)['repo']}")
        return
    git("fetch", "--quiet", "origin", cwd=root, check=False)
    behind = git("rev-list", "--count", "HEAD..@{u}", cwd=root, check=False).stdout.strip()
    if behind and behind != "0":
        res = git("pull", "--quiet", "--rebase", "--autostash", cwd=root, check=False)
        if res.returncode != 0:
            git("rebase", "--abort", cwd=root, check=False)
            die(f"Could not update {root} from GitHub; sync it by hand, then push again.\n{res.stderr.strip()}")
    if not message and sys.stdin.isatty():
        message = input(f"  {YELLOW}?{NC} What changed in v{version}? ").strip()
    notes = message or ("First version" if not last else "Updated")
    main = main_file(kind, item)
    if about:
        log["about"] = about
    elif not log["about"] or not last_tag or git("diff", "--quiet", last_tag, "--", f"{name}/{main.name}",
                                                  cwd=root, check=False).returncode != 0:
        log["about"] = core.ai_summary(item, main.name, f"AI {KINDS[kind]['one']} definition") or log["about"]
    me, today = core.my_name(), date.today().isoformat()
    if not log["created_by"]:
        slug = core.github_slug(kind_cfg(cfg, kind)["repo"])
        log["created_by"], log["created"] = me or "unknown", today
        log["owner_login"] = core.my_login() if slug else ""
    log["updates"] = "owner"  # per-owner repos: friends download and suggest; the owner publishes
    log["origin"], log["home"] = str(item), str(Path.home())
    log["entries"] = [{"version": version, "date": today, "author": me, "notes": notes}] + log["entries"]
    core.write_changelog(item, name, log)
    # Commit only the definition + memory snapshot (and their deletions); runtime files are left alone.
    ignore = item / ".skyllsignore"
    rules = parse_rules(ignore.read_text(errors="ignore")) if ignore.is_file() else []
    current = [f"{name}/{f}" for f in local_files(kind, item)]
    tracked = git("ls-files", "--", name, cwd=root).stdout.splitlines()
    memory = tuple(memory_dirs_in([t[len(name) + 1:] for t in tracked]) + local_memory_dirs(item))
    gone = [t for t in tracked if not (root / t).exists() and shareable(kind, t[len(name) + 1:], rules, 0, memory)]
    pathspec = "\n".join(current + gone)
    for cmd in (["add", "-A"], ["commit", "--quiet", "-m", f"{kind}: {name} {version} — {notes.splitlines()[0]}"]):
        res = subprocess.run(["git", *cmd, "--pathspec-from-file=-"], cwd=root, input=pathspec,
                             capture_output=True, text=True)
        if res.returncode != 0:
            die(f"git {cmd[0]} failed:\n{res.stderr.strip()}")
    tag = f"{name}@{version}"
    git("tag", tag, cwd=root)
    res = git("push", "--quiet", "--atomic", "origin", "HEAD", f"refs/tags/{tag}", cwd=root, check=False)
    if res.returncode != 0:
        git("tag", "-d", tag, cwd=root, check=False)
        git("reset", "--quiet", "--soft", "HEAD~1", cwd=root, check=False)  # undo the commit, keep the files
        die(f"Push failed; nothing was published (your files are untouched):\n{res.stderr.strip()}")
    ok(f"Published {name} v{version} to {kind_cfg(cfg, kind)['repo']}")
    if log["about"]:
        info(log["about"])


# ── Downloading from friends ───────────────────────────────────────────────
def rewrite_paths(dest: Path, rels: List[str], origin: str, home: str) -> None:
    """Point the owner's absolute paths (their copy, their home) at yours; report paths that don't exist here."""
    mine = str(Path.home())
    left = []
    for rel in rels:
        path = dest / rel
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        new = text.replace(origin, str(dest)) if origin else text
        if home and home != mine:
            new = new.replace(home + "/", mine + "/")
        if new != text:
            path.write_text(new)
        for m in re.finditer(re.escape(mine) + r"/[^\s\"'`)\]>,;*]+", new):
            target = m[0].rstrip("/.:")
            if "YYYY" not in target and "<" not in target and not Path(target).exists():
                left.append(f"{rel}: {target}")
    if left:
        warn("Paths that don't exist on this machine (check them):\n    " + "\n    ".join(sorted(set(left))[:10])
             + (" …" if len(set(left)) > 10 else ""))


def cmd_add(cfg: dict, kind: str, spec: str, owner: Optional[str], as_name: Optional[str], force: bool,
            dry_run: bool, update_memory: bool = False) -> None:
    """Download a friend's agent/swarm definition into your folder (updates keep your runtime data)."""
    name, _, version = spec.partition("@")
    repo, cache, where = pick_source(cfg, kind, name, owner)
    ref = resolve_ref(cache, name, version)
    root = Path(kind_cfg(cfg, kind)["dir"]).expanduser()
    dest = root / (as_name or name)
    section(f"Downloading {owner_of(repo)}'s {KINDS[kind]['one']} {name} → {dest}")
    fetched = fetch_item(kind, cache, ref, where)
    rels = [r for r in fetched if not r.startswith(MEMORY_DIR + "/")]
    memory = [r for r in fetched if r.startswith(MEMORY_DIR + "/")]
    inner = memory_dirs_in(rels)
    keep_mine = [d for d in inner if (dest / d).is_dir()] if not update_memory else []
    rels = [r for r in rels if r.split("/", 1)[0] not in keep_mine]
    for d in keep_mine:
        info(f"Kept your memory in {d}/ (refresh it from the source with --update-memory)")
    log = core.read_changelog(cache / where)
    got = log["entries"][0]["version"] if log["entries"] else "latest"
    if dry_run:
        info(f"Would install {len(rels)} definition files of {name} {got} from {repo} into {dest}"
             f"{f' and {len(memory)} memory files under ~/' if memory else ''}")
        return
    dest_existed = dest.exists()
    if dest_existed:
        mine = core.read_changelog(dest)
        from_them = mine["source"].startswith(f"{repo} {name}@")
        if not force and not from_them and \
                input(f"  {YELLOW}?{NC} {dest} exists and isn't a copy of {repo}'s {name}. Replace its "
                      f"definition files? (y/N): ").strip().lower() != "y":
            die("Nothing was changed.")
        for rel in local_files(kind, dest):  # drop definition files the new version no longer has
            if rel not in rels and rel != core.CHANGELOG and not rel.startswith(MEMORY_DIR + "/") \
                    and rel.split("/", 1)[0] not in local_memory_dirs(dest):
                (dest / rel).unlink()
    for rel in rels:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cache / where / rel, dest / rel)
    restored = install_memory(cache / where, memory, update_memory)  # existing memory only with --update-memory
    rewrite_paths(dest, rels, log["origin"], log["home"])
    log["source"] = f"{repo} {name}@{got}"
    log["origin"] = log["home"] = ""
    core.write_changelog(dest, as_name or name, log)
    ok(f"Installed {name} {got} from {repo} → {dest} ({len(rels)} files)")
    for folder in restored:
        ok(f"Memory → ~/{folder}")
    if (root / ".git").exists():
        info(f"It's in your own {kind} repo folder now; publish your version with: skylls {kind} push "
             f"{as_name or name}")


# ── Listing / finding / history ────────────────────────────────────────────
def all_records(cfg: dict, kind: str, owner: Optional[str] = None) -> List[Tuple[dict, Path]]:
    """Your items (unless --from) and every source's items, with the folder holding their files."""
    out = []
    if not owner and kind != "skills":
        for name, path in own_items(cfg, kind).items():
            out.append((record(kind, name, path), path))
    for repo in sources(cfg, kind):
        if owner and owner.lower() not in (owner_of(repo).lower(), repo.lower()):
            continue
        cache, items = source_items(kind, repo)
        for name, where in sorted(items.items()):
            out.append((record(kind, name, cache / where, owner_of(repo), repo), cache / where))
    return out


def print_record(r: dict) -> None:
    label = f" {BLUE}v{r['version']}{NC}" if r.get("version") else ""
    if r.get("from"):
        label += f"  from {r['from']}"
    if r.get("installed"):
        label += f"  {GREEN}(installed){NC}"
    say(f"  {GREEN}•{NC} {CYAN}{r['name']}{NC}{label}")
    if r.get("summary"):
        say(f"    {r['summary']}")
    extra = [f"updated {r['updated']}"] if r.get("updated") else []
    if r.get("source"):
        extra.append(f"copy of {r['source']}")
    if extra:
        say(f"    {' · '.join(extra)}")


def mark_installed(cfg: dict, kind: str, r: dict) -> dict:
    if r.get("from") and kind != "skills":
        r["installed"] = (Path(kind_cfg(cfg, kind)["dir"]).expanduser() / r["name"]).is_dir()
    elif r.get("from"):
        r["installed"] = core.installed_scope(cfg, r["name"])
    return r


def cmd_list(cfg: dict, kind: str, query: Optional[str], owner: Optional[str] = None) -> None:
    q = (query or "").lower()
    rows = [mark_installed(cfg, kind, r) for r, _ in all_records(cfg, kind, owner)
            if not q or q in f"{r['name']} {r.get('summary') or ''}".lower()]
    if core.JSON_MODE:
        for r in rows:
            emit(r)
        return
    groups: Dict[str, List[dict]] = {}
    for r in rows:
        groups.setdefault(r.get("from") or "", []).append(r)
    for who, items in groups.items():
        section(f"From {who} ({items[0]['repo']})" if who else f"Your {kind} ({kind_cfg(cfg, kind)['dir']})")
        for r in items:
            print_record(r)
    if not rows:
        warn(f"No {kind} found.")


def cmd_find(cfg: dict, kind: str, keywords: List[str], owner: Optional[str], limit: Optional[int]) -> None:
    terms = [k.lower() for k in keywords]
    scored = []
    for r, path in all_records(cfg, kind, owner):
        main = main_file(kind, path)
        fields = [(r["name"], 5), (r.get("summary") or "", 3),
                  (main.read_text(errors="ignore") if main else "", 1)]
        if all(any(t in text.lower() for text, _ in fields) for t in terms):
            scored.append((-sum(w for t in terms for text, w in fields if t in text.lower()), r["name"], r))
    scored.sort(key=lambda s: (s[0], s[1]))
    limit = limit if limit is not None else (10 if core.JSON_MODE else None)
    shown = [mark_installed(cfg, kind, r) for _, _, r in (scored[:limit] if limit else scored)]
    if core.JSON_MODE:
        for r in shown:
            emit(r)
        if len(scored) > len(shown):
            warn(f"{len(scored) - len(shown)} more; raise --limit")
        return
    section(f"{kind.capitalize()} matching '{' '.join(keywords)}'")
    for r in shown:
        print_record(r)
    if not shown:
        warn("No matches.")


def cmd_log(cfg: dict, kind: str, name: str, owner: Optional[str]) -> None:
    if owner or kind == "skills":
        repo, cache, where = pick_source(cfg, kind, name, owner)
        restore(cache, "origin/HEAD", [p for p in (f"{where}/{core.CHANGELOG}",) if p in tree(cache, "origin/HEAD")])
        path, who = cache / where, owner_of(repo)
    else:
        path = own_items(cfg, kind).get(name) or die(f"No {KINDS[kind]['one']} '{name}' in your {kind}.")
        who = None
    log = core.read_changelog(path)
    r = record(kind, name, path, who)
    if core.JSON_MODE:
        emit({**r, "owner": log["owner_login"] or log["created_by"], "created": log["created"],
              "versions": [{"v": e["version"], "date": e["date"], "by": e["author"], "notes": e["notes"]}
                           for e in log["entries"]]})
        return
    section(f"{name}{f'  (from {who})' if who else ''}")
    if r["summary"]:
        say(f"  {r['summary']}")
    if log["created_by"]:
        say(f"  Created by {core.owner_label(log)} on {log['created']}")
    if log["source"]:
        say(f"  Copy of {log['source']}")
    for e in log["entries"]:
        say(f"\n  {CYAN}v{e['version']}{NC}  {e['date']}  {BLUE}{e['author']}{NC}")
        for line in e["notes"].splitlines():
            say(f"    {line}")
    if not log["entries"]:
        warn("No versions yet.")


# ── Suggestions to owners ──────────────────────────────────────────────────
def cmd_suggest(cfg: dict, kind: str, name: str, owner: Optional[str], text: Optional[str], dry_run: bool) -> None:
    """Suggest an improvement to a friend's skill/agent/swarm: a GitHub issue in their repo."""
    repo, cache, where = pick_source(cfg, kind, name, owner)
    slug = core.github_slug(repo) or die(f"{repo} is not on GitHub; suggestions need a GitHub repo.")
    one = KINDS[kind]["one"]
    section(f"Suggesting an improvement to {owner_of(repo)}'s {one} {name}")
    if not text and sys.stdin.isatty():
        text = input(f"  {YELLOW}?{NC} What should be improved? ").strip()
    if not text:
        die(f'Describe the improvement: skylls{"" if kind == "skills" else " " + kind} suggest {name} '
            f'--from {owner_of(repo)} "what to improve"')
    title = f"{name}: {text.splitlines()[0][:70]}"
    body = f"{text}\n\n---\nSuggestion for the `{name}` {one}, sent with skylls."
    if dry_run:
        info(f"Would open an issue in {slug}: {title}")
        return
    label = f"{one}:{name}"
    core.gh("label", "create", label, "-R", slug, "--force", "--color", "1D76DB", "--description",
            f"Suggestions for {name}")
    args = ["issue", "create", "-R", slug, "--title", title, "--body", body, "--label", label]
    res = core.gh(*args, "--assignee", slug.split("/")[0])
    if res.returncode != 0:
        res = core.gh(*args)
    if res.returncode != 0:
        die(f"Could not open the issue: {res.stderr.strip()}")
    ok(f"Suggestion sent to {slug.split('/')[0]}: {res.stdout.strip()}")


def cmd_suggestions(cfg: dict, kind: str, name: Optional[str]) -> None:
    """Open suggestions others made for your agents/swarms."""
    slug = core.shared_repo_slug({"repo": kind_cfg(cfg, kind)["repo"]})
    one = KINDS[kind]["one"]
    res = core.gh("issue", "list", "-R", slug, "--state", "open", "--limit", "200",
                  "--json", "number,title,author,createdAt,labels,url", *(["--label", f"{one}:{name}"] if name else []))
    if res.returncode != 0:
        die(f"Could not list issues: {res.stderr.strip()}")
    issues = [i for i in json.loads(res.stdout or "[]")
              if any(lb["name"].startswith(f"{one}:") for lb in i.get("labels", []))]
    if core.JSON_MODE:
        for i in issues:
            emit({"number": i["number"], "title": i["title"], "by": i["author"]["login"],
                  "date": i["createdAt"][:10], "url": i["url"]})
        return
    section(f"Open suggestions for your {kind}{f' ({name})' if name else ''}")
    for i in issues:
        say(f"  {YELLOW}#{i['number']}{NC} {i['title']}")
        say(f"      by @{i['author']['login']} on {i['createdAt'][:10]}  {BLUE}{i['url']}{NC}")
    if not issues:
        info("None.")


def cmd_decide(cfg: dict, kind: str, number: int, accept: bool, note: Optional[str], dry_run: bool) -> None:
    repo_cfg = {"repo": kind_cfg(cfg, kind)["repo"]}
    slug = core.shared_repo_slug(repo_cfg)
    if not core.is_repo_owner(repo_cfg):
        die(f"Only the owner of {slug} can accept or decline its suggestions.")
    note = note or ("Done, thanks!" if accept else "Thanks, but not planned.")
    if dry_run:
        info(f"Would close #{number} in {slug} as {'done' if accept else 'not planned'}: {note}")
        return
    res = core.gh("issue", "close", str(number), "-R", slug, "--reason", "completed" if accept else "not planned",
                  "--comment", note)
    if res.returncode != 0:
        die(f"Could not close #{number}: {res.stderr.strip()}")
    ok(f"{'Accepted' if accept else 'Declined'} #{number}")


# ── CLI wiring for `skylls agents …` / `skylls swarms …` ───────────────────
def add_parsers(sub) -> None:
    for kind in ("agents", "swarms"):
        one = KINDS[kind]["one"]
        kp = sub.add_parser(kind, help=f"Share and install {kind} (yours: ~/{kind}; friends': sources).")
        ks = kp.add_subparsers(dest="kcmd")
        sp = ks.add_parser("list", help=f"Your {kind} and your sources' {kind}.")
        sp.add_argument("query", nargs="?")
        sp.add_argument("--from", dest="owner")
        sp = ks.add_parser("find", help=f"Search {kind} by keyword.")
        sp.add_argument("keywords", nargs="+")
        sp.add_argument("--from", dest="owner")
        sp.add_argument("-n", "--limit", type=int)
        sp = ks.add_parser("add", help=f"Download a friend's {one}: definition + Obsidian memory.")
        sp.add_argument("name", help="name or name@version")
        sp.add_argument("--from", dest="owner", help="Owner (GitHub user) of the source.")
        sp.add_argument("--as", dest="as_name", help="Install under another folder name.")
        sp.add_argument("-y", "--yes", action="store_true", help="Replace an existing folder without asking.")
        sp.add_argument("--update-memory", action="store_true",
                        help="Also overwrite your copy of its memory with the source's.")
        sp = ks.add_parser("push", help=f"Publish a new version of one of your {kind}.")
        sp.add_argument("name")
        sp.add_argument("-m", "--message")
        group = sp.add_mutually_exclusive_group()
        group.add_argument("--minor", dest="part", action="store_const", const="minor", default="patch")
        group.add_argument("--major", dest="part", action="store_const", const="major")
        sp.add_argument("--about")
        sp.add_argument("--skip-scan", action="store_true")
        sp = ks.add_parser("log", help="Version history.")
        sp.add_argument("name")
        sp.add_argument("--from", dest="owner")
        sp = ks.add_parser("source", help="List, add or remove friends' repos.")
        sp.add_argument("action", nargs="?", choices=["add", "remove"])
        sp.add_argument("repo", nargs="?")
        sp = ks.add_parser("share", help=f"Let GitHub users download your {kind}.")
        sp.add_argument("users", nargs="*", metavar="@github-user")
        sp.add_argument("--read-only", action="store_true")
        sp = ks.add_parser("unshare", help="Revoke access.")
        sp.add_argument("users", nargs="+", metavar="@github-user")
        sp = ks.add_parser("suggest", help=f"Suggest an improvement to a friend's {one}.")
        sp.add_argument("name")
        sp.add_argument("text", nargs="?")
        sp.add_argument("--from", dest="owner")
        ks.add_parser("suggestions", help="Open suggestions for your items.").add_argument("name", nargs="?")
        for verb in ("accept", "decline"):
            sp = ks.add_parser(verb, help=f"Owner: {verb} a suggestion.")
            sp.add_argument("number", type=lambda v: int(v.lstrip("#")))
            sp.add_argument("-m", "--message")


def run(cfg: dict, kind: str, args) -> None:
    c = args.kcmd or "list"
    if c == "list":
        cmd_list(cfg, kind, getattr(args, "query", None), getattr(args, "owner", None))
    elif c == "find":
        cmd_find(cfg, kind, args.keywords, args.owner, args.limit)
    elif c == "add":
        cmd_add(cfg, kind, args.name, args.owner, args.as_name, args.yes, args.dry_run, args.update_memory)
    elif c == "push":
        cmd_push(cfg, kind, args.name, args.message, args.part, args.about, args.skip_scan, args.dry_run)
    elif c == "log":
        cmd_log(cfg, kind, args.name, args.owner)
    elif c == "source":
        cmd_source(cfg, kind, args.action, args.repo, args.dry_run)
    elif c == "share":
        repo_cfg = {"repo": kind_cfg(cfg, kind)["repo"]}
        if args.users:
            core.cmd_share(repo_cfg, args.users, args.read_only, args.dry_run)
            info(f"They connect with: skylls {kind} source add {core.shared_repo_slug(repo_cfg)}")
        else:
            core.cmd_share_list(repo_cfg)
    elif c == "unshare":
        core.cmd_unshare({"repo": kind_cfg(cfg, kind)["repo"]}, args.users, args.dry_run)
    elif c == "suggest":
        cmd_suggest(cfg, kind, args.name, args.owner, args.text, args.dry_run)
    elif c == "suggestions":
        cmd_suggestions(cfg, kind, args.name)
    elif c in ("accept", "decline"):
        cmd_decide(cfg, kind, args.number, c == "accept", args.message, args.dry_run)
