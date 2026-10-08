#!/usr/bin/env python3
"""A fake `gh` for skylls tests: repos are bare git repos under $GHROOT, metadata in $GHROOT/state.json.
The current user is $GH_LOGIN. Implements only what skylls calls."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ["GHROOT"])
ME = os.environ["GH_LOGIN"]
STATE = ROOT / "state.json"
state = json.loads(STATE.read_text()) if STATE.exists() else {"repos": {}, "invites": [], "next": 1, "orgs": {}}
args = sys.argv[1:]
with open(ROOT / "log", "a") as f:
    f.write(f"[{ME}] gh {' '.join(a if len(a) < 60 else a[:57] + '...' for a in args)}\n")


def save():
    STATE.write_text(json.dumps(state, indent=1))


def out(obj):
    print(json.dumps(obj))


def opt(name, default=None):
    return args[args.index(name) + 1] if name in args else default


def can_admin(owner):
    return owner == ME or ME in state["orgs"].get(owner, {}).get("admins", [])


def can_see(full):
    r = state["repos"].get(full)
    return bool(r) and (can_admin(full.split("/")[0]) or ME in r["collabs"])


def show(full, path):
    res = subprocess.run(["git", "--git-dir", str(ROOT / f"{full}.git"), "show", f"HEAD:{path}"],
                         capture_output=True, text=True)
    return {"text": res.stdout} if res.returncode == 0 else None


def node(full):
    r = state["repos"][full]
    owner, name = full.split("/")
    return {"name": name, "owner": {"login": owner}, "isPrivate": r["private"], "pushedAt": "", "url": f"https://github.com/{full}",
            "repositoryTopics": {"nodes": [{"topic": {"name": t}} for t in r["topics"]]},
            "changelog": show(full, "CHANGELOG.md"), "skillmd": show(full, "SKILL.md"),
            "claudemd": show(full, "CLAUDE.md"), "agentsmd": show(full, "AGENTS.md"),
            "issues": {"nodes": [{"number": i["number"], "title": i["title"], "url": f"https://github.com/{full}/issues/{i['number']}",
                                  "createdAt": "2026-10-08T10:00:00Z", "author": {"login": i["author"]}}
                                 for i in r["issues"] if i["state"] == "OPEN" and "suggestion" in i["labels"]]}}


def fail(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


if args[:1] == ["api"]:
    method = opt("-X", "GET")
    path = next(a for a in args[1:] if not a.startswith("-") and a not in (method,) and "=" not in a)
    if path == "user":
        print(ME)
    elif path.startswith("users/"):
        login = path.split("/")[1]
        out({"login": login, "type": "Organization" if login in state["orgs"] else "User"})
    elif m := re.fullmatch(r"orgs/([^/]+)", path):
        org = state["orgs"].get(m[1]) or fail("Not Found (HTTP 404)")
        if method == "PATCH":
            if ME not in org["admins"]:
                fail("Must be an organization owner (HTTP 403)")
            org["base"] = next(a.split("=", 1)[1] for a in args if a.startswith("default_repository_permission="))
            save()
        out({"login": m[1], "default_repository_permission": org.get("base", "read")})
    elif path == "user/memberships/orgs":
        out([{"role": "admin", "state": "active", "organization": {"login": o}}
             for o, spec in state["orgs"].items() if ME in spec["admins"]])
    elif path == "graphql":
        query = next(a for a in args if a.startswith("query="))[6:]
        if "viewer" in query:
            orgs_too = re.search(r"ownerAffiliations:[^)]*ORGANIZATION_MEMBER", query)  # GitHub's default leaves org repos out
            nodes = [{"name": f.split("/")[1], "owner": {"login": f.split("/")[0]}} for f in state["repos"]
                     if can_see(f) and (orgs_too or f.split("/")[0] not in state["orgs"])]
            out({"data": {"viewer": {"repositories": {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}}}})
        else:
            data = {}
            for alias, owner, name in re.findall(r'(r\d+): repository\(owner: "([^"]+)", name: "([^"]+)"\)', query):
                full = f"{owner}/{name}"
                data[alias] = node(full) if can_see(full) else None
            out({"data": data})
    elif path == "user/repository_invitations":
        out([{"id": i["id"], "repository": {"full_name": i["repo"]}, "inviter": {"login": i["inviter"]}}
             for i in state["invites"] if i["invitee"] == ME])
    elif path.startswith("user/repository_invitations/") and method == "PATCH":
        iid = int(path.rsplit("/", 1)[1])
        inv = next((i for i in state["invites"] if i["id"] == iid and i["invitee"] == ME), None)
        if not inv:
            fail("Not Found (HTTP 404)")
        state["repos"][inv["repo"]]["collabs"][ME] = inv["permission"]
        state["invites"].remove(inv)
        save()
    elif m := re.fullmatch(r"repos/([^/]+/[^/]+)/collaborators/([^/]+)", path):
        full, user = m.groups()
        r = state["repos"].get(full) or fail("Not Found (HTTP 404)")
        if method == "PUT":
            if not can_admin(full.split("/")[0]):
                fail("Must have admin rights (HTTP 403)")
            if user in r["collabs"]:
                sys.exit(0)
            perm = "pull" if "permission=pull" in args else "push"
            iid = state["next"]
            state["next"] += 1
            state["invites"].append({"id": iid, "repo": full, "invitee": user, "inviter": ME, "permission": perm})
            save()
            out({"id": iid})
        elif method == "DELETE":
            r["collabs"].pop(user, None)
            save()
        else:
            sys.exit(0 if user in r["collabs"] or user == full.split("/")[0] else 1)
    elif m := re.fullmatch(r"repos/([^/]+/[^/]+)/collaborators", path):
        full = m[1]
        out([{"login": full.split("/")[0], "role_name": "admin"}] +
            [{"login": u, "role_name": "read" if p == "pull" else "write"} for u, p in state["repos"][full]["collabs"].items()])
    elif m := re.fullmatch(r"repos/([^/]+/[^/]+)/invitations(?:/(\d+))?", path):
        full, iid = m.groups()
        if method == "DELETE":
            state["invites"] = [i for i in state["invites"] if i["id"] != int(iid)]
            save()
        else:
            out([{"id": i["id"], "invitee": {"login": i["invitee"]}} for i in state["invites"] if i["repo"] == full])
    else:
        fail(f"fake gh: unsupported api {path}")
elif args[:2] == ["repo", "view"]:
    full = args[2]
    if not can_see(full):
        fail("Could not resolve to a Repository")
    r = state["repos"][full]
    if "--json" in args:
        out({"visibility": "PRIVATE" if r["private"] else "PUBLIC",
             "repositoryTopics": [{"name": t} for t in r["topics"]]})
elif args[:2] == ["repo", "create"]:
    full = args[2]
    if not can_admin(full.split("/")[0]):
        fail("permission denied")
    (ROOT / full.split("/")[0]).mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(ROOT / f"{full}.git")], check=True)
    state["repos"][full] = {"private": "--private" in args, "description": opt("--description", ""),
                            "topics": [], "collabs": {}, "issues": []}
    save()
    print(f"https://github.com/{full}")
elif args[:2] == ["repo", "edit"]:
    r = state["repos"][args[2]]
    if "--description" in args:
        r["description"] = opt("--description")
    if "--add-topic" in args:
        r["topics"] += [t for t in opt("--add-topic").split(",") if t not in r["topics"]]
    if "--remove-topic" in args:
        r["topics"] = [t for t in r["topics"] if t not in opt("--remove-topic").split(",")]
    if "--visibility" in args:
        r["private"] = opt("--visibility") == "private"
    save()
elif args[:2] == ["label", "create"]:
    pass
elif args[:2] == ["issue", "create"]:
    full = opt("-R")
    if not can_see(full):
        fail("no access")
    r = state["repos"][full]
    if opt("--assignee") and opt("--assignee") not in (full.split("/")[0], *r["collabs"]):
        fail("could not assign")
    n = len(r["issues"]) + 1
    r["issues"].append({"number": n, "title": opt("--title"), "labels": [opt("--label")], "state": "OPEN", "author": ME})
    save()
    print(f"https://github.com/{full}/issues/{n}")
elif args[:2] == ["issue", "close"]:
    r = state["repos"][opt("-R")]
    issue = next((i for i in r["issues"] if i["number"] == int(args[2])), None) or fail("no such issue")
    issue["state"] = "CLOSED"
    issue["reason"] = opt("--reason")
    save()
else:
    fail(f"fake gh: unsupported {' '.join(args)}")
