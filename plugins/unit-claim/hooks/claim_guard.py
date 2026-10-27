#!/usr/bin/env python3
"""Guard for claiming a team Unit: the developer chooses the design stages and the rhythm before the claim.

The order, for the session that claims a Unit:

 1. `/aidlc --claim <unit>` (UserPromptSubmit): the assistant is told how the claim dialog is opened, or, when the
    Unit already has a recorded answer, which one is in force.
 2. `aidlc unit claim <unit>` (or `aidlc --claim <unit>`, `aidlc-unit.ts claim <unit>`) is refused until the Unit has a
    recorded answer no earlier claim has used (each claim asks afresh; a claim that goes through marks its answer
    used), and unless it carries `--rhythm <the chosen rhythm>` and, where the project's engine takes it,
    `--skip-stages <the stages left out>` (exactly those; none when every stage runs). The refusal says how to open the dialog: an
    AskUserQuestion with `metadata.source` "unit-claim:<unit>", which the plugin's mod (hooks/register.tsx) fills with
    its own questions, shows the recommendation above, resolves and records with claim_choice.py.
 3. `claim_choice.py record` from Bash, and writing an answer file by hand, are refused: an answer is the developer's,
    recorded by the mod.
 4. After the claim, the assistant is told the left-out stages are skipped (an engine with --skip-stages) or which to
    report skipped as the directive reaches them (an older one); `aidlc engine state unit start` of a left-out stage is
    refused either way.

Fires on PreToolUse (refuses with exit 2 and the reason on stderr), PostToolUse and UserPromptSubmit. It does nothing
outside an AI-DLC project, and never fails a PostToolUse or UserPromptSubmit call. It reads no transcript. Standard
library only.
"""

import json
import os
import re
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import claim_choice as cc  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "claim_choice.py")
OPS = re.compile(r"^[();<>|&]+$")
HINT = "(Refused by the unit-claim plugin.)"


class Refusal(Exception):
    pass


def say(event, text):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": "unit-claim: " + text}}))


# ---------------------------------------------------------------- commands

def tokens_of(line):
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return list(lexer)


def segments(command):
    out = []
    for line in command.splitlines():
        try:
            toks = tokens_of(line)
        except ValueError:
            toks = line.split()
        seg = []
        for tok in toks + [";"]:
            if OPS.match(tok):
                if seg:
                    out.append(seg)
                seg = []
            else:
                seg.append(tok)
    return out


def option(seg, name):
    for i, tok in enumerate(seg):
        if tok == f"--{name}" and i + 1 < len(seg):
            return seg[i + 1]
        if tok.startswith(f"--{name}="):
            return tok.split("=", 1)[1]
    return None


VALUE_OPTIONS = {"--team", "--rhythm", "--skip-stages", "--space", "--intent", "--owner", "--label"}


def positional(tokens):
    """The first argument that is neither an option nor the value of one of the claim's value options."""
    skip = False
    for tok in tokens:
        if skip:
            skip = False
            continue
        if tok.startswith("-"):
            skip = tok in VALUE_OPTIONS
            continue
        return tok
    return None


def claims(command):
    """[(unit or None, rhythm or None, skip-stages or None)] of the Unit claims in a command line; a Unit of None when
    the claim names no Unit that can be read (the claim is then refused)."""
    found = []
    if "claim" not in command:
        return found
    for seg in segments(command):
        for i, tok in enumerate(seg):
            base = os.path.basename(tok)
            if not base.startswith("aidlc"):
                continue
            rest = seg[i + 1:]
            if "--help" in rest or "-h" in rest:
                break
            if base.startswith("aidlc-unit") and rest[:1] == ["claim"]:
                found.append((positional(rest[1:]), option(rest, "rhythm"), option(rest, "skip-stages")))
            elif rest[:2] == ["unit", "claim"]:
                found.append((positional(rest[2:]), option(rest, "rhythm"), option(rest, "skip-stages")))
            elif any(t == "--claim" or t.startswith("--claim=") for t in rest):
                found.append((option(rest, "claim"), option(rest, "rhythm"), option(rest, "skip-stages")))
            else:
                continue
            break
    return found


def unit_starts(command):
    """[(stage, unit)] of `aidlc engine state unit start --stage S --unit U` calls."""
    out = []
    if "unit" not in command or "start" not in command:
        return out
    for seg in segments(command):
        for i, tok in enumerate(seg):
            if os.path.basename(tok).startswith("aidlc") and seg[i + 1:i + 5] == ["engine", "state", "unit", "start"]:
                stage, unit = option(seg, "stage"), option(seg, "unit")
                if stage and unit:
                    out.append((stage, unit))
    return out


def ask_line(unit):
    return (f"Open the claim dialog: one AskUserQuestion with metadata {{\"source\": \"unit-claim:{unit}\"}} and a "
            f"placeholder question (\"Claim {unit}?\", options \"Yes\" and \"No\"). The unit-claim mod replaces it "
            "with its Stages and Rhythm questions and shows its stage recommendation above them; do not answer it or "
            "ask anything else. Then follow the line the mod adds after it.")


# ---------------------------------------------------------------- the events

def records(command):
    return "claim_choice" in command and any(
        os.path.basename(tok) == "claim_choice.py" and seg[i + 1:i + 2] == ["record"]
        for seg in segments(command) for i, tok in enumerate(seg))


def pre(event, project):
    tool, ti = event.get("tool_name"), event.get("tool_input") or {}
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = os.path.abspath(str(ti.get("file_path") or ti.get("notebook_path") or ""))
        if path.startswith(os.path.abspath(cc.data_dir()) + os.sep):
            raise Refusal("A claim answer is the developer's, recorded by the unit-claim mod after the claim dialog; "
                          "never written by hand.")
        return
    if tool != "Bash":
        return
    command = str(ti.get("command", ""))
    if records(command):
        raise Refusal("`claim_choice.py record` is run by the unit-claim mod with the developer's answer, never from "
                      "Bash. Open the claim dialog instead.")
    eng = None
    for unit, rhythm, skip in claims(command):
        if not unit or unit.startswith("-"):
            raise Refusal("This claim names no Unit that can be read. Write it as `aidlc unit claim <unit> --team \"<label>\" "
                          "--rhythm <rhythm>`, the Unit first.")
        choice = cc.open_choice_for(project, unit)
        if not choice:
            used = cc.choice_for(project, unit)
            again = (" Its earlier answer was used by an earlier claim; every claim asks afresh." if used else "")
            raise Refusal(f"Before {unit} is claimed, the developer chooses its design stages and rhythm.{again} {ask_line(unit)}")
        eng = eng or cc.engine(project)
        flags = cc.claim_flags(choice, eng)
        if rhythm != choice["rhythm"]:
            raise Refusal(f"Claim {unit} with the chosen rhythm: add `--rhythm {choice['rhythm']}`"
                          + (f" (not {rhythm})" if rhythm else "") + f". Its flags are `{flags}`.")
        given = sorted(s for s in (skip or "").split(",") if s)
        wanted = sorted(cc.left_out(choice)) if eng["skipStages"] else []
        if not eng["skipStages"] and given:
            raise Refusal("This project's engine has no `--skip-stages` at the claim. Claim with `--rhythm "
                          f"{choice['rhythm']}` alone; the left-out stages are reported skipped as the directive reaches them.")
        if given != wanted:
            raise Refusal(f"Claim {unit} with the stages the developer left out: its flags are `{flags}`"
                          + (f" (not --skip-stages {skip})" if skip else "") + ".")
    for stage, unit in unit_starts(command):
        choice = cc.choice_for(project, unit)
        if choice and stage in cc.left_out(choice):
            if cc.engine(project)["skipStages"]:
                raise Refusal(f"{cc.NAMES.get(stage, stage)} was left out for {unit} and skipped at the claim. Don't start "
                              "it; run `aidlc engine orchestrate next` for the next stage that runs.")
            raise Refusal(f"{cc.NAMES.get(stage, stage)} was left out for {unit} at the claim. Report it skipped for this "
                          f"Unit instead, then run `next`: {cc.skip_command(stage, unit)}")


def post(event, project):
    tool, ti = event.get("tool_name"), event.get("tool_input") or {}
    if tool != "Bash":
        return
    response = event.get("tool_response")
    if isinstance(response, dict) and (response.get("is_error") or response.get("interrupted")):
        return
    for unit, _rhythm, skip in claims(str(ti.get("command", ""))):
        choice = cc.open_choice_for(project, unit)
        if not choice or not claim_went_through(response):
            continue
        cc.mark_claimed(project, unit)
        out = cc.left_out(choice)
        names = ", ".join(cc.NAMES[s] for s in out)
        if not out:
            say("PostToolUse", f"{unit} is claimed with the {choice['rhythm']} rhythm; every design stage runs.")
        elif skip:
            say("PostToolUse", f"{unit} is claimed with the {choice['rhythm']} rhythm, and {names} "
                               f"{'is' if len(out) == 1 else 'are'} skipped for this Unit only. Run "
                               "`aidlc engine orchestrate next`: the Unit starts at its first stage that runs.")
        else:
            say("PostToolUse", f"{unit} is claimed with the {choice['rhythm']} rhythm. When the engine's directive names a "
                               f"stage left out at the claim ({names}), report it skipped for this Unit only and run "
                               "`next`: " + "; ".join(f"`{cc.skip_command(s, unit)}`" for s in out))


def claim_went_through(response):
    """Whether the engine's output says the Unit was claimed (`"claimed": true`): a command that only routes to the
    claim, or failed, leaves the answer open for the claim that follows."""
    text = response if isinstance(response, str) else json.dumps(response) if response is not None else ""
    if isinstance(response, dict):
        text = str(response.get("stdout", "")) + str(response.get("output", ""))
    return re.search(r'"claimed"\s*:\s*true', text) is not None


def prompt(event, project):
    text = str(event.get("prompt") or "")
    found = re.search(r"(?:^|\s)/aidlc\b[^\n]*?--claim[ =](\S+)", text) or re.search(r"\baidlc unit claim (\S+)", text)
    if not found:
        return
    unit = found.group(1).strip("`'\"")
    choice = cc.open_choice_for(project, unit)
    if choice:
        say("UserPromptSubmit", f"{unit} has a recorded claim choice: "
                                f"{', '.join(cc.NAMES[s] for s in choice['stages']) or 'no design stage'}; rhythm {choice['rhythm']}. "
                                f"Say so in one line and claim with `{cc.claim_flags(choice, cc.engine(project))}`.")
        return
    say("UserPromptSubmit", f"before claiming {unit}: {ask_line(unit)} The claim is refused until it is answered.")


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(event, dict):
        return 0
    name = event.get("hook_event_name")
    try:
        project = cc.project_dir(cwd=event.get("cwd"))
        if not os.path.isdir(os.path.join(project, "aidlc", "spaces")):
            return 0
        if name == "PreToolUse":
            pre(event, project)
        elif name == "PostToolUse":
            post(event, project)
        elif name == "UserPromptSubmit":
            prompt(event, project)
    except Refusal as why:
        print(f"{why} {HINT}", file=sys.stderr)
        return 2
    except Exception as why:  # never break the call; a guarded claim that cannot be checked is refused
        if name == "PreToolUse" and event.get("tool_name") == "Bash" and claims(str((event.get("tool_input") or {}).get("command", ""))):
            print(f"The claim could not be checked ({type(why).__name__}: {why}). {HINT}", file=sys.stderr)
            return 2
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
