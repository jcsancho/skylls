#!/bin/bash
# End-to-end test in a sandbox: fake HOMEs, a fake GitHub (tests/fakegh.py, bare repos in $T/gh),
# users alice (account), bob (friend), carol (organization carolco). Never touches real GitHub.

D=$(cd "$(dirname "$0")" && pwd); T=$(mktemp -d); mkdir -p $T/fake $T/gh
export GHROOT=$T/gh PYTHONPATH=$(dirname "$D")
PYV=$(python3 -c "import skylls; print(skylls.__version__)")
NPMV=$(python3 -c "import json; print(json.load(open('$(dirname "$D")/package.json'))['version'])")
[ "$PYV" = "$NPMV" ] && echo "versions match: $PYV" || { echo "VERSION MISMATCH: __version__ $PYV, package.json $NPMV"; exit 1; }
printf '#!/bin/bash\nexec python3 %s "$@"\n' "$D/fakegh.py" > $T/fake/gh
printf '#!/bin/bash\ncat >/dev/null; echo "Does useful things."\n' > $T/fake/claude
chmod +x $T/fake/gh $T/fake/claude; export PATH=$T/fake:$PATH
echo '{"repos": {}, "invites": [], "next": 1, "orgs": {"carolco": {"admins": ["carol"]}}}' > $GHROOT/state.json
s() { python3 -m skylls "$@" 2>&1 | sed -e 's/\x1b\[[0-9;]*m//g' -e "s#$T#\$T#g" | grep -v "^$"; }
sj() { python3 -m skylls --json "$@" 2>/dev/null; }
user() { export HOME=$T/home/$1 GH_LOGIN=$1; mkdir -p $HOME/.Trash; cd $HOME
  git config --global user.name "$1"; git config --global user.email "$1@x"
  git config --global url."file://$T/gh/".insteadOf "https://github.com/"; }
mkskill() { mkdir -p $HOME/.claude/skills/$1; printf -- "---\nname: $1\ndescription: $2\n---\n$3\n" > $HOME/.claude/skills/$1/SKILL.md; }

echo "######## ALICE (personal account, no organization: shown how to create one)"; user alice
s setup --agents all --no-agent-skill | grep -E "GitHub|organization yet|Open https|Using your account|published to"
mkskill pdf "Fill PDF forms" "Fills forms."; mkskill notes "Private notes" "Mine only."
echo "--- push pdf (new repo, folder docs)"; s push pdf -m first --folder docs --skip-scan | grep -E "Created|Published|folder"
echo "--- push again unchanged"; s push pdf --skip-scan | tail -1
echo "Also scans." >> $HOME/.claude/skills/pdf/SKILL.md; s push pdf -m "Scans" --minor --skip-scan | grep Published
s push notes -m first --skip-scan | grep Published
echo "--- agent btc with wiki memory + runtime"
A=$HOME/agents/btc; mkdir -p $A/wiki/.obsidian $A/logs $A/scripts; echo "# btc agent that tracks bitcoin" > $A/CLAUDE.md
echo page > $A/wiki/index.md; echo '{}' > $A/wiki/.obsidian/workspace.json; echo log > $A/logs/a.log; echo x > $A/scripts/run.py
s agents push btc -m first --skip-scan | grep -E "Memory|Published"
echo "  repo content:"; git --git-dir $GHROOT/alice/skylls-agent-btc.git ls-tree -r --name-only HEAD | paste -sd' ' -
W=$HOME/swarms/apps; mkdir -p $W/.swarm $W/scout; echo "# apps swarm finds app ideas" > $W/CLAUDE.md; echo '{}' > $W/.swarm/agents.json
echo "# scout" > $W/scout/CLAUDE.md; echo work > $W/scout/work.py; echo '{}' > $W/.swarm/bus.jsonl
s swarms push apps -m first --skip-scan | grep Published
echo "  repo content:"; git --git-dir $GHROOT/alice/skylls-swarm-apps.git ls-tree -r --name-only HEAD | paste -sd' ' -
echo "  tags pdf:"; git --git-dir $GHROOT/alice/skylls-skill-pdf.git tag | paste -sd' ' -
echo "  private/topics:"; python3 -c "import json;s=json.load(open('$GHROOT/state.json'));[print(' ',k,v['private'],v['topics']) for k,v in s['repos'].items()]"
echo "--- list / folder / find --json / log --json"
s list; s folder | head -4; sj find pdf; sj log pdf | head -c 300; echo
mkdir -p $HOME/agents/draft; echo "# draft agent not published yet" > $HOME/agents/draft/CLAUDE.md; s agents list
echo "--- share pdf + btc with bob (not notes)"
s share pdf @bob | grep -E "Invited|add you"; s agents share btc @bob | grep Invited

echo "######## BOB"; user bob
s setup --agents claude --no-agent-skill >/dev/null
echo "--- list before adding alice"; s list | grep -E "shared|No skills"
echo "--- source add alice"; s source add alice | grep -E "Accepted|Added"
s list; s agents list
echo "--- notes is not visible"; s add notes --from alice | tail -1
echo "--- install"; s add pdf --from alice -g -a all | grep -E "Installed|Linked"
s agents add btc --from alice | grep -E "Installed"; (cd $HOME/agents/btc && find . -type f | sort | paste -sd' ' -)
sj installed

echo "######## ALICE 1.2.0, BOB updates"; user alice
echo "v3" >> $HOME/.claude/skills/pdf/SKILL.md; s push pdf -m "v3" --skip-scan | grep Published
user bob
sj installed | grep pdf; s pull --update | grep -E "→|Installed"; sj installed | grep pdf
s add pdf@1.0.0 --from alice -y | grep Installed; grep -m1 "^## " $HOME/.claude/skills/pdf/CHANGELOG.md
echo "--- bob suggests"; s suggest pdf --from alice "Support Excel" | grep Sent
echo "--- bob can't share/accept alice's"; s share pdf @eve | tail -1

echo "######## ALICE answers, unshares"; user alice
s suggestions | grep -E "pdf#"; sj suggestions; s accept pdf#1 -m "Done in 1.3" | tail -1; s suggestions | tail -1
s move pdf work | tail -1; s folder rename work office | tail -1; sj list | grep -o '"folder":"[a-z]*"'
s unshare pdf @bob | grep Revoked
user bob; echo "--- bob after unshare"; s list | grep -E "pdf|btc|•"

echo "######## CAROL (organization carolco: chosen by default, base permission checked, short names)"; user carol
s setup --agents claude --no-agent-skill | grep -E "published to|base permission|Fix it"
gh api -X PATCH orgs/carolco -f default_repository_permission=none >/dev/null
s setup --agents claude --no-agent-skill | grep -E "base permission" || echo "  (no warning once the base permission is none)"
mkskill tax "Tax helper" "Taxes."; s push tax -m first --skip-scan | grep -E "Created|Published"
gh repo create carolco/agent-foo --private >/dev/null   # an unrelated repo with a skylls-like name, no 'skylls' topic
mkdir -p $HOME/agents/bar; echo "# bar agent does bar things" > $HOME/agents/bar/CLAUDE.md
s agents push bar -m first --skip-scan | grep Published
echo "--- carol's agents (foo must not appear)"; s agents list | grep -E "•"
s share tax @bob | grep -E "Invited|add you"
user bob; s source add carolco | grep Added; sj find tax
python3 -c "import json;s=json.load(open('$GHROOT/state.json'));print('  bob on carolco/skill-tax:', s['repos']['carolco/skill-tax']['collabs'])"

echo "######## remove agent, old config migration"; user bob
s agents remove btc -y | tail -1
mkdir -p $T/home/dave/.config/skylls; echo '{"repo": "dave/skills", "agents": ["codex"], "kinds": {}}' > $T/home/dave/.config/skylls/config.json
user dave; s list | grep -E "quick setup|published to" | head -2; python3 -c "import json;print('  migrated:', json.load(open('$HOME/.config/skylls/config.json')))"
echo "--- all --json lines valid"; for c in "list" "find pdf" "installed" "agents list" "suggestions"; do user alice; sj $c | python3 -c "import sys,json;[json.loads(l) for l in sys.stdin if l.strip()];print('  ok:', '$c')"; done

echo "######## update skylls itself (newest = highest tag of jcsancho/skylls)"; user alice
git init --quiet --bare $GHROOT/jcsancho/skylls.git; R=$T/skylls-src; git init --quiet $R
git -C $R commit --quiet --allow-empty -m x; git -C $R tag v1.0.0; git -C $R tag v99.0.0; git -C $R push --quiet --tags $GHROOT/jcsancho/skylls.git
s update --check | grep -E "available|Install it"; sj update --check
s --dry-run update | tail -1   # from a checkout (PYTHONPATH): it can't replace itself
git --git-dir $GHROOT/jcsancho/skylls.git tag -d v99.0.0 >/dev/null; s update | tail -1
