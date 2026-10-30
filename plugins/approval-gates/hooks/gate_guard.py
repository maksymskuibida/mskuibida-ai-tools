#!/usr/bin/env python3
"""Guard for the AI-DLC approval gate: the developer reads the stage's documents in a page before being asked.

The order, for the session that opens a gate:

 1. The engine's `aidlc engine orchestrate report --stage S --result awaiting-approval|revised` opens the gate.
    This hook notices it (PostToolUse Bash) and tells the assistant to publish the stage's documents:
    `scripts/gate_bundle.py` builds the rows, one ArtifactData batch writes them into the developer's
    "AI-DLC approval gates" artifact.
 2. This hook notices the write of a `gates` row for the stage (PostToolUse ArtifactData).
 3. Until that has happened, the Approval question (header `Approval`, options such as Approve) and the
    approved or rejected report are refused (PreToolUse). The page's link `<artifact url>#<gate id>` goes
    to the developer in a message of its own before the question: the question is refused until a message
    of the assistant in the session's transcript (the `transcript_path` of the hook input) carries that
    link, and a question that carries the link itself is refused, so the dialog stays readable.
 4. A write that sets `status: "decided"`, or carries `decision` or `notes`, on a `gates` row is refused: those
    belong to the developer, who writes them in the page.
 5. When the developer answers Request Changes, the assistant is told to read the notes they left in the page.
 6. A test plan (a `plans/<id>` row written into the AI-DLC test plans artifact) has the same order: the write is
    noticed (PostToolUse ArtifactData) and the exact link `<artifact url>#<plan id>` is named; until a text message of the
    assistant written after the write carries it, every AskUserQuestion is refused, and a turn that ends with the link
    never sent is blocked once (Stop). A plan written again needs its link again.

Under the unit-end rhythm (the Unit's claim, `aidlc/.aidlc-unit-scope.json`, says `gate_rhythm: "unit-end"`, or the
directive carries `unit_gate: "unit-end"`) a Unit has two pages instead of one per stage: the plan page at the Code
Generation plan approval and the unit-end page at the Unit's one gate. Both are `bundles/<id>` rows built by
`scripts/unit_bundle.py`, and the same order holds with them in place of the `gates` row: the question and the closing
report wait for the row of the right page, and the link goes in a message of its own. Per-stage gates are unchanged.

The plan approval is also opened by the engine's own ask: when the active directive is an `ask` with `ask_type:
"plan-approval"` (what `aidlc engine orchestrate next` returns once the plan is written), the gate is open for that Unit
even though no command of the assistant named it. Any question offering Approve Plan, Approve or Accept as-is while a
gate is open is the gate's question, whatever its header.

The state lives in ~/.claude/approval-gates/<session>.json (APPROVAL_GATES_DIR overrides the folder) and is
changed by this hook only. The developer clears it by typing /approval-gates:release.

Fires on PreToolUse (refuses with exit code 2 and the reason on stderr), PostToolUse (records, tells the
assistant what to do) and UserPromptSubmit (the release command). It does nothing outside an AI-DLC project
(no `aidlc/spaces` under $CLAUDE_PROJECT_DIR, else the working directory), does nothing on stdin it cannot
read, and never fails a PostToolUse or UserPromptSubmit call. A PreToolUse call that is known to be guarded
and cannot be checked is refused. Standard library only.
"""

import contextlib
import datetime
import json
import os
import re
import shlex
import sys
import tempfile
import time

try:
    import fcntl
except ImportError:  # no advisory locks on this platform: the unique temp file below still keeps writes whole
    fcntl = None

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STALE_DAYS = 14  # another session's state file untouched for this long is removed when a state is saved
GATE_LABELS = {"approve", "approve plan", "accept as-is"}
CLOSING = {"approved", "rejected", "accepted"}
OPENING = {"awaiting-approval", "revised"}
RELEASE_PROMPT = re.compile(r"^\s*/(?:(approval-gates):)?release\b")
OPS = re.compile(r"^[();<>|&]+$")
RELEASE_HINT = "(Blocked by the approval-gates plugin. The developer can release it by typing /approval-gates:release.)"


class Refusal(Exception):
    pass


# ---------------------------------------------------------------- state

def state_dir():
    return os.environ.get("APPROVAL_GATES_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "approval-gates")


def state_path(event):
    sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(event.get("session_id") or "default"))
    return os.path.join(state_dir(), sid + ".json")


def blank():
    return {"pending": None, "published": {}, "plans": {}, "updated": time.time()}


def normalize(data):
    state = blank()
    if isinstance(data, dict):
        if isinstance(data.get("pending"), dict):
            state["pending"] = data["pending"]
        if isinstance(data.get("published"), dict):
            state["published"] = {k: v for k, v in data["published"].items() if isinstance(v, dict)}
        if isinstance(data.get("plans"), dict):
            state["plans"] = {k: v for k, v in data["plans"].items() if isinstance(v, dict)}
        if isinstance(data.get("updated"), (int, float)):
            state["updated"] = data["updated"]
    return state


def load(event):
    """The session's state; a fresh one when there is none. A state that cannot be read refuses."""
    try:
        with open(state_path(event), encoding="utf-8") as f:
            return normalize(json.load(f))
    except FileNotFoundError:
        return blank()
    except (OSError, ValueError) as exc:
        raise Refusal(f"the approval-gates state of this session cannot be read ({exc}).") from None


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


def drop(event):
    for path in (state_path(event), state_path(event) + ".lock"):
        with contextlib.suppress(OSError):
            os.remove(path)


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


def project_dir(event):
    """The AI-DLC project the session works in. The working directory wins over CLAUDE_PROJECT_DIR when both hold a
    project: in a git worktree CLAUDE_PROJECT_DIR is the main checkout, whose per-clone pointers (aidlc/active-space,
    intents/active-intent, .aidlc-engine/) are not the worktree's. Of the folders that hold a project, the first whose
    active intent resolves is it; else the first one; else CLAUDE_PROJECT_DIR or the working directory as given."""
    given = [event.get("cwd"), os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()]
    found = []
    for folder in given:
        project = up_to_project(folder)
        if project and project not in found:
            found.append(project)
    for project in found:
        if intent_root(project)[1]:
            return project
    return found[0] if found else (os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd())


def first_line(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    return line.strip()
    except OSError:
        pass
    return ""


def intent_root(project):
    """(intent name, record folder) of the active intent, or (None, None)."""
    space = first_line(os.path.join(project, "aidlc", "active-space"))
    if not space:
        return None, None
    intents = os.path.join(project, "aidlc", "spaces", space, "intents")
    intent = first_line(os.path.join(intents, "active-intent"))
    return (intent, os.path.join(intents, intent)) if intent else (None, None)


def current_stage(project):
    """(stage, unit) the engine is at: the active directive's `stage` and `unit`, else the `Current Stage` line of
    aidlc-state.md. None when neither can be read."""
    _intent, root = intent_root(project)
    if not root:
        return None
    try:
        with open(os.path.join(root, ".aidlc-engine", "active-directive.json"), encoding="utf-8") as f:
            directive = json.load(f)
        stage = directive.get("stage")
        if isinstance(stage, str) and stage.strip():
            unit = directive.get("unit")
            return stage.strip(), (unit.strip() if isinstance(unit, str) and unit.strip() else None)
    except (OSError, ValueError, AttributeError):
        pass
    try:
        with open(os.path.join(root, "aidlc-state.md"), encoding="utf-8") as f:
            found = re.search(r"^\s*-\s*\*\*Current Stage\*\*:[ \t]*([a-z0-9][a-z0-9-]*)", f.read(), re.M)
        if found:
            return found.group(1), None
    except OSError:
        pass
    return None


UNIT_END_STAGE = "code-generation"  # the last per-Unit stage: its plan approval and its gate are a Unit's two pages


def make_key(stage, unit):
    return stage + (("/" + unit) if unit else "")


def unit_rhythm(project, unit, stage=UNIT_END_STAGE):
    """"unit-end" when the gate in hand is a Unit's under the unit-end rhythm, else "per-stage". Only the Code
    Generation gates of the Unit (its plan approval and its unit-end gate) are the Unit's two pages: the claim's scope
    stamp (aidlc/.aidlc-unit-scope.json, written by `aidlc unit claim`) names the Unit and its rhythm. A gate of any other
    stage is unit-end only when the active directive says so for that stage (`unit_gate: "unit-end"`)."""
    if not unit:
        return "per-stage"
    if stage != UNIT_END_STAGE:
        return "unit-end" if directive_unit_gate(project, stage, unit) else "per-stage"
    if directive_unit_gate(project, stage, unit):
        return "unit-end"
    try:
        with open(os.path.join(project, "aidlc", ".aidlc-unit-scope.json"), encoding="utf-8") as f:
            stamp = json.load(f)
        if isinstance(stamp, dict) and stamp.get("unit") == unit and stamp.get("gate_rhythm") == "unit-end":
            return "unit-end"
    except (OSError, ValueError):
        pass
    return "per-stage"


def directive_unit_gate(project, stage, unit):
    """True when the active directive is the unit-end gate of this stage and Unit."""
    _intent, root = intent_root(project)
    if not root:
        return False
    try:
        with open(os.path.join(root, ".aidlc-engine", "active-directive.json"), encoding="utf-8") as f:
            directive = json.load(f)
    except (OSError, ValueError):
        return False
    return isinstance(directive, dict) and directive.get("unit") == unit and directive.get("unit_gate") == "unit-end" \
        and directive.get("stage", stage) == stage


def directive_plan_ask(project):
    """(stage, unit, written at) when the active directive is the engine's plan-approval ask for a Unit, else None."""
    _intent, root = intent_root(project)
    if not root:
        return None
    path = os.path.join(root, ".aidlc-engine", "active-directive.json")
    try:
        with open(path, encoding="utf-8") as f:
            directive = json.load(f)
        written = os.path.getmtime(path)
    except (OSError, ValueError):
        return None
    if not isinstance(directive, dict) or directive.get("kind") != "ask" or directive.get("ask_type") != "plan-approval":
        return None
    unit = directive.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        return None
    stage = directive.get("stage") if isinstance(directive.get("stage"), str) and directive.get("stage") else UNIT_END_STAGE
    return stage, unit.strip(), written


def sync_pending(state, project):
    """Open the plan approval the engine is asking, when the state does not have it open yet. True when it opened."""
    ask = directive_plan_ask(project)
    if not ask:
        return False
    stage, unit, written = ask
    pending = state["pending"]
    if pending and pending.get("kind") == "plan" and pending.get("stage") == stage and pending.get("unit") == unit:
        return False
    state["pending"] = {"stage": stage, "unit": unit, "opened_at": written, "kind": "plan",
                        "rhythm": unit_rhythm(project, unit, stage)}
    return True


def page_of(pending):
    """The bundle page a unit-end-rhythm gate needs: the plan page at the plan approval, else the unit-end page."""
    return "plan" if (pending or {}).get("kind") == "plan" else "unit-end"


BUNDLE_ID = re.compile(r"^(?P<head>[a-z0-9][a-z0-9._-]*)-(?P<page>plan|unit-end)-v\d+-(?P<stamp>\d{8}[Tt]\d{4})$")


# ---------------------------------------------------------------- tool calls

def questions_of(tool_input):
    qs = (tool_input or {}).get("questions")
    return [q for q in qs if isinstance(q, dict)] if isinstance(qs, list) else []


def norm(text):
    return re.sub(r"\s+", " ", str(text)).strip().strip('"').lower()


def labels(question):
    return {norm(o.get("label", "")) for o in question.get("options") or [] if isinstance(o, dict)}


def answers_of(response):
    """{question: answer} from an AskUserQuestion tool response (`answers`, or the text form)."""
    if isinstance(response, dict):
        ans = response.get("answers")
        if isinstance(ans, dict):
            return {str(q): (", ".join(map(str, a)) if isinstance(a, list) else str(a)) for q, a in ans.items()}
    text = flat(response)
    return {m.group(1): m.group(2) for m in re.finditer(r'"((?:[^"\\]|\\.)*)"="((?:[^"\\]|\\.)*)"', text)}


def flat(response):
    if isinstance(response, str):
        return response
    if isinstance(response, list):
        return "\n".join(flat(r) for r in response)
    if isinstance(response, dict):
        if isinstance(response.get("text"), str):
            return response["text"]
        return json.dumps(response, ensure_ascii=False)
    return ""


def writes_of(tool_input):
    """[(op, collection, doc_id, data or None, url)] for an ArtifactData write call."""
    action = (tool_input or {}).get("action")
    url = (tool_input or {}).get("url", "")
    if action == "batch":
        return [(w.get("op"), w.get("collection", ""), w.get("doc_id", ""), payload(w), url)
                for w in tool_input.get("writes") or [] if isinstance(w, dict)]
    if action in ("set", "update", "delete", "str_replace"):
        data = payload(tool_input)
        if action == "str_replace":
            data = {tool_input.get("field", ""): tool_input.get("new_str", "")}
        return [(action, tool_input.get("collection", ""), tool_input.get("doc_id", ""), data, url)]
    return []


def payload(w):
    if isinstance(w.get("data"), dict):
        return w["data"]
    path = w.get("file_path")
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return None  # unreadable: the caller treats an unknown payload as unsafe
    return {}


def failed(response):
    """True when a tool response says the call did not succeed."""
    if isinstance(response, dict):
        return bool(response.get("is_error") or response.get("error"))
    return isinstance(response, str) and response.lstrip().lower().startswith("error")


# ---------------------------------------------------------------- engine commands

def option_map(tokens):
    """{'stage': 'x', 'result': 'y'} from `--stage x --result y` and `--stage=x` tokens."""
    found, i = {}, 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("--") and len(tok) > 2:
            if "=" in tok:
                name, _, value = tok[2:].partition("=")
                found[name] = value
            elif i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                found[tok[2:]] = tokens[i + 1]
                i += 1
        i += 1
    return found


def from_tokens(seg):
    """The engine calls one simple command makes: [{'kind': 'report'|'decision', ...}]."""
    calls = []
    for i in range(1, len(seg) - 2):
        if not os.path.basename(seg[i - 1]).startswith("aidlc"):
            continue
        triple = seg[i:i + 3]
        opts = option_map(seg[i + 3:])
        if triple == ["engine", "orchestrate", "report"]:
            calls.append({"kind": "report", "stage": opts.get("stage"), "result": opts.get("result"),
                          "unit": opts.get("unit")})
        elif triple == ["engine", "log", "decision"]:
            calls.append({"kind": "decision", "stage": opts.get("stage"), "checkpoint": opts.get("checkpoint"),
                          "unit": opts.get("unit")})
        elif triple == ["engine", "log", "answer"]:
            calls.append({"kind": "answer", "stage": opts.get("stage"), "checkpoint": opts.get("checkpoint"),
                          "unit": opts.get("unit"), "details": opts.get("details")})
    return calls


def tokens_of(line):
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return list(lexer)


def regex_calls(command):
    """The fallback when shlex cannot parse the command."""
    def grab(name, text):
        found = re.search(r"--" + name + r"[= ]\s*[\"']?([\w.-]+)", text)
        return found.group(1) if found else None

    calls = []
    for m in re.finditer(r"aidlc\S*\s+engine\s+(orchestrate\s+report|log\s+decision)\b([^;&|\n]*)", command):
        rest = m.group(2)
        if m.group(1).startswith("orchestrate"):
            calls.append({"kind": "report", "stage": grab("stage", rest), "result": grab("result", rest),
                          "unit": grab("unit", rest)})
        else:
            calls.append({"kind": "decision", "stage": grab("stage", rest), "checkpoint": grab("checkpoint", rest),
                          "unit": grab("unit", rest)})
    return calls


def engine_calls(command):
    """The `aidlc engine orchestrate report` and `aidlc engine log decision` calls in a shell command line,
    parsed with shlex and split on `&&`, `;`, `|` and newlines (no other shell structure is followed)."""
    if "aidlc" not in command:
        return []
    calls = []
    try:
        for line in command.splitlines():
            seg = []
            for tok in tokens_of(line) + [";"]:
                if OPS.match(tok):
                    calls.extend(from_tokens(seg))
                    seg = []
                else:
                    seg.append(tok)
    except ValueError:
        return regex_calls(command)
    return calls


# ---------------------------------------------------------------- gates

def names_pull_request(text):
    if re.search(r"/pull/\d+", text):
        return True
    text = re.sub(r"https?://\S+", " ", text)
    return bool(re.search(r"(?<![\w/.#&-])#\d+(?![\w-])|[\w.-]+/[\w.-]+#\d+(?![\w-])", text))


def is_gate(question):
    """An AI-DLC Approval question: header Approval, an approving option, and no pull request named in it."""
    if norm(question.get("header", "")) != "approval" or not labels(question) & GATE_LABELS:
        return False
    return not names_pull_request(str(question.get("question", "")))


def gate_questions(state, questions):
    """The gate's questions among these: an Approval question, or, while a gate is open, any question offering to
    approve (Approve Plan, Approve, Accept as-is) that names no pull request, whatever its header."""
    found = []
    for q in questions:
        if is_gate(q) or (state["pending"] and labels(q) & GATE_LABELS and not names_pull_request(str(q.get("question", "")))):
            found.append(q)
    return found


def publish_instruction(stage, unit, page=None):
    if page:
        script = os.path.join(PLUGIN_ROOT, "scripts", "unit_bundle.py")
        return (f"this Unit has the unit-end rhythm, so its {'plan' if page == 'plan' else 'unit-end'} page is one gate bundle: run "
                f"`python3 \"{script}\" draft --page {page} --unit {unit} --out <a scratch file>`, do what it lists under todo, "
                f"run `... finalize --bundle <that file> --out <a scratch folder>`, write its writes.json with one ArtifactData "
                "batch into the AI-DLC unit approvals artifact (a `bundles/<id>` row; never a per-stage `gates/` row, never "
                "the AI-DLC approval gates artifact), and give the developer the link `<artifact url>#<bundle id>` in "
                "a text block of the same response that makes the question, before the AskUserQuestion call (never inside the "
                "question, and never end the turn on the link alone)")
    script = os.path.join(PLUGIN_ROOT, "scripts", "gate_bundle.py")
    cmd = f'python3 "{script}" --stage {stage}' + (f" --unit {unit}" if unit else "")
    return (f"run `{cmd} --why <first|revision> --summary-file <a file holding your summary> --out <a scratch folder>`, "
            "write the rows of its writes.json with one ArtifactData batch, and give the developer the link "
            "`<artifact url>#<gate id>` in a text block of the same response that makes the question, before the "
            "AskUserQuestion call (never inside the question, and never end the turn on the link alone)")


def target_of(state, project, call_stage=None, call_unit=None):
    """(stage, unit, opened_at or None) the gate in hand is about."""
    pending = state["pending"]
    if call_stage:
        unit = call_unit
        if pending and pending.get("stage") == call_stage and not unit:
            unit = pending.get("unit")
        else:
            cur = current_stage(project)
            if not unit and cur and cur[0] == call_stage:
                unit = cur[1]
        stage = call_stage
    elif pending:
        stage, unit = pending.get("stage"), pending.get("unit")
    else:
        cur = current_stage(project)
        if not cur:
            return None, None, None
        stage, unit = cur
    opened = None
    if pending and pending.get("stage") == stage and (pending.get("unit") or None) == (unit or None):
        opened = pending.get("opened_at")
    return stage, unit, opened


def tested_first(pub, stage, unit):
    """The developer answered Test first on this page: the gate is asked again only after the test plan, about a page
    republished with its outcome (unit_bundle.py draft --tested)."""
    if pub.get("test_first"):
        raise Refusal("The developer answered Test first on this unit-end page, so the gate is not asked again until the "
                      "test plan is done and the page is republished with its outcome: run test_plan.py finish, then "
                      f"`unit_bundle.py draft --page unit-end --unit {unit} --tested <test-plan.json> ...`, finalize, write the "
                      "new bundle row and send its link. (If the developer does not want to test after all, they type "
                      "/approval-gates:release.)")


def require_published(state, project, stage, unit, opened):
    """The record of this stage's gate page, or a Refusal when it was not published since the gate opened. A row
    recorded by its id alone (the stage was unknown when it was written) counts when its id names this stage. Under the
    unit-end rhythm the page is the Unit's bundle of the page the gate needs."""
    pending = state["pending"]
    if pending and pending.get("rhythm") == "unit-end" and pending.get("stage") == stage and (pending.get("unit") or None) == (unit or None):
        page = page_of(pending)
        pub = state["published"].get(make_key(stage, unit) + "@" + page)
        if not pub or (isinstance(opened, (int, float)) and pub.get("at", 0) < opened):
            raise Refusal(f"The developer reads the Unit's {'plan' if page == 'plan' else 'unit-end'} page before being asked. "
                          f"Publish it first: {publish_instruction(stage, unit, page)}.")
        return pub
    if not (pending and pending.get("stage") == stage and (pending.get("unit") or None) == (unit or None)) \
            and unit_rhythm(project, unit, stage) == "unit-end":
        # The gate was opened where this session's state did not see it (another session, a subagent, the engine's
        # own directive): the Unit's claim still says its gate is the unit-end page.
        pub = state["published"].get(make_key(stage, unit) + "@unit-end")
        if not pub:
            raise Refusal("The developer reads the Unit's unit-end page before being asked. "
                          f"Publish it first: {publish_instruction(stage, unit, 'unit-end')}.")
        return pub
    pub = state["published"].get(make_key(stage, unit))
    if not pub:
        pub = next((p for p in state["published"].values() if id_matches(p.get("id"), None, stage, unit)), None)
    if not pub or (isinstance(opened, (int, float)) and pub.get("at", 0) < opened):
        raise Refusal("The developer reads the stage's documents in the AI-DLC approval gates page before being "
                      f"asked. Publish them first: {publish_instruction(stage, unit)}.")
    return pub


def unit_end_flow_for(state, project, doc_id):
    """(stage, unit) when a `gates/<doc_id>` row is the per-stage page of a gate that a unit-end Unit has as a bundle
    page (its Code Generation plan approval or unit-end gate), else None."""
    intent, _root = intent_root(project)
    pending = state["pending"]
    candidates = []
    for cand in ((pending.get("stage"), pending.get("unit")) if pending else None, current_stage(project)):
        if cand and cand[0] and cand not in candidates:
            candidates.append(cand)
    for stage, unit in candidates:
        if not unit or not id_matches(doc_id, intent, stage, unit):
            continue
        in_hand = bool(pending and pending.get("stage") == stage and pending.get("unit") == unit)
        if (in_hand and pending.get("rhythm") == "unit-end") or unit_rhythm(project, unit, stage) == "unit-end":
            return stage, unit
    return None


def wrong_flow_message(doc_id, stage, unit):
    return (f"gates/{doc_id} is the wrong page: {unit} was claimed with the unit-end rhythm, so its {stage} plan approval and "
            "its unit-end gate are `bundles/<id>` rows in the \"AI-DLC unit approvals\" artifact, built by unit_bundle.py, not "
            f"`gates/` rows of gate_bundle.py in the \"AI-DLC approval gates\" artifact. Nothing was written. Run the unit-end "
            f"flow: {publish_instruction(stage, unit, 'plan')} (page `unit-end` at the unit-end gate)")


def check_gate_rows(tool_input):
    """The developer's fields of a gate row are written by the page only."""
    for op, collection, doc_id, data, _url in writes_of(tool_input):
        if collection == "bundles":
            if op != "set":
                raise Refusal(f"bundles/{doc_id}: a bundle row is written once, whole, with `set`; the developer's notes "
                              "and picks live on it. Never update, edit or delete it: a new presentation is a new bundle.")
            if data is None:
                raise Refusal(f"The write to bundles/{doc_id} cannot be read, so it cannot be checked. Write the row "
                              "from the file unit_bundle.py made.")
            if any(str(k).split(".")[0] in ("notes", "picks", "decision") for k in data):
                raise Refusal(f"bundles/{doc_id}: `notes` and `picks` are written by the developer in the page. Never "
                              "write them, and never update a row you wrote: a new presentation is a new bundle.")
            continue
        if collection == "plans":
            if op == "delete":
                continue
            if data is None:
                raise Refusal(f"The write to plans/{doc_id} cannot be read, so it cannot be checked. Write the row from the "
                              "file test_plan.py made, or give the data inline.")
            if op != "set" and any(str(k).split(".")[0] == "results" for k in data):
                raise Refusal(f"plans/{doc_id}: `results` are the developer's Pass and Fail in the page. Never write them; "
                              "read them with ArtifactData get.")
            if op == "set" and data.get("results"):
                raise Refusal(f"plans/{doc_id}: a plan row starts with no `results`; the developer's Pass and Fail "
                              "are written by the page.")
            continue
        if collection != "gates" or op == "delete":
            continue
        if data is None:
            raise Refusal(f"The write to gates/{doc_id} cannot be read, so it cannot be checked. Write the row "
                          "from the file gate_bundle.py made, or with data given inline.")
        if str(data.get("status", "")).lower() == "decided" or "decision" in data or "notes" in data:
            raise Refusal(f"gates/{doc_id}: `status: \"decided\"`, `decision` and `notes` are written by the "
                          "developer in the page. Never write them, and never update a row you wrote.")


def link_of(pub):
    """The link the developer gets: `<artifact url>#<gate id>`, the `#<gate id>` alone when the url is unknown."""
    url = str(pub.get("url", "")).strip()
    return f"{url}#{pub.get('id', '')}"


def epoch_of(stamp):
    try:
        return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def link_sent(event, pub, after=False):
    """(True, _) when a message of the assistant in this session's transcript carries the page's link; else
    (False, counts) of the assistant's text, thinking and tool_use blocks written since the page was published.
    Tool results, the developer's prompts and subagent transcripts do not count. An unreadable transcript refuses.
    With after=True only a message written since the page was published counts (a page written again needs its link again)."""
    gate_id, needle, since = str(pub.get("id", "")), link_of(pub), pub.get("at")
    path = event.get("transcript_path")
    if not path or not gate_id:
        raise Refusal("the session transcript is not given, so whether the developer got the page's link cannot "
                      "be checked.")
    counts = {"text": 0, "thinking": 0, "tool_use": 0}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if '"assistant"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(entry, dict) or entry.get("type") != "assistant" or entry.get("isSidechain"):
                    continue
                content = (entry.get("message") or {}).get("content") if isinstance(entry.get("message"), dict) else None
                blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
                stamp = epoch_of(entry.get("timestamp"))
                recent = isinstance(since, (int, float)) and stamp is not None and stamp >= since
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text" and needle in str(block.get("text", "")) and (recent or not after):
                        return True, counts
                    if recent and block.get("type") in counts:
                        counts[block["type"]] += 1
    except OSError as exc:
        raise Refusal(f"the session transcript cannot be read ({exc}), so whether the developer got the page's "
                      "link cannot be checked.") from None
    return False, counts


def link_wait():
    try:
        return max(0.0, float(os.environ.get("APPROVAL_GATES_LINK_WAIT", "3")))
    except ValueError:
        return 3.0


def call_written(event):
    """True when the transcript already holds this very tool call: the response that makes it is then on disk whole."""
    call_id, path = event.get("tool_use_id"), event.get("transcript_path")
    if not call_id or not path:
        return False
    try:
        with open(path, encoding="utf-8") as f:
            return any(call_id in line for line in f if '"tool_use"' in line)
    except OSError:
        return False


def wait_for_link(event, pub, after=False):
    """link_sent, tried again for a moment when the link is missing. Claude Code writes the blocks of a response to the
    transcript as they stream, and the hook of a tool call can run before the text block of the same response (one
    entry per block, one message id) has reached the file; a link sent in the response that asks the question would be
    refused for good. It waits for the text to land, and stops waiting once the question's own tool call is on disk."""
    deadline = time.time() + link_wait()
    while True:
        sent, counts = link_sent(event, pub, after)
        if sent or time.time() >= deadline or call_written(event):
            return sent, counts
        time.sleep(0.2)


def plan_hint(plan_ids, state, with_bundle):
    links = " and ".join(f"`{link_of(state['plans'][i])}`" for i in plan_ids)
    text = (f"the test plan is published (plans/{', plans/'.join(plan_ids)}). Send the developer the link {links} as a text block "
            "in a message of its own, and in the SAME response make the AskUserQuestion call (header \"Test plan\": "
            "**Do the agent step for A** / **Change the plan**). Never ask before the link: every question is refused until "
            "a message of yours written after this write carries it, and never end the turn on the link alone.")
    if with_bundle:
        text += (" This batch also wrote the unit-end page: put both links in that one message. The question that follows is "
                 "the test-plan ask above, not the unit-end Approval question (the gate waits until the test plan is done and "
                 "the page is republished with its outcome).")
    return text


def unsent_plans(event, state, wait=True):
    """[(plan, counts)] of the test plans whose link no message of the assistant has carried since they were written."""
    found = []
    for plan in state["plans"].values():
        if plan.get("linked"):
            continue
        sent, counts = wait_for_link(event, plan, after=True) if wait else link_sent(event, plan, True)
        if sent:
            plan["linked"] = time.time()
        else:
            found.append((plan, counts))
    return found


def guard_plan_links(event, state):
    """Refuse any question while a test plan's link has not been sent: the developer opens the plan from the link."""
    found = unsent_plans(event, state)
    if found:
        plan, counts = found[0]
        raise Refusal(f"The developer gets the test plan's link before any test-plan question, and no message of yours written "
                      f"since plans/{plan.get('id', '')} was published carries it. Since then your transcript holds "
                      f"{counts['thinking']} thinking, {counts['tool_use']} tool-call and {counts['text']} text block(s), none "
                      "with the link. Thinking is not output and a tool call is not a message: write "
                      f"`**Read:** {link_of(plan)}` as the text of your message, then make the AskUserQuestion call in this ONE "
                      "response; never end the turn on the link alone. (A plan written again needs its link again.)")


def guard_question(event, state, project, questions):
    for q in questions:
        stage, unit, opened = target_of(state, project)
        if not stage:
            continue
        pub = require_published(state, project, stage, unit, opened)
        tested_first(pub, stage, unit)  # only the question: the rejected report (fixes picked after the test) still goes
        text = str(q.get("question", ""))
        url = str(pub.get("url", "")).strip()
        if (url and url in text) or re.search(r"claude\.ai/artifact/|#[0-9]{6}-[a-z0-9.-]+-\d{8}T\d{4}\b", text, re.I):
            raise Refusal("The page's link goes to the developer in a message of its own, before the question; the "
                          "question text carries no link. Send the link "
                          f"{link_of(pub)} as a message, then ask the engine's question as it is.")
        sent, counts = wait_for_link(event, pub)
        if not sent:
            raise Refusal("The developer gets the page's link before the question, and no message of yours carries "
                          f"it yet. Since {pub.get('id', '')} was published, your transcript holds "
                          f"{counts['thinking']} thinking, {counts['tool_use']} tool-call and {counts['text']} text "
                          "block(s), none with the link. Thinking is not output and a tool call is not a message: "
                          f"write `**Read:** {link_of(pub)}` as the text of your message, then ask the engine's "
                          "question as it is, with no link in it. Do both in this ONE response: the text block with the link first, "
                          "then the AskUserQuestion call; never end the turn on the link alone.")


def guard_report(state, project, call):
    stage, unit, opened = target_of(state, project, call.get("stage") or (current_stage(project) or (None,))[0],
                                    call.get("unit"))
    if stage:
        require_published(state, project, stage, unit, opened)


def pre(event, project):
    tool, ti = event.get("tool_name"), event.get("tool_input") or {}
    if tool == "ArtifactData":
        check_gate_rows(ti)
        try:
            state = load(event)
        except Refusal:
            return
        sync_pending(state, project)
        for _op, collection, doc_id, _data, _url in writes_of(ti):
            if collection == "gates" and doc_id:
                wrong = unit_end_flow_for(state, project, doc_id)
                if wrong:
                    raise Refusal(wrong_flow_message(doc_id, *wrong))
        return
    if tool == "AskUserQuestion":
        state = load(event)
        guard_plan_links(event, state)
        sync_pending(state, project)
        gates = gate_questions(state, questions_of(ti))
        if gates:
            guard_question(event, state, project, gates)
        return
    if tool == "Bash":
        closing = [c for c in engine_calls(ti.get("command", "")) if c["kind"] == "report" and c["result"] in CLOSING]
        if closing:
            state = load(event)
            sync_pending(state, project)
            for call in closing:
                guard_report(state, project, call)


def guarded_pre(event, project):
    tool = event.get("tool_name")
    if tool not in ("ArtifactData", "AskUserQuestion", "Bash"):
        return
    try:
        pre(event, project)
    except Refusal:
        raise
    except Exception as exc:  # a guarded call that cannot be checked is refused
        if tool == "Bash" and "aidlc" not in str((event.get("tool_input") or {}).get("command", "")):
            return
        raise Refusal(f"The approval gate could not be checked ({type(exc).__name__}: {exc}).") from None


# ---------------------------------------------------------------- recording

SAID = []  # what this run tells the assistant, printed once as one hook output


def say(event_name, text):
    SAID.append((event_name, "approval-gates: " + text))


def flush():
    if SAID:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": SAID[0][0],
                                                 "additionalContext": "\n".join(text for _name, text in SAID)}}))


def id_matches(doc_id, intent, stage, unit):
    start = re.escape(intent) + "-" if intent else r".+?-"
    middle = re.escape(stage) + (("-" + re.escape(unit)) if unit else "")
    return re.fullmatch(start + middle + r"-\d{8}[Tt]\d{4}", doc_id or "") is not None


def engine_refused(response):
    """True when the engine answered the command with an error (`"kind": "error"`), so it opened nothing."""
    if isinstance(response, dict):
        text = " ".join(str(response.get(k) or "") for k in ("stdout", "stderr", "text", "output"))
    else:
        text = flat(response)
    return bool(re.search(r'"kind"\s*:\s*"error"', text)) or failed(response)


def record_bash(event, project, state, tool_input):
    changed = False
    for call in engine_calls(tool_input.get("command", "")):
        stage = call.get("stage")
        cur = current_stage(project)
        if call["kind"] == "answer":
            pending = state["pending"]
            if call.get("checkpoint") == "plan-approval" and pending and pending.get("kind") == "plan":
                # Request Changes: the revised plan is a new presentation, the engine's next ask opens it again.
                # Approve: the plan gate is over; left open, it would stand in for the Unit's later unit-end gate.
                state["pending"] = None
                changed = True
            continue
        if call["kind"] == "decision":
            if call.get("checkpoint") != "plan-approval":
                continue
            stage = stage or "code-generation"
            unit = call.get("unit") or (cur[1] if cur and cur[0] == stage else None)
            rhythm = unit_rhythm(project, unit, stage)
            state["pending"] = {"stage": stage, "unit": unit, "opened_at": time.time(), "kind": "plan", "rhythm": rhythm}
            if rhythm == "unit-end":
                say("PostToolUse", f"the plan for {unit} is open for approval (Approve Plan), the developer's one look at every "
                                   f"design stage of the Unit. Before that question: {publish_instruction(stage, unit, 'plan')}.")
            else:
                say("PostToolUse", f"the plan for {stage} is open for approval (Approve Plan). Before that question, "
                                   f"publish its documents: {publish_instruction(stage, unit)}.")
            changed = True
            continue
        stage = stage or (cur[0] if cur else None)
        if not stage:
            continue
        unit = call.get("unit") or (cur[1] if cur and cur[0] == stage else None)
        if call["result"] in OPENING:
            if engine_refused(event.get("tool_response")):
                continue
            rhythm = unit_rhythm(project, unit, stage)
            state["pending"] = {"stage": stage, "unit": unit, "opened_at": time.time(), "kind": "gate", "rhythm": rhythm}
            if rhythm == "unit-end":
                say("PostToolUse", f"the unit-end gate for {unit} is open. Before the Approval question: "
                                   f"{publish_instruction(stage, unit, 'unit-end')}.")
            else:
                say("PostToolUse", f"the gate for {stage}{(' (' + unit + ')') if unit else ''} is open. Before the Approval "
                                   f"question, publish its documents: {publish_instruction(stage, unit)}.")
            changed = True
        elif call["result"] in CLOSING:
            if engine_refused(event.get("tool_response")):
                continue
            pending = state["pending"]
            if pending and pending.get("stage") == stage and (not call.get("unit") or pending.get("unit") == call["unit"]):
                state["pending"] = None
                changed = True
    return changed


def record_artifact(project, state, tool_input, response):
    if failed(response):
        return False
    intent, _root = intent_root(project)
    pending = state["pending"]
    candidates = []
    for cand in ((pending.get("stage"), pending.get("unit")) if pending else None, current_stage(project)):
        if cand and cand[0] and cand not in candidates:
            candidates.append(cand)
    changed = False
    plan_ids, bundle_ids = [], []
    for op, collection, doc_id, _data, url in writes_of(tool_input):
        if collection == "plans":
            if op == "set" and doc_id:
                state["plans"][doc_id] = {"id": doc_id, "url": str(url or "").rstrip("/"), "at": time.time()}
                if doc_id not in plan_ids:
                    plan_ids.append(doc_id)
                changed = True
            continue
        if collection == "bundles":
            if op != "set":
                continue
            if record_bundle(state, project, intent, doc_id, url):
                bundle_ids.append(doc_id)
                changed = True
            continue
        if op not in ("set", "update") or collection != "gates":
            continue
        wrong = unit_end_flow_for(state, project, doc_id)
        if wrong:
            say("PostToolUse", wrong_flow_message(doc_id, *wrong).replace("Nothing was written.", "It does not count for the gate."))
            continue
        key = next((make_key(stage, unit) for stage, unit in candidates if id_matches(doc_id, intent, stage, unit)), None)
        if key is None and not candidates and re.fullmatch(r"\d{6}-[a-z0-9-]+-\d{8}[Tt]\d{4}", doc_id or ""):
            key = "id:" + doc_id  # no stage is known here: the row is kept by its id and matched by it later
        if key is None:
            continue
        pub = {"id": doc_id, "url": str(url or "").rstrip("/"), "at": time.time()}
        state["published"][key] = pub
        if not changed:
            say("PostToolUse", f"gates/{doc_id} is published. Send the developer the link `{link_of(pub)}` in "
                               "a message of its own (the `**Read:**` line of the completion message), then "
                               "ask the engine's Approval question with no link in it; the question is "
                               "refused until that message was sent. Do both in ONE response: a text block with "
                               "the link first, then the AskUserQuestion call in the same response; never end the "
                               "turn on the link alone.")
        changed = True
    if plan_ids:
        say("PostToolUse", plan_hint(plan_ids, state, bool(bundle_ids)))
    return changed


def stamp_epoch(stamp):
    """Seconds since the epoch of a YYYYMMDDTHHMM stamp in UTC, or None."""
    try:
        return datetime.datetime.strptime(stamp.upper(), "%Y%m%dT%H%M").replace(tzinfo=datetime.timezone.utc).timestamp()
    except ValueError:
        return None


def claimed_unit(project):
    """The Unit the checkout's claim names (aidlc/.aidlc-unit-scope.json), or None."""
    try:
        with open(os.path.join(project, "aidlc", ".aidlc-unit-scope.json"), encoding="utf-8") as f:
            unit = json.load(f).get("unit")
    except (OSError, ValueError, AttributeError):
        return None
    return unit.strip() if isinstance(unit, str) and unit.strip() else None


def record_bundle(state, project, intent, doc_id, url):
    """A `bundles` row of the Unit whose unit-end-rhythm gate is open, for the page that gate needs. A unit-end page of
    the claimed Unit counts with no gate open in the state too: its gate may have been opened where this session's state
    did not see it, and the report that approves it asks for this page."""
    pending = state["pending"]
    found = BUNDLE_ID.match(doc_id or "")
    if not found:
        return False
    head, page = found.group("head"), found.group("page")
    if intent and not head.startswith(intent.lower()):
        return False
    if pending and pending.get("rhythm") == "unit-end" and pending.get("unit") and page == page_of(pending) \
            and head.endswith("-" + pending["unit"].lower()):
        unit = pending["unit"]
    else:
        unit = claimed_unit(project)
        if page != "unit-end" or not unit or not head.endswith("-" + unit.lower()) \
                or unit_rhythm(project, unit, UNIT_END_STAGE) != "unit-end":
            return False
        if pending and pending.get("unit") == unit:
            state["pending"] = None  # a gate of this Unit still open in the state (its plan) is over: the Unit is built
        pending = {"stage": UNIT_END_STAGE, "unit": unit}
    built = stamp_epoch(found.group("stamp"))
    opened = pending.get("opened_at")
    if built is None or (isinstance(opened, (int, float)) and built < opened - opened % 60):
        say("PostToolUse", f"bundles/{doc_id} was built before this gate opened, so it does not count for it. Build the page "
                           "again (unit_bundle.py draft, then finalize) and write the new bundle.")
        return False
    pub = {"id": doc_id, "url": str(url or "").rstrip("/"), "at": time.time(), "page": page}
    state["published"][make_key(pending["stage"], unit) + "@" + page] = pub
    say("PostToolUse", f"bundles/{doc_id} is published in the AI-DLC unit approvals artifact. Send the developer the link `{link_of(pub)}` in a message of its "
                       "own, then ask the engine's Approval question with no link in it; the question is refused until "
                       "that message was sent. Do both in ONE response: a text block with the link first, then the "
                       "AskUserQuestion call in the same response; never end the turn on the link alone.")
    return True


def record_answers(project, state, tool_input, response):
    """Say what the answer to the gate question asks of the assistant. True when the state changed."""
    answers = answers_of(response)
    changed = False
    for q in gate_questions(state, questions_of(tool_input)):
        answer = next((a for k, a in answers.items() if norm(k) == norm(q.get("question", ""))), None)
        pending = state["pending"]
        if answer is not None and pending and pending.get("rhythm") == "unit-end":
            page = page_of(pending)
            pub = state["published"].get(make_key(pending.get("stage"), pending.get("unit")) + "@" + page)
            where = f"bundles/{pub['id']}" if pub and pub.get("id") else "the Unit's bundle row"
            if is_test_first(answer):
                if pub:
                    pub["test_first"] = time.time()  # the gate is asked again only about a page republished after the testing
                    changed = True
                say("PostToolUse", "the developer chose Test first: that is neither Approve nor Request Changes, and the gate "
                                   f"stays open. Read {where} with ArtifactData get: `picks.<V row anchor>` is `now` or `later` on each "
                                   "not-verified row. Then follow the test-plan flow (SKILL.md § 7; the skill "
                                   "approval-gates:test-plan): write the plan, publish it in the AI-DLC test plans artifact, and "
                                   "go on from there. Report nothing to the engine until the unit-end gate is asked again.")
            elif "request changes" in norm(answer):
                say("PostToolUse", f"the developer chose Request Changes. Read {where} with ArtifactData get and quote the "
                                   "notes they left on rows (notes.<row>) and their picks on suggestions (picks.<row>) in "
                                   "--reason, together with what they typed in chat.")
            else:
                say("PostToolUse", f"read {where} with ArtifactData get: notes and picks reach you with the developer's "
                                   "answer. When it holds any, say so in one line and ask in chat whether to act on them "
                                   "before going on; the decision itself is the chat answer.")
            continue
        if answer is None or "request changes" not in norm(answer):
            continue
        stage, unit, _opened = target_of(state, project)
        pub = state["published"].get(make_key(stage, unit)) if stage else None
        where = f"gates/{pub['id']}" if pub and pub.get("id") else "the gate row of this stage"
        say("PostToolUse", f"the developer chose Request Changes. Read {where} with ArtifactData get and use the "
                           "notes they left in the page (decision.note, notes.<document>) in --reason, quoted, "
                           "together with what they typed in chat. The page's decision.k is a draft and never "
                           "replaces the chat answer.")
    return changed


def is_test_first(answer):
    """The unit-end gate's third answer: test the not-verified points before deciding. Not an approval, not a rejection."""
    return norm(answer).startswith("test first")


def pending_page(state, project):
    """The published page of the gate the state has open, or None (no gate open, or not published since it opened)."""
    pending = state["pending"]
    if not pending or not pending.get("stage"):
        return None
    try:
        return require_published(state, project, pending["stage"], pending.get("unit"), pending.get("opened_at"))
    except Refusal:
        return None


def mark_asked(project, state, tool_input, response):
    """The gate's question was asked (the tool call went through): the page needs no more nudging at a stop."""
    if failed(response) or not gate_questions(state, questions_of(tool_input)):
        return False
    pub = pending_page(state, project)
    if not pub or pub.get("asked_at"):
        return False
    pub["asked_at"] = time.time()
    return True


def stop(event, project):
    """Block the stop once per published page whose gate question was not asked since: the assistant ended its turn
    on the link (or on nothing) and the developer would never get the question."""
    if event.get("stop_hook_active"):
        return
    with state_lock(event):
        try:
            state = load(event)
        except Refusal:
            return
        sync_pending(state, project)
        try:
            unsent = [p for p, _c in unsent_plans(event, state, wait=False) if not p.get("stop_blocked")]
        except Refusal:
            unsent = []
        if unsent:
            for plan in unsent:
                plan["stop_blocked"] = time.time()
            save(event, state)
            links = " and ".join(link_of(p) for p in unsent)
            print(json.dumps({"decision": "block", "reason": f"approval-gates: the test plan {unsent[0].get('id', '')} is "
                              f"published but its link was never sent, so the developer cannot open it. In ONE response write "
                              f"`**Read:** {links}` as text, then ask the test-plan question with AskUserQuestion "
                              f"(**Do the agent step for A** / **Change the plan**). {RELEASE_HINT}"}))
            return
        pub = pending_page(state, project)
        if not pub or pub.get("asked_at") or pub.get("stop_blocked"):
            return
        pub["stop_blocked"] = time.time()
        save(event, state)
        try:
            sent, _counts = link_sent(event, pub)
        except Refusal:
            sent = False
    if sent:
        todo = "ask the engine's Approval question now with AskUserQuestion; the link is already sent."
    else:
        todo = (f"the page's link {link_of(pub)} is not sent yet: in ONE response write `**Read:** {link_of(pub)}` as "
                "text, then ask the engine's Approval question with AskUserQuestion.")
    print(json.dumps({"decision": "block", "reason": f"approval-gates: the gate for {pub.get('id', 'this page')} is "
                      f"published but its question was never asked, so the developer cannot answer it. {todo} "
                      f"{RELEASE_HINT}"}))


def post(event, project):
    tool, ti = event.get("tool_name"), event.get("tool_input") or {}
    if tool not in ("Bash", "ArtifactData", "AskUserQuestion"):
        return
    with state_lock(event):
        try:
            state = load(event)
        except Refusal:
            return
        changed = sync_pending(state, project)
        if changed:
            pending = state["pending"]
            say("PostToolUse", f"the engine asks for the plan approval of {pending['unit']}. Before that question: "
                               f"{publish_instruction(pending['stage'], pending['unit'], 'plan' if pending['rhythm'] == 'unit-end' else None)}.")
        if tool == "Bash":
            changed = record_bash(event, project, state, ti) or changed
        elif tool == "ArtifactData":
            changed = record_artifact(project, state, ti, event.get("tool_response")) or changed
        else:
            changed = record_answers(project, state, ti, event.get("tool_response")) or changed
            changed = mark_asked(project, state, ti, event.get("tool_response")) or changed
        if changed:
            save(event, state)


def prompt(event):
    match = RELEASE_PROMPT.match(str(event.get("prompt") or ""))
    if not match:
        return
    existed = os.path.exists(state_path(event))
    if not match.group(1) and not existed:
        return  # a bare /release that is some other command's, with nothing of ours to clear
    with state_lock(event):
        drop(event)
    say("UserPromptSubmit", "guard state cleared for this session.")


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(event, dict):
        return 0
    name = event.get("hook_event_name")
    try:
        if name == "UserPromptSubmit":
            prompt(event)
            flush()
            return 0
        project = project_dir(event)
        if not os.path.isdir(os.path.join(project, "aidlc", "spaces")):
            return 0
        if name == "PreToolUse":
            guarded_pre(event, project)
        elif name == "PostToolUse":
            post(event, project)
            flush()
        elif name == "Stop":
            stop(event, project)
    except Refusal as why:
        print(f"{why} {RELEASE_HINT}", file=sys.stderr)
        return 2
    except Exception:  # never break the call the engine's own hooks sit beside
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
