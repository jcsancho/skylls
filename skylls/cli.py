#!/usr/bin/env python3
"""
skylls - Manage agent skills from a shared GitHub repository
--------------------------------------------------------------
The GitHub repo (asked on first run) is the source of truth. A cached clone
lives in ~/.cache/skylls/repo. Skills are copied from it into an agent's
skills folder, either for the current project or globally (-g):

  claude  ./.claude/skills   ~/.claude/skills
  codex   ./.agents/skills   ~/.agents/skills
  gemini  ./.gemini/skills   ~/.gemini/skills

Global installs for several agents keep one real copy (in the first agent's
folder, claude when selected) and symlink the others to it, so every agent
uses the same files.

`skylls push` copies an installed skill back into the repo, commits and
pushes to the default branch. `skylls search` queries skills.sh, and
`skylls add owner/repo/skill` installs straight from any public GitHub repo.
"""

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple

# ── Colors ────────────────────────────────────────────────────────────────
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
BLUE = "\033[0;34m"
CYAN = "\033[0;36m"
RED = "\033[0;31m"
NC = "\033[0m"  # No color


JSON_MODE = False  # --json: data as JSON lines on stdout, messages on stderr


def say(text: str) -> None:
    print(text, file=sys.stderr if JSON_MODE else sys.stdout)


def emit(record: dict) -> None:
    """One compact JSON object per line (cheap for agents to read); empty fields dropped."""
    print(json.dumps({k: v for k, v in record.items() if v not in (None, "", [], False)},
                     ensure_ascii=False, separators=(",", ":")))


def section(msg: str) -> None:
    say(f"\n{CYAN}▸ {msg}{NC}")


def info(msg: str) -> None:
    say(f"  {BLUE}→{NC} {msg}")


def ok(msg: str) -> None:
    say(f"  {GREEN}✓{NC} {msg}")


def warn(msg: str) -> None:
    say(f"  {YELLOW}!{NC} {msg}")


def fail(msg: str) -> None:
    say(f"  {RED}✗{NC} {msg}")


def die(msg: str, code: int = 1) -> None:
    fail(msg)
    sys.exit(code)


# ── Configuration ──────────────────────────────────────────────────────────
CONFIG_PATH = Path.home() / ".config" / "skylls" / "config.json"
CACHE_REPO = Path.home() / ".cache" / "skylls" / "repo"
SKILLS_SH_API = "https://skills.sh/api/search"

AGENT_DIRS = {
    "claude": ".claude/skills",
    "codex": ".agents/skills",
    "gemini": ".gemini/skills",
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n")


def repo_url(repo: str) -> str:
    """Accept 'owner/name', an https/ssh URL, or a local path."""
    if "://" in repo or repo.startswith(("git@", "/", "~", ".")):
        return repo
    return f"https://github.com/{repo}.git"


def github_slug(repo: str) -> Optional[str]:
    """'owner/name' for a GitHub repo given as owner/name or URL; None for anything else."""
    if repo.startswith(("/", "~", ".")):
        return None
    m = re.fullmatch(r"(?:https://github\.com/|(?:ssh://)?git@github\.com[:/])?([\w.-]+)/([\w.-]+?)(?:\.git)?/?",
                     repo.strip())
    return f"{m[1]}/{m[2]}" if m else None


def setup(repo: Optional[str] = None, agents: Optional[str] = None, kind_args: Optional[dict] = None,
          create: bool = False) -> dict:
    """First run: your private GitHub repos for skills, agents and swarms (created if you have none),
    their folders, and default agent CLIs."""
    from skylls import kinds
    cfg = load_config()
    section("skylls setup: your private GitHub repos for skills, agents and swarms")
    repo = kinds.choose_repo("skills", repo, cfg.get("repo", ""), "", create)
    if not repo:
        die("A skills repo is required: give one with --repo owner/name, or add --create to make a private one.")
    kinds.ensure_private(repo)
    if not agents:
        current = ",".join(cfg.get("agents", ["claude"]))
        agents = (input(f"  {YELLOW}?{NC} Default agents (claude,codex,gemini) [{current}]: ").strip()
                  if sys.stdin.isatty() else "") or current
    agent_list = parse_agents(agents)

    if cfg.get("repo") != repo and CACHE_REPO.exists():
        shutil.rmtree(CACHE_REPO)
    cfg.update(repo=repo, agents=agent_list)
    sync_repo(cfg)
    ok(f"skills: {repo}")
    for kind in ("agents", "swarms"):
        args = (kind_args or {}).get(kind, {})
        kinds.setup_kind(cfg, kind, args.get("repo"), args.get("dir"), create)
    save_config(cfg)
    ok(f"Saved config to {CONFIG_PATH}")
    info("Friends share theirs with you, then: skylls source add <owner>/<repo> "
         "(or skylls agents|swarms source add …)")
    return cfg


def get_config() -> dict:
    cfg = load_config()
    return cfg if cfg.get("repo") else setup()


def parse_agents(value: str) -> List[str]:
    agents = list(AGENT_DIRS) if value == "all" else [a.strip() for a in value.split(",") if a.strip()]
    bad = [a for a in agents if a not in AGENT_DIRS]
    if bad:
        die(f"Unknown agent(s): {', '.join(bad)}. Use claude, codex, gemini or all.")
    return [a for a in AGENT_DIRS if a in agents]


def target_dirs(cfg: dict, agent: Optional[str], is_global: bool) -> List[Path]:
    base = Path.home() if is_global else Path.cwd()
    agents = parse_agents(agent) if agent else cfg.get("agents", ["claude"])
    return [base / AGENT_DIRS[a] for a in agents]


# ── Git repo cache ─────────────────────────────────────────────────────────
def git(*args: str, cwd: Path = CACHE_REPO, check: bool = True) -> subprocess.CompletedProcess:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and res.returncode != 0:
        die(f"git {' '.join(args)} failed:\n{res.stderr.strip()}")
    return res


def sync_repo(cfg: dict) -> None:
    """Clone the shared repo into the cache, or fast-forward it."""
    if not (CACHE_REPO / ".git").exists():
        CACHE_REPO.parent.mkdir(parents=True, exist_ok=True)
        info(f"Cloning {cfg['repo']} …")
        git("clone", "--quiet", repo_url(cfg["repo"]), str(CACHE_REPO), cwd=CACHE_REPO.parent)
        from skylls import kinds
        kinds.init_empty_repo(CACHE_REPO, "skills")  # a brand-new repo gets its first commit
    else:
        git("pull", "--quiet", "--rebase", "--autostash")


def publish(cfg: dict, message: str, tag: Optional[str] = None) -> None:
    """Commit what is staged and push it (plus tag) atomically; undo locally if the push fails.

    Refuses (and discards the staged change) if it touches an owner-only skill
    and the current user is not its owner: skylls never makes such a commit."""
    blocked = locked_skills_in_commit(cfg)
    if blocked:
        git("reset", "--quiet", "--hard", "HEAD", check=False)
        die(f"Not committed: only the owner can change {', '.join(blocked)}. "
            "Suggest your change with: skylls suggest <skill> \"...\"")
    git("commit", "--quiet", "-m", message)
    if tag:
        git("tag", tag)
    res = git("push", "--quiet", "--atomic", "origin", "HEAD", *([f"refs/tags/{tag}"] if tag else []), check=False)
    if res.returncode != 0:
        if tag:
            git("tag", "-d", tag, check=False)
        git("reset", "--quiet", "--hard", "@{u}", check=False)
        die(f"Push failed, nothing was published (someone may have pushed at the same time; try again):\n"
            f"{res.stderr.strip()}")


def locked_skills_in_commit(cfg: dict) -> List[str]:
    """Owner-only skills (as committed in HEAD) that the staged change touches, owned by someone else."""
    changed = git("diff", "--cached", "--name-only", "--no-renames").stdout.splitlines()
    head = git("ls-tree", "-r", "--name-only", "HEAD", check=False).stdout.splitlines()
    skill_dirs = {str(Path(f).parent) for f in head if Path(f).name == "SKILL.md" and str(Path(f).parent) != "."}
    touched = {d for d in skill_dirs for f in changed if f.startswith(d + "/")}
    blocked = []
    for d in sorted(touched):
        text = git("show", f"HEAD:{d}/{CHANGELOG}", check=False).stdout
        log = parse_changelog(text)
        if log["updates"] == "owner" and not is_owner(cfg, log):
            blocked.append(f"{Path(d).name} (owner {owner_label(log)})")
    return blocked


def require_owner(cfg: dict, skill_dirs: List[Path], action: str) -> None:
    """Stop early, before any change, if one of these skills is someone else's owner-only skill."""
    locked = [f"{p.name} (owner {owner_label(lg)})" for p in skill_dirs
              if (lg := read_changelog(p))["updates"] == "owner" and not is_owner(cfg, lg)]
    if locked:
        die(f"Only their owners can {action} these owner-only skills: {', '.join(locked)}")


def skills_root(repo: Path) -> Path:
    """Skills live in <repo>/skills/ if that folder exists, else at the repo root."""
    return repo / "skills" if (repo / "skills").is_dir() else repo


def repo_index() -> dict:
    """{skill name: [skill dirs]} for skills at the top level or one folder down."""
    root = skills_root(CACHE_REPO)
    found: dict = {}
    for p in sorted(root.iterdir()):
        if not p.is_dir() or p.name.startswith("."):
            continue
        if (p / "SKILL.md").is_file():
            found.setdefault(p.name, []).append(p)
            continue
        for q in sorted(p.iterdir()):
            if q.is_dir() and (q / "SKILL.md").is_file():
                found.setdefault(q.name, []).append(q)
    return found


def repo_folders() -> List[str]:
    root = skills_root(CACHE_REPO)
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and not p.name.startswith(".") and not (p / "SKILL.md").is_file())


def folder_of(skill_dir: Path) -> str:
    """The folder a repo skill lives in ('' = top level)."""
    return "" if skill_dir.parent == skills_root(CACHE_REPO) else skill_dir.parent.name


def folder_label(folder: str) -> str:
    return f"{folder}/" if folder else "the top level"


def valid_folder(folder: str) -> str:
    """Normalise a folder argument; '.', '/' or '' mean the top level."""
    folder = folder.strip().strip("/")
    if folder in ("", "."):
        return ""
    if not re.fullmatch(r"[A-Za-z0-9][\w.-]*", folder):
        die(f"'{folder}' is not a valid folder name (letters, digits, - _ . ; one level only).")
    return folder


def find_repo_skill(cfg: dict, spec: str) -> Path:
    """'name' or 'folder/name' → that skill's folder in the repo cache."""
    folder, _, name = spec.strip("/").rpartition("/")
    paths = [p for p in repo_index().get(name, []) if not folder or folder_of(p) == folder]
    if not paths:
        die(f"Skill '{spec}' not found in {cfg['repo']}. Run 'skylls list'.")
    if len(paths) > 1:
        where = ", ".join(folder_label(folder_of(p)) for p in paths)
        die(f"'{name}' exists in several places ({where}); use folder/{name}.")
    return paths[0]


def get_skill_description(skill_dir: Path) -> Optional[str]:
    """Extract the description from a skill's SKILL.md frontmatter."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    lines = skill_md.read_text(errors="ignore").splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            break
        if line.startswith("description:"):
            desc = line[len("description:"):].strip().strip("\"'")
            if desc in (">", "|", ">-", "|-") and i + 1 < len(lines):
                desc = lines[i + 1].strip()
            return desc[:77] + "..." if len(desc) > 80 else desc
    return None


def print_skill(name: str, skill_dir: Path, latest: Optional[str] = None, indent: int = 2,
                folder: Optional[str] = None) -> None:
    """Name, version (and folder), plain summary, then owner · updates · created · updated."""
    log = read_changelog(skill_dir)
    version = log["entries"][0]["version"] if log["entries"] else None
    label = f" {BLUE}v{version}{NC}" if version else ""
    if latest and (not version or version_key(latest) > version_key(version)):
        label += f" {YELLOW}(v{latest} available){NC}"
    if folder is not None:
        label += f"  {folder_label(folder) if folder else '(top level)'}"
    pad = " " * indent
    print(f"{pad}{GREEN}•{NC} {CYAN}{name}{NC}{label}")
    desc = log["about"] or get_skill_description(skill_dir)
    if desc:
        print(f"{pad}  {desc}")
    if log["created_by"]:
        updates = f"{YELLOW}owner only{NC}" if log["updates"] == "owner" else "anyone"
        dates = f"created {log['created']}" + (f" · updated {log['entries'][0]['date']}" if log["entries"] else "")
        print(f"{pad}  {BLUE}owner{NC} {owner_label(log)} · {BLUE}updates{NC} {updates} · {dates}")


# ── Versions & changelog ───────────────────────────────────────────────────
CHANGELOG = "CHANGELOG.md"  # per skill, written by push: plain summary + one entry per version
CREATED_RE = re.compile(r"^Created by (.+?)(?: \(@([A-Za-z0-9-]+)\))? on (\d{4}-\d{2}-\d{2})\.$")
UPDATES_RE = re.compile(r"^Updates: (anyone|owner only)")
SOURCE_RE = re.compile(r"^Source: (.+?)\.?$")   # downloaded copy: "<repo> <name>@<version>"
ORIGIN_RE = re.compile(r"^Origin: (.+)$")        # owner's folder (agents/swarms), for path rewriting
HOME_RE = re.compile(r"^Home: (.+)$")            # owner's home folder
ENTRY_RE = re.compile(r"^## (\d+\.\d+\.\d+) — (\S+)(?: — (.*))?$")


def read_changelog(skill_dir: Path) -> dict:
    """{about, created_by, owner_login, created, updates, entries (newest first)} from a skill's CHANGELOG.md."""
    path = skill_dir / CHANGELOG
    return parse_changelog(path.read_text(errors="ignore") if path.is_file() else "")


def parse_changelog(text: str) -> dict:
    log = {"about": "", "created_by": "", "owner_login": "", "created": "", "updates": "anyone", "entries": [],
           "source": "", "origin": "", "home": ""}
    entries = log["entries"]
    for line in text.splitlines():
        m = ENTRY_RE.match(line)
        if m:
            entries.append({"version": m[1], "date": m[2], "author": m[3] or "", "notes": []})
        elif entries:
            entries[-1]["notes"].append(line)
        elif line.startswith("> ") and not log["about"]:
            log["about"] = line[2:].strip()
        elif (c := CREATED_RE.match(line)):
            log["created_by"], log["owner_login"], log["created"] = c[1], c[2] or "", c[3]
        elif (u := UPDATES_RE.match(line)):
            log["updates"] = "owner" if u[1] == "owner only" else "anyone"
        else:
            for key, rx in (("source", SOURCE_RE), ("origin", ORIGIN_RE), ("home", HOME_RE)):
                if (m2 := rx.match(line)):
                    log[key] = m2[1].strip()
    for e in entries:
        e["notes"] = "\n".join(e["notes"]).strip()
    return log


def write_changelog(skill_dir: Path, name: str, log: dict) -> None:
    out = [f"# {name}", ""]
    if log["about"]:
        out += [f"> {log['about']}", ""]
    if log["created_by"]:
        out += [f"Created by {owner_label(log)} on {log['created']}.", ""]
        out += ["Updates: owner only — others suggest changes with 'skylls suggest'." if log["updates"] == "owner"
                else "Updates: anyone.", ""]
    for key in ("source", "origin", "home"):
        if log.get(key):
            out += [f"{key.capitalize()}: {log[key]}" + ("." if key == "source" else ""), ""]
    for e in log["entries"]:
        out += [f"## {e['version']} — {e['date']}" + (f" — {e['author']}" if e["author"] else ""), "", e["notes"], ""]
    (skill_dir / CHANGELOG).write_text("\n".join(out))


def skill_version(skill_dir: Path) -> Optional[str]:
    entries = read_changelog(skill_dir)["entries"]
    return entries[0]["version"] if entries else None


def version_key(version: str) -> Tuple[int, ...]:
    return tuple(int(n) for n in version.split("."))


def bump(version: Optional[str], part: str) -> str:
    if not version:
        return "1.0.0"
    major, minor, patch = version_key(version)
    return {"major": f"{major + 1}.0.0", "minor": f"{major}.{minor + 1}.0"}.get(part, f"{major}.{minor}.{patch + 1}")


def ai_summary(skill_dir: Path, main: str = "SKILL.md", what: str = "AI agent skill") -> Optional[str]:
    """One plain sentence on what the skill/agent/swarm does, written by Claude (claude -p)."""
    if not shutil.which("claude"):
        warn("claude CLI not found; no plain-language summary (use --about \"...\" to write one).")
        return None
    info("Asking Claude for a plain-language summary …")
    prompt = (f"Below is an {what} ({main}). In ONE short, simple sentence (max 20 words, no jargon), "
              "say what it does for the person using it. Reply with only that sentence.")
    with tempfile.TemporaryDirectory() as tmp:  # neutral cwd: no project CLAUDE.md in the context
        try:
            res = subprocess.run(["claude", "-p", "--model", "haiku", prompt], cwd=tmp, capture_output=True,
                                 text=True, timeout=180,
                                 input=(skill_dir / main).read_text(errors="ignore")[:20000])
        except subprocess.TimeoutExpired:
            res = None
    summary = " ".join(res.stdout.split())[:300] if res and res.returncode == 0 else ""
    if not summary:
        warn("Claude could not write a summary; use --about \"...\" to write one.")
    return summary or None


def extract_version(name: str, version: str, tmp: Path) -> Path:
    """Unpack the tagged version '<name>@<version>' of a repo skill into tmp."""
    tag = f"{name}@{version.lstrip('v')}"
    if not git("tag", "-l", tag).stdout.strip():
        known = sorted((t.split("@", 1)[1] for t in git("tag", "-l", f"{name}@*").stdout.split()), key=version_key)
        die(f"No version {version} of '{name}'. Available: {', '.join(known) or 'none'}")
    files = git("ls-tree", "-r", "--name-only", tag).stdout.splitlines()
    rel = next((str(Path(f).parent) for f in files
                if Path(f).name == "SKILL.md" and Path(f).parent.name == name), None)
    if not rel:
        die(f"Tag {tag} has no '{name}' skill folder.")
    res = subprocess.run(["git", "archive", "--format=tar", tag, rel], cwd=CACHE_REPO, capture_output=True)
    if res.returncode != 0:
        die(f"git archive {tag} failed: {res.stderr.decode(errors='ignore').strip()}")
    with tarfile.open(fileobj=io.BytesIO(res.stdout)) as tar:
        tar.extractall(tmp, filter="data")
    return tmp / rel


# ── Owners & permissions ───────────────────────────────────────────────────
# The owner of a skill is whoever first uploaded it. With "owner only" updates,
# skylls refuses pushes from anyone else; they send suggestions (GitHub issues)
# that the owner accepts or declines. GitHub itself can't lock a folder, so this
# is enforced by skylls, not by repo permissions.
_identity: dict = {}


def my_name() -> str:
    return git("config", "user.name", check=False).stdout.strip()


def my_login() -> str:
    """GitHub login of the gh user ('' without gh)."""
    if "login" not in _identity:
        res = gh_api("user", "--jq", ".login") if shutil.which("gh") else None
        _identity["login"] = res.stdout.strip() if res and res.returncode == 0 else ""
    return _identity["login"]


def owner_label(log: dict) -> str:
    return log["created_by"] + (f" (@{log['owner_login']})" if log["owner_login"] else "")


def is_owner(cfg: dict, log: dict) -> bool:
    """Is the current user the skill's owner? GitHub login when known, else git user name."""
    if log["owner_login"] and github_slug(cfg["repo"]):
        return my_login().lower() == log["owner_login"].lower()
    return bool(log["created_by"]) and my_name() == log["created_by"]


def is_repo_owner(cfg: dict) -> bool:
    slug = github_slug(cfg["repo"])
    return bool(slug) and my_login().lower() == slug.split("/")[0].lower()


def commit_login(cfg: dict, sha: str) -> str:
    """GitHub login of a commit's author ('' if unknown)."""
    slug = github_slug(cfg["repo"])
    if not slug or not shutil.which("gh"):
        return ""
    res = gh_api(f"repos/{slug}/commits/{sha}", "--jq", ".author.login // empty")
    return res.stdout.strip() if res.returncode == 0 else ""


# ── Install helpers ────────────────────────────────────────────────────────
def copy_skill(source: Path, dest_root: Path, name: str, dry_run: bool, force: bool) -> None:
    dest = dest_root / name
    if dest.exists() and not force:
        answer = input(f"  {YELLOW}?{NC} '{name}' already exists at {dest}. Overwrite? (y/N): ").strip().lower()
        if answer != "y":
            info("Skipped.")
            return
    if dry_run:
        info(f"Would copy: {source} → {dest}")
        return
    remove_path(dest)
    dest_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns(".git"))
    ok(f"Installed '{name}' → {dest}")


def remove_path(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def link_skill(primary: Path, dest_root: Path, name: str, dry_run: bool) -> None:
    """Point dest_root/name at the primary global copy."""
    dest = dest_root / name
    if dry_run:
        info(f"Would link: {dest} → {primary}")
        return
    remove_path(dest)
    dest_root.mkdir(parents=True, exist_ok=True)
    dest.symlink_to(primary)
    ok(f"Linked '{name}' → {dest} → {primary}")


def gitleaks_config() -> Optional[Path]:
    """The git-scan-secrets skill's gitleaks rules (secrets + personal data)."""
    for base in (Path.home() / ".claude" / "skills", Path.home() / "SKILLS"):
        cfg = base / "git-scan-secrets" / "gitleaks.toml"
        if cfg.is_file():
            return cfg
    return None


def scan_secrets(skill_dir: Path) -> None:
    """Abort unless gitleaks finds no API keys, passwords or private info in skill_dir."""
    if not shutil.which("gitleaks"):
        die("gitleaks is required to scan skills before pushing (brew install gitleaks), "
            "or pass --skip-scan.")
    info("Scanning for API keys, secrets and private info (gitleaks) …")
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        cmd = ["gitleaks", "dir", str(skill_dir), "--redact", "--no-banner", "--exit-code", "0",
               "--log-level", "error", "--report-format", "json", "--report-path", str(report)]
        cfg = gitleaks_config()
        if cfg:
            cmd += ["--config", str(cfg)]
        else:
            warn("git-scan-secrets config not found; using gitleaks default rules (no personal-data checks).")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not report.is_file():
            die(f"gitleaks failed: {(result.stderr or result.stdout).strip()}")
        findings = json.loads(report.read_text() or "[]")
    if not findings:
        ok("No secrets or private info found.")
        return
    fail(f"Found {len(findings)} possible secret(s) or private info:")
    for f in findings:
        path = Path(f.get("File", "?"))
        rel = path.relative_to(skill_dir) if path.is_relative_to(skill_dir) else path
        print(f"    {RED}•{NC} {rel}:{f.get('StartLine', '?')}  {YELLOW}{f.get('RuleID', '?')}{NC}  {f.get('Match', '')}")
    die("Nothing was pushed. Remove them (use placeholders or env vars), "
        "or pass --skip-scan if they are false positives.")


def fetch_remote_skill(spec: str, tmp: Path) -> Path:
    """Fetch 'owner/repo/skill' (skills.sh id) from GitHub into tmp."""
    owner, repo, skill = spec.split("/", 2)
    info(f"Fetching {owner}/{repo} from GitHub …")
    git("clone", "--quiet", "--depth", "1", f"https://github.com/{owner}/{repo}.git", str(tmp / "src"), cwd=tmp)
    for skill_md in (tmp / "src").rglob("SKILL.md"):
        if skill_md.parent.name == skill:
            return skill_md.parent
    die(f"No skill folder named '{skill}' with a SKILL.md found in {owner}/{repo}.")


# ── Commands ───────────────────────────────────────────────────────────────
AGENT_SKILL = """---
name: skylls
description: Find, install and share agent skills from the team's shared skylls repo. Use when a task needs a capability you don't have, the user asks which skills exist, or wants to save or share a skill with other agents or people.
---

# skylls

Shared skills live in a GitHub repo managed by the `skylls` CLI. Keep output small: always use `--json` (one compact JSON object per line) and `--limit`.

## Find
    skylls find <keywords> --json --limit 5     # best matches first
    skylls find --folder <folder> --json        # everything in a folder
Fields: name, folder, version, summary, owner, updated, installed (project|global), updates ("owner" = only the owner may push; absent = anyone). Missing fields are empty.

## Install
    skylls add <name> -g -a all                 # all agents, global (one copy + symlinks)
    skylls add <name>                           # this project only
Then read the installed SKILL.md only if you are going to use it.
Results with "from" are in a friend's repo: install with `skylls add <name> --from <from> -g -a all`.

## Agents and swarms (same pattern)
    skylls agents find <keywords> --json --limit 5    # yours + friends' (also: skylls swarms …)
    skylls agents add <name> --from <owner>           # into ~/agents/<name>, with its Obsidian memory

## Details / what's installed
    skylls log <name> --json                    # owner, permission, version history
    skylls installed --json                     # with "newer" when an update exists

## Share (only when the user asks)
    skylls push <name> -m "what changed" [--folder F] [--updates anyone|owner]
- Push scans for secrets and refuses if it finds any; never put keys or personal data in a skill.
- If the skill is owner-only you'll be refused; suggest instead:
      skylls suggest <name> "what to improve"

Don't read the repo cache directly; don't edit CHANGELOG.md (skylls writes it).
"""


def cmd_agent_skill(cfg: dict, agent: Optional[str], is_global: bool, dry_run: bool) -> None:
    """Install the 'skylls' skill, which teaches agents to find, install and share skills cheaply."""
    section("Installing the skylls skill for your agents")
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "skylls"
        source.mkdir()
        (source / "SKILL.md").write_text(AGENT_SKILL)
        dests = target_dirs(cfg, agent, is_global)
        copy_skill(source, dests[0], "skylls", dry_run, force=True)
        for dest_root in dests[1:]:
            if is_global:
                link_skill(dests[0] / "skylls", dest_root, "skylls", dry_run)
            else:
                copy_skill(source, dest_root, "skylls", dry_run, force=True)


def cmd_list(cfg: dict, query: Optional[str]) -> None:
    sync_repo(cfg)
    if JSON_MODE:
        q = (query or "").lower()
        for name, paths in sorted(repo_index().items()):
            for path in paths:
                record = skill_record(cfg, name, path)
                if not q or q in " ".join(str(v) for v in record.values()).lower():
                    emit(record)
        return
    section(f"Skills in {cfg['repo']}")
    q = (query or "").lower()
    groups: dict = {} if q else {f: [] for f in repo_folders()}
    for name, paths in repo_index().items():
        for path in paths:
            folder = folder_of(path)
            text = f"{name} {folder} {read_changelog(path)['about']} {get_skill_description(path) or ''}"
            if not q or q in text.lower():
                groups.setdefault(folder, []).append((name, path))
    total = 0
    for folder in sorted(groups, key=lambda f: (f != "", f.lower())):
        items = sorted(groups[folder])
        total += len(items)
        if folder or len(groups) > 1:
            count = f"{len(items)} skill{'s' if len(items) != 1 else ''}"
            print(f"\n  {BLUE}{folder + '/' if folder else '(top level)'}{NC}  {count}")
        for name, path in items:
            print_skill(name, path, indent=4 if (folder or len(groups) > 1) else 2)
    print(f"\n{BLUE}Total: {total} skills{NC}")


def installed_scope(cfg: dict, name: str) -> Optional[str]:
    """'project' / 'global' if the skill is installed for the default agents, else None."""
    for scope, is_global in (("project", False), ("global", True)):
        if any((d / name / "SKILL.md").is_file() for d in target_dirs(cfg, None, is_global)):
            return scope
    return None


def skill_record(cfg: dict, name: str, path: Path) -> dict:
    """The fields an agent needs to pick and install a repo skill."""
    log = read_changelog(path)
    return {"name": name, "folder": folder_of(path),
            "version": log["entries"][0]["version"] if log["entries"] else None,
            "summary": log["about"] or get_skill_description(path),
            "owner": log["owner_login"] or log["created_by"], "updates": "owner" if log["updates"] == "owner" else None,
            "updated": log["entries"][0]["date"] if log["entries"] else None,
            "installed": installed_scope(cfg, name)}


def cmd_find(cfg: dict, keywords: List[str], folder: Optional[str], limit: Optional[int] = None) -> None:
    """Search the shared repo by keyword and/or folder; best matches first, then related skills."""
    sync_repo(cfg)
    terms = [k.lower() for k in keywords]
    want = valid_folder(folder).lower() if folder is not None else None
    found = []
    for name, paths in repo_index().items():
        for path in paths:
            where = folder_of(path)
            if want is not None and where.lower() != want:
                continue
            log = read_changelog(path)
            fields = [(name, 5), (where, 3), (log["about"], 3), (get_skill_description(path) or "", 2),
                      ((path / "SKILL.md").read_text(errors="ignore"), 1)]
            if not all(any(t in text.lower() for text, _ in fields) for t in terms):
                continue
            score = sum(weight for t in terms for text, weight in fields if t in text.lower())
            found.append((-score, name, path))
    found.sort()
    total = len(found)
    if JSON_MODE:
        limit = 10 if limit is None else limit
    found = found[:limit] if limit else found
    if JSON_MODE:
        for _, name, path in found:
            emit(skill_record(cfg, name, path))
        if total > len(found):
            warn(f"{total - len(found)} more; raise --limit")
        return
    what = " ".join(keywords) or "all skills"
    section(f"Skills matching '{what}'{f' in {folder_label(want)}' if want is not None else ''}")
    if not found:
        warn("No matches in the shared repo. Try 'skylls search <words>' for public skills on skills.sh.")
        return
    for _, name, path in found:
        print_skill(name, path, folder=folder_of(path))
    matched = {path for _, _, path in found}
    folders = {folder_of(path) for path in matched if folder_of(path)}
    related = sorted(p.name for paths in repo_index().values() for p in paths
                     if p not in matched and folder_of(p) in folders)
    if terms and related:
        info(f"Related (same folder): {', '.join(related)}")
    shown = f"{len(found)} of {total}" if total > len(found) else str(total)
    print(f"\n{BLUE}{shown} match{'es' if total != 1 else ''}{NC}")


def cmd_search(query: str, limit: int) -> None:
    section(f"skills.sh results for '{query}'")
    url = f"{SKILLS_SH_API}?{urllib.parse.urlencode({'q': query, 'limit': limit})}"
    with urllib.request.urlopen(url, timeout=20) as resp:
        results = json.load(resp).get("skills", [])
    if not results:
        warn("No results.")
        return
    for s in results:
        print(f"  {GREEN}•{NC} {CYAN}{s['id']}{NC}  {s.get('installs', 0):,} installs")
    info("Install with: skylls add <owner/repo/skill> [-g] [-a agent]")


def cmd_add(cfg: dict, name: str, agent: Optional[str], is_global: bool, dry_run: bool, force: bool,
            owner: Optional[str] = None) -> None:
    section(f"Installing skill: {name}")
    with tempfile.TemporaryDirectory() as tmp:
        if owner:
            from skylls import kinds
            source, name = kinds.fetch_source_skill(cfg, name, owner)
        elif name.count("/") == 2:
            source = fetch_remote_skill(name, Path(tmp))
            name = source.name
        else:
            sync_repo(cfg)
            spec, _, version = name.partition("@")
            name = spec.rpartition("/")[2]
            source = find_repo_skill(cfg, spec) if not version else None
            if version:
                source = extract_version(name, version, Path(tmp))
        dests = target_dirs(cfg, agent, is_global)
        copy_skill(source, dests[0], name, dry_run, force)
        for dest_root in dests[1:]:
            if is_global:
                link_skill(dests[0] / name, dest_root, name, dry_run)
            else:
                copy_skill(source, dest_root, name, dry_run, force)


def cmd_remove(cfg: dict, name: str, agent: Optional[str], is_global: bool, dry_run: bool) -> None:
    section(f"Removing skill: {name}")
    found = False
    for dest_root in target_dirs(cfg, agent, is_global):
        path = dest_root / name
        if not (path.is_dir() or path.is_symlink()):
            continue
        found = True
        if dry_run:
            info(f"Would remove: {path}")
            continue
        remove_path(path)
        ok(f"Removed {path}")
        for other in target_dirs(cfg, "all", is_global):
            link = other / name
            if link.is_symlink() and not link.exists():
                warn(f"{link} now points at a removed copy — run 'skylls remove {name} -g -a all' or re-add it")
    if not found:
        die(f"'{name}' is not installed in the selected {'global' if is_global else 'project'} folders.")


def cmd_installed(cfg: dict, agent: Optional[str], is_global: Optional[bool]) -> None:
    index = repo_index() if (CACHE_REPO / ".git").is_dir() else {}
    scopes = [is_global] if is_global is not None else [False, True]
    for scope in scopes:
        for dest_root in target_dirs(cfg, agent, scope):
            if not dest_root.is_dir():
                continue
            names = sorted(p.name for p in dest_root.iterdir() if (p / "SKILL.md").is_file())
            if JSON_MODE:
                agent_name = next((a for a, d in AGENT_DIRS.items() if dest_root.as_posix().endswith(d)), None)
                for n in names:
                    path, cached = dest_root / n, index.get(n, [None])[0]
                    mine, latest = skill_version(path), skill_version(cached) if cached else None
                    emit({"name": n, "scope": "global" if scope else "project", "agent": agent_name,
                          "version": mine, "link": path.is_symlink(),
                          "newer": latest if latest and (not mine or version_key(latest) > version_key(mine)) else None})
                continue
            if not names:
                continue
            section(f"{'Global' if scope else 'Project'}: {dest_root}")
            for n in names:
                path = dest_root / n
                if path.is_symlink():
                    print(f"  {GREEN}•{NC} {CYAN}{n}{NC} → {os.readlink(path)}")
                else:
                    cached = index.get(n, [None])[0]
                    print_skill(n, path, skill_version(cached) if cached else None)
            print(f"\n{BLUE}Total: {len(names)}{NC}")


def find_installed(cfg: dict, name: str, agent: Optional[str], is_global: Optional[bool]) -> Path:
    """Locate a skill to upload: an explicit path, or an installed copy (project first)."""
    if Path(name).expanduser().is_dir():
        return Path(name).expanduser().resolve()
    scopes = [is_global] if is_global is not None else [False, True]
    for scope in scopes:
        for dest_root in target_dirs(cfg, agent or ",".join(AGENT_DIRS), scope):
            if (dest_root / name / "SKILL.md").is_file():
                return dest_root / name
    die(f"Skill '{name}' not found in any project or global skills folder.")


def cmd_push(cfg: dict, name: str, agent: Optional[str], is_global: Optional[bool], message: Optional[str],
             dry_run: bool, skip_scan: bool = False, part: str = "patch", about: Optional[str] = None,
             force: bool = False, folder: Optional[str] = None, updates: Optional[str] = None) -> None:
    source = find_installed(cfg, name, agent, is_global)
    name = source.name
    section(f"Uploading skill: {name}")
    if not (source / "SKILL.md").is_file():
        die(f"{source} has no SKILL.md.")
    if skip_scan:
        warn("Skipping the secret scan (--skip-scan).")
    else:
        scan_secrets(source.resolve())
    sync_repo(cfg)
    existing = repo_index().get(name, [])
    if len(existing) > 1:
        die(f"'{name}' exists in several folders of {cfg['repo']}; tidy up with 'skylls move'.")
    target = valid_folder(folder) if folder is not None else None
    if existing:
        dest = existing[0]
        if target is not None and folder_of(dest) != target:
            die(f"'{name}' is in {folder_label(folder_of(dest))}; move it with 'skylls move {name} {target or '.'}'.")
    else:
        dest = skills_root(CACHE_REPO) / (target or "") / name
    log = read_changelog(dest)
    old_about, old_entries = log["about"], log["entries"]
    if log["created_by"] and (log["updates"] == "owner" or updates) and not is_owner(cfg, log):
        if log["updates"] == "owner":
            die(f"'{name}' only takes updates from its owner, {owner_label(log)}. Suggest your change instead:\n"
                f"    skylls suggest {name} \"what to improve\"")
        die(f"Only the owner, {owner_label(log)}, can change who may update '{name}'.")
    repo_version = old_entries[0]["version"] if old_entries else None
    base = skill_version(source)
    if repo_version and base and version_key(base) < version_key(repo_version) and not force:
        latest = old_entries[0]
        warn(f"{cfg['repo']} has {name} v{repo_version} ({latest['date']}, {latest['author'] or 'unknown'}); "
             f"your copy is based on v{base}.")
        if not dry_run and input(f"  {YELLOW}?{NC} Replace it with your copy? (y/N): ").strip().lower() != "y":
            die(f"Nothing was pushed. Get the latest with 'skylls add {name} -y', redo your changes, then push.")
    version = bump(repo_version, part)
    while git("tag", "-l", f"{name}@{version}").stdout.strip():
        version = bump(version, "patch")
    if dry_run:
        info(f"Would push {name} v{repo_version or '-'} → v{version} to {folder_label(folder_of(dest))} "
             f"in {cfg['repo']} (tag {name}@{version})")
        return
    old_log = (dest / CHANGELOG).read_text() if (dest / CHANGELOG).is_file() else None
    rel = dest.relative_to(CACHE_REPO).as_posix()
    first = git("log", "--reverse", "--format=%H%x09%an%x09%as", "--", rel, check=False).stdout.splitlines()
    old_skill_md = (dest / "SKILL.md").read_text(errors="ignore") if dest.exists() else None
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", ".DS_Store", CHANGELOG))
    if old_log is not None:
        (dest / CHANGELOG).write_text(old_log)  # the repo's log is the source of truth
    git("add", "-A", str(dest))
    permission_change = bool(updates) and updates != log["updates"]
    if not about and not permission_change and not git("status", "--porcelain", "--", str(dest)).stdout.strip():
        ok(f"'{name}' v{repo_version} is already up to date in {cfg['repo']}.")
        return
    if not message and sys.stdin.isatty():
        message = input(f"  {YELLOW}?{NC} What changed in v{version}? ").strip()
    notes = message or ("First version" if not repo_version else "Updated")
    if not about:
        unchanged = old_about and old_skill_md == (dest / "SKILL.md").read_text(errors="ignore")
        about = old_about if unchanged else (ai_summary(dest) or old_about)
    author = git("config", "user.name", check=False).stdout.strip()
    today = date.today().isoformat()
    if not log["created_by"]:  # first version: the owner is whoever first committed it, else the pusher
        sha, log["created_by"], log["created"] = first[0].split("\t") if first else ("", author or "unknown", today)
        mine = log["created_by"] == author
        log["owner_login"] = my_login() if mine and github_slug(cfg["repo"]) else commit_login(cfg, sha) if sha else ""
        if not updates and mine and sys.stdin.isatty():
            answer = input(f"  {YELLOW}?{NC} Who can push updates? [a]nyone / [o]nly you, others suggest [a]: ")
            updates = "owner" if answer.strip().lower().startswith("o") else "anyone"
    if updates:
        log["updates"] = updates
    log["about"] = about
    log["entries"] = [{"version": version, "date": today, "author": author, "notes": notes}] + old_entries
    write_changelog(dest, name, log)
    git("add", "-A", str(dest))
    publish(cfg, f"skills: {name} {version} — {notes.splitlines()[0]}", tag=f"{name}@{version}")
    shutil.copy2(dest / CHANGELOG, source.resolve() / CHANGELOG)  # local copy now knows its version
    ok(f"Pushed {name} v{version} to {folder_label(folder_of(dest))} in {cfg['repo']}")
    if about:
        info(about)


def cmd_log(cfg: dict, name: str) -> None:
    sync_repo(cfg)
    skill_dir = find_repo_skill(cfg, name)
    name = skill_dir.name
    log = read_changelog(skill_dir)
    entries = log["entries"]
    if JSON_MODE:
        emit({**skill_record(cfg, name, skill_dir), "created": log["created"],
              "versions": [{"v": e["version"], "date": e["date"], "by": e["author"], "notes": e["notes"]}
                           for e in entries]})
        return
    section(f"{name}  ({folder_label(folder_of(skill_dir))})")
    desc = log["about"] or get_skill_description(skill_dir)
    if desc:
        print(f"  {desc}")
    if log["created_by"]:
        print(f"  Created by {owner_label(log)} on {log['created']}")
        print(f"  Updates: {'owner only (others: skylls suggest ' + name + ' ...)' if log['updates'] == 'owner' else 'anyone'}")
    if not entries:
        warn("No versions yet; the next 'skylls push' creates v1.0.0.")
        return
    for e in entries:
        print(f"\n  {CYAN}v{e['version']}{NC}  {e['date']}  {BLUE}{e['author']}{NC}")
        for line in e["notes"].splitlines():
            print(f"    {line}")
    print()
    info(f"Install an older version with: skylls add {name}@<version>")


def cmd_pull(cfg: dict, update: bool, agent: Optional[str], is_global: Optional[bool], dry_run: bool) -> None:
    section(f"Syncing {cfg['repo']}")
    sync_repo(cfg)
    index = repo_index()
    ok(f"Repo cache up to date ({sum(len(p) for p in index.values())} skills)")
    if not update:
        return
    scopes = [is_global] if is_global is not None else [False, True]
    for scope in scopes:
        for dest_root in target_dirs(cfg, agent, scope):
            if not dest_root.is_dir():
                continue
            for p in sorted(dest_root.iterdir()):
                if len(index.get(p.name, [])) == 1 and not p.is_symlink():
                    copy_skill(index[p.name][0], dest_root, p.name, dry_run, force=True)


def cmd_move(cfg: dict, spec: str, folder: str, dry_run: bool) -> None:
    sync_repo(cfg)
    src = find_repo_skill(cfg, spec)
    name, folder = src.name, valid_folder(folder)
    section(f"Moving {name} to {folder_label(folder)}")
    if folder in repo_index():
        die(f"'{folder}' is a skill name; pick another folder name.")
    if folder_of(src) == folder:
        ok(f"'{name}' is already in {folder_label(folder)}.")
        return
    require_owner(cfg, [src], "move")
    dest = skills_root(CACHE_REPO) / folder / name
    if dry_run:
        info(f"Would move {src.relative_to(CACHE_REPO)} → {dest.relative_to(CACHE_REPO)} in {cfg['repo']}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    git("mv", str(src), str(dest))
    publish(cfg, f"skills: move {name} to {folder_label(folder)}")
    ok(f"Moved '{name}' from {folder_label(folder_of(src))} to {folder_label(folder)}")


def cmd_folder(cfg: dict, action: Optional[str], names: List[str], keep_skills: bool, delete_skills: bool,
               force: bool, dry_run: bool) -> None:
    sync_repo(cfg)
    root = skills_root(CACHE_REPO)
    index = repo_index()
    if not action:
        section(f"Folders in {cfg['repo']}")
        for f in repo_folders():
            count = sum(1 for paths in index.values() for p in paths if folder_of(p) == f)
            print(f"  {GREEN}•{NC} {CYAN}{f}/{NC}  {count} skill{'s' if count != 1 else ''}")
        return
    wanted = {"create": 1, "remove": 1, "rename": 2}[action]
    if len(names) != wanted:
        die(f"Usage: skylls folder {action} {'<old> <new>' if wanted == 2 else '<folder>'}")
    folder = valid_folder(names[0])
    if not folder:
        die("The top level is not a folder.")
    path = root / folder
    if action == "create":
        if path.exists():
            die(f"'{folder}' already exists in {cfg['repo']}.")
        section(f"Creating folder {folder}/")
        if dry_run:
            info(f"Would create {path.relative_to(CACHE_REPO)}/ in {cfg['repo']}")
            return
        path.mkdir(parents=True)
        (path / "README.md").write_text(f"# {folder}\n\nA folder of agent skills, managed with skylls.\n")
        git("add", str(path))
        publish(cfg, f"skills: create folder {folder}")
        ok(f"Created {folder}/ — add skills with 'skylls move <skill> {folder}' or 'skylls push <skill> --folder {folder}'")
        return
    if folder not in repo_folders():
        die(f"No folder '{folder}' in {cfg['repo']}. Run 'skylls folder'.")
    skills = sorted(p for paths in index.values() for p in paths if folder_of(p) == folder)
    if action == "rename":
        new = valid_folder(names[1])
        if not new or (root / new).exists() or new in index:
            die(f"Cannot rename to '{names[1]}': it is empty, already exists, or is a skill name.")
        section(f"Renaming {folder}/ → {new}/")
        require_owner(cfg, skills, "move (by renaming their folder)")
        if dry_run:
            info(f"Would rename {folder}/ to {new}/ ({len(skills)} skills) in {cfg['repo']}")
            return
        git("mv", str(path), str(root / new))
        publish(cfg, f"skills: rename folder {folder} to {new}")
        ok(f"Renamed {folder}/ → {new}/ ({len(skills)} skills)")
        return
    section(f"Removing folder {folder}/")
    names_list = ", ".join(p.name for p in skills)
    if skills and not (keep_skills or delete_skills):
        die(f"{folder}/ has {len(skills)} skill(s): {names_list}. Use --keep-skills to move them to the top "
            "level, or --delete-skills to delete them from the repo.")
    if keep_skills or delete_skills:
        require_owner(cfg, skills, "move" if keep_skills else "delete")
    if keep_skills:
        clash = [p.name for p in skills if (root / p.name).exists()]
        if clash:
            die(f"Cannot move to the top level, these names are taken there: {', '.join(clash)}")
    if dry_run:
        what = f" and {'move' if keep_skills else 'delete'} {names_list}" if skills else ""
        info(f"Would remove {folder}/{what} in {cfg['repo']}")
        return
    if skills and delete_skills and not force:
        warn(f"This deletes {names_list} from {cfg['repo']} for everyone (old versions stay installable "
             "with 'skylls add <skill>@<version>').")
        if input(f"  {YELLOW}?{NC} Delete folder {folder}/ and its skills? (y/N): ").strip().lower() != "y":
            die("Nothing was changed.")
    if keep_skills:
        for p in skills:
            git("mv", str(p), str(root / p.name))
    git("rm", "-r", "--quiet", "--ignore-unmatch", str(path))
    if path.exists():
        shutil.rmtree(path)
    if not skills:
        detail = ""
    elif keep_skills:
        detail = f"; moved {names_list} to the top level"
    else:
        detail = f"; deleted {names_list}"
    publish(cfg, f"skills: remove folder {folder}{detail}")
    ok(f"Removed {folder}/{detail}")


def gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def gh_api(*args: str) -> subprocess.CompletedProcess:
    return gh("api", *args)


def gh_lines(*args: str) -> List[str]:
    res = gh_api(*args)
    if res.returncode != 0:
        die(f"gh api {args[0]} failed: {res.stderr.strip()}")
    return [line for line in res.stdout.splitlines() if line.strip()]


def shared_repo_slug(cfg: dict) -> str:
    """owner/name of the shared repo, checking it is on GitHub and gh is ready."""
    slug = github_slug(cfg["repo"])
    if not slug:
        die(f"{cfg['repo']} is not a GitHub repo; sharing only works for GitHub-hosted skill repos.")
    if not shutil.which("gh"):
        die("The GitHub CLI is required (brew install gh, then gh auth login).")
    return slug


def github_users(users: List[str]) -> List[str]:
    """Strip '@' and drop anything that is not a valid GitHub username."""
    valid = []
    for user in (u.lstrip("@") for u in users):
        if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", user):
            valid.append(user)
        else:
            fail(f"'{user}' is not a valid GitHub username.")
    return valid


def pending_invites(slug: str) -> dict:
    """{login (lowercase): invitation id} for invitations not yet accepted."""
    lines = gh_lines(f"repos/{slug}/invitations", "--paginate", "--jq", r'.[] | "\(.invitee.login)\t\(.id)"')
    return {login.lower(): inv_id for login, inv_id in (line.split("\t") for line in lines)}


def cmd_share_list(cfg: dict) -> None:
    slug = shared_repo_slug(cfg)
    section(f"Who can use {slug}")
    for line in gh_lines(f"repos/{slug}/collaborators", "--paginate", "--jq", r'.[] | "\(.login)\t\(.role_name)"'):
        login, role = line.split("\t")
        print(f"  {GREEN}•{NC} {CYAN}@{login}{NC} ({role})")
    for login in pending_invites(slug):
        print(f"  {YELLOW}•{NC} {CYAN}@{login}{NC} (invite pending)")


def cmd_share(cfg: dict, users: List[str], read_only: bool, dry_run: bool) -> None:
    """Invite GitHub users as collaborators on the shared repo."""
    slug = shared_repo_slug(cfg)
    section(f"Sharing {slug}")
    owner_type = gh_lines(f"repos/{slug}", "--jq", ".owner.type")[0]
    is_org = owner_type == "Organization"
    if read_only and not is_org:
        die(f"{slug} is owned by a personal account, where every collaborator can push. "
            "For read-only friends, make the repo public (no invite needed) or move it to an organization.")
    permission = ["-f", f"permission={'pull' if read_only else 'push'}"] if is_org else []
    access = "read-only: add/pull" if read_only else "read + push"
    invited = 0
    for user in github_users(users):
        if dry_run:
            info(f"Would invite @{user} to {slug} with {access} access")
            continue
        res = gh_api("-X", "PUT", f"repos/{slug}/collaborators/{user}", *permission)
        if res.returncode != 0:
            fail(f"@{user}: {(res.stderr or res.stdout).strip()}")
        elif res.stdout.strip():
            ok(f"Invited @{user} ({access})")
            invited += 1
        else:
            ok(f"@{user} already has access ({access})")
    if invited:
        info(f"They accept at https://github.com/{slug}/invitations, then run:")
        print(f"    skylls setup --repo {slug}")


def cmd_unshare(cfg: dict, users: List[str], dry_run: bool) -> None:
    """Remove collaborators from the shared repo and cancel their pending invitations."""
    slug = shared_repo_slug(cfg)
    owner = slug.split("/")[0].lower()
    section(f"Revoking access to {slug}")
    invites = pending_invites(slug)
    for user in github_users(users):
        if user.lower() == owner:
            fail(f"@{user} owns {slug}; their access cannot be revoked.")
            continue
        invite_id = invites.get(user.lower())
        is_collaborator = gh_api(f"repos/{slug}/collaborators/{user}").returncode == 0
        if not invite_id and not is_collaborator:
            warn(f"@{user} has no access to {slug}.")
            continue
        if dry_run:
            info(f"Would revoke @{user}'s {'pending invite' if invite_id else 'access'} to {slug}")
            continue
        if invite_id:
            res = gh_api("-X", "DELETE", f"repos/{slug}/invitations/{invite_id}")
            if res.returncode != 0:
                fail(f"@{user}: {res.stderr.strip()}")
                continue
            ok(f"Cancelled @{user}'s pending invite")
        if is_collaborator:
            res = gh_api("-X", "DELETE", f"repos/{slug}/collaborators/{user}")
            if res.returncode != 0:
                fail(f"@{user}: {res.stderr.strip()}")
                continue
            ok(f"Removed @{user} from {slug} (skills they already installed stay on their machine)")


def skill_of_issue(issue: dict) -> Optional[str]:
    return next((lb["name"][len("skill:"):] for lb in issue.get("labels", []) if lb["name"].startswith("skill:")), None)


def cmd_suggest(cfg: dict, spec: str, text: Optional[str], dry_run: bool) -> None:
    """Open a GitHub issue suggesting an improvement, assigned to the skill's owner."""
    slug = shared_repo_slug(cfg)
    sync_repo(cfg)
    skill_dir = find_repo_skill(cfg, spec)
    name, log = skill_dir.name, read_changelog(skill_dir)
    section(f"Suggesting an improvement to {name}")
    if not text and sys.stdin.isatty():
        text = input(f"  {YELLOW}?{NC} What should be improved? ").strip()
    if not text:
        die('Describe the improvement: skylls suggest <skill> "what to improve"')
    version = log["entries"][0]["version"] if log["entries"] else None
    title = f"{name}: {text.splitlines()[0][:70]}"
    body = f"{text}\n\n---\nSuggestion for the `{name}` skill{f' (v{version})' if version else ''}, sent with skylls."
    to = owner_label(log) if log["created_by"] else "the repo owner"
    if dry_run:
        info(f"Would open an issue in {slug} for {to}: {title}")
        return
    label = f"skill:{name}"
    gh("label", "create", label, "-R", slug, "--force", "--color", "1D76DB", "--description", f"Suggestions for {name}")
    args = ["issue", "create", "-R", slug, "--title", title, "--body", body, "--label", label]
    res = gh(*args, "--assignee", log["owner_login"]) if log["owner_login"] else None
    if not res or res.returncode != 0:  # the owner may not be assignable (e.g. no longer a collaborator)
        res = gh(*args)
    if res.returncode != 0:
        die(f"Could not open the issue: {res.stderr.strip()}")
    ok(f"Suggestion sent to {to}: {res.stdout.strip()}")


def cmd_suggestions(cfg: dict, spec: Optional[str]) -> None:
    slug = shared_repo_slug(cfg)
    name = None
    if spec:
        sync_repo(cfg)
        name = find_repo_skill(cfg, spec).name
    res = gh("issue", "list", "-R", slug, "--state", "open", "--limit", "200",
             "--json", "number,title,author,createdAt,labels,url", *(["--label", f"skill:{name}"] if name else []))
    if res.returncode != 0:
        die(f"Could not list issues: {res.stderr.strip()}")
    issues = [i for i in json.loads(res.stdout or "[]") if skill_of_issue(i)]
    section(f"Open suggestions{f' for {name}' if name else ''} in {slug}")
    if not issues:
        info("None.")
        return
    for i in issues:
        skill = skill_of_issue(i)
        print(f"  {YELLOW}#{i['number']}{NC} {CYAN}{skill}{NC}  {i['title'].removeprefix(f'{skill}: ')}")
        print(f"      by @{i['author']['login']} on {i['createdAt'][:10]}  {BLUE}{i['url']}{NC}")
    info("The skill's owner answers with: skylls accept <#> or skylls decline <#> [-m note]")


def cmd_decide(cfg: dict, number: int, accept: bool, note: Optional[str], dry_run: bool) -> None:
    """Owner closes a suggestion as done (accept) or not planned (decline)."""
    slug = shared_repo_slug(cfg)
    res = gh("issue", "view", str(number), "-R", slug, "--json", "title,state,labels")
    if res.returncode != 0:
        die(f"No issue #{number} in {slug}: {res.stderr.strip()}")
    issue = json.loads(res.stdout)
    skill = skill_of_issue(issue)
    if not skill:
        die(f"#{number} is not a skylls suggestion (no skill: label).")
    if issue["state"] != "OPEN":
        die(f"#{number} is already closed.")
    sync_repo(cfg)
    paths = repo_index().get(skill, [])
    log = read_changelog(paths[0]) if paths else None
    if log and log["created_by"]:
        allowed, who = is_owner(cfg, log), owner_label(log)
    else:
        allowed, who = is_repo_owner(cfg), f"the repo owner ({slug.split('/')[0]})"
    if not allowed:
        die(f"Only {who} can accept or decline suggestions for '{skill}'.")
    verb = "Accepted" if accept else "Declined"
    note = note or ("Done, thanks! Get it with 'skylls pull --update'." if accept else "Thanks, but not planned.")
    if dry_run:
        info(f"Would close #{number} as {'done' if accept else 'not planned'}: {note}")
        return
    res = gh("issue", "close", str(number), "-R", slug, "--reason", "completed" if accept else "not planned",
             "--comment", note)
    if res.returncode != 0:
        die(f"Could not close #{number}: {res.stderr.strip()}")
    ok(f"{verb} #{number} ({skill}): {issue['title'].removeprefix(f'{skill}: ')}")


# ── UI / CLI ───────────────────────────────────────────────────────────────
def show_help() -> None:
    print(f"""
{CYAN}skylls - shared agent skills manager{NC}

{CYAN}USAGE:{NC}
  skylls [--dry-run] [--json] <COMMAND> [ARGS]

{CYAN}COMMANDS:{NC}
  {GREEN}setup{NC} [--create]                First run: your private repos for skills, agents, swarms
  {GREEN}source{NC} [add|remove] <owner/repo> Friends' skills repos you can install from (they share first)
  {GREEN}list{NC} [query]                    Skills available in the shared repo
  {GREEN}find{NC} [words] [--folder F]       Search the shared repo: summary, owner, updates, dates
  {GREEN}agent-skill{NC} [-g] [-a A]         Teach your agents to find, install and share skills
  {GREEN}search{NC} <query>                  Search public skills on skills.sh
  {GREEN}add{NC} <name[@version]|owner/repo/skill>  Install from the shared repo or any GitHub repo
  {GREEN}remove{NC} <name>                   Remove a local copy (never touches the repo)
  {GREEN}installed{NC}                       Installed skills (project + global)
  {GREEN}push{NC} <name|path> [-m msg]       Scan for secrets, then upload a new version → commit + push
  {GREEN}log{NC} <name>                      Version history: who created it, what changed, when and by whom
  {GREEN}move{NC} <name> <folder>            Move a skill into a folder of the repo ('.' = top level)
  {GREEN}folder{NC} [create|rename|remove]   List folders, or create / rename / remove one
  {GREEN}pull{NC} [--update]                 Refresh the repo cache (--update: refresh installed copies)
  {GREEN}suggest{NC} <name> "text"           Suggest an improvement to a skill's owner (GitHub issue)
  {GREEN}suggestions{NC} [name]              Open suggestions (all skills, or one)
  {GREEN}accept{NC} / {GREEN}decline{NC} <#> [-m note]  Owner: mark a suggestion done / not planned
  {GREEN}share{NC} [@user...]                Invite friends to the shared repo (no names: list who has access)
  {GREEN}unshare{NC} @user...                Revoke their access / cancel pending invites

{CYAN}AGENTS AND SWARMS:{NC}  skylls agents|swarms <command>   (yours: ~/agents, ~/swarms)
  {GREEN}list{NC} / {GREEN}find{NC} <words>             Yours and your sources' (--from OWNER for one friend)
  {GREEN}push{NC} <name> [-m msg]            Publish a version of yours: definition + Obsidian memory
  {GREEN}add{NC} <name[@ver]> --from OWNER   Download a friend's (definition + memory; --update-memory)
  {GREEN}log{NC} / {GREEN}source{NC} / {GREEN}share{NC} / {GREEN}unshare{NC} / {GREEN}suggest{NC} / {GREEN}suggestions{NC} / {GREEN}accept{NC} / {GREEN}decline{NC}

{CYAN}OPTIONS (add/remove/installed/push/pull):{NC}
  {YELLOW}--from OWNER{NC}        add/list/find/log/suggest: use a friend's repo (a source)
  {YELLOW}--json{NC}              For agents: find/list/installed/log print compact JSON lines
  {YELLOW}--limit N{NC}           find: at most N results (default 10 with --json)
  {YELLOW}-g, --global{NC}        Use ~/<agent dir> instead of ./<agent dir>
  {YELLOW}-a, --agent A{NC}       claude, codex, gemini, a comma list, or all (default from setup)
  {YELLOW}-y, --yes{NC}           Overwrite without asking (add; push: replace a newer repo version)
  {YELLOW}-m "what changed"{NC}   Log entry for the new version (push asks if omitted)
  {YELLOW}--minor, --major{NC}    Bump 1.2.3 → 1.3.0 / 2.0.0 instead of 1.2.4 (push)
  {YELLOW}--about "..."{NC}       Write the plain summary yourself instead of Claude (push)
  {YELLOW}--folder F{NC}          Put a new skill in folder F of the repo (push)
  {YELLOW}--updates WHO{NC}       anyone | owner: who may push updates (push; set by the owner)
  {YELLOW}--keep-skills{NC}       folder remove: move its skills to the top level first
  {YELLOW}--delete-skills{NC}     folder remove: delete its skills from the repo too (asks first)
  {YELLOW}--skip-scan{NC}         Push without the gitleaks secret/private-info scan (push)
  {YELLOW}--read-only{NC}         Friends can add/pull but not push (share; organization repos only)

{CYAN}AGENT FOLDERS:{NC}
  claude  .claude/skills    codex  .agents/skills    gemini  .gemini/skills
  Global installs: one real copy (claude first), other agents are symlinks to it.

{CYAN}EXAMPLES:{NC}
  skylls add youtube-transcribe                 {BLUE}# into ./.claude/skills{NC}
  skylls add youtube-transcribe -g -a all       {BLUE}# global, every agent{NC}
  skylls search pdf && skylls add anthropics/skills/pdf -g
  skylls push my-new-skill -m "Better prompts"  {BLUE}# share a new version{NC}
  skylls log my-new-skill                       {BLUE}# what changed and when{NC}
  skylls add my-new-skill@1.0.0                 {BLUE}# install an older version{NC}
  skylls folder create work && skylls move my-new-skill work
  skylls suggest my-new-skill "Also handle PDFs"  {BLUE}# ask its owner{NC}
  skylls find pdf --json --limit 5              {BLUE}# for agents: compact output{NC}
  skylls agent-skill -g -a all                  {BLUE}# agents learn to use skylls{NC}
  skylls pull --update -g                       {BLUE}# get teammates' changes{NC}
  skylls share @alice @bob                      {BLUE}# share the repo with friends{NC}
  skylls unshare @bob                           {BLUE}# revoke bob's access{NC}

  Config: {CONFIG_PATH}
  Cache:  {CACHE_REPO}
""")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="skylls", description="Manage agent skills from a shared GitHub repo.")
    p.add_argument("--dry-run", action="store_true", help="Show actions without executing.")
    p.add_argument("--json", action="store_true",
                   help="Compact JSON lines on stdout for find/list/installed/log (for agents).")
    sub = p.add_subparsers(dest="cmd", required=False)

    def scoped(sp: argparse.ArgumentParser) -> argparse.ArgumentParser:
        sp.add_argument("-g", "--global", dest="is_global", action="store_true", default=None,
                        help="Use the global (home) skills folder.")
        sp.add_argument("-a", "--agent", help="claude, codex, gemini, comma list, or all.")
        return sp

    sp = sub.add_parser("setup", help="Your GitHub repos for skills, agents and swarms; default agent CLIs.")
    sp.add_argument("--repo", help="Your skills repo.")
    sp.add_argument("--agents", help="Default agent CLIs: claude, codex, gemini, comma list or all.")
    for kind in ("agents", "swarms"):
        sp.add_argument(f"--{kind}-repo", help=f"Your {kind} repo.")
        sp.add_argument(f"--{kind}-dir", help=f"Folder holding your {kind} (default ~/{kind}).")
    sp.add_argument("--create", action="store_true",
                    help="Create missing repos as private <your-login>/skylls-<kind> without asking.")

    sp = sub.add_parser("source", help="List, add or remove friends' skills repos.")
    sp.add_argument("action", nargs="?", choices=["add", "remove"])
    sp.add_argument("repo", nargs="?")

    sp = sub.add_parser("list", help="List skills in the shared repo.")
    sp.add_argument("query", nargs="?")
    sp.add_argument("--from", dest="owner", help="Only this friend's repo.")

    sp = sub.add_parser("find", help="Search the shared repo by keyword and/or folder.")
    sp.add_argument("keywords", nargs="*")
    sp.add_argument("-f", "--folder", help="Only this folder ('.' = top level).")
    sp.add_argument("-n", "--limit", type=int, help="At most N results (default 10 with --json).")
    sp.add_argument("--from", dest="owner", help="Only this friend's repo.")

    sp = sub.add_parser("search", help="Search skills.sh.")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=15)

    sp = scoped(sub.add_parser("add", help="Install a skill."))
    sp.add_argument("name")
    sp.add_argument("--from", dest="owner", help="Install from this friend's repo (a source).")
    sp.add_argument("-y", "--yes", action="store_true", help="Overwrite without asking.")

    scoped(sub.add_parser("remove", help="Remove an installed skill.")).add_argument("name")
    scoped(sub.add_parser("installed", help="List installed skills."))

    for cmd in ("push", "save"):
        sp = scoped(sub.add_parser(cmd, help="Upload a skill to the shared repo."))
        sp.add_argument("name")
        sp.add_argument("-m", "--message", help="What changed (logged with the new version).")
        bump_group = sp.add_mutually_exclusive_group()
        bump_group.add_argument("--minor", dest="part", action="store_const", const="minor", default="patch")
        bump_group.add_argument("--major", dest="part", action="store_const", const="major")
        sp.add_argument("--about", help="Plain one-sentence summary (default: written by Claude).")
        sp.add_argument("--folder", help="Folder of the repo for a new skill (default: top level).")
        sp.add_argument("--updates", choices=["anyone", "owner"],
                        help="Who may push updates: anyone, or only the owner (others suggest).")
        sp.add_argument("-y", "--yes", action="store_true", help="Replace a newer repo version without asking.")
        sp.add_argument("--skip-scan", action="store_true",
                        help="Push without scanning for secrets/private info (gitleaks).")

    sp = sub.add_parser("suggest", aliases=["comment"], help="Suggest an improvement to a skill's owner.")
    sp.add_argument("name")
    sp.add_argument("text", nargs="?")
    sp.add_argument("--from", dest="owner", help="The skill is in this friend's repo.")
    sub.add_parser("suggestions", help="List open suggestions.").add_argument("name", nargs="?")
    for cmd in ("accept", "decline"):
        sp = sub.add_parser(cmd, help=f"Owner: {cmd} a suggestion.")
        sp.add_argument("number", type=lambda v: int(v.lstrip("#")))
        sp.add_argument("-m", "--message", help="Note posted on the suggestion.")

    sp = sub.add_parser("move", help="Move a skill into a folder of the repo ('.' = top level).")
    sp.add_argument("name")
    sp.add_argument("folder")

    sp = sub.add_parser("folder", help="List, create, rename or remove folders in the repo.")
    sp.add_argument("action", nargs="?", choices=["create", "rename", "remove"])
    sp.add_argument("names", nargs="*")
    group = sp.add_mutually_exclusive_group()
    group.add_argument("--keep-skills", action="store_true", help="remove: move its skills to the top level.")
    group.add_argument("--delete-skills", action="store_true", help="remove: delete its skills from the repo.")
    sp.add_argument("-y", "--yes", action="store_true", help="remove: don't ask before deleting skills.")

    sp = sub.add_parser("log", aliases=["history"], help="Show a skill's version history.")
    sp.add_argument("name")
    sp.add_argument("--from", dest="owner", help="The skill is in this friend's repo.")

    sp = scoped(sub.add_parser("pull", help="Refresh the repo cache."))
    sp.add_argument("--update", action="store_true", help="Also refresh installed copies.")

    sp = sub.add_parser("share", aliases=["adduser"], help="Invite GitHub users to the shared repo.")
    sp.add_argument("users", nargs="*", metavar="@github-user")
    sp.add_argument("--read-only", action="store_true",
                    help="Add/pull only, no push (organization-owned repos only).")

    sp = sub.add_parser("unshare", aliases=["revoke"], help="Revoke GitHub users' access to the shared repo.")
    sp.add_argument("users", nargs="+", metavar="@github-user")

    scoped(sub.add_parser("agent-skill", help="Install the skylls skill so agents can find and share skills."))

    from skylls import kinds
    kinds.add_parsers(sub)

    sub.add_parser("help", help="Show detailed help and usage examples.")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    global JSON_MODE
    parser = build_parser()
    args = parser.parse_args(argv)
    JSON_MODE = args.json

    if args.cmd == "help":
        show_help()
        return 0
    if args.cmd == "search":
        cmd_search(args.query, args.limit)
        return 0
    if args.cmd == "setup":
        setup(args.repo, args.agents, {k: {"repo": getattr(args, f"{k}_repo"), "dir": getattr(args, f"{k}_dir")}
                                       for k in ("agents", "swarms")}, args.create)
        return 0

    from skylls import kinds
    cfg = get_config()
    owner = getattr(args, "owner", None)
    has_sources = bool(kinds.sources(cfg, "skills"))
    if args.cmd in ("agents", "swarms"):
        kinds.run(cfg, args.cmd, args)
        return 0
    if args.cmd == "source":
        kinds.cmd_source(cfg, "skills", args.action, args.repo, args.dry_run)
        return 0
    if owner and args.cmd in ("list", "find", "log", "history", "suggest", "comment"):
        if args.cmd == "list":
            kinds.cmd_list(cfg, "skills", args.query, owner)
        elif args.cmd == "find":
            kinds.cmd_find(cfg, "skills", getattr(args, "key" + "words"), owner, args.limit)
        elif args.cmd in ("log", "history"):
            kinds.cmd_log(cfg, "skills", args.name, owner)
        else:
            kinds.cmd_suggest(cfg, "skills", args.name, owner, args.text, args.dry_run)
        return 0
    if args.cmd in (None, "installed"):
        cmd_installed(cfg, getattr(args, "agent", None), getattr(args, "is_global", None))
    elif args.cmd == "find":
        if not args.keywords and args.folder is None:
            die("Give keywords and/or --folder, e.g. skylls find pdf  or  skylls find --folder work")
        cmd_find(cfg, getattr(args, "key" + "words"), args.folder, args.limit)
        if has_sources and args.folder is None:
            kinds.cmd_find(cfg, "skills", getattr(args, "key" + "words"), None, args.limit)
    elif args.cmd == "agent-skill":
        cmd_agent_skill(cfg, args.agent, bool(args.is_global), args.dry_run)
    elif args.cmd == "list":
        cmd_list(cfg, args.query)
        if has_sources:
            kinds.cmd_list(cfg, "skills", args.query)
    elif args.cmd == "add":
        cmd_add(cfg, args.name, args.agent, bool(args.is_global), args.dry_run, args.yes, owner)
    elif args.cmd == "remove":
        cmd_remove(cfg, args.name, args.agent, bool(args.is_global), args.dry_run)
    elif args.cmd in ("push", "save"):
        cmd_push(cfg, args.name, args.agent, args.is_global, args.message, args.dry_run, args.skip_scan,
                 args.part, args.about, args.yes, args.folder, args.updates)
    elif args.cmd in ("suggest", "comment"):
        cmd_suggest(cfg, args.name, args.text, args.dry_run)
    elif args.cmd == "suggestions":
        cmd_suggestions(cfg, args.name)
    elif args.cmd in ("accept", "decline"):
        cmd_decide(cfg, args.number, args.cmd == "accept", args.message, args.dry_run)
    elif args.cmd == "move":
        cmd_move(cfg, args.name, args.folder, args.dry_run)
    elif args.cmd == "folder":
        cmd_folder(cfg, args.action, args.names, args.keep_skills, args.delete_skills, args.yes, args.dry_run)
    elif args.cmd in ("log", "history"):
        cmd_log(cfg, args.name)
    elif args.cmd == "pull":
        cmd_pull(cfg, args.update, args.agent, args.is_global, args.dry_run)
    elif args.cmd in ("share", "adduser"):
        if args.users:
            cmd_share(cfg, args.users, args.read_only, args.dry_run)
        else:
            cmd_share_list(cfg)
    elif args.cmd in ("unshare", "revoke"):
        cmd_unshare(cfg, args.users, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
