#!/usr/bin/env python3
"""Guard for claiming a team Unit: the developer chooses the design stages and the rhythm before the claim.

The order, for the session that claims a Unit:

 1. `/aidlc --claim <unit>` (UserPromptSubmit): the assistant is told to follow the unit-claim skill, or, when a choice
    is saved, which one is in force.
 2. The claim dialog (AskUserQuestion with the headers Stages, Rhythm and Save) is refused unless
    - no choice is saved (a saved choice is never asked again),
    - a message of the assistant since the developer's last prompt names all four design stages (its reasoning, one
      line per stage, judged against each stage's `condition:`),
    - the Stages question is multiSelect, names the Unit in backticks and offers the four stages, and the Rhythm and
      Save questions offer unit-end / per-stage and No / For me / For this project.
 3. Its answer (PostToolUse) is recorded as the Unit's choice; NFR Design without NFR Requirements adds NFR
    Requirements back, with a note for the developer. "For me" also saves the choice in the plugin's data folder.
 4. `aidlc unit claim <unit>` (or `aidlc --claim <unit>`, `aidlc-unit.ts claim <unit>`) is refused until the Unit has a
    choice (its answer, or a saved one), and unless it carries `--rhythm <the chosen rhythm>`.
 5. After the claim, the assistant is told which stages to skip for the Unit; `aidlc engine state unit start` of a stage
    the choice leaves out is refused with the skip report to run instead.

Fires on PreToolUse (refuses with exit 2 and the reason on stderr), PostToolUse and UserPromptSubmit. It does nothing
outside an AI-DLC project, and never fails a PostToolUse or UserPromptSubmit call. Standard library only.
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
HEADERS = ("stages", "rhythm", "save")
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


VALUE_OPTIONS = {"--team", "--rhythm", "--space", "--intent", "--owner", "--label"}


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
    """[(unit or None, rhythm or None)] of the Unit claims in a command line; None when a claim names no Unit that can
    be read (the claim is then refused)."""
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
                found.append((positional(rest[1:]), option(rest, "rhythm")))
            elif rest[:2] == ["unit", "claim"]:
                found.append((positional(rest[2:]), option(rest, "rhythm")))
            elif any(t == "--claim" or t.startswith("--claim=") for t in rest):
                found.append((option(rest, "claim"), option(rest, "rhythm")))
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


# ---------------------------------------------------------------- the dialog

def questions_of(tool_input):
    qs = (tool_input or {}).get("questions")
    return [q for q in qs if isinstance(q, dict)] if isinstance(qs, list) else []


def header(q):
    return str(q.get("header", "")).strip().lower()


def is_dialog(tool_input):
    return any(header(q) == "stages" for q in questions_of(tool_input))


def labels(q):
    return [str(o.get("label", "")) for o in q.get("options") or [] if isinstance(o, dict)]


def unit_named(text):
    found = re.search(r"`([A-Za-z0-9][A-Za-z0-9._-]*)`", str(text))
    return found.group(1) if found else None


def check_dialog(tool_input):
    """The Unit the dialog asks about, or a Refusal naming what is missing from its shape."""
    qs = {header(q): q for q in questions_of(tool_input)}
    shape = ("one AskUserQuestion with three questions: header `Stages` (multiSelect, the four design stages as options, "
             "the agent's pick marked \"(Recommended)\" and named in the question line, the Unit in backticks), header "
             "`Rhythm` (options `unit-end` and `per-stage`) and header `Save` (options `No`, `For me`, `For this project`)")
    if set(qs) != set(HEADERS) or len(questions_of(tool_input)) != 3:
        raise Refusal(f"The claim dialog is {shape}.")
    stages = qs["stages"]
    if stages.get("multiSelect") is not True:
        raise Refusal(f"The Stages question is multiSelect: the developer may pick any of the four. The dialog is {shape}.")
    slugs = [cc.slug_of(label) for label in labels(stages)]
    if sorted(s for s in slugs if s) != sorted(cc.DESIGN_STAGES) or len(slugs) != 4:
        raise Refusal(f"The Stages question offers exactly the four design stages ({', '.join(cc.NAMES.values())}). The dialog is {shape}.")
    picked = [label for label in labels(stages) if "(recommended)" in label.lower()]
    text = str(stages.get("question", ""))
    for label in picked:
        name = cc.NAMES[cc.slug_of(label)]
        if name.lower() not in text.lower():
            raise Refusal(f"The Stages question line names the agent's pick: \"{name}\" is marked (Recommended) but the "
                          "question does not name it.")
    unit = unit_named(text)
    if not unit:
        raise Refusal("The Stages question names the Unit in backticks, for example: Which design stages should "
                      "`u4-day-navigation` run? I'd run Functional Design only.")
    rhythm = [cc.parse_rhythm(label) for label in labels(qs["rhythm"])]
    if sorted(r for r in rhythm if r) != sorted(cc.RHYTHMS):
        raise Refusal(f"The Rhythm question offers `unit-end` and `per-stage`. The dialog is {shape}.")
    save = [cc.parse_save(label) for label in labels(qs["save"])]
    if sorted(s for s in save if s) != ["me", "no", "project"]:
        raise Refusal(f"The Save question offers No, For me and For this project. The dialog is {shape}.")
    return unit


def entries(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and not entry.get("isSidechain"):
                yield entry


def is_prompt(entry):
    if entry.get("type") != "user":
        return False
    content = (entry.get("message") or {}).get("content") if isinstance(entry.get("message"), dict) else None
    if isinstance(content, str):
        return True
    return isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "text" for b in content) \
        and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def reasoning_sent(event):
    """True when the assistant's text since the developer's last prompt names all four design stages."""
    path = event.get("transcript_path")
    if not path:
        raise Refusal("the session transcript is not given, so whether the reasoning was sent cannot be checked.")
    texts = []
    try:
        for entry in entries(path):
            if is_prompt(entry):
                texts = []
            elif entry.get("type") == "assistant":
                content = (entry.get("message") or {}).get("content")
                blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
                texts += [str(b.get("text", "")) for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    except OSError as why:
        raise Refusal(f"the session transcript cannot be read ({why}).") from None
    said = " ".join(texts).lower()
    return all(name.lower() in said for name in cc.NAMES.values())


def answers_of(response):
    if isinstance(response, dict) and isinstance(response.get("answers"), dict):
        return {str(q): (", ".join(map(str, a)) if isinstance(a, list) else str(a)) for q, a in response["answers"].items()}
    text = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
    return {m.group(1): m.group(2) for m in re.finditer(r'"((?:[^"\\]|\\.)*)"="((?:[^"\\]|\\.)*)"', text)}


def norm(text):
    return re.sub(r"\s+", " ", str(text)).strip().lower()


# ---------------------------------------------------------------- the events

def pre(event, project):
    tool, ti = event.get("tool_name"), event.get("tool_input") or {}
    if tool == "AskUserQuestion" and is_dialog(ti):
        unit = check_dialog(ti)
        scope, saved = cc.saved_choice(project)
        if saved:
            raise Refusal(f"A choice is saved ({'for this project' if scope == 'project' else 'for you'}), so the dialog is "
                          f"not shown again. Run `python3 \"{SCRIPT}\" status --unit {unit}` and claim with it.")
        if not reasoning_sent(event):
            raise Refusal("Send your reasoning first, as a plain message of its own: one line per design stage "
                          "(Functional Design, NFR Requirements, NFR Design, Infrastructure Design), each judged against "
                          f"the stage's own condition (`python3 \"{SCRIPT}\" stages` prints them). Then ask the dialog.")
        return
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = os.path.abspath(str(ti.get("file_path") or ti.get("notebook_path") or ""))
        if os.path.basename(path) == cc.PROJECT_FILE or path.startswith(os.path.abspath(cc.data_dir()) + os.sep):
            raise Refusal("A claim choice is written by claim_choice.py and the claim dialog only, never by hand.")
        return
    if tool != "Bash":
        return
    command = str(ti.get("command", ""))
    check_saves(event, project, command)
    for unit, rhythm in claims(command):
        if not unit or unit.startswith("-"):
            raise Refusal("This claim names no Unit that can be read. Write it as `aidlc unit claim <unit> --team \"<label>\" "
                          "--rhythm <rhythm>`, the Unit first.")
        choice = cc.choice_for(project, unit)
        if not choice:
            scope, saved = cc.saved_choice(project)
            if saved and saved["stages"] == "agent":
                raise Refusal(f"Your saved choice is the agent's pick. Send your reasoning (one line per design stage), then "
                              f"record the pick with `python3 \"{SCRIPT}\" pick --unit {unit} --stages <slugs|none>` and claim.")
            raise Refusal(f"Before {unit} is claimed, the developer chooses its design stages and rhythm. Follow the "
                          "unit-claim skill: your reasoning as a message of its own (one line per design stage, judged "
                          "against its condition), then the claim dialog (Stages, Rhythm, Save).")
        if rhythm != choice["rhythm"]:
            raise Refusal(f"Claim {unit} with the chosen rhythm: add `--rhythm {choice['rhythm']}`"
                          + (f" (not {rhythm})" if rhythm else "") + ".")
    for stage, unit in unit_starts(command):
        choice = cc.choice_for(project, unit)
        if choice and stage in cc.left_out(choice):
            raise Refusal(f"{cc.NAMES.get(stage, stage)} was left out for {unit} at the claim. Report it skipped for this "
                          f"Unit instead, then run `next`: {cc.skip_command(stage, unit)}")


def saves(command):
    """[(scope, stages, rhythm)] of the `claim_choice.py save` calls in a command line."""
    out = []
    if "claim_choice" not in command:
        return out
    for seg in segments(command):
        for i, tok in enumerate(seg):
            if os.path.basename(tok) == "claim_choice.py" and seg[i + 1:i + 2] == ["save"]:
                out.append((option(seg, "scope"), option(seg, "stages"), option(seg, "rhythm")))
    return out


def last_prompt(event):
    """The text of the developer's last prompt in the transcript, or ''."""
    path = event.get("transcript_path")
    text = ""
    if not path:
        return text
    try:
        for entry in entries(path):
            if is_prompt(entry):
                content = entry["message"]["content"]
                text = content if isinstance(content, str) else " ".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    except (OSError, KeyError, TypeError):
        return ""
    return text


def check_saves(event, project, command):
    """A choice is saved only when the developer chose so: "For this project" in the dialog (the bookkeeping pull request
    saves exactly that answer), or a prompt of theirs that asks to save or change it."""
    for scope, stages, rhythm in saves(command):
        if scope == "project":
            answers = os.path.join(cc.data_dir(), "answers")  # any checkout: the pull request runs in a worktree of its own
            wanted = cc.parse_stages(stages or "") if stages != "agent" else "agent"
            if wanted not in (None, "agent"):
                wanted, _notes = cc.with_needs(wanted)
            for dirpath, _dirs, files in os.walk(answers):
                for name in files:
                    a = cc.load(os.path.join(dirpath, name)) or {}
                    if a.get("save") == "project" and a.get("stages") == wanted and a.get("rhythm") == rhythm:
                        break
                else:
                    continue
                break
            else:
                if not re.search(r"\b(save|saved|claim choice|remember)\b", last_prompt(event), re.I):
                    raise Refusal("A choice is saved for the project only when the developer chose \"For this project\" in "
                                  "the claim dialog (with these stages and rhythm) or asked for it in their last message.")
        elif not re.search(r"\b(save|saved|claim choice|remember)\b", last_prompt(event), re.I):
            raise Refusal("A choice is saved for the developer when they pick \"For me\" in the claim dialog (the hook "
                          "saves it) or ask for it in their last message; never on your own.")


def post(event, project):
    tool, ti = event.get("tool_name"), event.get("tool_input") or {}
    if tool == "AskUserQuestion" and is_dialog(ti):
        record_dialog(project, ti, event.get("tool_response"))
        return
    if tool == "Bash":
        response = event.get("tool_response")
        if isinstance(response, dict) and (response.get("is_error") or response.get("interrupted")):
            return
        for unit, _rhythm in claims(str(ti.get("command", ""))):
            choice = cc.choice_for(project, unit)
            if not choice:
                continue
            out = left_out(choice)
            if out:
                say("PostToolUse", f"{unit} is claimed with the {choice['rhythm']} rhythm. When the engine's directive names a "
                                   f"stage left out at the claim ({', '.join(cc.NAMES[s] for s in out)}), report it skipped "
                                   "for this Unit only and run `next`: " + "; ".join(f"`{cc.skip_command(s, unit)}`" for s in out))
            else:
                say("PostToolUse", f"{unit} is claimed with the {choice['rhythm']} rhythm; every design stage runs.")


def left_out(choice):
    return cc.left_out(choice)


def record_dialog(project, tool_input, response):
    qs = {header(q): q for q in questions_of(tool_input)}
    answers = answers_of(response)

    def answer_to(key):
        q = qs.get(key)
        if not q:
            return None
        return next((a for k, a in answers.items() if norm(k) == norm(q.get("question", ""))), None)

    unit = unit_named((qs.get("stages") or {}).get("question", ""))
    stages_text, rhythm_text, save_text = answer_to("stages"), answer_to("rhythm"), answer_to("save")
    if not unit or stages_text is None or rhythm_text is None or save_text is None:
        say("PostToolUse", "the claim dialog's answer could not be read. Ask the dialog again.")
        return
    stages, rhythm, save = cc.parse_stages(stages_text), cc.parse_rhythm(rhythm_text), cc.parse_save(save_text)
    if stages is None or rhythm is None or save is None:
        say("PostToolUse", f"the answer ({stages_text!r}; {rhythm_text!r}; {save_text!r}) could not be read as stages, a "
                           "rhythm and a save choice. Ask in chat what the developer meant, then ask the dialog again.")
        return
    choice, notes = cc.record_answer(project, unit, stages, rhythm, save)
    names = ", ".join(cc.NAMES[s] for s in choice["stages"]) or "no design stage"
    text = f"recorded for {unit}: {names}; rhythm {rhythm}. "
    if notes:
        text += "Tell the developer in one line: " + " ".join(notes) + " "
    text += f"Claim with `--rhythm {rhythm}`. "
    if save == "me":
        text += "The choice is saved for the developer, so the dialog is not shown again. "
    elif save == "project":
        text += ("For this project: the choice lands through a bookkeeping pull request that adds `.unit-claim.json` "
                 f"(`python3 \"{SCRIPT}\" save --scope project --stages {','.join(choice['stages']) or 'none'} --rhythm {rhythm}` "
                 "in a checkout of the default branch). Offer to run it in its own session; follow the unit-claim skill. "
                 "The Unit carries on here with this choice either way. ")
    say("PostToolUse", text.strip())


def prompt(event, project):
    text = str(event.get("prompt") or "")
    found = re.search(r"(?:^|\s)/aidlc\b[^\n]*?--claim[ =](\S+)", text) or re.search(r"\baidlc unit claim (\S+)", text)
    if not found:
        return
    unit = found.group(1).strip("`'\"")
    choice = cc.choice_for(project, unit)
    if choice:
        say("UserPromptSubmit", f"{unit} has a claim choice ({choice['source']}): "
                                f"{', '.join(cc.NAMES[s] for s in choice['stages']) or 'no design stage'}; rhythm {choice['rhythm']}. "
                                f"Say so in one line and claim with `--rhythm {choice['rhythm']}`.")
        return
    scope, saved = cc.saved_choice(project)
    if saved and saved["stages"] == "agent":
        say("UserPromptSubmit", f"before claiming {unit}: the saved choice is your pick (rhythm {saved['rhythm']}). Send your "
                                "reasoning, one line per design stage, then record the pick and claim (unit-claim skill).")
        return
    say("UserPromptSubmit", f"before claiming {unit}, follow the unit-claim skill: your reasoning as a message of its own, "
                            "then the claim dialog (Stages, Rhythm, Save). The claim is refused until it is answered.")


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
