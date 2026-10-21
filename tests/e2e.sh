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
mkdir -p $A/wiki/.obsidian/plugins/style $A/.claude/skills/own; echo js > $A/wiki/.obsidian/plugins/style/main.js
cp -R $HOME/.claude/skills/pdf $A/.claude/skills/pdf; echo "# own" > $A/.claude/skills/own/SKILL.md  # pdf: a reference
printf -- "---\nprivate: true\n---\nclient X owes us\n" > $A/wiki/clients.md  # private note: stays home
s agents push btc -m first --skip-scan | grep -E "Memory|Published|reference|wiki/|private"
git --git-dir $GHROOT/alice/skylls-agent-btc.git ls-tree -r --name-only HEAD | grep -q clients.md && echo "  FAIL: private note published" || echo "  ok: private note kept home"
echo "decision" > $A/wiki/log.md; s agents push btc -m "log" --skip-scan --dry-run | grep -E "new or changed|wiki/"
echo "  repo content:"; git --git-dir $GHROOT/alice/skylls-agent-btc.git ls-tree -r --name-only HEAD | paste -sd' ' -
W=$HOME/swarms/apps; mkdir -p $W/.swarm $W/scout; echo "# apps swarm finds app ideas" > $W/CLAUDE.md; echo '{}' > $W/.swarm/agents.json
echo "# scout" > $W/scout/CLAUDE.md; echo work > $W/scout/work.py; echo '{}' > $W/.swarm/bus.jsonl
# scripts the instructions run are shared with them (check.py by full path, tally.sh relative to its role)
echo 'Done when `python3 ~/swarms/apps/check.py 1` prints ALL PASS.' >> $W/CLAUDE.md; echo 'print("ALL PASS")' > $W/check.py
echo 'Count with `bash tally.sh`.' >> $W/scout/CLAUDE.md; echo 'echo 3' > $W/scout/tally.sh
s swarms push apps -m first --skip-scan | grep Published
echo "  repo content:"; git --git-dir $GHROOT/alice/skylls-swarm-apps.git ls-tree -r --name-only HEAD | paste -sd' ' -
C=$(git --git-dir $GHROOT/alice/skylls-swarm-apps.git ls-tree -r --name-only HEAD)
case "$C" in *check.py*scout/tally.sh*) case "$C" in *work.py*) echo "  FAIL: unreferenced work.py shared";; *) echo "  ok: referenced scripts shared, work.py not";; esac;;
  *) echo "  FAIL: check.py / scout/tally.sh missing from the swarm repo";; esac
echo "  tags pdf:"; git --git-dir $GHROOT/alice/skylls-skill-pdf.git tag | paste -sd' ' -
echo "  private/topics:"; python3 -c "import json;s=json.load(open('$GHROOT/state.json'));[print(' ',k,v['private'],v['topics']) for k,v in s['repos'].items()]"
echo "--- list / folder / find --json / log --json"
s list; s folder | head -4; sj find pdf; sj log pdf | head -c 300; echo
mkdir -p $HOME/agents/draft; echo "# draft agent not published yet" > $HOME/agents/draft/CLAUDE.md; s agents list
echo "--- share pdf + btc with bob (not notes)"
s share pdf @bob | grep -E "Invited|add you"; s agents share btc @bob | grep Invited
echo "--- alice: shared (bob hasn't accepted yet)"; s shared

echo "######## BOB"; user bob
s setup --agents claude --no-agent-skill >/dev/null
echo "--- list before adding alice"; s list | grep -E "shared|No skills"
echo "--- bob: shared before adding alice (waiting for him)"; s shared | grep -A3 Waiting; sj shared; s people
echo "--- source add alice"; s source add alice | grep -E "Accepted|Added"
echo "--- bob: shared after"; s shared; s shared @carol | grep -E "Nothing"
user alice; echo "--- alice: shared @bob after he accepted"; s shared @bob | grep "→"; sj shared | head -2; s people; user bob
s list; s agents list
echo "--- notes is not visible"; s add notes --from alice | tail -1
echo "--- install"; s add pdf --from alice -g -a all | grep -E "Installed|Linked"
s agents add btc --from alice | grep -E "Installed|Skill pdf"; (cd $HOME/agents/btc && find . -type f | sort | paste -sd' ' -)
sj installed

echo "######## ALICE 1.2.0, BOB updates"; user alice
echo "v3" >> $HOME/.claude/skills/pdf/SKILL.md; s push pdf -m "v3" --skip-scan | grep Published
user bob
sj installed | grep pdf; s pull --update | grep -E "→|Installed"; sj installed | grep pdf
s add pdf@1.0.0 --from alice -y | grep Installed; grep -m1 "^## " $HOME/.claude/skills/pdf/CHANGELOG.md
echo "--- sync: alice publishes her changes, bob gets them"; user alice
echo "Syncs." >> $HOME/.claude/skills/pdf/SKILL.md; echo "more" >> $HOME/agents/btc/CLAUDE.md
echo "--- view lists what sync would do and changes nothing"
s view | grep -E "^  •|^      [+~-] |Unchanged|Nothing was"; sj view | head -c 60; echo
s sync -m "Synced" --skip-scan | grep -E "Published|up to date|Sync done"
user bob; s view | grep -E "^  •|Nothing:|Install one"
s sync | grep -E "→|Updated from|Published:"; sj installed | grep pdf
grep -m1 "^## " $HOME/agents/btc/CHANGELOG.md; s sync | grep "Updated from"
echo "--- updates refresh bob's copy of the memory; --keep-memory keeps his and puts alice's next to it"; user alice
echo "page v2" > $HOME/agents/btc/wiki/index.md; s agents push btc -m "wiki v2" --skip-scan -y | grep Published
user bob; echo "bob's" > $HOME/agents/btc/wiki/index.md; echo mine > $HOME/agents/btc/wiki/bob.md
s sync | grep -E "Kept|Updated from"; cat $HOME/agents/btc/wiki/index.md $HOME/agents/btc/wiki/bob.md
user alice; echo "page v3" > $HOME/agents/btc/wiki/index.md; s agents push btc -m "wiki v3" --skip-scan -y | grep Published
user bob; echo "bob's" > $HOME/agents/btc/wiki/index.md; s sync --keep-memory | grep -E "Kept|Updated from"
cat $HOME/agents/btc/wiki/index.md $HOME/agents/btc/alice-wiki/index.md
echo "--- sync without -m never asks: the log lists the changed files"; user alice
echo "Quiet." >> $HOME/.claude/skills/pdf/SKILL.md
s sync --skip-scan | grep -c "not found" || true; grep -m1 -A2 "^## " $HOME/.claude/skills/pdf/CHANGELOG.md | tail -1
echo "--- sync with nothing changed skips every item (no scan, no fetch, nothing read from GitHub)"
n=$(wc -l < $T/gh/log); s sync | grep -E "Unchanged|Scanning|Published:"
echo "items read from GitHub: $(tail -n +$((n + 1)) $T/gh/log | grep -c "query { r0" || true)"
echo "her repos listed on GitHub (only what friends shared is): $(tail -n +$((n + 1)) $T/gh/log | grep -c "affiliations: \[OWNER" || true)"
echo "--- an item pushed to a fresh folder stays known to sync without listing her repos"
mkskill fresh "Fresh skill" "New."; s push fresh -m first --folder tools --skip-scan | grep -E "Created|folder"
n=$(wc -l < $T/gh/log); s sync | grep -E "Unchanged"; python3 -c "import json; print(sorted(json.load(open('$HOME/.cache/skylls/mine.json'))['repos']))"
echo "her repos listed on GitHub: $(tail -n +$((n + 1)) $T/gh/log | grep -c "affiliations: \[OWNER" || true)"
echo "--- a skill linked to a folder another installer keeps elsewhere still syncs"
mkdir -p $HOME/elsewhere; mv $HOME/.claude/skills/pdf $HOME/elsewhere/pdf; ln -s $HOME/elsewhere/pdf $HOME/.claude/skills/pdf
echo "Linked." >> $HOME/elsewhere/pdf/SKILL.md; s view | grep -E "skill pdf"
s sync -m "Linked" --skip-scan | grep -E "Published:"; unlink $HOME/.claude/skills/pdf; mv $HOME/elsewhere/pdf $HOME/.claude/skills/pdf
echo "--- bob has write access and pushes to alice's pdf: her sync brings it into her untouched copy"; user bob
git clone -q https://github.com/alice/skylls-skill-pdf.git $HOME/w-pdf; cd $HOME/w-pdf; echo "Bob's tip." >> SKILL.md
echo extra > EXTRA.md; git add -A; git commit -qm "bob's tip"; git push -q; cd $HOME
user alice; s view | grep -E "someone else|by bob|^      [+~-] "; s sync | grep -E "took|Taken|Published:"
tail -1 $HOME/.claude/skills/pdf/SKILL.md; ls $HOME/.claude/skills/pdf; s sync | grep -E "took|Unchanged"
echo "--- both change SKILL.md: not synced, she is told how to keep hers"; user bob
cd $HOME/w-pdf; git pull -q; echo "Bob again." >> SKILL.md; git commit -qam again; git push -q; cd $HOME
user alice; echo "Alice too." >> $HOME/.claude/skills/pdf/SKILL.md; s sync | grep -E "changed it on GitHub|Not synced"
s push pdf -m "kept mine" --skip-scan | grep Published; s sync | grep -E "took|Unchanged"
echo "--- they change different files: sync takes his, then publishes hers"; user bob
cd $HOME/w-pdf; git pull -q --rebase; echo notes > BOB.md; git add -A; git commit -qm notes; git push -q; cd $HOME
user alice; echo "Alice again." >> $HOME/.claude/skills/pdf/SKILL.md; s sync -m mine --skip-scan | grep -E "took|Published:"
ls $HOME/.claude/skills/pdf; s sync | grep -E "took|Unchanged"
echo "--- revoke: alice takes back everything from bob, then shares again"; user alice
s revoke @bob --dry-run | grep -E "•|Would"; s revoke @bob -y | grep -E "Revoked"; s revoke @bob | tail -1
s share pdf @bob >/dev/null; s agents share btc @bob | grep Invited; user bob; s list >/dev/null
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
echo "--- alice follows carol the person: carol's organization comes along"; user carol; s share tax @alice | grep -E "Invited"
user alice; s source add carol | grep Added; s list | grep -E "carolco|tax"
python3 -c "import json;print('  alice friends:', json.load(open('$HOME/.config/skylls/config.json'))['friends'])"

echo "######## PULL REQUESTS: bob proposes a change to alice's swarm, alice reviews and accepts"; user alice
s swarms share apps @bob | grep -E "Invited|Pull requests from them are off"
user bob; s list >/dev/null; s swarms add apps --from alice | grep Installed
echo "Also count reviews: $HOME/swarms/apps/check.py" >> $HOME/swarms/apps/scout/CLAUDE.md
echo "--- forks are off until alice allows them"; s swarms propose apps --from alice -m "Count reviews" --skip-scan | grep -E "allow-prs apps"
user alice; s swarms allow-prs apps | grep -E "are on"
user bob; s swarms propose apps --from alice -m "Count reviews" --skip-scan | grep -E "changed vs|scout/CLAUDE.md|Forked|Pull request"
s swarms propose apps --from alice -m "Count reviews" --skip-scan --dry-run | grep -E "Would fork"
user alice; s swarms suggestions | grep -E "apps#"; sj swarms suggestions | grep -o '"type":"[a-z ]*"'
s swarms review apps#1 | grep -E "^\+Also count"
echo "mine" >> $HOME/swarms/apps/scout/CLAUDE.md
echo "--- alice changed the same file: accept stops"; s swarms accept apps#1 | grep -E "You changed|scout/CLAUDE.md" | head -2
s swarms accept apps#1 --force | grep -E "Applied|Published|Closed"
grep -c "home/alice/swarms/apps/check.py" $HOME/swarms/apps/scout/CLAUDE.md | sed 's/^/  paths put back to alice: /'
s swarms suggestions | tail -1
echo "--- share asks about pull requests: --no-prs turns them off, --prs on"
s swarms share apps @bob --no-prs | grep -E "are off"; s swarms share apps @bob --prs | grep -E "are on"
user bob; s swarms add apps --from alice -y | grep Installed; grep -m1 -A1 "^## " $HOME/swarms/apps/CHANGELOG.md
grep -c "home/bob/swarms/apps/check.py" $HOME/swarms/apps/scout/CLAUDE.md | sed 's/^/  and back to bob in his copy: /'

echo "######## remove agent, old config migration"; user bob
s agents remove btc -y | tail -1
mkdir -p $T/home/dave/.config/skylls; echo '{"repo": "dave/skills", "agents": ["codex"], "kinds": {}}' > $T/home/dave/.config/skylls/config.json
user dave; s list | grep -E "quick setup|published to" | head -2; python3 -c "import json;print('  migrated:', json.load(open('$HOME/.config/skylls/config.json')))"
echo "--- all --json lines valid"; for c in "list" "find pdf" "installed" "agents list" "suggestions" "shared" "people"; do user alice; sj $c | python3 -c "import sys,json;[json.loads(l) for l in sys.stdin if l.strip()];print('  ok:', '$c')"; done
echo "--- --json / --dry-run after the command (as the skill writes them)"; user alice
python3 -m skylls find pdf --json --limit 1 2>/dev/null | python3 -c "import sys,json;print('  ok: find pdf --json ->', json.loads(sys.stdin.readline())['name'])"
python3 -m skylls agents list --json 2>/dev/null | python3 -c "import sys,json;[json.loads(l) for l in sys.stdin if l.strip()];print('  ok: agents list --json')"
python3 -m skylls share pdf @carol --dry-run 2>&1 | grep -q "Would invite @carol" && echo "  ok: share --dry-run" || echo "  FAIL: share --dry-run"

echo "######## update skylls itself (newest = highest tag of jcsancho/skylls)"; user alice
git init --quiet --bare $GHROOT/jcsancho/skylls.git; R=$T/skylls-src; git init --quiet $R
git -C $R commit --quiet --allow-empty -m x; git -C $R tag v1.0.0; git -C $R tag v99.0.0; git -C $R push --quiet --tags $GHROOT/jcsancho/skylls.git
s update --check | grep -E "available|Install it"; sj update --check
s --dry-run update | tail -1   # from a checkout (PYTHONPATH): it can't replace itself
git --git-dir $GHROOT/jcsancho/skylls.git tag -d v99.0.0 >/dev/null; s update | tail -1
