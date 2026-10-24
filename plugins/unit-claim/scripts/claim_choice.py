#!/usr/bin/env python3
"""The claim choice of a team Unit: which design stages run and which approval rhythm it is claimed with.

    claim_choice.py stages   [--project-dir <dir>]                 the four design stages and their `condition:`
    claim_choice.py status   --unit <u> [--project-dir <dir>]      the choice in force for the Unit, and where it is from
    claim_choice.py pick     --unit <u> --stages <a,b|none> [--project-dir <dir>]
                             record the agent's pick for the Unit; only when a saved choice says "use the agent's pick"
    claim_choice.py save     --scope me|project --stages <a,b|none|agent> --rhythm per-stage|unit-end [--project-dir <dir>]
                             save a choice: for me in the plugin's data folder, for the project in <project>/.unit-claim.json
    claim_choice.py skips    --unit <u> [--project-dir <dir>]      the skip report of every stage the choice leaves out
    claim_choice.py forget   --unit <u> [--project-dir <dir>]      drop the answer recorded for the Unit

Where a choice comes from, first match wins:
  1. the answer of the claim dialog for this Unit in this checkout (written by hooks/claim_guard.py when the dialog is
     answered, or by `pick`), in <data>/answers/<project key>/<intent>/<unit>.json;
  2. the project's saved choice, <project>/.unit-claim.json (landed through a bookkeeping pull request);
  3. the developer's saved choice, <data>/choice.json.
<data> is $UNIT_CLAIM_DIR, else $CLAUDE_PLUGIN_DATA, else ~/.claude/plugins/data/unit-claim. A saved choice is
{"stages": [slugs] | "agent", "rhythm": "per-stage"|"unit-end"}: a fixed set of stages, or "agent" for the agent's pick
of each Unit without asking (the reasoning message is still sent). Standard library only.
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
RHYTHMS = ("per-stage", "unit-end")
SKIP_REASON = "skipped at claim by the developer"
PROJECT_FILE = ".unit-claim.json"


class ChoiceError(Exception):
    pass


# ---------------------------------------------------------------- places

def data_dir():
    return (os.environ.get("UNIT_CLAIM_DIR") or os.environ.get("CLAUDE_PLUGIN_DATA")
            or os.path.join(os.path.expanduser("~"), ".claude", "plugins", "data", "unit-claim"))


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


def intent_of(project):
    space = first_line(os.path.join(project, "aidlc", "active-space")) or "default"
    return first_line(os.path.join(project, "aidlc", "spaces", space, "intents", "active-intent")) or "no-intent"


def project_key(project):
    return hashlib.sha256(os.path.realpath(project).encode("utf-8")).hexdigest()[:12]


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


def valid_saved(data):
    if not data or data.get("rhythm") not in RHYTHMS:
        return None
    stages = data.get("stages")
    if stages == "agent" or (isinstance(stages, list) and all(s in DESIGN_STAGES for s in stages)):
        return data
    return None


def saved_choice(project):
    """(scope, choice) of the saved choice in force for the project, or (None, None)."""
    project_saved = valid_saved(load(os.path.join(project, PROJECT_FILE)))
    if project_saved:
        return "project", project_saved
    mine = valid_saved(load(os.path.join(data_dir(), "choice.json")))
    if mine:
        return "me", mine
    return None, None


def choice_for(project, unit):
    """{"stages": [...], "rhythm": ..., "source": "answer"|"pick"|"project"|"me", ...} in force for the Unit, or None.
    A saved "agent" choice is in force only once the agent's pick for the Unit is recorded."""
    answer = load(answer_path(project, unit))
    if answer and isinstance(answer.get("stages"), list) and answer.get("rhythm") in RHYTHMS:
        return dict(answer, source=answer.get("source") or "answer")
    scope, saved = saved_choice(project)
    if saved and isinstance(saved["stages"], list):
        return {"unit": unit, "stages": list(saved["stages"]), "rhythm": saved["rhythm"], "source": scope}
    return None


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


def parse_rhythm(text):
    low = str(text).lower()
    if "unit-end" in low or "unit end" in low or "one approval per unit" in low:
        return "unit-end"
    if "per-stage" in low or "per stage" in low or "every stage" in low:
        return "per-stage"
    return None


def parse_save(text):
    low = str(text).lower()
    if "project" in low:
        return "project"
    if "for me" in low or low.strip() in ("me", "mine"):
        return "me"
    if low.strip().startswith("no") or "don't" in low or "do not" in low:
        return "no"
    return None


def record_answer(project, unit, stages, rhythm, save, source="answer"):
    """Write the Unit's answer (and, for "me", the developer's saved choice). Returns (choice, notes)."""
    stages, notes = with_needs(stages)
    choice = {"unit": unit, "stages": stages, "rhythm": rhythm, "save": save, "source": source, "at": now()}
    write(answer_path(project, unit), choice)
    if save == "me":
        write(os.path.join(data_dir(), "choice.json"), {"stages": stages, "rhythm": rhythm, "savedAt": now()})
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


# ---------------------------------------------------------------- command line

def main(argv=None):
    ap = argparse.ArgumentParser(prog="claim_choice.py", description="The claim choice of a team Unit.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("stages", "status", "pick", "save", "skips", "forget"):
        p = sub.add_parser(name)
        p.add_argument("--project-dir")
        if name in ("status", "pick", "skips", "forget"):
            p.add_argument("--unit", required=True)
        if name in ("pick", "save"):
            p.add_argument("--stages", required=True)
        if name == "save":
            p.add_argument("--scope", choices=("me", "project"), required=True)
            p.add_argument("--rhythm", choices=RHYTHMS, required=True)
    args = ap.parse_args(argv)
    project = project_dir(given=args.project_dir)
    try:
        if args.cmd == "stages":
            print(json.dumps(stage_info(project), indent=2))
        elif args.cmd == "status":
            choice = choice_for(project, args.unit)
            scope, saved = saved_choice(project)
            print(json.dumps({"unit": args.unit, "choice": choice, "saved": scope, "savedStages": (saved or {}).get("stages"),
                              "ask": choice is None and not (saved and saved["stages"] == "agent"),
                              "agentPick": bool(saved and saved["stages"] == "agent" and choice is None)}, indent=2))
        elif args.cmd == "pick":
            scope, saved = saved_choice(project)
            if not saved or saved["stages"] != "agent":
                raise ChoiceError("a pick without asking needs a saved choice that says so (stages: \"agent\"); "
                                  "otherwise ask the claim dialog")
            stages = parse_stages(args.stages)
            if stages is None:
                raise ChoiceError(f"cannot read the stages {args.stages!r}; name them by slug, comma-separated, or none")
            choice, notes = record_answer(project, args.unit, stages, saved["rhythm"], "no", source="pick")
            print(json.dumps({"choice": choice, "notes": notes, "skips": [skip_command(s, args.unit) for s in left_out(choice)]}, indent=2))
        elif args.cmd == "save":
            if args.stages == "agent":
                stages = "agent"
            else:
                stages = parse_stages(args.stages)
                if stages is None:
                    raise ChoiceError(f"cannot read the stages {args.stages!r}")
                stages, _notes = with_needs(stages)
            value = {"stages": stages, "rhythm": args.rhythm, "savedAt": now()}
            path = os.path.join(project, PROJECT_FILE) if args.scope == "project" else os.path.join(data_dir(), "choice.json")
            write(path, value)
            print(json.dumps({"saved": args.scope, "path": path, "choice": value}, indent=2))
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
