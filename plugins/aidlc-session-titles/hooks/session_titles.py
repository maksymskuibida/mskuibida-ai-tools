#!/usr/bin/env python3
"""Keeps an AI-DLC session's title in step with the work it is on.

The title, separated by an em dash:

  - in a Unit's checkout, on a per-Unit stage:  `<unit> — <stage>`    e.g. `u4-day-navigation — Functional Design`
  - Build and Test, CI Pipeline, other phases:  `<phase> — <stage>`   e.g. `Construction — Build and Test`
  - a Construction stage outside a Unit's checkout (e.g. Functional Design): just `Construction`

What the session is on is read from the project, never from the assistant: the intent this session is bound to
(aidlc/.aidlc-sessions/<session>.binding.json), else the space's active-intent cursor, else its one live intent; the
stage from the state file's `Unit Stage`, else the engine's active directive when it is newer than the state file,
else `Current Stage`; the Unit from this checkout's claim (aidlc/.aidlc-unit-scope.json), else the directive's unit,
else `Active Unit`, and only on a per-Unit stage. Stage and phase names come from the project's stage graph
(.claude/tools/data/stage-graph.json), else the slug title-cased.

A session counts as an AI-DLC session once it shows it runs the workflow: an `aidlc` engine, unit or claim command
in Bash, an `aidlc*` skill, a prompt starting with `/aidlc`, or a binding file of its own. Other sessions in the
same repository are left alone.

How the title is set:

  1. UserPromptSubmit and SessionStart return it as `hookSpecificOutput.sessionTitle`, which the harness applies.
  2. In the desktop app the title can also change mid-turn, when a stage or a Unit claim moves on: PostToolUse
     tells the assistant, once per new title, to call `mcp__ccd_session_mgmt__set_session_title` with
     `session_id: "self"`. The call is recorded when it succeeds; a declined call is not asked for again.
  3. Stop refuses the end of the turn once per title while the desktop title is still behind.

The state lives in ~/.claude/aidlc-session-titles/<session>.json (AIDLC_SESSION_TITLES_DIR overrides the folder).
The hook does nothing outside an AI-DLC project, in a subagent, or on stdin it cannot read, and never fails the
call it sits beside. Standard library only.
"""

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

try:
    import fcntl
except ImportError:  # no advisory locks on this platform: the unique temp file below still keeps writes whole
    fcntl = None

STALE_DAYS = 14  # another session's state file untouched for this long is removed when a state is saved
JUDGE_RETRY_SECONDS = 600  # after a judge that could not answer, wait this long before asking again
JUDGE_TIMEOUT_SECONDS = 60
JUDGING_ENV = "AIDLC_SESSION_TITLES_JUDGING"  # set in the judge's own process so its hooks do nothing
JUDGE_CMD_ENV = "AIDLC_SESSION_TITLES_JUDGE_CMD"  # replaces `claude -p --model haiku …`; reads the prompt on stdin
SEPARATOR = " — "
RENAME_TOOL = "mcp__ccd_session_mgmt__set_session_title"
# The stages that run once per Unit; on any other the title names the phase.
PER_UNIT_STAGES = ("functional-design", "nfr-requirements", "nfr-design", "infrastructure-design", "code-generation")
# Construction stages that keep their name in the title outside a Unit's checkout; every other Construction stage is
# titled just `Construction` there.
NAMED_CONSTRUCTION_STAGES = ("build-and-test", "ci-pipeline")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
UNIT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SPACE_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
PHASE_HEADING = re.compile(r"^#{2,4}\s+([A-Z][A-Z ]*?)\s+PHASE\s*$")
STAGE_ROW = re.compile(r"^- \[[^\n]\]\s+([a-z0-9][a-z0-9-]*)\s+(?:—|–|--|-)\s+(?:EXECUTE|SKIP)\b")
# `aidlc engine …`, `aidlc unit …`, `aidlc --claim …`, also through a path or wrapper (`./aidlc`, `aidlc.js`).
ENGINE_CALL = re.compile(r"(?:^|[\s;&|(/])aidlc[\w.-]*\s+(?:engine|unit|--claim)\b")
AIDLC_PROMPT = re.compile(r"^\s*/aidlc[\w:-]*\b")


# ---------------------------------------------------------------- state

def state_dir():
    return os.environ.get("AIDLC_SESSION_TITLES_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude", "aidlc-session-titles")


def state_path(event):
    sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(event.get("session_id") or "default"))
    return os.path.join(state_dir(), sid + ".json")


def blank():
    """`aidlc`: the session runs the workflow. `emitted`: the title last handed to the harness. `applied`: the title
    the desktop app last confirmed. `asked`, `declined`, `blocked`: the title the assistant was last told to set,
    refused, or was stopped for. `judged`: the Haiku verdict on whether the session is a Unit session,
    {"unit", "verdict" (true, false, or null when the judge could not answer), "at"}."""
    return {"aidlc": False, "emitted": None, "applied": None, "asked": None, "declined": None, "blocked": None,
            "judged": None, "updated": time.time()}


def load(event):
    state = blank()
    try:
        with open(state_path(event), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return state
    if isinstance(data, dict):
        state["aidlc"] = data.get("aidlc") is True
        for key in ("emitted", "applied", "asked", "declined", "blocked"):
            if isinstance(data.get(key), str):
                state[key] = data[key]
        judged = data.get("judged")
        if isinstance(judged, dict) and isinstance(judged.get("unit"), str) and isinstance(judged.get("at"), (int, float)):
            state["judged"] = {"unit": judged["unit"], "verdict": judged.get("verdict") if isinstance(
                judged.get("verdict"), bool) else None, "at": judged["at"]}
    return state


def save(event, state):
    """Write the state whole: a temp file of its own (parallel tool calls run parallel hooks), then an atomic replace."""
    folder = state_dir()
    os.makedirs(folder, exist_ok=True)
    path = state_path(event)
    state["updated"] = time.time()
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(tmp)
        raise
    sweep(folder, path)


def sweep(folder, keep):
    """Remove the state files of other sessions that nobody touched for STALE_DAYS."""
    limit = time.time() - STALE_DAYS * 86400
    with contextlib.suppress(OSError):
        for name in os.listdir(folder):
            full = os.path.join(folder, name)
            if full != keep and name.endswith((".json", ".lock")) and os.path.getmtime(full) < limit:
                os.remove(full)


@contextlib.contextmanager
def state_lock(event):
    """One hook at a time reads, changes and writes a session's state. Best effort: without the lock the call goes on."""
    handle = None
    if fcntl is not None:
        try:
            os.makedirs(state_dir(), exist_ok=True)
            handle = open(state_path(event) + ".lock", "w", encoding="utf-8")  # noqa: SIM115
            fcntl.flock(handle, fcntl.LOCK_EX)
        except OSError:
            handle = None
    try:
        yield
    finally:
        if handle is not None:
            handle.close()


# ---------------------------------------------------------------- the project

def has_project(folder):
    return bool(folder) and os.path.isdir(os.path.join(folder, "aidlc", "spaces"))


def up_to_project(folder):
    """The folder, or the nearest parent, that holds aidlc/spaces; None when none does."""
    folder = os.path.abspath(folder) if folder else ""
    while folder:
        if has_project(folder):
            return folder
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    return None


def projects(event):
    """The AI-DLC projects the session may work in, the working directory first: in a git worktree
    CLAUDE_PROJECT_DIR is the main checkout, whose per-clone pointers are not the worktree's."""
    found = []
    for folder in (event.get("cwd"), os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()):
        project = up_to_project(folder)
        if project and project not in found:
            found.append(project)
    return found


def read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def read_json(path):
    text = read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def first_line(path):
    for line in (read_text(path) or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def safe_session_id(raw):
    return bool(raw) and re.fullmatch(r"[A-Za-z0-9._-]{1,180}", raw) is not None and raw not in (".", "..")


def binding(project, session_id):
    """(space, intent) this session is bound to, else None."""
    if not safe_session_id(session_id):
        return None
    record = read_json(os.path.join(project, "aidlc", ".aidlc-sessions", session_id + ".binding.json"))
    if not isinstance(record, dict):
        return None
    space, intent = record.get("space"), record.get("intent")
    if not isinstance(space, str) or not SPACE_NAME.match(space) or not isinstance(intent, str) or "/" in intent:
        return None
    return space, intent


def state_file(project, space, intent):
    return os.path.join(project, "aidlc", "spaces", space, "intents", intent, "aidlc-state.md")


def is_archived(text):
    return re.search(r"^- \*\*Status\*\*:\s*Archived\s*$", text, re.M) is not None


def live_intent(project, space, intent):
    text = read_text(state_file(project, space, intent)) if intent and "/" not in intent else None
    return text is not None and not is_archived(text)


def selected_intent(project, session_id):
    """(space, intent) the session is on: its binding, else the active space's cursor, else its one live intent."""
    bound = binding(project, session_id)
    if bound and live_intent(project, *bound):
        return bound
    space = first_line(os.path.join(project, "aidlc", "active-space"))
    if not SPACE_NAME.match(space or "") or not os.path.isdir(os.path.join(project, "aidlc", "spaces", space)):
        space = "default"
    intents = os.path.join(project, "aidlc", "spaces", space, "intents")
    cursor = first_line(os.path.join(intents, "active-intent"))
    if live_intent(project, space, cursor):
        return space, cursor
    try:
        names = sorted(os.listdir(intents))
    except OSError:
        return None
    live = [name for name in names if live_intent(project, space, name)]
    return (space, live[0]) if len(live) == 1 else None


def field(text, name):
    found = re.search(r"^\s*-\s*\*\*" + re.escape(name) + r"\*\*:[ \t]*(\S[^\n]*?)?\s*$", text, re.M)
    return (found.group(1) or "").strip() if found else ""


def step(intent_dir, text):
    """(stage, unit or '') the session is shown at: `Unit Stage`, else the active directive when nothing has written
    the state since it was issued, else `Current Stage`."""
    unit_stage = field(text, "Unit Stage").split(" ")[0]
    if SLUG.match(unit_stage):
        return unit_stage, ""
    current = (field(text, "Current Stage").split(" ") or [""])[0]
    current = current if SLUG.match(current) else ""
    directive_path = os.path.join(intent_dir, ".aidlc-engine", "active-directive.json")
    directive_at, state_at = mtime(directive_path), mtime(os.path.join(intent_dir, "aidlc-state.md"))
    if directive_at is None or state_at is None or directive_at < state_at:
        return current, ""
    directive = read_json(directive_path)
    if not isinstance(directive, dict) or directive.get("delivery") == "superseded":
        return current, ""
    stage = directive.get("stage")
    if not isinstance(stage, str) or not SLUG.match(stage):
        return current, ""
    unit = directive.get("unit")
    return stage, (unit if isinstance(unit, str) and UNIT_NAME.match(unit) else "")


def claimed_unit(project, space, intent_uuid):
    """The Unit this checkout has claimed for the intent (the engine's scope file), '' when none."""
    scope = read_json(os.path.join(project, "aidlc", ".aidlc-unit-scope.json"))
    if not isinstance(scope, dict):
        return ""
    unit = scope.get("unit")
    if not isinstance(unit, str) or not UNIT_NAME.match(unit):
        return ""
    if isinstance(scope.get("space"), str) and scope["space"] != space:
        return ""
    if intent_uuid and isinstance(scope.get("intent_uuid"), str) and scope["intent_uuid"] != intent_uuid:
        return ""
    return unit


def intent_uuid(project, space, intent):
    rows = read_json(os.path.join(project, "aidlc", "spaces", space, "intents", "intents.json"))
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("uuid"), str):
            continue
        if row.get("dirName") == intent:
            return row["uuid"]
        if isinstance(row.get("slug"), str) and intent == row["slug"] + "-" + row["uuid"].replace("-", "")[-16:]:
            return row["uuid"]
    return ""


def stage_graph(project):
    """{slug: (name, phase)} from the project's stage graph; empty when there is none."""
    graph = read_json(os.path.join(project, ".claude", "tools", "data", "stage-graph.json"))
    out = {}
    for row in graph if isinstance(graph, list) else []:
        if isinstance(row, dict) and isinstance(row.get("slug"), str):
            name = row.get("name") if isinstance(row.get("name"), str) and row["name"].strip() else ""
            phase = row.get("phase") if isinstance(row.get("phase"), str) else ""
            out[row["slug"]] = (name.strip(), phase.strip())
    return out


def phase_in_state(text, stage):
    """The phase whose `### <NAME> PHASE` heading the stage's row sits under, '' when it is not listed."""
    phase = ""
    for line in text.splitlines():
        heading = PHASE_HEADING.match(line.strip())
        if heading:
            phase = heading.group(1)
            continue
        row = STAGE_ROW.match(line.strip())
        if row and row.group(1) == stage:
            return phase
    return ""


def titled(slug):
    return " ".join(word.capitalize() for word in re.split(r"[-_\s]+", slug) if word)


def user_prompts(event, limit=4, width=600):
    """The session's first user prompts (from its transcript) and the one being submitted, each cut to `width`."""
    prompts = []
    for line in (read_text(str(event.get("transcript_path") or "")) or "").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        message = row.get("message") if isinstance(row, dict) and row.get("type") == "user" else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            content = " ".join(str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text")
        if isinstance(content, str) and content.strip() and not content.lstrip().startswith("<"):
            prompts.append(content.strip()[:width])
        if len(prompts) >= limit:
            break
    current = str(event.get("prompt") or "").strip()
    if current and current[:width] not in prompts:
        prompts.append(current[:width])
    return prompts


def branch_of(project):
    try:
        done = subprocess.run(["git", "-C", project, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True,
                              text=True, timeout=5)
        return done.stdout.strip() if done.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def judge_prompt(project, unit, stage, prompts):
    shown = "\n".join(f"{n}. {text}" for n, text in enumerate(prompts, 1))
    return (
        "You classify one Claude Code session that runs inside an AI-DLC Unit's checkout (a git worktree claimed for "
        f"the Unit `{unit}`).\n\n"
        "A UNIT SESSION works on that Unit itself: its stages (functional design, NFR requirements/design, "
        "infrastructure design, code generation), its code, its plan, its approval gates, or runs `aidlc` engine/unit "
        "commands for it.\n"
        "NOT A UNIT SESSION: a session that was merely started from the Unit's branch or checkout to change something "
        "else - the workspace, tooling, plugins, config, CI, docs or another project - and does not advance the Unit.\n\n"
        f"Checkout: {project}\nBranch: {branch_of(project) or 'unknown'}\nClaimed Unit: {unit}\nWorkflow stage: {stage}\n"
        f"The session's first prompts:\n{shown}\n\n"
        "If the prompts are only a bare /aidlc command or say nothing against the Unit, it is a Unit session.\n"
        'Reply with one line of JSON and nothing else: {"unit_session": true|false, "reason": "<short>"}')


def ask_judge(prompt):
    """True/False from the judge, None when it cannot answer."""
    if os.environ.get(JUDGING_ENV):
        return None
    command = os.environ.get(JUDGE_CMD_ENV)
    command = [command] if command else ([shutil.which("claude"), "-p", "--model", "haiku", "--no-session-persistence",
                                          "--disable-slash-commands", "--tools", ""] if shutil.which("claude") else None)
    if not command:
        return None
    try:
        done = subprocess.run(command, input=prompt, capture_output=True, text=True, timeout=JUDGE_TIMEOUT_SECONDS,
                              env={**os.environ, JUDGING_ENV: "1"}, cwd=tempfile.gettempdir())
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.search(r"\{[^{}]*\"unit_session\"[^{}]*\}", done.stdout or "")
    try:
        verdict = json.loads(found.group(0)).get("unit_session") if found else None
    except ValueError:
        return None
    return verdict if isinstance(verdict, bool) else None


def is_unit_session(event, state, project, unit, stage):
    """Whether the session in a claimed Unit's checkout works on the Unit: True, False, or None while it has no prompt
    to be judged by. The verdict is kept in the state per Unit; one the judge could not give is retried later."""
    judged = state["judged"]
    if judged and judged["unit"] == unit and (judged["verdict"] is not None
                                              or time.time() - judged["at"] < JUDGE_RETRY_SECONDS):
        return judged["verdict"] is not False
    prompts = user_prompts(event)
    if not prompts:
        return None
    verdict = ask_judge(judge_prompt(project, unit, stage, prompts))
    state["judged"] = {"unit": unit, "verdict": verdict, "at": time.time()}
    return verdict is not False


def expected_title(event, state, project):
    """The title the session should carry, or None when the project does not say what it is on or the session is
    not a Unit session in a Unit's checkout."""
    selected = selected_intent(project, str(event.get("session_id") or ""))
    if not selected:
        return None
    space, intent = selected
    intent_dir = os.path.dirname(state_file(project, space, intent))
    text = read_text(state_file(project, space, intent)) or ""
    stage, _ = step(intent_dir, text)
    if not stage:
        return None
    name, phase = stage_graph(project).get(stage, ("", ""))
    stage_name = name or titled(stage)
    unit = claimed_unit(project, space, intent_uuid(project, space, intent))
    if unit and stage in PER_UNIT_STAGES:
        session = is_unit_session(event, state, project, unit, stage)
        if session is None or session is False:
            return None
        return unit + SEPARATOR + stage_name
    phase = phase or phase_in_state(text, stage)
    if not phase:
        return None
    if phase.lower() == "construction" and not unit and stage not in NAMED_CONSTRUCTION_STAGES:
        return titled(phase)  # not in a Unit's checkout: the phase alone
    return titled(phase) + SEPARATOR + stage_name


def title_for(event, state):
    for project in projects(event):
        title = expected_title(event, state, project)
        if title:
            return title
    return None


def bound_here(event):
    sid = str(event.get("session_id") or "")
    return any(binding(project, sid) for project in projects(event))


# ---------------------------------------------------------------- what shows the session runs AI-DLC

def shows_aidlc(event):
    tool, ti = event.get("tool_name"), event.get("tool_input") or {}
    if not isinstance(ti, dict):
        return False
    if tool == "Bash":
        return ENGINE_CALL.search(str(ti.get("command") or "")) is not None
    if tool == "Skill":
        return str(ti.get("skill") or "").split(":")[-1].startswith("aidlc")
    return False


def in_desktop():
    return os.environ.get("CLAUDE_CODE_ENTRYPOINT") == "claude-desktop"


def failed(response, title):
    """The rename did not happen: an error result, or the developer declined it. The title is cut out of the text
    first, so a Unit called `u3-error-pages` does not read as a failure."""
    if isinstance(response, dict) and (response.get("isError") or response.get("is_error")):
        return True
    text = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
    text = text.replace(title, "").replace(json.dumps(title, ensure_ascii=False)[1:-1], "")
    return re.search(r"\b(declin|denied|refus|not approved|failed|error)", text, re.I) is not None


# ---------------------------------------------------------------- output

def emit(event_name, title=None, context=None):
    out = {"hookEventName": event_name}
    if title:
        out["sessionTitle"] = title
    if context:
        out["additionalContext"] = "aidlc-session-titles: " + context
    print(json.dumps({"hookSpecificOutput": out}))


def rename_instruction(title):
    return (f'this AI-DLC session is now on "{title}". Rename it now: call {RENAME_TOOL} with '
            f'{{"session_id": "self", "title": "{title}"}}, then carry on. Do not mention the rename to the developer.')


# ---------------------------------------------------------------- events

def on_prompt(event, state):
    """UserPromptSubmit and SessionStart: hand the harness the title when it changed since last time."""
    changed = False
    if not state["aidlc"]:
        prompt = str(event.get("prompt") or "")
        if not (AIDLC_PROMPT.match(prompt) or bound_here(event)):
            return False
        state["aidlc"] = changed = True
    title = title_for(event, state)
    if not title or title == state["emitted"]:
        return changed
    state["emitted"] = title
    if not in_desktop():
        state["applied"] = title  # outside the desktop app the harness title is the only one
    emit(event["hook_event_name"], title=title)
    return True


def on_tool(event, state):
    tool = event.get("tool_name")
    if tool == RENAME_TOOL:
        ti = event.get("tool_input") or {}
        title = ti.get("title") if isinstance(ti, dict) and ti.get("session_id") == "self" else None
        if not isinstance(title, str):
            return False
        if event.get("hook_event_name") == "PostToolUseFailure" or failed(event.get("tool_response"), title):
            state["declined"] = title
        else:
            state["applied"] = title
        return True
    changed = False
    if not state["aidlc"] and (shows_aidlc(event) or bound_here(event)):
        state["aidlc"] = changed = True
    if not state["aidlc"] or not in_desktop():
        return changed
    title = title_for(event, state)
    if not title or title in (state["applied"], state["asked"], state["declined"]):
        return changed
    state["asked"] = title
    emit(event["hook_event_name"], context=rename_instruction(title))
    return True


def on_stop(event, state):
    """Refuse the end of the turn once per title while the desktop title is behind."""
    if not state["aidlc"] or not in_desktop() or event.get("stop_hook_active"):
        return False
    title = title_for(event, state)
    if not title or title in (state["applied"], state["declined"], state["blocked"]):
        return False
    state["blocked"] = title
    print(json.dumps({"decision": "block", "reason": "aidlc-session-titles: " + rename_instruction(title)}))
    return True


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(event, dict) or event.get("agent_id") or os.environ.get(JUDGING_ENV):
        return 0  # a subagent cannot rename the session it runs in; the judge's own session is not a session to title
    name = event.get("hook_event_name")
    handler = {"UserPromptSubmit": on_prompt, "SessionStart": on_prompt, "PostToolUse": on_tool,
               "PostToolUseFailure": on_tool, "Stop": on_stop}.get(name)
    if handler is None or not projects(event):
        return 0
    try:
        with state_lock(event):
            state = load(event)
            before = json.dumps(state["judged"])
            if handler(event, state) | (json.dumps(state["judged"]) != before):
                save(event, state)
    except Exception:  # never break the call this hook sits beside
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
