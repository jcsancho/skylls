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
import time
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
_bar_shown = False  # a progress bar is on the last line of the terminal


def progress(done: int, total: int, label: str = "") -> None:
    """Draw (or redraw in place) a progress bar on stderr; only on a terminal and never with --json."""
    global _bar_shown
    if JSON_MODE or total <= 0 or not sys.stderr.isatty():
        return
    width = 24
    filled = width * min(done, total) // total
    room = shutil.get_terminal_size().columns - width - len(f"{done}/{total}") - 7  # never wrap: \r only clears one line
    label = label if len(label) <= room else label[:max(room - 1, 0)] + "…"
    sys.stderr.write(f"\r\033[K  {CYAN}{'█' * filled}{'░' * (width - filled)}{NC} {done}/{total} {label}")
    sys.stderr.flush()
    _bar_shown = True


def progress_clear() -> None:
    global _bar_shown
    if _bar_shown:
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()
        _bar_shown = False


def progress_done() -> None:
    """Keep the bar's last state on screen (end its line) instead of erasing it."""
    global _bar_shown
    if _bar_shown:
        sys.stderr.write("\n")
        sys.stderr.flush()
        _bar_shown = False


def say(text: str) -> None:
    progress_clear()
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


def gh(*args: str, timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    """Run gh; a call still running after timeout seconds is stopped and fails (returncode 124)."""
    try:
        return subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(["gh", *args], 124, "", f"gh: no answer from GitHub in {timeout:.0f} s")


def gh_api(*args: str, timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    return gh("api", *args, timeout=timeout)


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


# Values in docs and drafts that only show what a key looks like: cut short with an
# ellipsis ("sk-proj-abc…"), xxxx'd out, <your-key> or your_api_key.
PLACEHOLDER = re.compile(r"…|\.\.\.|[xX*]{6,}|<[^>]*>|\byour[_-]?(api[_-]?)?(key|token|secret|password)", re.I)


def is_placeholder(match: str) -> bool:
    """True when a gitleaks match is an example value, not a real secret."""
    return bool(PLACEHOLDER.search(match.replace("REDACTED", "")))


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def expired_jwt(token: str) -> bool:
    """A JWT whose exp claim is in the past (sample tokens quoted in papers and docs)."""
    import base64
    try:
        body = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        return isinstance(claims.get("exp"), (int, float)) and claims["exp"] < time.time()
    except (IndexError, ValueError, TypeError, AttributeError):
        return False


def is_false_positive(finding: dict, lines: List[str]) -> bool:
    """Matches that only look like secrets: digit runs inside decimals (SVG coordinates, timings, constants)
    taken for card or phone numbers, card numbers that fail the Luhn check, expired sample JWTs, and private-key headers
    with no key under them (a paper quoting `openssl` output)."""
    rule, secret = finding.get("RuleID", ""), finding.get("Secret", "")
    start = max(int(finding.get("StartLine") or 1) - 1, 0)
    line = lines[start] if start < len(lines) else ""
    in_number = bool(secret) and re.search(rf"[\d.]{re.escape(secret)}|{re.escape(secret)}\.?\d", line)
    if rule == "credit-card-number":
        return bool(in_number) or not luhn_ok(re.sub(r"\D", "", secret))
    if "phone" in rule:
        return bool(in_number)
    if rule == "jwt":
        return expired_jwt(secret)
    if "private-key" in rule:
        after = "\n".join(lines[start:start + 60]).split(secret, 1)[-1]
        return not re.match(r"[\s\"',\\n]*[A-Za-z0-9+/=]{40,}", after)
    return False


def is_binary(path: Path) -> bool:
    """Videos, images and other binaries: gitleaks reads random bytes in them as emails and keys."""
    try:
        with path.open("rb") as f:
            return b"\0" in f.read(8192)
    except OSError:
        return False


def file_lines(path: Path, cache: dict) -> List[str]:
    if path not in cache:
        try:
            cache[path] = path.read_text(errors="ignore").splitlines()
        except OSError:
            cache[path] = []
    return cache[path]


def redact(secret: str) -> str:
    return (secret[:4] + "…") if len(secret) > 6 else "…"


# ── Local JEV decision model (optional) ────────────────────────────────────
# A local JEV-9B server (Jev-compatible typed decisions, e.g. jev-mlx's `jev-server`) tells real secrets from
# look-alikes. Only ever a server on this machine: findings hold the unredacted values, so they never go to a
# hosted model. SKYLLS_JEV_URL changes the address; SKYLLS_JEV=off turns it off.
JEV_URL = "http://127.0.0.1:8090"
JEV_NOT_REAL = 0.25  # p(real secret) below this: ignored as a false positive (cautious: misses cost more)
JEV_MIN_FREE_GB = 12


def jev_off() -> bool:
    return os.environ.get("SKYLLS_JEV", "").lower() in ("0", "off", "no", "false")


def jev_url() -> Optional[str]:
    if jev_off():
        return None
    url = os.environ.get("SKYLLS_JEV_URL", JEV_URL).rstrip("/")
    host = urllib.parse.urlparse(url).hostname or ""
    return url if host in ("127.0.0.1", "localhost", "::1") else None  # never a hosted model


def jev_up(url: str) -> bool:
    try:
        with urllib.request.urlopen(url + "/health", timeout=2) as r:
            return r.status == 200
    except (OSError, ValueError):
        return False


def free_memory_gb() -> Optional[float]:
    """Free + reclaimable memory on macOS (vm_stat), None elsewhere or when unknown."""
    if not shutil.which("vm_stat"):
        return None
    out = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
    size = re.search(r"page size of (\d+)", out)
    pages = sum(int(n) for k, n in re.findall(r"Pages (free|inactive|speculative|purgeable):\s+(\d+)", out))
    return pages * int(size.group(1)) / 2**30 if size else None


def jev_start(url: str) -> Optional[str]:
    """Start the local JEV server (`jev-server start`) when it is installed and memory allows. Returns the
    script to stop it with afterwards, or None when it couldn't be started."""
    script = shutil.which("jev-server") or str(Path.home() / "bin" / "jev-server")
    if url != JEV_URL or not Path(script).is_file():
        return None
    free = free_memory_gb()
    if free is not None and free < JEV_MIN_FREE_GB:
        info(f"Local JEV model not started: {free:.0f} GB free memory (needs {JEV_MIN_FREE_GB}).")
        return None
    info("Starting the local JEV model to check the findings …")
    try:
        subprocess.run([script, "start"], capture_output=True, text=True, timeout=150)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return script if jev_up(url) else None


def jev_real(url: str, finding: dict, context: str) -> Optional[float]:
    """Probability (0–1) that a gitleaks finding is a real secret or private info, per the local JEV model."""
    state = {"finding": {"rule": finding.get("RuleID", ""), "file": Path(finding.get("File", "")).name,
                         "value": (finding.get("Secret") or finding.get("Match") or "")[:200],
                         "context": context[:800]}}
    question = {"real": {"type": "noul", "instructions":
                         "`finding` is a match from a secret scanner in files about to be published (`context` is the "
                         "lines around it). Is `value` a "
                         "real secret or real private data (a working API key, token, password, private key, or "
                         "a real person's email, phone or card number), rather than a false positive (an example, "
                         "placeholder, test or dummy value, documentation, a hash, an ID, a version, a public or "
                         "generic address, a number or constant in code, random-looking data that is not a credential)?"}}
    body = json.dumps({"state": state, "questions": question}).encode()
    req = urllib.request.Request(url + "/api/alpha/decisions", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return float(json.loads(r.read())["answers"]["real"]["noul"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def jev_context(finding: dict, lines: List[str], width: int = 200) -> str:
    """The lines around a finding for the model. In minified code (lines longer than 300 characters) the
    neighbours are noise and the match drowns in its own line: give `width` characters on each side of it."""
    start = max(int(finding.get("StartLine") or 1) - 1, 0)
    line = lines[start] if start < len(lines) else ""
    if len(line) <= 300:
        return "\n".join(lines[max(start - 3, 0):start + 2])
    value = finding.get("Secret") or finding.get("Match") or ""
    at = line.find(value) if value else -1
    if at < 0:
        at = max(int(finding.get("StartColumn") or 1) - 1, 0)
    return "…" + line[max(at - width, 0):at + len(value) + width] + "…"


JEV_VERDICTS = Path.home() / ".cache" / "skylls" / "jev-verdicts.json"  # hashed finding → JEV's p(real)


def load_jev_verdicts() -> dict:
    try:
        data = json.loads(JEV_VERDICTS.read_text())
        return {k: float(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def save_jev_verdicts(new: dict) -> None:
    if not new:
        return
    try:
        JEV_VERDICTS.parent.mkdir(parents=True, exist_ok=True)
        JEV_VERDICTS.write_text(json.dumps({**load_jev_verdicts(), **new}, indent=0, sort_keys=True) + "\n")
    except OSError:
        pass


def jev_filter(findings: List[dict], cache: dict) -> Tuple[List[dict], List[dict]]:
    """(kept, ignored): findings the local JEV model is confident are false positives are ignored. Without a
    local model (or when it fails) everything is kept. Its answers are remembered by finding (rule + value,
    hashed, in ~/.cache/skylls/jev-verdicts.json), so a finding is asked about once and the model is only
    started for new ones; the cutoff is applied when reading, so changing it applies to old answers too."""
    if jev_off() or not findings:
        return findings, []
    url = jev_url()
    known = load_jev_verdicts()
    probs = {id(f): known.get(finding_key(f)) for f in findings}
    new_ones = [f for f in findings if probs[id(f)] is None]
    if new_ones and url:
        started = None if jev_up(url) else jev_start(url)
        if started or jev_up(url):
            answers = {}
            try:
                for f in new_ones:
                    key = finding_key(f)
                    if key not in answers:
                        p = jev_real(url, f, jev_context(f, file_lines(Path(f.get("File", "")), cache)))
                        if p is not None:
                            answers[key] = round(p, 4)
                    probs[id(f)] = answers.get(key)
            finally:
                if started:
                    subprocess.run([started, "stop"], capture_output=True)
            save_jev_verdicts(answers)
    kept, ignored = [], []
    for f in findings:
        p = probs[id(f)]
        (ignored if p is not None and p < JEV_NOT_REAL else kept).append(f)
    return kept, ignored


ALLOWED_SECRETS = Path.home() / ".config" / "skylls" / "allowed-secrets.json"  # findings you said are fine


def finding_key(f: dict) -> str:
    """Hash of rule + value, so a finding you allowed stays allowed wherever it moves (the value isn't stored)."""
    import hashlib
    return hashlib.sha256(f"{f.get('RuleID', '')}\0{f.get('Secret') or f.get('Match', '')}".encode()).hexdigest()


def load_allowed() -> set:
    try:
        return set(json.loads(ALLOWED_SECRETS.read_text()))
    except (OSError, ValueError, TypeError):
        return set()


def remember_allowed(keys: set) -> None:
    ALLOWED_SECRETS.parent.mkdir(parents=True, exist_ok=True)
    ALLOWED_SECRETS.write_text(json.dumps(sorted(load_allowed() | keys), indent=2) + "\n")


def scan_secrets(folder: Path, ask: bool = False) -> None:
    """Abort unless gitleaks finds no API keys, passwords or private info in folder. With ask (and a
    terminal) the user can say the findings are false positives: they are published and remembered."""
    if not shutil.which("gitleaks"):
        die("gitleaks is required to check for secrets before publishing (brew install gitleaks), "
            "or pass --skip-scan.")
    info("Scanning for API keys, secrets and private info (gitleaks) …")
    with tempfile.TemporaryDirectory() as tmp:
        # Unredacted so false positives can be told apart; the report stays in tmp and only redacted
        # values are printed.
        report = Path(tmp) / "report.json"
        cmd = ["gitleaks", "dir", str(folder), "--no-banner", "--exit-code", "0",
               "--log-level", "error", "--report-format", "json", "--report-path", str(report)]
        cfg = gitleaks_config()
        if cfg:
            cmd += ["--config", str(cfg)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not report.is_file():
            die(f"gitleaks failed: {(result.stderr or result.stdout).strip()}")
        findings = json.loads(report.read_text() or "[]")
    findings = [f for f in findings if not is_binary(Path(f.get("File", "")))]
    examples = [f for f in findings if is_placeholder(f.get("Match", ""))]
    findings = [f for f in findings if f not in examples]
    cache: dict = {}
    lookalikes = [f for f in findings if is_false_positive(f, file_lines(Path(f.get("File", "")), cache))]
    findings = [f for f in findings if f not in lookalikes]
    allowed = load_allowed()
    known = [f for f in findings if finding_key(f) in allowed]
    findings = [f for f in findings if f not in known]
    findings, judged = jev_filter(findings, cache)
    if examples:
        info(f"Ignored {len(examples)} example value(s) like \"sk-abc…\" (cut short or placeholders).")
    if lookalikes:
        info(f"Ignored {len(lookalikes)} look-alike(s): decimals or non-Luhn digits taken for card or phone numbers, "
             "expired sample JWTs, private-key headers with no key.")
    if known:
        info(f"Ignored {len(known)} you said are fine before (~/.config/skylls/allowed-secrets.json).")
    if judged:
        info(f"Ignored {len(judged)} the local JEV model judged false positives "
             f"({', '.join(sorted({f.get('RuleID', '?') for f in judged}))}).")
    if not findings:
        ok("No secrets or private info found.")
        return
    fail(f"Found {len(findings)} possible secret(s) or private info:")
    for f in findings:
        path = Path(f.get("File", "?"))
        rel = path.relative_to(folder) if path.is_relative_to(folder) else path
        say(f"    {RED}•{NC} {rel}:{f.get('StartLine', '?')}  {YELLOW}{f.get('RuleID', '?')}{NC}  "
            f"{redact(f.get('Secret') or '')}")
    if ask and not JSON_MODE and sys.stdin.isatty():
        answer = input(f"  {YELLOW}?{NC} Are these false positives? Publish anyway and don't ask about them "
                       "again? (y/N): ").strip().lower()
        if answer in ("y", "yes"):
            remember_allowed({finding_key(f) for f in findings})
            ok(f"Publishing; remembered as fine in ~/.config/skylls/allowed-secrets.json.")
            return
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


def locate_installed(cfg: dict, name: str, agent: Optional[str], is_global: Optional[bool]) -> Optional[Path]:
    """A skill to publish: a folder path, or an installed copy (project first, then global); None if neither."""
    if Path(name).expanduser().is_dir():
        return Path(name).expanduser().resolve()
    scopes = [is_global] if is_global is not None else [False, True]
    for scope in scopes:
        for dest_root in target_dirs(cfg, agent or ",".join(AGENT_DIRS), scope):
            if (dest_root / name / "SKILL.md").is_file():
                return dest_root / name
    return None


def find_installed(cfg: dict, name: str, agent: Optional[str], is_global: Optional[bool]) -> Path:
    return (locate_installed(cfg, name, agent, is_global)
            or die(f"Skill '{name}' not found in any project or global skills folder."))


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
NPM_PACKAGE = "@skylls/cli"
OLD_NPM_PACKAGE = "@jcsancho/skylls"  # the name before 1.4.0; `skylls update` moves npm installs off it


def old_npm_install() -> bool:
    """True when this skylls came from the old npm package name."""
    parts = Path(__file__).resolve().parts
    return "node_modules" in parts and "@jcsancho" in parts


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
        for package in (NPM_PACKAGE, OLD_NPM_PACKAGE):
            res = subprocess.run(["npm", "view", package, "version"], capture_output=True, text=True)
            if res.stdout.strip():
                return res.stdout.strip()
        return None
    res = git("ls-remote", "--tags", "--refs", repo_url(SKYLLS_REPO), check=False)
    tags = re.findall(r"refs/tags/v(\d+\.\d+\.\d+)$", res.stdout, re.M)
    return max(tags, key=version_key) if tags else None


def cmd_update(check: bool, dry_run: bool) -> None:
    """Install the newest skylls the same way this one was installed (uv, pipx or npm)."""
    kind = install_kind()
    latest = latest_version(kind)
    if not latest:
        die("Could not find the newest skylls version (no network, or GitHub/npm unreachable).")
    moving = kind == "npm" and old_npm_install()
    newer = version_key(latest) > version_key(__version__) or moving
    if JSON_MODE and (check or not newer):
        emit({"version": __version__, "latest": latest, "newer": newer, "installed_with": kind})
    if not newer:
        ok(f"skylls {__version__} is the newest version.")
        return
    if moving:
        info(f"skylls moved on npm from {OLD_NPM_PACKAGE} to {NPM_PACKAGE}.")
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
    # Both npm packages own the `skylls` command, so the old one goes first.
    uninstall = ["npm", "uninstall", "-g", OLD_NPM_PACKAGE] if moving else None
    if dry_run:
        if uninstall:
            info(f"[dry-run] Would run: {' '.join(uninstall)}")
        info(f"[dry-run] Would run: {' '.join(cmd)}")
        return
    section(f"Updating skylls {__version__} → {latest}")
    if uninstall:
        subprocess.run(uninstall, capture_output=True, text=True)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 and uninstall:
        subprocess.run(["npm", "install", "-g", f"{OLD_NPM_PACKAGE}@{__version__}"], capture_output=True, text=True)
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
  {GREEN}list{NC} [words] [--from O] [-f F]     Yours and your friends' (grouped by folder)
       filters (list, find): --mine --shared --installed --created D --since D --created-before D
       --updated D --updated-after D --updated-before D --sort name|created|updated -n N --fresh
       (D: 2026-11-19, 2026-11, today, 7d, 2w, 3m)
  {GREEN}find{NC} <words> [--from O] [-f F]     Search: summary, version, owner, folder
  {GREEN}add{NC} <name[@ver]> [--from O]        Install (skills: [-g] [-a A]; agents: [--as N])
  {GREEN}log{NC} <name> [--from O]              Who made it, versions, what changed
  {GREEN}installed{NC} [-g] [-a A]              Installed skills (and newer versions)
  {GREEN}pull{NC} [--update]                    Check for new versions (--update: install them)
  {GREEN}sync{NC} [-m msg]                      Publish your changes + get friends' new versions and shares
  {GREEN}view{NC}                               What sync would do, and what's on GitHub but not here
  {GREEN}remove{NC} <name>                      Remove from this computer (agents/swarms: to the Trash)
  {GREEN}search{NC} <query>                     Public skills on skills.sh (add owner/repo/skill)

{CYAN}PUBLISH & SHARE:{NC}
  {GREEN}push{NC} <name> [-m msg]               Publish a new version to its private repo
  {GREEN}share{NC} <name> @user… | --all @user  Let friends install it (no users: who has access)
  {GREEN}unshare{NC} <name> @user…              Revoke access to one item
  {GREEN}revoke{NC} @user… [-y]                 Take back everything you shared with them
  {GREEN}shared{NC} [@user…]                    What you shared (with whom) and what's shared with you
  {GREEN}people{NC}                             Who you share with / who shares with you, and what
  {GREEN}move{NC} <name> <folder>               Put it in a folder (a GitHub topic; '.' = none)
  {GREEN}folder{NC} [rename|remove]             Your folders
  {GREEN}source{NC} [add|remove] <login>        Friends whose shares you see (accepts their invites)

{CYAN}SUGGESTIONS:{NC}
  {GREEN}suggest{NC} <name> --from O "text"     Suggest an improvement (GitHub issue to the owner)
  {GREEN}suggestions{NC} [name]                 Open suggestions for yours
  {GREEN}review{NC} <name>#<n>                   Read one; a pull request shows its changes
  {GREEN}accept{NC} / {GREEN}decline{NC} <name>#<n> [-m note]  Answer one (accepting a pull request merges + publishes it)

{CYAN}PULL REQUESTS (agents/swarms):{NC}
  {GREEN}agents|swarms propose{NC} <name> --from O -m "what"  Send your changes to a friend's copy as a pull request
  {GREEN}agents|swarms allow-prs{NC} <name> | --all   Let the people you share with send pull requests (--off)

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
  {YELLOW}--keep-memory{NC}       Agents/swarms add, sync: keep your copy of the memory (updates refresh it
                      by default); the owner's latest goes next to it, e.g. alice-btc-wiki/
  {YELLOW}-y, --yes{NC}           Agents/swarms push: publish new memory notes without asking (sync never asks)
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
    sp = sub.add_parser("sync", help="Publish your changes, then install newer versions and new shares from friends.")
    sp.add_argument("-m", "--message", help="What changed (logged with each new version; asked if omitted).")
    sp.add_argument("--skip-scan", action="store_true", help="Publish without the secret scan.")
    sp.add_argument("-y", "--yes", action="store_true", help="Publish new memory notes without asking.")
    sp.add_argument("--keep-memory", action="store_true",
                    help="Keep your copies of agents'/swarms' memory; the owners' latest go next to them.")
    sub.add_parser("view", help="What sync would publish and install, and what isn't on this computer (changes nothing).")
    sp = sub.add_parser("revoke", help="Take back everything you shared with these users.")
    sp.add_argument("users", nargs="+", metavar="@user")
    sp.add_argument("-y", "--yes", action="store_true", help="Don't ask first.")
    sub.add_parser("people", help="Who you share with and who shares with you (and what).")
    sp = sub.add_parser("shared", help="What you shared (and with whom) and what friends shared with you.")
    sp.add_argument("users", nargs="*", metavar="@user", help="Only what you share with / get from these users.")
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
    # --json and --dry-run are global but may be written anywhere (`skylls find pdf --json`):
    # move them in front of the command, where argparse expects them.
    argv = list(sys.argv[1:] if argv is None else argv)
    end = argv.index("--") if "--" in argv else len(argv)
    flags = [a for a in argv[:end] if a in ("--json", "--dry-run")]
    argv = flags + [a for a in argv[:end] if a not in flags] + argv[end:]
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
    elif args.cmd == "sync":
        kinds.cmd_sync(cfg, args.message, args.skip_scan, args.dry_run, args.yes, args.keep_memory)
    elif args.cmd == "view":
        kinds.cmd_view(cfg)
    elif args.cmd == "revoke":
        kinds.cmd_revoke(cfg, args.users, args.yes, args.dry_run)
    elif args.cmd == "people":
        kinds.cmd_people(cfg)
    elif args.cmd == "shared":
        kinds.cmd_shared(cfg, args.users)
    elif args.cmd == "folder":
        kinds.cmd_folder(cfg, args.action, args.names, args.dry_run)
    elif args.cmd == "add" and args.name.count("/") == 2:
        cmd_add_remote(cfg, args.name, args.agent, bool(args.is_global), args.dry_run, args.yes)
    else:
        kinds.run(cfg, "skills", args.cmd, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
