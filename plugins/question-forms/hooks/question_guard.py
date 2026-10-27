#!/usr/bin/env python3
"""Guard for the AI-DLC questions files: the developer's question-forms preference decides how each one is answered,
and this hook holds the agent to it. Per-session state: scripts/preference.py keeps it under <data>/sessions/.

The order, for a questions file (`…/aidlc/spaces/…/<stage>-questions.md` with `[Answer]:` tags):

 1. Write/Edit/MultiEdit of it (PostToolUse) records it as pending and says the next step: the preference dialog (no
    preference recorded for this project yet), the per-file ask (preference `ask`), publishing the form (`always`,
    or the ask answered "form"), or nothing (`never`, or the ask answered "edit").
 2. Stop is refused (`decision: block`) while the preference dialog or the per-file ask is owed, and while the form's
    `forms/<id>` row was not written by ArtifactData in this session after the file, or no message of the assistant in
    the transcript carries `<artifact url>#<id>`. Bounded: a refusal that was already followed once (`stop_hook_active`)
    is repeated up to MAX_BLOCKS times, then the stop goes through with a note.
 3. AskUserQuestion with the form's link inside it is refused: the link goes in a message of its own before the ask.
 4. `aidlc engine orchestrate next|continue|report` is refused (for that stage when --stage names one) while a file
    whose form was opened still has an empty `[Answer]:` tag: read the form and copy the answers first.
 5. `preference.py set|answer|forget` from Bash, and writing a file in the plugin's data folder, are refused: the
    developer's choice is recorded by the plugin's mod after its dialog.
 6. `/question-forms:release` clears this session's state; `/question-forms:preference` says how to open the dialog.

Does nothing outside an AI-DLC project and never fails a PostToolUse or UserPromptSubmit call. Standard library only.
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))

import preference as pf  # noqa: E402

MAX_BLOCKS = 3
HINT = "(Refused by the question-forms plugin.)"
EMPTY_TAG = re.compile(r"\[Answer\]\s*:\s*(\*\*)?\s*$", re.MULTILINE)
URL = r"https?://[^\s\"'\\)>\]]*artifact[^\s\"'\\)>\]]*"


class Refusal(Exception):
    pass


def say(event, text):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": "question-forms: " + text}}))


# ---------------------------------------------------------------- questions files

def is_questions_file(path):
    norm = os.path.abspath(path).replace(os.sep, "/")
    if "/aidlc/spaces/" not in norm or not norm.endswith("-questions.md"):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            return "[Answer]:" in f.read()
    except OSError:
        return False


def rel_of(project, path):
    path = os.path.abspath(path)
    base = os.path.abspath(project) + os.sep
    if path.startswith(base):
        return path[len(base):]
    return "aidlc/" + path.replace(os.sep, "/").split("/aidlc/", 1)[-1]


def has_empty_tag(path):
    try:
        with open(path, encoding="utf-8") as f:
            return EMPTY_TAG.search(f.read()) is not None
    except OSError:
        return False


# ---------------------------------------------------------------- what is owed

def status(project, rel, entry):
    """'pref' (the preference dialog is owed), 'ask' (the per-file ask), 'form', 'edit' or 'never'."""
    if entry.get("formId"):
        return "form"
    pref = pf.get_preference(project)
    if pref is None:
        return "pref"
    if pref == "never":
        return "never"
    if pref == "always":
        return "form"
    choice = pf.get_ask(project, rel)
    return "ask" if choice is None else choice


def next_step(kind, rel, entry):
    if kind == "pref":
        return (f"no question-forms preference is recorded for this project, and `{rel}` was written. Open the preference "
                "dialog before asking the developer anything about it: one AskUserQuestion with metadata "
                "{\"source\": \"question-forms:preference\"} and a placeholder question (\"Show question forms?\", "
                "options \"Always\" and \"Ask\"). The question-forms mod replaces it with its own question and explains "
                "what a question form is above it; do not answer it or ask anything else. Then follow the line the mod adds.")
    if kind == "ask":
        return (f"the preference is `ask`: open the per-file ask for `{rel}` before anything else about it: one AskUserQuestion "
                f"with metadata {{\"source\": \"question-forms:ask:{rel}\"}} and a placeholder question (\"Open the form?\", "
                "options \"Form\" and \"Edit\"). The mod replaces it with the real choice; do not answer it.")
    if kind == "form":
        if entry.get("formId") and not entry.get("linked"):
            return (f"the form `{entry['formId']}` for `{rel}` is written. Send its link `<artifact url>#{entry['formId']}` in a "
                    "message of its own, before and apart from any question; then ask the developer to say when the form is done.")
        return (f"`{rel}` becomes a form (skill question-forms § 2): one ArtifactData `batch` writing `forms/<id>` with `file` "
                f"`{rel}` and its question rows, then send `<artifact url>#<id>` in a message of its own, before and apart from "
                "any question. The turn cannot end until both are done.")
    if kind == "edit":
        return f"the developer chose to edit `{rel}` themselves; no form for it."
    return None


def link_in_transcript(path, form_id, start):
    """Whether a message of the assistant after line `start` of the transcript carries `<artifact url>#<form id>`.
    Tool results, prompts and subagent transcripts do not count."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, TypeError):
        return None
    pattern = re.compile(URL + "#" + re.escape(form_id) + r"(?![A-Za-z0-9._-])")
    for line in lines[start:]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("type") != "assistant" or row.get("isSidechain"):
            continue
        content = (row.get("message") or {}).get("content")
        texts = [content] if isinstance(content, str) else [b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text"]
        if any(pattern.search(t) for t in texts):
            return True
    return False


def transcript_lines(path):
    try:
        with open(path, encoding="utf-8") as f:
            return sum(1 for _ in f)
    except (OSError, TypeError):
        return 0


# ---------------------------------------------------------------- events

def is_write_to_data(command):
    folder = os.path.abspath(pf.data_dir())
    return folder in command and re.search(r">|\btee\b|\bmv\b|\bcp\b|\brm\b|\bsed\s+-i|\bpython|\bperl|\bdd\b", command) is not None


def pre(event, project):
    tool, ti = event.get("tool_name"), event.get("tool_input") or {}
    state = pf.load_session(event.get("session_id"))
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        path = os.path.abspath(str(ti.get("file_path") or ti.get("notebook_path") or ""))
        if path.startswith(os.path.abspath(pf.data_dir()) + os.sep):
            raise Refusal("The question-forms preference and answers are the developer's, recorded by the plugin's mod after "
                          "its dialog; never written by hand.")
        return
    if tool == "AskUserQuestion":
        text = json.dumps(ti.get("questions") or [])
        for rel, entry in state["files"].items():
            form_id = entry.get("formId")
            if form_id and re.search(URL + "#" + re.escape(form_id) + r"(?![A-Za-z0-9._-])", text):
                raise Refusal(f"The form's link is not part of a question. Send `<artifact url>#{form_id}` in a message of its "
                              "own first, then ask the question without it.")
        return
    if tool != "Bash":
        return
    command = str(ti.get("command", ""))
    if re.search(r"preference\.py[\"']?\s+(set|answer|forget)\b", command) or is_write_to_data(command):
        raise Refusal("The question-forms preference is recorded by the plugin's mod with the developer's answer, never from "
                      "Bash. Open the dialog instead: AskUserQuestion with metadata {\"source\": \"question-forms:preference\"}.")
    step = re.search(r"\baidlc\S*\s+engine\s+orchestrate\s+(next|continue|report)\b", command)
    if not step:
        return
    stage = re.search(r"--stage[ =]+([A-Za-z0-9._-]+)", command)
    for rel, entry in state["files"].items():
        if not entry.get("formId") or entry.get("released"):
            continue
        if stage and f"/{stage.group(1)}/" not in "/" + rel.replace(os.sep, "/"):
            continue
        if has_empty_tag(entry.get("abs") or os.path.join(project, rel)):
            raise Refusal(f"`{rel}` still has empty [Answer]: tags and its form `{entry['formId']}` was opened. Read the form "
                          f"(ArtifactData `get` of `forms/{entry['formId']}`) and copy the developer's answers word for word "
                          "into the file (skill question-forms § 4) before the engine moves on. If the developer has not said "
                          "the form is done, ask them to.")


def post(event, project):
    tool, ti = event.get("tool_name"), event.get("tool_input") or {}
    response = event.get("tool_response")
    if isinstance(response, dict) and (response.get("is_error") or response.get("interrupted")):
        return
    sid = event.get("session_id")
    state = pf.load_session(sid)
    notes = []
    if tool in ("Write", "Edit", "MultiEdit"):
        path = str(ti.get("file_path") or "")
        if not path or not is_questions_file(path):
            return
        rel = rel_of(project, path)
        entry = state["files"].get(rel)
        if entry is None:
            entry = state["files"][rel] = {"abs": os.path.abspath(path)}
            pf.clear_ask(project, rel)  # an ask answers one file once; a file written afresh asks afresh
        pf.save_session(sid, state)
        kind = status(project, rel, entry)
        text = next_step(kind, rel, entry)
        if text and kind != "never":
            notes.append(text)
    elif tool == "ArtifactData":
        text = json.dumps(ti)
        if ti.get("action") in ("get", "list", "query", "delete") or "forms/" not in text:
            return
        for rel, entry in state["files"].items():
            if entry.get("formId") or rel not in text:
                continue
            found = re.search(r"forms/([a-z0-9._-]+)", text)
            if not found:
                continue
            entry["formId"] = found.group(1)
            entry["transcriptLine"] = transcript_lines(event.get("transcript_path"))
            notes.append(next_step("form", rel, entry))
        pf.save_session(sid, state)
    elif tool == "AskUserQuestion":
        if not str((ti.get("metadata") or {}).get("source", "")).startswith("question-forms:"):
            return
        for rel, entry in state["files"].items():
            kind = status(project, rel, entry)
            if kind in ("pref", "ask", "form") and not (kind == "form" and entry.get("formId")):
                notes.append(next_step(kind, rel, entry))
    if notes:
        say("PostToolUse", " ".join(notes))


def stop(event, project):
    sid = event.get("session_id")
    state = pf.load_session(sid)
    reasons = []
    for rel, entry in state["files"].items():
        if entry.get("released"):
            continue
        kind = status(project, rel, entry)
        if kind in ("pref", "ask"):
            reasons.append(next_step(kind, rel, entry))
        elif kind == "form":
            if not entry.get("formId"):
                reasons.append(next_step("form", rel, entry))
                continue
            if entry.get("linked"):
                continue
            found = link_in_transcript(event.get("transcript_path"), entry["formId"], int(entry.get("transcriptLine") or 0))
            if found:
                entry["linked"] = True
            else:
                reasons.append(next_step("form", rel, entry) if found is not None
                               else f"the transcript cannot be read, so whether the link of form `{entry['formId']}` was sent cannot be checked; send it in a message of its own.")
    if not reasons:
        state["stopBlocks"] = 0
        pf.save_session(sid, state)
        return
    if event.get("stop_hook_active"):
        blocks = int(state.get("stopBlocks") or 0)
    else:
        blocks = 0
    if blocks >= MAX_BLOCKS:
        state["stopBlocks"] = 0
        pf.save_session(sid, state)
        print(json.dumps({"systemMessage": f"question-forms: the turn was held {MAX_BLOCKS} times for a question form that is still "
                                           "not set up, and is let through now: " + " ".join(reasons)}))
        return
    state["stopBlocks"] = blocks + 1
    pf.save_session(sid, state)
    print(json.dumps({"decision": "block", "reason": "question-forms: this turn cannot end yet: " + " ".join(reasons)}))


def prompt(event, project):
    text = str(event.get("prompt") or "")
    if "question-forms:release" in text:
        pf.clear_session(event.get("session_id"))
        say("UserPromptSubmit", "the guard is cleared for this session: no questions file is pending and nothing is held back. "
                                "Say so in one line and go on.")
    elif "question-forms:preference" in text:
        say("UserPromptSubmit", "the developer wants to change their question-forms preference for this project. Open the "
                                "dialog: one AskUserQuestion with metadata {\"source\": \"question-forms:preference\"} and a "
                                "placeholder question (\"Show question forms?\", options \"Always\" and \"Ask\"). The mod "
                                "replaces it; do not answer it or ask anything else.")


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(event, dict):
        return 0
    name = event.get("hook_event_name")
    try:
        project = pf.project_dir(cwd=event.get("cwd"))
        if not os.path.isdir(os.path.join(project, "aidlc", "spaces")):
            return 0
        {"PreToolUse": pre, "PostToolUse": post, "Stop": stop, "UserPromptSubmit": prompt}.get(name, lambda *_: None)(event, project)
    except Refusal as why:
        print(f"{why} {HINT}", file=sys.stderr)
        return 2
    except Exception:  # never break the call
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
