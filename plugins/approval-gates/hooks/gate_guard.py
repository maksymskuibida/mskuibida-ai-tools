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

Every Approval question (header Approval or Unit-end, or options Approve and Request Changes) needs the page's link in
visible assistant text since the developer's last message: a text block before the call, in this response or an earlier
one. Thinking, tool calls, tool results and text written after a question box are not shown, so they do not count; a
markdown link counts only by its target. It holds with no recorded publication too (a restarted session has a new id and
an empty state): the link is then found again, as the newest page for the intent, the stage and the Unit in the state of
any session of this machine and in the bundles and gates rows written in the transcript; with no exact link, a link to
one of the artifacts that names the Unit or stage is needed. The refusal is three numbered steps to follow word for word.

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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import findings_round  # noqa: E402  (review findings at the gate: cards on the page, no Findings question)
STALE_DAYS = 14  # another session's state file untouched for this long is removed when a state is saved
GATE_LABELS = {"approve", "approve plan", "accept as-is"}
CLOSING = {"approved", "rejected", "accepted"}
OPENING = {"awaiting-approval", "revised"}
RELEASE_PROMPT = re.compile(r"^\s*/(?:(approval-gates):)?release\b")
OPS = re.compile(r"^[();<>|&]+$")
RELEASE_HINT = "(Blocked by the approval-gates plugin. The developer can release it by typing /approval-gates:release.)"
SCRATCH = "<your scratchpad folder>"


def one_line(text):
    return re.sub(r"\s+", " ", str(text)).strip()


def shaped(what, steps, check):
    """The one shape of every refusal: what was refused and why on one line, numbered steps to follow word for word,
    and how to tell they worked."""
    return "\n".join(["Refused: " + one_line(what), "Do this:"]
                     + [f"{n}. {one_line(step)}" for n, step in enumerate(steps, 1)]
                     + ["It worked when: " + one_line(check)])


class Refusal(Exception):
    """A refused call. str() is the shaped message the hook prints."""

    def __init__(self, what, steps, check):
        self.what, self.steps, self.check = what, list(steps), check
        super().__init__(shaped(what, self.steps, check))


def retry_steps(problem):
    """The steps when the guard itself cannot check: try once more, then hand the developer the release."""
    return ["Make the same call once more, unchanged.",
            f"If it is refused again, tell the developer in one line: \"The approval-gates check failed ({one_line(problem)}); "
            "please type /approval-gates:release.\" Then end your turn and wait for their message."]


RETRY_CHECK = "the same call goes through, or, after the developer typed /approval-gates:release, it goes through then."


# ---------------------------------------------------------------- state

def state_dir():
    return os.environ.get("APPROVAL_GATES_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "approval-gates")


def state_path(event):
    sid = re.sub(r"[^A-Za-z0-9_.-]", "_", str(event.get("session_id") or "default"))
    return os.path.join(state_dir(), sid + ".json")


def blank():
    return {"pending": None, "published": {}, "plans": {}, "findings": None, "updated": time.time()}


def normalize(data):
    state = blank()
    if isinstance(data, dict):
        if isinstance(data.get("pending"), dict):
            state["pending"] = data["pending"]
        if isinstance(data.get("published"), dict):
            state["published"] = {k: v for k, v in data["published"].items() if isinstance(v, dict)}
        if isinstance(data.get("plans"), dict):
            state["plans"] = {k: v for k, v in data["plans"].items() if isinstance(v, dict)}
        if isinstance(data.get("findings"), dict):
            state["findings"] = data["findings"]
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
        raise Refusal(f"this call, because the approval-gates record of this session ({state_path(event)}) cannot be read.",
                      retry_steps(f"its record {state_path(event)} cannot be read: {exc}"), RETRY_CHECK) from None


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


def findings_file(event):
    return state_path(event)[:-len(".json")] + ".findings.json"


def drop(event):
    for path in (state_path(event), state_path(event) + ".lock", findings_file(event)):
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


LINK_THEN_ASK = ("In ONE response, write a text message whose first line is the link `<artifact url>#<id>` (the artifact's "
                 "URL, `#`, the id you wrote), then call AskUserQuestion with the engine's question as it is, with no link in "
                 "it. Do not end the turn on the link alone.")


def publish_steps(stage, unit, page=None):
    """The numbered steps that publish the page a gate needs: the unit-end bundle of `page` ("plan" or "unit-end"), or,
    with no page, the per-stage gates row."""
    if page:
        script = os.path.join(PLUGIN_ROOT, "scripts", "unit_bundle.py")
        return [f"Run `python3 \"{script}\" draft --page {page} --unit {unit} --out {SCRATCH}/bundle.json`.",
                f"Do every item the draft lists under `todo` in {SCRATCH}/bundle.json.",
                f"Run `python3 \"{script}\" finalize --bundle {SCRATCH}/bundle.json --out {SCRATCH}/out`; when it prints "
                "problems, fix them in bundle.json and run it again until it prints none.",
                f"Send the `writes` array of {SCRATCH}/out/writes.json, as it is, with one ArtifactData batch to the "
                "\"AI-DLC unit approvals\" artifact (its URL: Artifact `action: \"list\"`). It is a `bundles/<id>` row: never a "
                "`gates/` row, never the \"AI-DLC approval gates\" artifact.",
                LINK_THEN_ASK]
    script = os.path.join(PLUGIN_ROOT, "scripts", "gate_bundle.py")
    cmd = f'python3 "{script}" --stage {stage}' + (f" --unit {unit}" if unit else "")
    return [f"Write your summary of the stage, in Markdown, to {SCRATCH}/summary.md.",
            f"Run `{cmd} --why first --summary-file {SCRATCH}/summary.md --out {SCRATCH}/gate` (`--why revision` after a "
            "Request Changes round).",
            f"Send the `writes` array of {SCRATCH}/gate/writes.json, as it is, with one ArtifactData batch to the "
            "\"AI-DLC approval gates\" artifact (its URL: Artifact `action: \"list\"`); when the script names `batches`, send "
            "those files in order.",
            LINK_THEN_ASK]


def published_check(page=None):
    row = "bundles/<id>" if page else "gates/<id>"
    return f"the hook answers your batch with `{row} is published`, and the question after the link goes through."


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
        plan_script = os.path.join(PLUGIN_ROOT, "scripts", "test_plan.py")
        bundle_script = os.path.join(PLUGIN_ROOT, "scripts", "unit_bundle.py")
        raise Refusal(f"the unit-end Approval question for {unit}, because the developer answered Test first: the gate is "
                      "asked again only after the test plan is done and the unit-end page is rebuilt with its outcome.",
                      [f"Finish the test plan as the skill approval-gates:test-plan says; its last command is `python3 "
                       f"\"{plan_script}\" finish --plan <plan file> --results <results file> --bundle <unit-end bundle.json>`.",
                       f"Run `python3 \"{bundle_script}\" draft --page unit-end --unit {unit} --tested <the Unit's "
                       f"code-generation stage folder>/test-plan.json --out {SCRATCH}/bundle.json`, do its `todo` list, then run "
                       f"`python3 \"{bundle_script}\" finalize --bundle {SCRATCH}/bundle.json --out {SCRATCH}/out`.",
                       f"Send the `writes` array of {SCRATCH}/out/writes.json with one ArtifactData batch to the \"AI-DLC unit "
                       "approvals\" artifact.",
                       LINK_THEN_ASK,
                       "If the developer says they do not want to test after all, ask them to type /approval-gates:release."],
                      published_check("unit-end"))


def require_published(state, project, stage, unit, opened, call="the Approval question"):
    """The record of this stage's gate page, or a Refusal when it was not published since the gate opened. A row
    recorded by its id alone (the stage was unknown when it was written) counts when its id names this stage. Under the
    unit-end rhythm the page is the Unit's bundle of the page the gate needs."""
    pending = state["pending"]
    if pending and pending.get("rhythm") == "unit-end" and pending.get("stage") == stage and (pending.get("unit") or None) == (unit or None):
        page = page_of(pending)
        pub = state["published"].get(make_key(stage, unit) + "@" + page)
        if not pub or (isinstance(opened, (int, float)) and pub.get("at", 0) < opened):
            raise Refusal(f"{call} for {unit}, because the developer reads the Unit's {page} page before being asked, and it "
                          "was not published since the gate opened. Publish it first.",
                          publish_steps(stage, unit, page), published_check(page))
        return pub
    if not (pending and pending.get("stage") == stage and (pending.get("unit") or None) == (unit or None)) \
            and unit_rhythm(project, unit, stage) == "unit-end":
        # The gate was opened where this session's state did not see it (another session, a subagent, the engine's
        # own directive): the Unit's claim still says its gate is the unit-end page.
        pub = state["published"].get(make_key(stage, unit) + "@unit-end")
        if not pub:
            raise Refusal(f"{call} for {unit}, because the developer reads the Unit's unit-end page before being asked, and "
                          "this session has not published it. Publish it first.",
                          publish_steps(stage, unit, "unit-end"), published_check("unit-end"))
        return pub
    pub = state["published"].get(make_key(stage, unit))
    if not pub:
        pub = next((p for p in state["published"].values() if id_matches(p.get("id"), None, stage, unit)), None)
    if not pub or (isinstance(opened, (int, float)) and pub.get("at", 0) < opened):
        raise Refusal(f"{call} for {stage}{(' (' + unit + ')') if unit else ''}, because the developer reads the stage's "
                      "documents in the AI-DLC approval gates page before being asked, and no page was published since the "
                      "gate opened. Publish them first.",
                      publish_steps(stage, unit), published_check())
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


def wrong_flow_refusal(doc_id, stage, unit):
    return Refusal(f"the write to gates/{doc_id}, because it is the wrong page: {unit} was claimed with the unit-end rhythm, so "
                   f"its {stage} plan approval and its unit-end gate are `bundles/<id>` rows in the \"AI-DLC unit approvals\" "
                   "artifact, built by unit_bundle.py, not `gates/` rows in the \"AI-DLC approval gates\" artifact. Nothing "
                   "was written.",
                   ["Use `--page plan` below at the plan approval (Approve Plan), `--page unit-end` at the unit-end gate."]
                   + publish_steps(stage, unit, "plan"), published_check("plan"))


DEVELOPER_FIELDS = ("decision", "notes", "findingPicks", "targetPicks")
NO_DEVELOPER_FIELDS = "Never update a row you wrote: a new presentation is a new row with a new id."


def unreadable_write(collection, doc_id, maker):
    return Refusal(f"the write to {collection}/{doc_id}, because its data file cannot be read, so it cannot be checked.",
                   [f"Check that the `file_path` of that write is a file {maker} wrote, and that it exists (`ls -l <that path>`).",
                    f"Send the `writes` array of the writes.json {maker} wrote again, as it is, with one ArtifactData batch."],
                   "the batch goes through with no approval-gates refusal.")


def check_gate_rows(tool_input):
    """The developer's fields of a gate row are written by the page only."""
    for op, collection, doc_id, data, _url in writes_of(tool_input):
        if collection == "bundles":
            if op != "set":
                raise Refusal(f"the `{op}` of bundles/{doc_id}, because a bundle row is written once, whole, with `set`: the "
                              "developer's notes and picks live on it.",
                              [f"Leave bundles/{doc_id} as it is.",
                               "If the page must change, build a new presentation: run unit_bundle.py draft, do its todo "
                               "list, run finalize, and write the new writes.json with one ArtifactData batch (a new id)."],
                              "the hook answers the new batch with `bundles/<id> is published`.")
            if data is None:
                raise unreadable_write("bundles", doc_id, "`unit_bundle.py finalize`")
            if any(str(k).split(".")[0] in ("notes", "picks", "decision") for k in data):
                raise Refusal(f"the write to bundles/{doc_id}, because `notes`, `picks` and `decision` are written by the "
                              "developer in the page.",
                              ["Remove `notes`, `picks` and `decision` from the row's data.",
                               "Write the row once, with `set`, from the writes.json `unit_bundle.py finalize` made. "
                               + NO_DEVELOPER_FIELDS],
                              "the batch goes through with no approval-gates refusal.")
            continue
        if collection == "plans":
            if op == "delete":
                continue
            if data is None:
                raise unreadable_write("plans", doc_id, "`test_plan.py publish`")
            if op != "set" and any(str(k).split(".")[0] == "results" for k in data):
                raise Refusal(f"the `{op}` of plans/{doc_id}, because `results` are the developer's Pass and Fail, written "
                              "by the page.",
                              ["Leave `results` out of the write: to mark an agent step done, update only `agentDone`.",
                               f"Read the developer's results with ArtifactData `get` of plans/{doc_id}."],
                              "the update goes through with no approval-gates refusal.")
            if op == "set" and data.get("results"):
                raise Refusal(f"the write to plans/{doc_id}, because a plan row starts with no `results`: the developer's "
                              "Pass and Fail are written by the page.",
                              ["Write the plan row from the writes.json `test_plan.py publish` made, as it is, with no "
                               "`results`."],
                              "the batch goes through with no approval-gates refusal.")
            continue
        if collection != "gates" or op == "delete":
            continue
        if data is None:
            raise unreadable_write("gates", doc_id, "`gate_bundle.py`")
        if str(data.get("status", "")).lower() == "decided" or any(str(k).split(".")[0] in DEVELOPER_FIELDS for k in data):
            raise Refusal(f"the write to gates/{doc_id}, because `status: \"decided\"`, `decision`, `notes`, `findingPicks` "
                          "and `targetPicks` are written by the developer in the page.",
                          ["Remove `status: \"decided\"`, `decision`, `notes`, `findingPicks` and `targetPicks` from the row's "
                           "data.",
                           "Write the row from the writes.json gate_bundle.py made, as it is. " + NO_DEVELOPER_FIELDS],
                          "the batch goes through with no approval-gates refusal.")


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
        raise transcript_refusal("the session transcript is not given")
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
                    if block.get("type") == "text" and has_link(str(block.get("text", "")), needle) and (recent or not after):
                        return True, counts
                    if recent and block.get("type") in counts:
                        counts[block["type"]] += 1
    except OSError as exc:
        raise transcript_refusal(f"the session transcript cannot be read ({exc})") from None
    return False, counts


def transcript_refusal(problem):
    return Refusal(f"this question, because {problem}, so whether the developer got the page's link cannot be checked.",
                   retry_steps(problem), RETRY_CHECK)


def link_then_ask(event, pub):
    """(key, asked) of the latest message of the assistant that carries the page's link: key names that message (its uuid,
    else its timestamp), asked is True when an AskUserQuestion call came after it. (None, False) when no such message."""
    needle, since, path = link_of(pub), pub.get("at"), event.get("transcript_path")
    key, asked = None, False
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
                message = entry.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                if not isinstance(content, list):
                    continue
                stamp = epoch_of(entry.get("timestamp"))
                recent = not isinstance(since, (int, float)) or stamp is None or stamp >= since
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text" and needle in str(block.get("text", "")) and recent:
                        key, asked = str(entry.get("uuid") or entry.get("timestamp") or ""), False
                    elif block.get("type") == "tool_use" and block.get("name") == "AskUserQuestion" and key is not None:
                        asked = True
    except (OSError, TypeError):
        return None, False
    return (key or None), asked


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
        raise Refusal(f"this question, because the developer gets the test plan's link before any question, and no message of "
                      f"yours written since plans/{plan.get('id', '')} was published carries it (since then: "
                      f"{counts['thinking']} thinking, {counts['tool_use']} tool-call and {counts['text']} text block(s), none "
                      "with the link; thinking is not output and a tool call is not a message).",
                      [f"In ONE response, write a text message whose first line is `**Read:** {link_of(plan)}`.",
                       "In that same response, make the AskUserQuestion call (header \"Test plan\": **Do the agent step for "
                       "A** / **Change the plan**).",
                       "Do not end the turn on the link alone: a response with only the link ends your turn and the developer "
                       "has no question to answer. Your next response must hold both: the link text block AND this "
                       "AskUserQuestion call."],
                      "the question goes through. A plan written again needs its link again.")


def unit_end_page(state, project):
    """The unit-end page recorded for a gate the state has not opened: the claimed Unit's, else the latest one written.
    A session whose gate came without a `report --result awaiting-approval` it saw has no pending gate and may have no
    stage the engine names, yet the page it wrote is the one its Approval question is about."""
    unit = claimed_unit(project)
    if unit and unit_rhythm(project, unit, UNIT_END_STAGE) == "unit-end":
        pub = state["published"].get(make_key(UNIT_END_STAGE, unit) + "@unit-end")
        if pub:
            return pub
    pages = [p for k, p in state["published"].items() if k.endswith("@unit-end")]
    return max(pages, key=lambda p: p.get("at", 0), default=None)


def guard_question(event, state, project, questions):
    """The page behind each of the gate's questions, {id(question): pub}; a Refusal when it was not published or the
    question carries the link itself. That the link was shown to the developer is guard_visible_link's check."""
    pubs = {}
    for q in questions:
        stage, unit, opened = target_of(state, project)
        pub = None
        if not state["pending"]:
            fallback = None if "approve plan" in labels(q) else unit_end_page(state, project)  # a plan question is about the plan page
            if not stage and fallback:
                stage, unit, pub = UNIT_END_STAGE, claimed_unit(project), fallback
            elif stage and fallback:
                try:
                    require_published(state, project, stage, unit, opened)
                except Refusal:
                    stage, unit, pub = UNIT_END_STAGE, claimed_unit(project), fallback
        if not stage:
            continue
        if not pub:
            try:
                pub = require_published(state, project, stage, unit, opened)
            except Refusal:
                # No gate open in the state (a restarted session, a lost record): when the page is on record elsewhere,
                # the question is held to the visible link of that page instead of being told to publish it again.
                if state["pending"] or not recoverable(event, state, project, q):
                    raise
                continue
        tested_first(pub, stage, unit)  # only the question: the rejected report (fixes picked after the test) still goes
        text = str(q.get("question", ""))
        url = str(pub.get("url", "")).strip()
        if (url and url in text) or re.search(r"claude\.ai/artifact/|#[0-9]{6}-[a-z0-9.-]+-\d{8}T\d{4}\b", text, re.I):
            raise Refusal("this Approval question, because its text carries a link: the page's link goes to the developer in "
                          "a message of its own, before the question, so the dialog stays readable.",
                          ["Remove every link, URL and gate id from the question text.",
                           f"In ONE response, write a text message whose first line is exactly this link: {link_of(pub)}",
                           "Then, in the same response, call AskUserQuestion with the engine's question as it is."],
                          "the question goes through.")
        pubs[id(q)] = pub
    return pubs


# ---------------------------------------------------------------- the link must be visible

APPROVAL_HEADERS = {"approval", "unit-end", "unit end"}
NOT_A_USER_MESSAGE = ("<task-notification", "[request interrupted", "stop hook feedback", "another claude session sent",
                      "your response above was cut off")
MD_LINK = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]*)>?[^)]*\)")
REFERS = re.compile(r"linked (?:artifact|page)|the (?:page|link|artifact) (?:above|below)|(?:see|check|open|read) the "
                    r"(?:linked|approval|unit-end|page|link|artifact)|link above|page above", re.I)
ANY_PAGE_LINK = r"https?://claude\.ai/(?:code/)?artifact/[A-Za-z0-9_-]+"


def is_approval_question(question):
    """An AI-DLC Approval or unit-end question: its header is Approval or Unit-end, or its options offer Approve and
    Request Changes. A question that names a pull request is some other approval."""
    if names_pull_request(str(question.get("question", ""))):
        return False
    ls = labels(question)
    return norm(question.get("header", "")) in APPROVAL_HEADERS or ("approve" in ls and "request changes" in ls)


def shown_text(text):
    """The text as the developer reads it: a markdown link shows its label, and a label never stands in for the address,
    so only the target of a markdown link is kept as an address."""
    return MD_LINK.sub(lambda m: " " + m.group(1) + " ", text)


def link_pattern(link):
    return re.escape(link) + r"(?![A-Za-z0-9_-]|\.[A-Za-z0-9])"


def has_link(text, link):
    return bool(link) and re.search(link_pattern(link), shown_text(text)) is not None


def has_page_link(text, urls, tokens):
    """A link to one of the artifacts, with a fragment that names the Unit or the stage (any fragment when none is known)."""
    shown = shown_text(text)
    bases = [re.escape(u) for u in urls] or [ANY_PAGE_LINK]
    for base in bases:
        for m in re.finditer(base + r"#([\w.-]+)", shown):
            frag = m.group(1).lower()
            if not tokens or any(t in frag for t in tokens):
                return True
    return False


def genuine_user(entry):
    """A message the developer wrote, not a tool result nor something the harness or another session injected."""
    if entry.get("isMeta") or entry.get("isCompactSummary") or entry.get("isSidechain"):
        return False
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        content = "\n".join(str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(content, str):
        return False
    text = re.sub(r"<system-reminder>.*?</system-reminder>", "", content, flags=re.S).strip().lower()
    return bool(text) and not text.startswith(NOT_A_USER_MESSAGE)


def read_transcript(event):
    path = event.get("transcript_path")
    if not path:
        raise transcript_refusal("the session transcript is not given")
    entries = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and entry.get("type") in ("assistant", "user") and not entry.get("isSidechain"):
                    entries.append(entry)
    except OSError as exc:
        raise transcript_refusal(f"the session transcript cannot be read ({exc})") from None
    return entries


def blocks_of(entry):
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def segment(entries):
    """[(kind, text, hidden)] of everything since the developer's last message: the assistant's text, thinking and tool
    calls, and the tool results. hidden is True for text written after an AskUserQuestion call of the same response: the
    app does not show it."""
    items, after_question = [], False
    for entry in entries:
        if entry["type"] == "user":
            if genuine_user(entry):
                items, after_question = [], False
                continue
            after_question = False  # the question was answered or dropped: the next response is a new one
            for block in blocks_of(entry):
                if block.get("type") == "tool_result":
                    items.append(("tool_result", flat(block.get("content")), False))
            continue
        for block in blocks_of(entry):
            kind = block.get("type")
            if kind == "text":
                items.append(("text", str(block.get("text", "")), after_question))
            elif kind == "thinking":
                items.append(("thinking", str(block.get("thinking", "")), False))
            elif kind == "tool_use":
                items.append(("tool_use", json.dumps(block.get("input"), ensure_ascii=False), False))
                if block.get("name") == "AskUserQuestion":
                    after_question = True
    return items


def other_states(event):
    """The states of the other sessions of this machine: a restarted session has a new id and an empty state, while the
    page it published stays on record in the state of the session it came from."""
    own = os.path.basename(state_path(event))
    try:
        names = sorted(n for n in os.listdir(state_dir()) if n.endswith(".json") and n != own
                       and not n.endswith(".findings.json") and n != findings_round.OWNER)
    except OSError:
        return []
    found = []
    for name in names:
        try:
            with open(os.path.join(state_dir(), name), encoding="utf-8") as f:
                found.append(normalize(json.load(f)))
        except (OSError, ValueError):
            continue
    return found


def published_in_transcript(entries):
    """[(time, collection, doc_id, url)] of the bundles and gates rows this session's ArtifactData calls wrote."""
    found = []
    for entry in entries:
        if entry["type"] != "assistant":
            continue
        for block in blocks_of(entry):
            if block.get("type") != "tool_use" or block.get("name") != "ArtifactData" or not isinstance(block.get("input"), dict):
                continue
            ti = block["input"]
            writes = [w for w in ti.get("writes") or [] if isinstance(w, dict)] if ti.get("action") == "batch" else [ti]
            for w in writes:
                if w.get("collection") in ("bundles", "gates") and w.get("doc_id") and (w.get("op") or w.get("action")) == "set":
                    found.append((epoch_of(entry.get("timestamp")) or 0, w["collection"], str(w["doc_id"]),
                                  str(ti.get("url") or "").rstrip("/")))
    return found


def recoverable(event, state, project, question):
    """True when the page this question is about is on record outside this session's state: its exact link is found."""
    return bool(expected_page(event, state, project, question, read_transcript(event))[0])


def page_key_matches(key, stage, unit, page):
    base, _, kpage = key.partition("@")
    if kpage and kpage != page:
        return False
    if kpage and unit:
        return base.endswith("/" + unit)
    if base.startswith("id:"):
        return not stage or stage in base
    if unit:
        return base == make_key(stage, unit)
    return not stage or base == stage or base.startswith(stage + "/")


def expected_page(event, state, project, question, entries):
    """(link or None, artifact urls, tokens): the page this Approval question is about, found without the session's own
    record when it has none. The link is the newest page on record for the intent, the stage and the Unit: this
    session's state, the state of the other sessions, then the bundles and gates rows written in the transcript."""
    intent, _root = intent_root(project)
    stage, unit, _opened = target_of(state, project)
    if not unit:
        unit = claimed_unit(project)
        if unit and (not stage or unit_rhythm(project, unit, UNIT_END_STAGE) == "unit-end"):
            stage = UNIT_END_STAGE
    page = "plan" if "approve plan" in labels(question) else "unit-end"
    start = (intent or "").lower()
    found, urls = [], []

    def note(url):
        if url and url not in urls:
            urls.append(url)

    for number, known in enumerate([state] + other_states(event)):
        for key, pub in known["published"].items():
            pid = str(pub.get("id", ""))
            if not pid or not pid.lower().startswith(start):
                continue
            note(str(pub.get("url", "")).rstrip("/"))
            if page_key_matches(key, stage, unit, page):
                found.append((pub.get("at", 0) or 0, pid, str(pub.get("url", "")).rstrip("/")))
    for at, collection, doc_id, url in published_in_transcript(entries):
        if not doc_id.lower().startswith(start):
            continue
        note(url)
        if collection == "bundles":
            m = BUNDLE_ID.match(doc_id)
            fits = bool(m) and m.group("page") == page and (not unit or m.group("head").endswith("-" + unit.lower()))
        else:
            fits = not stage or id_matches(doc_id, intent, stage, unit)
        if fits:
            found.append((at, doc_id, url))
    best = max(found, default=None)
    link = f"{best[2]}#{best[1]}" if best and best[2] else None
    tokens = [t.lower() for t in (unit,) if t] or [t for t in (stage,) if t]
    return link, urls, tokens


def where_it_went(segment_items, link, urls):
    """Why the link did not reach the developer, as one of the known cases, or None."""
    def mentions(text):
        if link:
            return link in text or link.rpartition("#")[2] in text
        return any(u + "#" in text for u in urls) or re.search(ANY_PAGE_LINK + "#", text) is not None

    for kind, text, hidden in segment_items:
        if kind == "text" and not hidden and mentions(text) and not (has_link(text, link) if link else
                                                                       has_page_link(text, urls, [])):
            return "markdown"
    if any(k == "text" and h and mentions(t) for k, t, h in segment_items):
        return "after"
    if any(k == "thinking" and mentions(t) for k, t, _h in segment_items):
        return "thinking"
    if any(k == "text" and not h and REFERS.search(t) for k, t, h in segment_items):
        return "refers"
    if any(k in ("tool_use", "tool_result") and mentions(t) for k, t, _h in segment_items):
        return "tool"
    return None


WHY = {
    "none": "no text message of yours since the developer's last message carries the page's link",
    "thinking": "the link is only in your thinking, and thinking is not output: the developer never sees it",
    "tool": "the link is only in a tool call or a tool result (ArtifactData, Artifact open, Bash output): the developer does not see those",
    "after": "the link was written after an AskUserQuestion call in the same response: the app does not show text after a question box",
    "refers": "the text only refers to the page (\"linked artifact\", \"page above\") and holds no URL: there is nothing for the developer to open",
    "markdown": "the markdown link's target is not the page's URL (a label showing the URL does not count): the developer would open another address",
}


def visible_refusal(case, link, urls, tokens, session_lost):
    if link:
        first = f"exactly this link, in full, with nothing else on that line (copy it, no backticks): {link}"
    elif urls:
        first = ("a link to the page of this " + (f"Unit ({tokens[0]})" if tokens else "stage") + " in the artifact where you wrote it: "
                 + " or ".join(f"`{u}#<the row id you wrote>`" for u in urls) + ", the whole link, nothing else on that line")
    else:
        first = ("a link to the page, `<artifact url>#<the row id you wrote>` (find the artifact with Artifact `action: \"list\"`: "
                 "AI-DLC unit approvals, or AI-DLC approval gates), the whole link, nothing else on that line")
    lost = (" The session was restarted or its record of the page was lost, so the link below is found again, not "
            "as it was recorded." if session_lost else "")
    return Refusal(f"this AI-DLC Approval question, because {WHY[case]}. Thinking is not output, and tool calls, tool results "
                   f"and text written after a question box are not shown to the developer.{lost}",
                   [f"Write a text message whose first line is {first}",
                    "Put nothing after the question: no text and no link after the AskUserQuestion call.",
                    "Then call AskUserQuestion with the engine's question as it is, with no link in it. Do steps 1 to 3 in "
                    "ONE response, in this order. Do not end the turn on the link alone."],
                   "the question goes through.")


def guard_visible_link(event, state, project, questions, pubs):
    """An AI-DLC Approval question needs the page's link in visible assistant text since the developer's last message:
    a text block before the call, in this response or an earlier one. It holds with no recorded publication too."""
    for q in questions:
        pub = pubs.get(id(q))
        deadline = time.time() + link_wait()
        while True:
            entries = read_transcript(event)
            if pub:
                link, urls, tokens = link_of(pub), [], []
            else:
                link, urls, tokens = expected_page(event, state, project, q, entries)
            items = segment(entries)
            texts = [t for k, t, h in items if k == "text" and not h]
            ok = any(has_link(t, link) for t in texts) if link else any(has_page_link(t, urls, tokens) for t in texts)
            if ok or time.time() >= deadline or call_written(event):
                break
            time.sleep(0.2)
        if not ok:
            case = where_it_went(items, link, urls) or "none"
            raise visible_refusal(case, link, urls, tokens, not pub)


def guard_report(state, project, call):
    stage, unit, opened = target_of(state, project, call.get("stage") or (current_stage(project) or (None,))[0],
                                    call.get("unit"))
    if stage:
        require_published(state, project, stage, unit, opened, f"`aidlc engine orchestrate report --result {call['result']}`")


def pre(event, project):
    tool, ti = event.get("tool_name"), event.get("tool_input") or {}
    if tool == "ArtifactData":
        check_gate_rows(ti)
        try:
            state = load(event)
        except Refusal:
            return
        sync_pending(state, project)
        intent, _root = intent_root(project)
        rnd = state["findings"]
        for op, collection, doc_id, data, _url in writes_of(ti):
            if collection == "gates" and doc_id:
                wrong = unit_end_flow_for(state, project, doc_id)
                if wrong:
                    raise wrong_flow_refusal(doc_id, *wrong)
                if op == "set" and rnd:
                    with refused_as_refusal():
                        findings_round.check_gate_write(rnd, doc_id, data, id_matches(doc_id, intent, rnd.get("stage"), rnd.get("unit")))
        return
    if tool == "AskUserQuestion":
        state = load(event)
        guard_plan_links(event, state)
        sync_pending(state, project)
        questions = questions_of(ti)
        gates = gate_questions(state, questions)
        pubs = guard_question(event, state, project, gates) if gates else {}
        visible = [q for q in questions if q in gates or is_approval_question(q)]
        with refused_as_refusal():
            findings_round.pre_question(state["findings"], bool(visible))
        if visible:
            guard_visible_link(event, state, project, visible, pubs)
        return
    if tool == "Bash":
        command = ti.get("command", "")
        closing = [c for c in engine_calls(command) if c["kind"] == "report" and c["result"] in CLOSING]
        if closing or "review-brief" in command:
            state = load(event)
            sync_pending(state, project)
            with refused_as_refusal():
                findings_round.pre_bash(state["findings"], command)
            for call in closing:
                guard_report(state, project, call)


@contextlib.contextmanager
def refused_as_refusal():
    """The findings round says what it refuses; the guard refuses it in its own shape."""
    try:
        yield
    except findings_round.Refused as r:
        raise Refusal(r.what, r.steps, r.check) from None


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
        raise Refusal(f"this {tool} call, because the approval gate could not be checked.",
                      retry_steps(f"{type(exc).__name__}: {exc}"), RETRY_CHECK) from None


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
        rnd = state["findings"]
        if rnd and id_matches(doc_id, intent, rnd.get("stage"), rnd.get("unit")):
            note = findings_round.on_page(state, doc_id, pub["url"])
            if note:
                say("PostToolUse", note)
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
        rnd = state["findings"]
        if answer is not None and rnd and rnd.get("page"):
            typed = findings_round.on_typed(state, answer)
            changed = True
            say("PostToolUse", typed or (f"the gate page holds {len(rnd['ids'])} finding card(s) the developer sorted: read "
                                         f"gates/{rnd['page']} with ArtifactData get now and act on `findingPicks` before "
                                         "any report (the hook says what each pick means when you read it)."))
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


def record_findings(event, project, state, tool_input):
    """A review brief, a review pass or a closing report: what it means for the findings round."""
    before = json.dumps(state["findings"], sort_keys=True)
    note = findings_round.post_bash(state, state_dir(), project, findings_file(event), tool_input.get("command", ""),
                                    event.get("tool_response"), lambda stage, unit: unit_rhythm(project, unit or None, stage))
    if note:
        say("PostToolUse", note)
    return json.dumps(state["findings"], sort_keys=True) != before


def record_read(project, state, tool_input, response):
    """An ArtifactData get of the round's page: the developer's sort of the finding cards."""
    if (tool_input or {}).get("action") != "get" or tool_input.get("collection") != "gates" or failed(response):
        return False
    note = findings_round.on_read(state, state_dir(), project, str(tool_input.get("doc_id", "")), response)
    if note:
        say("PostToolUse", note)
        return True
    return False


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
            print(json.dumps({"decision": "block", "reason": stop_reason(
                f"ending the turn, because the test plan {unsent[0].get('id', '')} is published but its link was never sent, "
                "so the developer cannot open it.",
                [f"In ONE response, write a text message whose first line is `**Read:** {links}`.",
                 "In that same response, ask the test-plan question with AskUserQuestion (**Do the agent step for A** / "
                 "**Change the plan**)."],
                "the question box is shown to the developer.")}))
            return
        pub = pending_page(state, project)
        if pub and not pub.get("asked_at"):
            reason = None
            if not pub.get("stop_blocked"):
                try:
                    sent, _counts = link_sent(event, pub)
                except Refusal:
                    sent = False
                if not sent:
                    pub["stop_blocked"] = time.time()
                    reason = stop_reason(
                        f"ending the turn, because the gate for {pub.get('id', 'this page')} is published but its question "
                        "was never asked and its link was never sent, so the developer cannot answer it.",
                        [f"In ONE response, write a text message whose first line is `**Read:** {link_of(pub)}`.",
                         "In that same response, ask the engine's Approval question with AskUserQuestion, with no link in it."],
                        "the question box is shown to the developer.")
            if reason is None:
                reason = bare_link(event, pub, "the engine's Approval question")
            if reason:
                save(event, state)
                print(json.dumps({"decision": "block", "reason": reason}))
                return
        bare = [(p, bare_link(event, p, "the test-plan question (**Do the agent step for A** / **Change the plan**)"))
                for p in state["plans"].values() if p.get("linked")]
        bare = [(p, r) for p, r in bare if r]
        if bare:
            save(event, state)
            print(json.dumps({"decision": "block", "reason": bare[0][1]}))


def bare_link(event, pub, question):
    """The stop reason when the latest message with the page's link has no AskUserQuestion after it and that message
    was not blocked yet (one block per link message, so one ending cannot loop and each new bare ending is caught)."""
    key, asked = link_then_ask(event, pub)
    if not key or asked or pub.get("bare_blocked") == key:
        return None
    pub["bare_blocked"] = key
    return stop_reason(f"ending the turn here. The link is sent; now ask {question} with AskUserQuestion — it will be "
                       "allowed.",
                       ["Do not write the link again.",
                        f"Call AskUserQuestion with {question}, with no link in it."],
                       "the question box is shown to the developer.")


def stop_reason(what, steps, check):
    """A blocked stop has the shape of a refusal too."""
    return "approval-gates: " + shaped(what, steps, check) + "\n" + RELEASE_HINT


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
            changed = record_findings(event, project, state, ti) or changed
        elif tool == "ArtifactData":
            changed = record_artifact(project, state, ti, event.get("tool_response")) or changed
            changed = record_read(project, state, ti, event.get("tool_response")) or changed
        else:
            changed = record_answers(project, state, ti, event.get("tool_response")) or changed
            changed = mark_asked(project, state, ti, event.get("tool_response")) or changed
        if changed:
            save(event, state)


SHOW_PAGE = re.compile(r"\b(show|send|open|give|where)\b.*\b(approval|page|link|gate|bundle)|\b(approval ?page|the link)\b", re.I)


def show_page_hint(event):
    """The developer asks to see the page: say which link to write, as text. Nothing is said when no page is waiting."""
    try:
        project = project_dir(event)
        if not os.path.isdir(os.path.join(project, "aidlc", "spaces")) or not os.path.exists(state_path(event)):
            return
        with state_lock(event):
            state = load(event)
            sync_pending(state, project)
            pub = pending_page(state, project) if state["pending"] else unit_end_page(state, project)
        if pub and pub.get("id"):
            say("UserPromptSubmit", f"the developer asks to see the approval page. Write `**Read:** {link_of(pub)}` as plain "
                                    "text in a message of its own now (thinking does not count and `Artifact open` does not "
                                    "show it to them), then ask the question again if the gate is still open.")
    except Exception:
        return


def typed_findings(event):
    """A message that is just one answer for every finding card ("fix all", "accept all") is recorded as the sort."""
    try:
        project = project_dir(event)
        if not os.path.isdir(os.path.join(project, "aidlc", "spaces")) or not os.path.exists(state_path(event)):
            return
        with state_lock(event):
            state = load(event)
            note = findings_round.on_typed(state, event.get("prompt"))
            if note:
                save(event, state)
                say("UserPromptSubmit", note)
    except Exception:
        return


def prompt(event):
    match = RELEASE_PROMPT.match(str(event.get("prompt") or ""))
    if not match:
        typed_findings(event)
        if SHOW_PAGE.search(str(event.get("prompt") or "")):
            show_page_hint(event)
        return
    existed = os.path.exists(state_path(event))
    if not match.group(1) and not existed:
        return  # a bare /release that is some other command's, with nothing of ours to clear
    with state_lock(event):
        drop(event)
    say("UserPromptSubmit", "guard state cleared for this session.")


def plugin_version():
    try:
        with open(os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            return json.load(f).get("version", "")
    except (OSError, ValueError):
        return ""


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
        findings_round.write_owner(state_dir(), plugin_version())
        if name == "PreToolUse":
            guarded_pre(event, project)
        elif name == "PostToolUse":
            post(event, project)
            flush()
        elif name == "Stop":
            stop(event, project)
    except Refusal as why:
        print(f"{why}\n{RELEASE_HINT}", file=sys.stderr)
        return 2
    except Exception:  # never break the call the engine's own hooks sit beside
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
