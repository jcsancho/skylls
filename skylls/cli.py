#!/usr/bin/env python3
"""
skylls - share agent skills, agents and swarms through your own private GitHub repos
-------------------------------------------------------------------------------------
Every skill, agent and swarm you publish gets its own private GitHub repo
(<owner>/skylls-skill-<name>, skylls-agent-<name>, skylls-swarm-<name>) in your
account or an organization chosen at setup. You share item by item; friends
add you as a source and see exactly what you shared with them.

Skills are installed per agent CLI, for the current project or globally (-g):

  claude  ./.claude/skills   ~/.claude/skills
  codex   ./.agents/skills   ~/.agents/skills
  gemini  ./.gemini/skills   ~/.gemini/skills

Global installs for several agents keep one real copy (in the first agent's
folder, claude when selected) and symlink the others to it. Agents and swarms
live in the folders chosen at setup (default ~/agents and ~/swarms).

This module holds output, configuration, setup, changelogs, the secret scan,
skill install helpers and the command line; kinds.py holds the GitHub side
(catalog, publish, install, share, suggestions, folders, memory).
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

from skylls import __version__

# ── Output ─────────────────────────────────────────────────────────────────
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
                     ensure_ascii=False, separators=(",", ":"), default=str))


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
SKILLS_SH_API = "https://skills.sh/api/search"
CONFIG_VERSION = 1  # 1.0: one repo per item (older configs pointed at one repo per kind)

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


def setup(agents: Optional[str] = None, owner: Optional[str] = None, dirs: Optional[dict] = None,
          agent_skill: bool = True) -> dict:
    """First run: where your private repos are created, your agent CLIs and folders, and the skylls skill."""
    from skylls import kinds
    old = load_config()
    section("skylls setup")
    if not shutil.which("gh"):
        die("skylls needs the GitHub CLI: brew install gh, then gh auth login")
    login = my_login() or die("The GitHub CLI isn't logged in. Run: gh auth login")
    ok(f"GitHub: @{login}")
    owner = kinds.choose_owner(login, owner, old.get("owner"))
    owner_is_org = owner.lower() != login.lower()
    ok(f"Your skills, agents and swarms are published to {owner}, each in its own private repo "
       f"(named like {kinds.repo_name('skills', 'pdf', owner_is_org)}); nothing is shared until you share it")
    if owner_is_org:
        kinds.ensure_org_private(owner)
    interactive = sys.stdin.isatty()
    if not agents:
        current = ",".join(old.get("agents", ["claude"]))
        agents = (input(f"  {YELLOW}?{NC} Agent CLIs you use (claude,codex,gemini or all) [{current}]: ").strip()
                  if interactive else "") or current
    agent_list = parse_agents(agents)
    folders = {}
    for kind in ("agents", "swarms"):
        given = (dirs or {}).get(kind)
        default = old.get("dirs", {}).get(kind) or old.get("kinds", {}).get(kind, {}).get("dir") \
            or str(Path.home() / kind)
        folder = given or (input(f"  {YELLOW}?{NC} Folder for your {kind} [{default}]: ").strip()
                           if interactive else "") or default
        path = Path(folder).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        folders[kind] = str(path)
    friends = old.get("friends") or sorted({
        r.split("/")[0] for rs in old.get("sources", {}).values() for r in rs if re.fullmatch(r"[\w.-]+/[\w.-]+", r)})
    cfg = {"version": CONFIG_VERSION, "login": login, "owner": owner, "owner_is_org": owner_is_org,
           "agents": agent_list, "dirs": folders, "friends": friends}
    save_config(cfg)
    ok(f"Saved {CONFIG_PATH}")
    if agent_skill:  # last step: let Claude Code, Codex and Gemini use skylls themselves
        which = "all"
        if interactive:
            answer = input(f"  {YELLOW}?{NC} Install the skylls skill globally so your agents can use skylls? "
                           f"claude, codex, gemini, a comma list or all [all] ('-' = no): ").strip()
            which = None if answer == "-" else answer or "all"
        if which:
            cmd_agent_skill(cfg, which, True, False)
        else:
            info("Skipped the skylls skill; add it later with: skylls agent-skill -g -a all")
    info("Publish: skylls push <skill> · skylls agents push <name> · share: skylls share <name> @friend")
    info("A friend shared with you? skylls source add <their-login>")
    return cfg


def get_config() -> dict:
    cfg = load_config()
    if cfg.get("version") == CONFIG_VERSION and cfg.get("owner"):
        if "owner_is_org" not in cfg:  # configs from 1.0.0
            cfg["owner_is_org"] = cfg["owner"].lower() != cfg["login"].lower()
            save_config(cfg)
        return cfg
    if cfg:
        warn("skylls 1.0 publishes every skill, agent and swarm to its own repo; a quick setup first "
             "(your installed skills, agents and swarms stay where they are).")
    return setup()


def refresh_agent_skill(cfg: dict) -> None:
    """After an upgrade, bring an installed skylls skill in line with this version of skylls."""
    bundled = (AGENT_SKILL_DIR / "SKILL.md").read_text()
    for root in target_dirs(cfg, "all", True):
        installed = root / "skylls" / "SKILL.md"
        if installed.is_file() and not (root / "skylls").is_symlink() and installed.read_text() != bundled:
            installed.write_text(bundled)
            info(f"Updated the skylls skill in {root} for skylls {__version__}")


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


# ── git / gh ───────────────────────────────────────────────────────────────
def git(*args: str, cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    res = subprocess.run(["git", *args], cwd=cwd or Path.home(), capture_output=True, text=True)
    if check and res.returncode != 0:
        die(f"git {' '.join(args)} failed:\n{res.stderr.strip()}")
    return res


def gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def gh_api(*args: str) -> subprocess.CompletedProcess:
    return gh("api", *args)


def github_users(users: List[str]) -> List[str]:
    """Strip '@' and drop anything that is not a valid GitHub username."""
    valid = []
    for user in (u.lstrip("@") for u in users):
        if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", user):
            valid.append(user)
        else:
            fail(f"'{user}' is not a valid GitHub username.")
    return valid


_identity: dict = {}


def my_name() -> str:
    return git("config", "user.name", check=False).stdout.strip()


def my_login() -> str:
    """GitHub login of the gh user ('' without gh)."""
    if "login" not in _identity:
        res = gh_api("user", "--jq", ".login") if shutil.which("gh") else None
        _identity["login"] = res.stdout.strip() if res and res.returncode == 0 else ""
    return _identity["login"]


# ── Versions & changelog ───────────────────────────────────────────────────
CHANGELOG = "CHANGELOG.md"  # per item, written by push: plain summary + one entry per version
CREATED_RE = re.compile(r"^Created by (.+?)(?: \(@([A-Za-z0-9-]+)\))? on (\d{4}-\d{2}-\d{2})\.$")
SOURCE_RE = re.compile(r"^Source: (.+?)\.?$")   # an installed copy: "<owner>/<repo> v<version>"
ORIGIN_RE = re.compile(r"^Origin: (.+)$")        # owner's folder (agents/swarms), for path rewriting
HOME_RE = re.compile(r"^Home: (.+)$")            # owner's home folder
MEMORY_RE = re.compile(r"^Memory: (.+)$")        # downloaded copy: its memory folders outside it (home-relative)
ENTRY_RE = re.compile(r"^## (\d+\.\d+\.\d+) — (\S+)(?: — (.*))?$")


def read_changelog(item: Path) -> dict:
    path = item / CHANGELOG
    return parse_changelog(path.read_text(errors="ignore") if path.is_file() else "")


def parse_changelog(text: str) -> dict:
    """{about, created_by, owner_login, created, source, origin, home, memory, entries (newest first)}."""
    log = {"about": "", "created_by": "", "owner_login": "", "created": "", "entries": [],
           "source": "", "origin": "", "home": "", "memory": ""}
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
        else:
            for key, rx in (("source", SOURCE_RE), ("origin", ORIGIN_RE), ("home", HOME_RE),
                            ("memory", MEMORY_RE)):
                if (m2 := rx.match(line)):
                    log[key] = m2[1].strip()
    for e in entries:
        e["notes"] = "\n".join(e["notes"]).strip()
    return log


def write_changelog(item: Path, name: str, log: dict) -> None:
    out = [f"# {name}", ""]
    if log["about"]:
        out += [f"> {log['about']}", ""]
    if log["created_by"]:
        out += [f"Created by {owner_label(log)} on {log['created']}.", ""]
    for key in ("source", "origin", "home", "memory"):
        if log.get(key):
            out += [f"{key.capitalize()}: {log[key]}" + ("." if key == "source" else ""), ""]
    for e in log["entries"]:
        out += [f"## {e['version']} — {e['date']}" + (f" — {e['author']}" if e["author"] else ""), "", e["notes"], ""]
    (item / CHANGELOG).write_text("\n".join(out))


def owner_label(log: dict) -> str:
    return log["created_by"] + (f" (@{log['owner_login']})" if log["owner_login"] else "")


def version_key(version: str) -> Tuple[int, ...]:
    return tuple(int(n) for n in version.split("."))


def bump(version: Optional[str], part: str) -> str:
    if not version:
        return "1.0.0"
    major, minor, patch = version_key(version)
    return {"major": f"{major + 1}.0.0", "minor": f"{major}.{minor + 1}.0"}.get(part, f"{major}.{minor}.{patch + 1}")


def ai_summary(item: Path, main: str = "SKILL.md", what: str = "AI agent skill") -> Optional[str]:
    """One plain sentence on what the item does, written by Claude (claude -p)."""
    if not shutil.which("claude"):
        warn("claude CLI not found; no plain-language summary (use --about \"...\" to write one).")
        return None
    info("Asking Claude for a plain-language summary …")
    prompt = (f"Below is an {what} ({main}). In ONE short, simple sentence (max 20 words, no jargon), "
              "say what it does for the person using it. Reply with only that sentence.")
    with tempfile.TemporaryDirectory() as tmp:  # neutral cwd: no project CLAUDE.md in the context
        try:
            res = subprocess.run(["claude", "-p", "--model", "haiku", prompt], cwd=tmp, capture_output=True,
                                 text=True, timeout=180, input=(item / main).read_text(errors="ignore")[:20000])
        except subprocess.TimeoutExpired:
            res = None
    summary = " ".join(res.stdout.split())[:300] if res and res.returncode == 0 else ""
    if not summary:
        warn("Claude could not write a summary; use --about \"...\" to write one.")
    return summary or None


# ── Secret scan ────────────────────────────────────────────────────────────
def gitleaks_config() -> Optional[Path]:
    """The git-scan-secrets skill's gitleaks rules (secrets + personal data), if installed."""
    for base in (Path.home() / ".claude" / "skills", Path.home() / "SKILLS"):
        cfg = base / "git-scan-secrets" / "gitleaks.toml"
        if cfg.is_file():
            return cfg
    return None


def scan_secrets(folder: Path) -> None:
    """Abort unless gitleaks finds no API keys, passwords or private info in folder."""
    if not shutil.which("gitleaks"):
        die("gitleaks is required to check for secrets before publishing (brew install gitleaks), "
            "or pass --skip-scan.")
    info("Scanning for API keys, secrets and private info (gitleaks) …")
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        cmd = ["gitleaks", "dir", str(folder), "--redact", "--no-banner", "--exit-code", "0",
               "--log-level", "error", "--report-format", "json", "--report-path", str(report)]
        cfg = gitleaks_config()
        if cfg:
            cmd += ["--config", str(cfg)]
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
        rel = path.relative_to(folder) if path.is_relative_to(folder) else path
        say(f"    {RED}•{NC} {rel}:{f.get('StartLine', '?')}  {YELLOW}{f.get('RuleID', '?')}{NC}  {f.get('Match', '')}")
    die("Nothing was published. Remove them (use placeholders or env vars), "
        "or pass --skip-scan if they are false positives.")


# ── Installing skills ──────────────────────────────────────────────────────
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


def get_skill_description(skill_dir: Path) -> Optional[str]:
    """The description from a skill's SKILL.md frontmatter."""
    from skylls import kinds
    skill_md = skill_dir / "SKILL.md"
    return kinds.summary_from(skill_md.read_text(errors="ignore")) if skill_md.exists() else None


def installed_scope(cfg: dict, name: str) -> Optional[str]:
    """'project' / 'global' if the skill is installed for the default agents, else None."""
    for scope, is_global in (("project", False), ("global", True)):
        if any((d / name / "SKILL.md").is_file() for d in target_dirs(cfg, None, is_global)):
            return scope
    return None


def find_installed(cfg: dict, name: str, agent: Optional[str], is_global: Optional[bool]) -> Path:
    """A skill to publish: a folder path, or an installed copy (project first, then global)."""
    if Path(name).expanduser().is_dir():
        return Path(name).expanduser().resolve()
    scopes = [is_global] if is_global is not None else [False, True]
    for scope in scopes:
        for dest_root in target_dirs(cfg, agent or ",".join(AGENT_DIRS), scope):
            if (dest_root / name / "SKILL.md").is_file():
                return dest_root / name
    die(f"Skill '{name}' not found in any project or global skills folder.")


def fetch_remote_skill(spec: str, tmp: Path) -> Path:
    """Fetch 'owner/repo/skill' (a skills.sh id) from a public GitHub repo into tmp."""
    owner, repo, skill = spec.split("/", 2)
    info(f"Fetching {owner}/{repo} from GitHub …")
    git("clone", "--quiet", "--depth", "1", f"https://github.com/{owner}/{repo}.git", str(tmp / "src"), cwd=tmp)
    for skill_md in (tmp / "src").rglob("SKILL.md"):
        if skill_md.parent.name == skill:
            return skill_md.parent
    die(f"No skill folder named '{skill}' with a SKILL.md found in {owner}/{repo}.")


def cmd_add_remote(cfg: dict, spec: str, agent: Optional[str], is_global: bool, dry_run: bool, force: bool) -> None:
    from skylls import kinds
    section(f"Installing {spec}")
    with tempfile.TemporaryDirectory() as tmp:
        source = fetch_remote_skill(spec, Path(tmp))
        kinds.install_skill_copy(cfg, source, source.name, agent, is_global, force, dry_run)


def cmd_remove(cfg: dict, name: str, agent: Optional[str], is_global: bool, dry_run: bool) -> None:
    """Remove an installed skill from this computer (never touches GitHub)."""
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


def cmd_search(query: str, limit: int) -> None:
    section(f"skills.sh results for '{query}'")
    url = f"{SKILLS_SH_API}?{urllib.parse.urlencode({'q': query, 'limit': limit})}"
    with urllib.request.urlopen(url, timeout=20) as resp:
        results = json.load(resp).get("skills", [])
    if not results:
        warn("No results.")
        return
    for s in results:
        say(f"  {GREEN}•{NC} {CYAN}{s['id']}{NC}  {s.get('installs', 0):,} installs")
    info("Install with: skylls add <owner/repo/skill> [-g] [-a agent]")


# The skill that teaches any agent (Claude Code, Codex, Gemini) to use skylls; also installable
# straight from GitHub: skylls add jcsancho/skylls/skylls -g -a all
AGENT_SKILL_DIR = Path(__file__).parent / "skills" / "skylls"


def cmd_agent_skill(cfg: dict, agent: Optional[str], is_global: bool, dry_run: bool) -> None:
    """Install the 'skylls' skill, which teaches agents to find, install and share with skylls."""
    from skylls import kinds
    section("Installing the skylls skill for your agents")
    if not (AGENT_SKILL_DIR / "SKILL.md").is_file():
        die(f"The skylls skill is missing from this install ({AGENT_SKILL_DIR}). Reinstall skylls.")
    kinds.install_skill_copy(cfg, AGENT_SKILL_DIR, "skylls", agent, is_global, True, dry_run)


# ── Updating skylls itself ─────────────────────────────────────────────────
SKYLLS_REPO = "jcsancho/skylls"
NPM_PACKAGE = "@jcsancho/skylls"


def install_kind() -> str:
    """How this skylls was installed: npm, uv, pipx, source (a checkout or editable install) or pip."""
    pkg = Path(__file__).resolve().parent
    if "node_modules" in pkg.parts:
        return "npm"
    prefix = Path(sys.prefix).resolve()
    if not pkg.is_relative_to(prefix):
        return "source"
    if (prefix / "uv-receipt.toml").is_file():
        return "uv"
    return "pipx" if (prefix / "pipx_metadata.json").is_file() else "pip"


def latest_version(kind: str) -> Optional[str]:
    """The newest released skylls: on npm for npm installs, else the highest v<x.y.z> tag on GitHub."""
    if kind == "npm":
        res = subprocess.run(["npm", "view", NPM_PACKAGE, "version"], capture_output=True, text=True)
        return res.stdout.strip() or None
    res = git("ls-remote", "--tags", "--refs", repo_url(SKYLLS_REPO), check=False)
    tags = re.findall(r"refs/tags/v(\d+\.\d+\.\d+)$", res.stdout, re.M)
    return max(tags, key=version_key) if tags else None


def cmd_update(check: bool, dry_run: bool) -> None:
    """Install the newest skylls the same way this one was installed (uv, pipx or npm)."""
    kind = install_kind()
    latest = latest_version(kind)
    if not latest:
        die("Could not find the newest skylls version (no network, or GitHub/npm unreachable).")
    newer = version_key(latest) > version_key(__version__)
    if JSON_MODE and (check or not newer):
        emit({"version": __version__, "latest": latest, "newer": newer, "installed_with": kind})
    if not newer:
        ok(f"skylls {__version__} is the newest version.")
        return
    info(f"skylls {latest} is available (you have {__version__}). What changed: "
         f"https://github.com/{SKYLLS_REPO}/blob/main/CHANGES.md")
    if check:
        info("Install it with: skylls update")
        return
    source = os.environ.get("SKYLLS_SOURCE", f"git+https://github.com/{SKYLLS_REPO}")
    spec = f"{source}@v{latest}" if source.startswith("git+") else source
    cmd = {"uv": ["uv", "tool", "install", "--force", "--quiet", spec],
           "pipx": ["pipx", "install", "--force", spec],
           "npm": ["npm", "install", "-g", f"{NPM_PACKAGE}@{latest}"]}.get(kind)
    if not cmd:
        where = Path(__file__).resolve().parent.parent
        die(f"This skylls runs from {where} ({kind} install), so it can't update itself. "
            + ("Run git pull there." if kind == "source" else f"Reinstall with: uv tool install --force {spec}"))
    if not shutil.which(cmd[0]):
        die(f"{cmd[0]} is not on your PATH; skylls was installed with it. Run: {' '.join(cmd)}")
    if dry_run:
        info(f"[dry-run] Would run: {' '.join(cmd)}")
        return
    section(f"Updating skylls {__version__} → {latest}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        die(f"The update failed ({' '.join(cmd)}):\n{(res.stderr or res.stdout).strip()}")
    ok(f"skylls {latest} installed. The skylls skill for your agents updates the next time you run skylls.")
    if JSON_MODE:
        emit({"version": latest, "previous": __version__, "updated": True, "installed_with": kind})


# ── Command line ───────────────────────────────────────────────────────────
def show_help() -> None:
    say(f"""
{CYAN}skylls {__version__} - share agent skills, agents and swarms{NC}
Every item you publish gets its own private GitHub repo; you share item by item.

{CYAN}USAGE:{NC}
  skylls [--dry-run] [--json] <COMMAND> [ARGS]
  skylls agents <COMMAND> …   /   skylls swarms <COMMAND> …   (same commands)

{CYAN}FIND & INSTALL:{NC}
  {GREEN}list{NC} [query] [--from O] [-f F]     Yours and your friends' (grouped by folder)
  {GREEN}find{NC} <words> [--from O] [-f F]     Search: summary, version, owner, folder
  {GREEN}add{NC} <name[@ver]> [--from O]        Install (skills: [-g] [-a A]; agents: [--as N])
  {GREEN}log{NC} <name> [--from O]              Who made it, versions, what changed
  {GREEN}installed{NC} [-g] [-a A]              Installed skills (and newer versions)
  {GREEN}pull{NC} [--update]                    Check for new versions (--update: install them)
  {GREEN}remove{NC} <name>                      Remove from this computer (agents/swarms: to the Trash)
  {GREEN}search{NC} <query>                     Public skills on skills.sh (add owner/repo/skill)

{CYAN}PUBLISH & SHARE:{NC}
  {GREEN}push{NC} <name> [-m msg]               Publish a new version to its private repo
  {GREEN}share{NC} <name> @user… | --all @user  Let friends install it (no users: who has access)
  {GREEN}unshare{NC} <name> @user…              Revoke access
  {GREEN}move{NC} <name> <folder>               Put it in a folder (a GitHub topic; '.' = none)
  {GREEN}folder{NC} [rename|remove]             Your folders
  {GREEN}source{NC} [add|remove] <login>        Friends whose shares you see (accepts their invites)

{CYAN}SUGGESTIONS:{NC}
  {GREEN}suggest{NC} <name> --from O "text"     Suggest an improvement (GitHub issue to the owner)
  {GREEN}suggestions{NC} [name]                 Open suggestions for yours
  {GREEN}accept{NC} / {GREEN}decline{NC} <name>#<n> [-m note]  Answer one

{CYAN}SETUP & MORE:{NC}
  {GREEN}setup{NC}                              Your account or organization, agent CLIs, folders
  {GREEN}agent-skill{NC} [-g] [-a A]            Teach your agents to use skylls
  {GREEN}version{NC}                            Show the skylls version
  {GREEN}update{NC} [--check]                   Update skylls itself to the newest version

{CYAN}OPTIONS:{NC}
  {YELLOW}-g, --global{NC}        Skills: ~/<agent dir> instead of ./<agent dir>
  {YELLOW}-a, --agent A{NC}       claude, codex, gemini, a comma list, or all (default from setup)
  {YELLOW}--from OWNER{NC}        Whose item (when several people have one with that name)
  {YELLOW}-m "what changed"{NC}   Log entry for a new version (push asks if omitted)
  {YELLOW}--minor, --major{NC}    Bump 1.2.3 → 1.3.0 / 2.0.0 instead of 1.2.4 (push)
  {YELLOW}--about "..."{NC}       Write the plain summary yourself instead of Claude (push)
  {YELLOW}--folder F{NC}          Put it in folder F (push); -f F filters list/find
  {YELLOW}--skip-scan{NC}         Publish without the gitleaks secret/private-info scan
  {YELLOW}--update-memory{NC}     Agents/swarms add: also refresh your copy of its memory
  {YELLOW}--json{NC}              For agents: compact JSON lines (list/find/log/installed/suggestions)
  {YELLOW}--limit N{NC}           find: at most N results (default 10 with --json)

{CYAN}EXAMPLES:{NC}
  skylls push pdf -m "Handles scans" --folder docs   {BLUE}# → <you>/skylls-skill-pdf{NC}
  skylls share pdf @bob                              {BLUE}# bob: skylls source add <you>{NC}
  skylls find invoice                                {BLUE}# yours + friends'{NC}
  skylls add pdf --from alice -g -a all              {BLUE}# Claude, Codex and Gemini{NC}
  skylls agents push btc -m "Adds ETH"               {BLUE}# ~/agents/btc + its memory{NC}
  skylls agents add btc --from alice                 {BLUE}# → ~/agents/btc{NC}
  skylls suggest btc --from alice "Also track SOL"

  Config: {CONFIG_PATH}
""")


def build_parser() -> argparse.ArgumentParser:
    from skylls import kinds
    p = argparse.ArgumentParser(prog="skylls", description="Share agent skills, agents and swarms via GitHub.")
    p.add_argument("-V", "--version", action="version", version=f"skylls {__version__}")
    p.add_argument("--dry-run", action="store_true", help="Show actions without executing.")
    p.add_argument("--json", action="store_true", help="Compact JSON lines on stdout (for agents).")
    sub = p.add_subparsers(dest="cmd", required=False)

    def scoped(sp: argparse.ArgumentParser) -> argparse.ArgumentParser:
        sp.add_argument("-g", "--global", dest="is_global", action="store_true", default=None,
                        help="Use the global (home) skills folder.")
        sp.add_argument("-a", "--agent", help="claude, codex, gemini, comma list, or all.")
        return sp

    sp = sub.add_parser("setup", help="Your account or organization, agent CLIs and folders.")
    sp.add_argument("--owner", help="Publish to this account or organization (default: ask / your account).")
    sp.add_argument("--agents", help="Agent CLIs: claude, codex, gemini, comma list or all.")
    for kind in ("agents", "swarms"):
        sp.add_argument(f"--{kind}-dir", help=f"Folder for your {kind} (default ~/{kind}).")
    sp.add_argument("--no-agent-skill", dest="agent_skill", action="store_false",
                    help="Don't install the skylls skill for Claude Code, Codex and Gemini.")

    sub.add_parser("version", help="Show the skylls version.")
    sp = sub.add_parser("update", help="Update skylls itself to the newest version.")
    sp.add_argument("--check", action="store_true", help="Only say whether a newer version exists.")
    sub.add_parser("help", help="Show detailed help and usage examples.")
    sp = sub.add_parser("search", help="Search public skills on skills.sh.")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=15)
    scoped(sub.add_parser("agent-skill", help="Install the skylls skill so agents can use skylls."))
    scoped(sub.add_parser("installed", help="List installed skills."))
    scoped(sub.add_parser("remove", help="Remove an installed skill (never touches GitHub).")).add_argument("name")
    sp = scoped(sub.add_parser("pull", help="Check for new versions (--update installs them)."))
    sp.add_argument("--update", action="store_true")
    sp = sub.add_parser("source", help="Friends whose shared items you see.")
    sp.add_argument("action", nargs="?", choices=["add", "remove"])
    sp.add_argument("owner", nargs="?")
    sp = sub.add_parser("folder", help="Your folders (GitHub topics): list, rename or remove.")
    sp.add_argument("action", nargs="?", choices=["rename", "remove"])
    sp.add_argument("names", nargs="*")

    kinds.add_item_parsers(sub, "skills", scoped)
    for kind in ("agents", "swarms"):
        kp = sub.add_parser(kind, help=f"Share and install {kind} (yours live in ~/{kind}).")
        kinds.add_item_parsers(kp.add_subparsers(dest="kcmd"), kind, scoped)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    global JSON_MODE
    from skylls import kinds
    parser = build_parser()
    args = parser.parse_args(argv)
    JSON_MODE = args.json

    if args.cmd == "version":
        print(f"skylls {__version__}")
        return 0
    if args.cmd == "help":
        show_help()
        return 0
    if args.cmd == "search":
        cmd_search(args.query, args.limit)
        return 0
    if args.cmd == "update":
        cmd_update(args.check, args.dry_run)
        return 0
    if args.cmd == "setup":
        setup(args.agents, args.owner, {k: getattr(args, f"{k}_dir") for k in ("agents", "swarms")},
              args.agent_skill)
        return 0

    cfg = get_config()
    refresh_agent_skill(cfg)
    if args.cmd in ("agents", "swarms"):
        if not args.kcmd:
            kinds.cmd_list(cfg, args.cmd, None, None, None)
        else:
            kinds.run(cfg, args.cmd, args.kcmd, args)
    elif args.cmd in (None, "installed"):
        kinds.cmd_installed(cfg, getattr(args, "agent", None), getattr(args, "is_global", None))
    elif args.cmd == "agent-skill":
        cmd_agent_skill(cfg, args.agent, bool(args.is_global), args.dry_run)
    elif args.cmd == "remove":
        cmd_remove(cfg, args.name, args.agent, bool(args.is_global), args.dry_run)
    elif args.cmd == "pull":
        kinds.cmd_pull(cfg, args.update, args.agent, args.is_global, args.dry_run)
    elif args.cmd == "source":
        kinds.cmd_source(cfg, args.action, args.owner, args.dry_run)
    elif args.cmd == "folder":
        kinds.cmd_folder(cfg, args.action, args.names, args.dry_run)
    elif args.cmd == "add" and args.name.count("/") == 2:
        cmd_add_remote(cfg, args.name, args.agent, bool(args.is_global), args.dry_run, args.yes)
    else:
        kinds.run(cfg, "skills", args.cmd, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
