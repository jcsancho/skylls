#!/usr/bin/env bash
# Install skylls: share agent skills, agents and swarms through your own private GitHub repos.
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/jcsancho/skylls/main/install.sh)"
#
# Options:
#   -y, --yes       install missing tools and answer yes to every question
#                   (no keyboard: setup uses its defaults: your organization if you have one, claude)
#   --no-setup      only install; run `skylls setup` yourself later
#   --ref REF       install a specific version tag or branch (e.g. v0.3.0)
# Environment:
#   SKYLLS_SOURCE   where to install skylls from (default: git+https://github.com/jcsancho/skylls)
set -euo pipefail

SOURCE="${SKYLLS_SOURCE:-git+https://github.com/jcsancho/skylls}"
YES=0
SETUP=1
REF=""
while [ $# -gt 0 ]; do
  case "$1" in
    -y|--yes) YES=1 ;;
    --no-setup) SETUP=0 ;;
    --ref) REF="${2:?--ref needs a tag or branch}"; shift ;;
    -h|--help)
      echo "Install skylls. Options: -y/--yes (no questions), --no-setup, --ref <tag|branch>."
      echo "Env: SKYLLS_SOURCE=<where to install from> (default git+https://github.com/jcsancho/skylls)"
      exit 0 ;;
    *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done
[ -n "$REF" ] && SOURCE="$SOURCE@$REF"

say()  { printf '\033[%sm%s\033[0m\n' "$1" "$2"; }
step() { say "0;36" "▸ $1"; }
ok()   { say "0;32" "  ✓ $1"; }
warn() { say "0;33" "  ! $1"; }
fail() { say "0;31" "  ✗ $1"; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
has_tty() { [ -r /dev/tty ] && [ -w /dev/tty ] && (exec </dev/tty) 2>/dev/null; }

ask() {  # ask "question" → yes (0) / no (1); default yes
  [ "$YES" = 1 ] && return 0
  has_tty || return 1
  printf '  ? %s (Y/n): ' "$1" > /dev/tty
  local answer
  read -r answer < /dev/tty || return 1
  case "$answer" in n|N|no|No|NO) return 1 ;; *) return 0 ;; esac
}

brew_install() {  # brew_install <formula> <what it is for>
  if have brew && ask "Install $1 with Homebrew ($2)?"; then
    brew install "$1" && ok "$1 installed" && return 0
  fi
  return 1
}

echo
say "0;36" "skylls installer"
echo "  Your skills, agents and swarms stay in your own PRIVATE GitHub repos."
echo

step "Checking the tools skylls needs"
have git && ok "git" || brew_install git "required" || fail "Install git first: https://git-scm.com/downloads"

if have uv; then
  ok "uv"
elif brew_install uv "installs skylls"; then
  :
elif ask "Install uv with its official installer (astral.sh)?"; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  have uv && ok "uv installed"
fi
INSTALLER=""
if have uv; then
  INSTALLER=uv
elif have pipx; then
  INSTALLER=pipx
  warn "uv not found; using pipx (needs Python 3.11+)."
else
  fail "Install uv (https://docs.astral.sh/uv/) or pipx, then run this again."
fi

have gh && ok "gh (GitHub CLI)" || brew_install gh "creates your private repos and handles sharing" \
  || warn "The GitHub CLI is needed to create your repos and share them: https://cli.github.com"
have gitleaks && ok "gitleaks" || brew_install gitleaks "checks for secrets before every upload" \
  || warn "Without gitleaks, uploads (push) are refused: https://github.com/gitleaks/gitleaks"
have claude && ok "claude (optional: writes the plain summaries)" \
  || warn "Optional: the claude CLI writes plain one-line summaries of what you publish."

step "Installing skylls"
if [ "$INSTALLER" = uv ]; then
  uv tool install --force --quiet "$SOURCE" || fail "Could not install from $SOURCE.
    If the repo is private, use SSH: SKYLLS_SOURCE=git+ssh://git@github.com/jcsancho/skylls"  # gitleaks:allow (SSH host, not an email)
  BIN="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"
else
  pipx install --force "$SOURCE" || fail "Could not install from $SOURCE."
  BIN="$HOME/.local/bin"
fi
if ! have skylls; then
  # Update the shell files first: uv skips them if $BIN is already on this process's PATH.
  if [ "$INSTALLER" = uv ] && ask "Add $BIN to your PATH for new terminals (uv tool update-shell)?" \
      && uv tool update-shell; then
    ok "PATH updated (open a new terminal to use skylls everywhere)"
  else
    warn "Add $BIN to your PATH to run skylls from any terminal."
  fi
  export PATH="$BIN:$PATH"
fi
have skylls || fail "skylls was installed into $BIN but can't be run."
ok "$(skylls --version) installed"

if have gh && ! gh auth status >/dev/null 2>&1; then
  step "GitHub login"
  if has_tty && ask "Log in to GitHub now (gh auth login)?"; then
    gh auth login < /dev/tty
  else
    warn "Log in later with: gh auth login"
  fi
fi

CONFIG="$HOME/.config/skylls/config.json"
if [ "$SETUP" = 1 ]; then
  step "Setting up skylls"
  if [ -f "$CONFIG" ] && grep -q '"owner"' "$CONFIG"; then
    ok "Already set up ($CONFIG). Run 'skylls setup' to change it."
    # setup's last step installs the skylls skill; offer it if it's missing (e.g. skipped before)
    if [ ! -f "$HOME/.claude/skills/skylls/SKILL.md" ] \
        && ask "Install the skylls skill globally for Claude Code, Codex and Gemini?"; then
      skylls agent-skill -g -a all
    fi
  elif has_tty; then
    skylls setup < /dev/tty      # its last step asks to install the skylls skill globally
  elif [ "$YES" = 1 ]; then
    skylls setup --agents claude
  else
    warn "Run 'skylls setup' in a terminal to finish (your account or organization, agent CLIs, folders)."
  fi
fi

echo
say "0;32" "Done. Next:"
echo "  skylls help                          every command"
echo "  skylls push <skill>                  publish one of your skills (its own private repo)"
echo "  skylls share <skill> @friend         let a friend install it"
echo "  skylls source add <friend>           see what a friend shared with you"
echo "  uv tool upgrade skylls               get new versions (skylls --version to check)"
