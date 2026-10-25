#!/usr/bin/env python3
"""The forks of the AI-DLC engine (awslabs/aidlc-workflows) this person patches: one JSON file in the
plugin's data directory, which survives plugin updates.

    forks.py [--data DIR] resolve              which fork to use now (exit codes below)
    forks.py [--data DIR] list                 every saved fork, one per line
    forks.py [--data DIR] show REPO            one saved fork as JSON (exit 5 if not saved)
    forks.py [--data DIR] add REPO [--clone PATH] [--upstream REPO]
                                               save a fork, or update its clone/upstream
    forks.py [--data DIR] remove REPO
    forks.py [--data DIR] path                 the registry file's path

REPO is `owner/name`. The data directory is --data, else $CLAUDE_PLUGIN_DATA, else
~/.claude/plugins/data/aidlc-patches (an empty --data counts as unset, so a skill that passes an
unexpanded variable still lands in the same place). The file is <data>/forks.json:

    {"version": 1, "forks": [{"repo": "owner/name", "clone": "/abs/path" | null,
                              "upstream": "awslabs/aidlc-workflows"}]}

`resolve` exits:
    0  exactly one fork is saved: its JSON is printed; use it without asking
    3  none is saved: ask the person which fork (and its clone path), then `add` it
    4  several are saved: they are printed; ask the person which one, every time
Errors (a bad REPO, an unreadable file) exit 2.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

UPSTREAM = "awslabs/aidlc-workflows"
REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")
FALLBACK = Path.home() / ".claude" / "plugins" / "data" / "aidlc-patches"


class Refused(Exception):
    pass


def data_dir(arg):
    for value in (arg, os.environ.get("CLAUDE_PLUGIN_DATA")):
        if value and "${" not in value:
            return Path(value).expanduser()
    return FALLBACK


def registry_path(arg):
    return data_dir(arg) / "forks.json"


def load(path):
    if not path.exists():
        return {"version": 1, "forks": []}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise Refused(f"{path} is not readable JSON ({e}); fix or remove it")
    if not isinstance(data, dict) or not isinstance(data.get("forks"), list):
        raise Refused(f"{path} has no \"forks\" list; fix or remove it")
    return data


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".forks-")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def check_repo(repo):
    repo = repo.strip().removeprefix("https://github.com/").removesuffix(".git").strip("/")
    if not REPO.match(repo):
        raise Refused(f"{repo!r} is not owner/name")
    return repo


def find(data, repo):
    for fork in data["forks"]:
        if fork.get("repo", "").lower() == repo.lower():
            return fork
    return None


def line(fork):
    clone = fork.get("clone") or "(no local clone)"
    return f"{fork['repo']}\t{clone}\tupstream {fork.get('upstream') or UPSTREAM}"


def cmd_resolve(path, _args):
    forks = load(path)["forks"]
    if not forks:
        print(f"No fork saved yet ({path}). Ask which fork (owner/name) and its local clone path, then add it.")
        return 3
    if len(forks) == 1:
        print(json.dumps(forks[0]))
        return 0
    print(f"{len(forks)} forks saved. Ask which one to use:")
    for fork in forks:
        print(line(fork))
    return 4


def cmd_list(path, _args):
    for fork in load(path)["forks"]:
        print(line(fork))
    return 0


def cmd_show(path, args):
    fork = find(load(path), check_repo(args.repo))
    if fork is None:
        print(f"{args.repo} is not saved. Add it with: forks.py add {args.repo} [--clone PATH]")
        return 5
    print(json.dumps(fork))
    return 0


def cmd_add(path, args):
    data = load(path)
    repo = check_repo(args.repo)
    fork = find(data, repo)
    if fork is None:
        fork = {"repo": repo, "clone": None, "upstream": UPSTREAM}
        data["forks"].append(fork)
        verb = "saved"
    else:
        verb = "updated"
    if args.clone is not None:
        clone = Path(args.clone).expanduser().resolve() if args.clone else None
        if clone is not None and not (clone / ".git").exists():
            raise Refused(f"{clone} is not a git clone; clone the fork there first, or leave --clone out")
        fork["clone"] = str(clone) if clone else None
    if args.upstream:
        fork["upstream"] = check_repo(args.upstream)
    save(path, data)
    print(f"{verb}: {line(fork)}")
    if len(data["forks"]) > 1:
        print(f"{len(data['forks'])} forks are saved now: ask which one to use every time.")
    return 0


def cmd_remove(path, args):
    data = load(path)
    fork = find(data, check_repo(args.repo))
    if fork is None:
        print(f"{args.repo} is not saved.")
        return 5
    data["forks"].remove(fork)
    save(path, data)
    print(f"removed: {fork['repo']}")
    return 0


def cmd_path(path, _args):
    print(path)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="The AI-DLC engine forks this person patches.")
    p.add_argument("--data", default=None, help="the plugin's data directory")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("resolve")
    sub.add_parser("list")
    sub.add_parser("path")
    s = sub.add_parser("show")
    s.add_argument("repo")
    a = sub.add_parser("add")
    a.add_argument("repo")
    a.add_argument("--clone", default=None, help="the local clone; an empty value clears it")
    a.add_argument("--upstream", default=None, help=f"default {UPSTREAM}")
    r = sub.add_parser("remove")
    r.add_argument("repo")
    args = p.parse_args(argv)
    path = registry_path(args.data)
    handler = {"resolve": cmd_resolve, "list": cmd_list, "path": cmd_path, "show": cmd_show,
               "add": cmd_add, "remove": cmd_remove}[args.cmd]
    try:
        return handler(path, args)
    except Refused as e:
        print(f"forks.py: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
