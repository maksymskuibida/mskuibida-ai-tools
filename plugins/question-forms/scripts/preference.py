#!/usr/bin/env python3
"""The developer's question-forms preference, per user and per project, and the answers of the per-file ask.

    preference.py get     [--project-dir <dir>]                      the recorded preference, or null
    preference.py set     --value always|ask|never [--project-dir]   record it; run by the plugin's mod after the
                                                                     preference dialog, never by the agent
    preference.py answer  --file <repo path> --choice form|edit      record the per-file ask's answer for one questions
                          [--project-dir <dir>]                      file; run by the mod, never by the agent
    preference.py forget  [--project-dir <dir>]                      drop the preference (the dialog asks again)

Kept under <data>/ — $QUESTION_FORMS_DIR, else ~/.claude/plugins/data/question-forms:

    preferences/<project key>.json      {"value", "at"}
    asks/<project key>/<file key>.json  {"file", "choice", "at"}
    sessions/<session id>.json          the hook's per-session state (hooks/question_guard.py)

The project key is the main checkout's, so a git worktree shares its main checkout's preference. The hook refuses
`set` and `answer` from Bash and a hand-written file in <data>: they are the developer's, recorded by the mod.
Standard library only.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

VALUES = ("always", "ask", "never")
CHOICES = ("form", "edit")


def data_dir():
    """One folder for the hook and the mod alike (the processes the mod starts are not given $CLAUDE_PLUGIN_DATA)."""
    return os.environ.get("QUESTION_FORMS_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "plugins", "data", "question-forms")


def first_line(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    return line.strip()
    except OSError:
        pass
    return ""


def has_project(folder):
    return bool(folder) and os.path.isdir(os.path.join(folder, "aidlc", "spaces"))


def up_to_project(folder):
    folder = os.path.abspath(folder) if folder else ""
    while folder:
        if has_project(folder):
            return folder
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    return None


def project_dir(cwd=None, given=None):
    """The AI-DLC project: --project-dir, else the working directory (or its nearest parent) that holds aidlc/spaces,
    else CLAUDE_PROJECT_DIR."""
    if given:
        return os.path.abspath(given)
    for folder in (cwd, os.getcwd(), os.environ.get("CLAUDE_PROJECT_DIR")):
        found = up_to_project(folder)
        if found:
            return found
    return os.path.abspath(cwd or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def main_checkout(folder):
    """The repository's main checkout when `folder` is a linked git worktree (its `.git` is a file pointing into the
    main checkout's `.git/worktrees/`), else `folder`."""
    try:
        with open(os.path.join(folder, ".git"), encoding="utf-8") as f:
            line = f.readline().strip()
    except OSError:
        return folder
    if not line.startswith("gitdir:"):
        return folder
    gitdir = os.path.join(folder, line[len("gitdir:"):].strip())
    common = first_line(os.path.join(gitdir, "commondir"))
    common = os.path.normpath(os.path.join(gitdir, common)) if common else ""
    if os.path.basename(common) == ".git" and has_project(os.path.dirname(common)):
        return os.path.dirname(common)
    return folder


def project_key(project):
    return hashlib.sha256(os.path.realpath(main_checkout(project)).encode("utf-8")).hexdigest()[:12]


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


# ---------------------------------------------------------------- the preference

def preference_path(project):
    return os.path.join(data_dir(), "preferences", project_key(project) + ".json")


def get_preference(project):
    """'always', 'ask' or 'never', or None when the developer has not chosen for this project yet."""
    found = load(preference_path(project))
    return found["value"] if found and found.get("value") in VALUES else None


def set_preference(project, value):
    if value not in VALUES:
        raise ValueError(f"the preference is one of {', '.join(VALUES)}")
    write(preference_path(project), {"value": value, "at": now()})


# ---------------------------------------------------------------- the per-file ask

def ask_path(project, rel):
    return os.path.join(data_dir(), "asks", project_key(project), hashlib.sha256(rel.encode("utf-8")).hexdigest()[:16] + ".json")


def get_ask(project, rel):
    found = load(ask_path(project, rel))
    return found["choice"] if found and found.get("choice") in CHOICES else None


def set_ask(project, rel, choice):
    if choice not in CHOICES:
        raise ValueError(f"the choice is one of {', '.join(CHOICES)}")
    write(ask_path(project, rel), {"file": rel, "choice": choice, "at": now()})


def clear_ask(project, rel):
    remove(ask_path(project, rel))


# ---------------------------------------------------------------- session state

def session_path(session_id):
    return os.path.join(data_dir(), "sessions", re.sub(r"[^A-Za-z0-9._-]", "_", str(session_id or "none")) + ".json")


def load_session(session_id):
    state = load(session_path(session_id)) or {}
    state.setdefault("files", {})
    return state


def save_session(session_id, state):
    write(session_path(session_id), state)


def clear_session(session_id):
    remove(session_path(session_id))


# ---------------------------------------------------------------- command line

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("get", "set", "answer", "forget"))
    ap.add_argument("--value")
    ap.add_argument("--file")
    ap.add_argument("--choice")
    ap.add_argument("--project-dir")
    args = ap.parse_args(argv)
    project = project_dir(given=args.project_dir)
    try:
        if args.command == "get":
            print(json.dumps({"preference": get_preference(project)}))
        elif args.command == "set":
            set_preference(project, args.value or "")
            print(json.dumps({"preference": args.value}))
        elif args.command == "answer":
            if not args.file:
                raise ValueError("--file is required")
            set_ask(project, args.file, args.choice or "")
            print(json.dumps({"file": args.file, "choice": args.choice}))
        else:
            remove(preference_path(project))
            print(json.dumps({"preference": None}))
    except ValueError as why:
        print(str(why), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
