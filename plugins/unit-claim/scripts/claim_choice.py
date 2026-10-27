#!/usr/bin/env python3
"""The claim choice of a team Unit: which design stages run and which approval rhythm it is claimed with.

    claim_choice.py stages   [--project-dir <dir>]                 the four design stages and their `condition:`
    claim_choice.py brief    --unit <u> [--project-dir <dir>]      what the recommendation reads: the stages, the
                                                                   Unit's entry in unit-of-work.md and its stories
    claim_choice.py status   --unit <u> [--project-dir <dir>]      the choice recorded for the Unit, or null; whether a
                                                                   claim already used it (`used`) and so the dialog is
                                                                   asked again (`ask`); the flags its claim takes
    claim_choice.py engine   [--project-dir <dir>]                 what the project's pinned engine accepts at a claim:
                                                                   its rhythms, and whether it takes --skip-stages
    claim_choice.py record   --unit <u> --stages <a,b|none> --rhythm <r> [--project-dir <dir>]
                             record the developer's answer; run by the plugin's mod after the claim dialog, never by
                             the agent (the hook refuses it from Bash)
    claim_choice.py skips    --unit <u> [--project-dir <dir>]      the skip report of every stage the choice leaves out
    claim_choice.py forget   --unit <u> [--project-dir <dir>]      drop the answer recorded for the Unit

The answer of each Unit is kept in <data>/answers/<project key>/<intent>/<unit>.json, where <data> is $UNIT_CLAIM_DIR,
else ~/.claude/plugins/data/unit-claim, and the project key is the main checkout's, shared by its git worktrees.
Nothing is saved across Units: every claim is asked, and an answer serves the one claim it was given for: once that claim goes through it is marked used
(`claimedAt`), and a later claim of the same Unit asks again. Standard library only.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

DESIGN_STAGES = ("functional-design", "nfr-requirements", "nfr-design", "infrastructure-design")
NAMES = {
    "functional-design": "Functional Design",
    "nfr-requirements": "NFR Requirements",
    "nfr-design": "NFR Design",
    "infrastructure-design": "Infrastructure Design",
}
# The engine's own `condition:` lines (core/aidlc-common/stages/construction/*.md), used when the project's stage graph
# does not carry them.
CONDITIONS = {
    "functional-design": "New data models, complex business logic, or business rules need design. Skip if simple logic changes with no new business logic.",
    "nfr-requirements": "Performance, security, scalability, reliability, or observability requirements needed, or tech stack selection needed. Skip if no NFR requirements and tech stack already determined.",
    "nfr-design": "NFR Requirements was executed and NFR patterns need design. Skip if NFR Requirements was skipped.",
    "infrastructure-design": "Infrastructure services need mapping, deployment architecture required, or cloud resources needed. Skip if no infrastructure changes and infrastructure already defined.",
}
# A stage that needs another: picking the first without the second adds the second back.
NEEDS = {"nfr-design": "nfr-requirements"}
# The rhythms this plugin knows; the mod asks the pinned engine (`aidlc unit claim --help`) for the ones it accepts.
RHYTHMS = ("per-stage", "unit-end")
SKIP_REASON = "skipped at claim by the developer"


class ChoiceError(Exception):
    pass


# ---------------------------------------------------------------- places

def data_dir():
    """One folder for the hook and the mod alike. Not $CLAUDE_PLUGIN_DATA: the hook is given it, the processes the mod
    starts are not, so the two would read and write different folders."""
    return os.environ.get("UNIT_CLAIM_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "plugins", "data", "unit-claim")


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
    else CLAUDE_PROJECT_DIR. In a git worktree the working directory wins: its per-checkout pointers are its own."""
    if given:
        return os.path.abspath(given)
    for folder in (cwd, os.getcwd(), os.environ.get("CLAUDE_PROJECT_DIR")):
        found = up_to_project(folder)
        if found:
            return found
    return os.path.abspath(cwd or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def main_checkout(folder):
    """The repository's main checkout when `folder` is a linked git worktree (its `.git` is a file pointing into the
    main checkout's `.git/worktrees/`), else `folder`. A session in a worktree may have its hooks run from the main
    checkout and its mod's processes from the worktree: both must find the same answer."""
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


def cursor(project, *parts):
    """A gitignored AI-DLC cursor (active-space, active-intent): the checkout's own, else the main checkout's."""
    for place in (project, main_checkout(project)):
        found = first_line(os.path.join(place, "aidlc", *parts))
        if found:
            return found
    return ""


def active_space(project):
    return cursor(project, "active-space") or "default"


def intent_of(project):
    return cursor(project, "spaces", active_space(project), "intents", "active-intent") or "no-intent"


def project_key(project):
    return hashlib.sha256(os.path.realpath(main_checkout(project)).encode("utf-8")).hexdigest()[:12]


def answer_path(project, unit):
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", unit)
    return os.path.join(data_dir(), "answers", project_key(project), intent_of(project), safe + ".json")


# ---------------------------------------------------------------- reading and writing

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


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def choice_for(project, unit):
    """{"unit", "stages": [...], "rhythm", "at", "claimedAt"?} recorded for the Unit, or None. A used answer (one whose
    claim went through, `claimedAt` set) is still the Unit's choice for the rest of that claim: its skips and refusals."""
    answer = load(answer_path(project, unit))
    if answer and isinstance(answer.get("stages"), list) and answer.get("rhythm") in RHYTHMS:
        return answer
    return None


def open_choice_for(project, unit):
    """The Unit's answer a claim may still use: recorded and not yet used by a claim that went through. Each claim asks
    the developer afresh: an answer belongs to the one claim it was given for."""
    choice = choice_for(project, unit)
    return choice if choice and not choice.get("claimedAt") else None


def mark_claimed(project, unit):
    """Record that the Unit's answer was used by a claim that went through, so a later claim asks again."""
    choice = choice_for(project, unit)
    if choice and not choice.get("claimedAt"):
        choice["claimedAt"] = now()
        write(answer_path(project, unit), choice)


# ---------------------------------------------------------------- the choice itself

def slug_of(text):
    """A design stage's slug from a label such as "NFR Design (Recommended)", or None."""
    text = re.sub(r"\(recommended\)", "", str(text), flags=re.I).strip().lower()
    text = re.sub(r"[^a-z]+", " ", text).strip()
    for slug, name in NAMES.items():
        if text in (name.lower(), slug.replace("-", " ")):
            return slug
    if text in ("infrastructure", "infra design", "infra"):
        return "infrastructure-design"
    if text in ("functional",):
        return "functional-design"
    return None


def parse_stages(text):
    """[slugs] from a dialog answer ("Functional Design, NFR Design"), [] for none, None when it cannot be read."""
    if isinstance(text, list):
        parts = text
    else:
        if re.fullmatch(r"\s*(none|no stages?|skip (them )?all|nothing)\s*\.?\s*", str(text), re.I):
            return []
        parts = re.split(r"\s*(?:,|;|\band\b|\n)\s*", str(text))
    found = []
    for part in parts:
        if not str(part).strip():
            continue
        slug = slug_of(part)
        if slug is None:
            return None
        if slug not in found:
            found.append(slug)
    return [s for s in DESIGN_STAGES if s in found]


def with_needs(stages):
    """(stages in engine order, [note]) with every stage a chosen stage needs added back."""
    chosen, notes = list(stages), []
    for stage, need in NEEDS.items():
        if stage in chosen and need not in chosen:
            chosen.append(need)
            notes.append(f"{NAMES[need]} was added back: {NAMES[stage]} needs it.")
    return [s for s in DESIGN_STAGES if s in chosen], notes


def record_answer(project, unit, stages, rhythm):
    """Write the Unit's answer. Returns (choice, notes)."""
    stages, notes = with_needs(stages)
    choice = {"unit": unit, "stages": stages, "rhythm": rhythm, "at": now()}
    write(answer_path(project, unit), choice)
    return choice, notes


def left_out(choice):
    return [s for s in DESIGN_STAGES if s not in (choice or {}).get("stages", [])]


def skip_command(stage, unit):
    return f'aidlc engine orchestrate report --stage {stage} --unit {unit} --result skipped --reason "{SKIP_REASON}"'


def stage_info(project):
    """[{slug, name, condition}] of the four design stages, the condition from the project's stage graph when it has one."""
    graph = {}
    try:
        with open(os.path.join(project, ".claude", "tools", "data", "stage-graph.json"), encoding="utf-8") as f:
            data = json.load(f)
        graph = {s["slug"]: s for s in data if isinstance(s, dict) and isinstance(s.get("slug"), str)}
    except (OSError, ValueError, TypeError):
        pass
    out = []
    for slug in DESIGN_STAGES:
        g = graph.get(slug) or {}
        out.append({"slug": slug, "name": g.get("name") or NAMES[slug], "condition": g.get("condition") or CONDITIONS[slug]})
    return out


def engine(project):
    """What the project's pinned engine accepts at a claim, from the claim's usage line in its harness
    (`<harness>/tools/aidlc-unit.ts`): {"rhythms": [...], "skipStages": bool, "usage": str}. Read from the file, not
    by running `aidlc`, which fails while the project's pin is not registered on the machine."""
    usage = ""
    for harness in (".claude", ".kiro", ".codex"):
        try:
            with open(os.path.join(project, harness, "tools", "aidlc-unit.ts"), encoding="utf-8") as f:
                found = re.search(r"Usage: aidlc-unit claim[^\"'`\n]*", f.read())
        except OSError:
            continue
        if found:
            usage = found.group(0).strip()
            break
    rhythms = re.search(r"--rhythm\s+([a-z|-]+)", usage)
    return {"rhythms": [r for r in rhythms.group(1).split("|") if r] if rhythms else list(RHYTHMS),
            "skipStages": "--skip-stages" in usage, "usage": usage}


def claim_flags(choice, eng):
    """The flags a claim of the Unit carries: its rhythm and, where the engine takes it, the stages left out."""
    flags = f"--rhythm {choice['rhythm']}"
    out = left_out(choice)
    if eng["skipStages"] and out:
        flags += " --skip-stages " + ",".join(out)
    return flags


def intent_dir(project):
    return os.path.join(project, "aidlc", "spaces", active_space(project), "intents", intent_of(project))


def section(path, heading):
    """The Markdown section whose heading matches `heading` (a regex), down to the next heading of its level or above."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return ""
    out, level = [], None
    for line in lines:
        mark = re.match(r"^(#{1,6})\s", line)
        if level is None:
            if mark and re.search(heading, line, re.I):
                level, out = len(mark.group(1)), [line]
        elif mark and len(mark.group(1)) <= level:
            break
        else:
            out.append(line)
    return "\n".join(out).strip()


def brief(project, unit):
    """What the stage recommendation reads: the four stages and their conditions, the Unit's entry, its stories."""
    folder = intent_dir(project)
    entry = section(os.path.join(folder, "inception", "units-generation", "unit-of-work.md"), rf"\b{re.escape(unit)}\b")
    stories = []
    for story in sorted(set(re.findall(r"\bUS\d+(?:\.\d+)*\b", entry))):
        text = section(os.path.join(folder, "inception", "user-stories", "stories.md"), rf"\b{re.escape(story)}\b")
        if text:
            stories.append(text)
    return {"unit": unit, "stages": stage_info(project), "entry": entry, "stories": stories}


# ---------------------------------------------------------------- command line

def main(argv=None):
    ap = argparse.ArgumentParser(prog="claim_choice.py", description="The claim choice of a team Unit.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("stages", "engine", "brief", "status", "record", "skips", "forget"):
        p = sub.add_parser(name)
        p.add_argument("--project-dir")
        if name not in ("stages", "engine"):
            p.add_argument("--unit", required=True)
        if name == "record":
            p.add_argument("--stages", required=True)
            p.add_argument("--rhythm", choices=RHYTHMS, required=True)
    args = ap.parse_args(argv)
    project = project_dir(given=args.project_dir)
    try:
        if args.cmd == "stages":
            print(json.dumps(stage_info(project), indent=2))
        elif args.cmd == "engine":
            print(json.dumps(engine(project), indent=2))
        elif args.cmd == "brief":
            print(json.dumps(brief(project, args.unit), indent=2))
        elif args.cmd == "status":
            choice = choice_for(project, args.unit)
            usable = open_choice_for(project, args.unit)
            flags = claim_flags(usable, engine(project)) if usable else None
            print(json.dumps({"unit": args.unit, "choice": choice, "used": bool(choice and choice.get("claimedAt")),
                              "ask": usable is None, "claimFlags": flags}, indent=2))
        elif args.cmd == "record":
            stages = parse_stages(args.stages)
            if stages is None:
                raise ChoiceError(f"cannot read the stages {args.stages!r}; name them by slug, comma-separated, or none")
            choice, notes = record_answer(project, args.unit, stages, args.rhythm)
            eng = engine(project)
            skips = [] if eng["skipStages"] else [skip_command(s, args.unit) for s in left_out(choice)]
            print(json.dumps({"choice": choice, "notes": notes, "claimFlags": claim_flags(choice, eng), "skips": skips}, indent=2))
        elif args.cmd == "skips":
            choice = choice_for(project, args.unit)
            if not choice:
                raise ChoiceError(f"no claim choice for {args.unit} yet")
            print("\n".join(skip_command(s, args.unit) for s in left_out(choice)))
        elif args.cmd == "forget":
            try:
                os.remove(answer_path(project, args.unit))
            except FileNotFoundError:
                pass
            print(json.dumps({"forgotten": args.unit}))
    except ChoiceError as why:
        print(f"claim_choice.py: {why}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
