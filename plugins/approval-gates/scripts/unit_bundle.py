#!/usr/bin/env python3
"""Build the gate bundle of a Unit claimed with the unit-end rhythm: its plan page or its unit-end page.

    unit_bundle.py draft    --page plan|unit-end --unit <u> [--project-dir <dir>] [--previous <bundle.json>]
                            [--same-revision] --out <draft.json>
    unit_bundle.py finalize --bundle <draft.json> [--project-dir <dir>] [--previous <bundle.json>] --out <dir>

`draft` reads the Unit's stage records and writes a bundle with every row a script can find by itself:

  plan page      the answers of every questions file (one group per file, the proposed answer kept);
                 every `[assumption]` line of the design records and the code plan (section `assumptions`);
                 every reviewer finding the newest review of a stage left open or waived (section `findings`), with
                 what in the code plan settles it when a step names it; the code plan's steps (layer, file count,
                 sub-steps, the design ids each step implements, with the id's text as its tip);
                 empty `narrows`, `visible` and `tests` sections for the agent to fill.
  unit-end page  `code-summary.md`: Deviations From the Plan as `changes`, Not Verified Here as `unverified`,
                 Files Created and Changed as `built`; the approved plan bundle, folded, as `design`.

Rows the script cannot judge carry `"label": null` (and the header a lede to rewrite): the bundle does not validate until
the agent has labelled every row, rewritten the titles and bodies in plain words and filled the empty sections. The
script prints what is left to do. With an earlier presentation of the same page (the newest one this script finalized,
or --previous), every row whose source has not changed is carried over as the agent left it, and so is every row the
agent wrote by hand; the revision is the earlier one plus one (--same-revision keeps it).

`finalize` marks what changed since the earlier presentation (a row or step whose content differs gets `rev` and, when
new, `revKind: "new"`; a changed sub-step gets its own `rev`), fills the default header facts, validates the bundle
against contract/gate-bundle.schema.json and its rules, and writes into <dir>:

    bundle.json     the bundle
    row.json        the `bundles/<id>` row: {bundle, page, unit, intent, title, createdAt, status}
    writes.json     the `writes` array for one ArtifactData batch
and keeps a copy in the bundle store (`$APPROVAL_GATES_DIR/bundles/<intent>/<unit>/`, default ~/.claude/approval-gates),
which the next draft reads. A changed row with no `revNote` is refused: say what changed. It prints
{"id", "page", "unit", "revision", "bundle", "writes", "lookFirst", "rows"}.

The script never touches the artifact: the agent makes the ArtifactData call. Standard library only.
"""

import argparse
import copy
import datetime
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gate_bundle  # noqa: E402  (same folder: record_root, load_graph, state_field, slugify)
import validate_bundle  # noqa: E402

DESIGN_STAGES = ("functional-design", "nfr-requirements", "nfr-design", "infrastructure-design")
STAGE_SHORT = {
    "functional-design": ("FD", "Functional"),
    "nfr-requirements": ("NR", "NFR Req."),
    "nfr-design": ("ND", "NFR Design"),
    "infrastructure-design": ("ID", "Infra"),
    "code-generation": ("CG", "Code plan"),
}
STAGE_NAME = {
    "functional-design": "Functional Design",
    "nfr-requirements": "NFR Requirements",
    "nfr-design": "NFR Design",
    "infrastructure-design": "Infrastructure Design",
    "code-generation": "Code Generation",
}
SETTLED = re.compile(r"^(resolved|fixed|closed|done|addressed|verified)\b", re.I)
WAIVED = re.compile(r"^(waived|accepted|deferred|won'?t fix|wontfix)\b", re.I)
SEVERITY_HINT = {"critical": "critical", "blocker": "critical", "major": "medium", "minor": "low", "nit": "low", "info": "low"}
ID_TOKEN = re.compile(r"\b(?:[A-Z]{1,6}\d+(?:\.\d+)*|R-\d+|ADR-\d+|Q\d+)\b")
DEFINED_ID = re.compile(r"^(?:[A-Z]{1,6}\d+(?:\.\d+)*|ADR-\d+)$")
FILE_TOKEN = re.compile(r"`([^`\s]+\.[A-Za-z]{1,5})`")
MAX_ROW_BYTES = 900_000
LAYERS = (
    (re.compile(r"\btests?\b|test runner", re.I), "tests"),
    (re.compile(r"project structure|setup|scaffold|branch", re.I), "setup"),
    (re.compile(r"data access|storage|persistence|database|data model", re.I), "data"),
    (re.compile(r"business logic|domain|rules", re.I), "logic"),
    (re.compile(r"\bapi\b|endpoint|http|mcp|backend", re.I), "api"),
    (re.compile(r"frontend|\bui\b|component|screen|page", re.I), "UI"),
    (re.compile(r"infrastructure|deploy|ci\b|pipeline", re.I), "infra"),
    (re.compile(r"build|check|lint|configuration", re.I), "checks"),
    (re.compile(r"documentation|readme|docs", re.I), "docs"),
)


class BundleError(Exception):
    pass


# ---------------------------------------------------------------- small helpers

def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def digest(*parts):
    return hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]


def plain(text):
    """Markdown emphasis and code ticks dropped, whitespace joined."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", text)
    text = text.replace("`", "")
    return " ".join(text.split())


def one_line(text, size=120):
    """The first sentence, cut at a word boundary to `size`; never ends in a space or an ellipsis."""
    text = plain(text)
    first = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", text, maxsplit=1)[0].rstrip(".")
    if len(first) > size:
        first = first[:size].rsplit(" ", 1)[0]
    return first.rstrip(" ,;:—-…") or "(no text)"


def clip(text, size):
    text = plain(text)
    return text if len(text) <= size else text[: size - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def sentence(text):
    """The text with its first letter upper-case."""
    return text[:1].upper() + text[1:] if text else text


def humanize(slug):
    words = re.sub(r"^\d{6}-", "", slug).replace("-", " ").split()
    keep = {"mvp": "MVP", "api": "API", "mcp": "MCP", "ui": "UI", "nfr": "NFR"}
    out = [keep.get(w.lower(), w) for w in words]
    if out:
        out[0] = out[0] if out[0].isupper() else out[0].capitalize()
    return " ".join(out)


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def rel(path, project):
    return os.path.relpath(path, project)


def store_dir(intent, unit):
    base = os.environ.get("APPROVAL_GATES_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "approval-gates")
    return os.path.join(base, "bundles", intent, unit)


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def latest(intent, unit, page):
    return load_json(os.path.join(store_dir(intent, unit), f"{page}-latest.json"))


# ---------------------------------------------------------------- the project

class Unit:
    """The Unit's record folders, read once."""

    def __init__(self, project, unit):
        self.project = os.path.abspath(project)
        self.space, self.intent, self.root = gate_bundle.record_root(self.project)
        self.unit = unit
        self.folder = os.path.join(self.root, "construction", unit)
        if not os.path.isdir(self.folder):
            raise BundleError(f"the Unit has no record folder: {self.folder}")
        self.graph = gate_bundle.load_graph(self.project) or {}

    def stage_folder(self, stage):
        return os.path.join(self.folder, stage)

    def ran(self, stage):
        folder = self.stage_folder(stage)
        return os.path.isdir(folder) and any(n.endswith(".md") and not n.endswith("-questions.md") for n in os.listdir(folder))

    def documents(self, stage):
        """The stage's records (no questions file, no memory, no reviews), by name."""
        folder = self.stage_folder(stage)
        if not os.path.isdir(folder):
            return []
        return [os.path.join(folder, n) for n in sorted(os.listdir(folder))
                if n.endswith(".md") and not n.endswith("-questions.md") and n != "memory.md" and not n.startswith(".")]

    def stage_name(self, stage):
        g = self.graph.get(stage) or {}
        return g.get("name") or STAGE_NAME.get(stage) or humanize(stage)

    def names(self):
        """(unitLabel, unitName) from the first record H1 that reads `— U4 Moving between days (`slug`)`."""
        for stage in DESIGN_STAGES + ("code-generation",):
            for path in self.documents(stage):
                head = read(path).split("\n", 1)[0]
                found = re.search(r"[—-]\s*(U\d+)\s+(.+?)\s*\(`?" + re.escape(self.unit), head)
                if found:
                    return found.group(1), found.group(2).strip()
        return "", humanize(self.unit)


def definitions(unit):
    """{id: text} of the ids the records define: a table row whose first cell is the id, or a heading that starts with it.
    The Unit's own records win over the intent's other records."""
    found = {}

    def scan(path):
        try:
            text = read(path)
        except OSError:
            return
        for line in text.splitlines():
            row = re.match(r"^\|\s*\**([A-Z][A-Za-z0-9.-]*\d)\**\s*\|\s*(.+?)\s*\|", line)
            if row and DEFINED_ID.match(row.group(1)):
                found.setdefault(row.group(1), clip(row.group(2), 220))
                continue
            head = re.match(r"^#{2,4}\s+([A-Z][A-Za-z0-9.-]*\d)[:.]?\s+(.+)$", line)
            if head and DEFINED_ID.match(head.group(1)):
                found.setdefault(head.group(1), clip(head.group(2), 220))
                continue
            bullet = re.match(r"^\s*[-*]\s+\*\*([A-Z][A-Za-z0-9.-]*\d)\b[^*]*\*\*:?\s*(.*)$", line)
            if bullet and DEFINED_ID.match(bullet.group(1)) and bullet.group(2):
                found.setdefault(bullet.group(1), clip(bullet.group(2), 220))

    for stage in DESIGN_STAGES + ("code-generation",):
        for path in unit.documents(stage):
            scan(path)
    for phase in ("inception", "ideation"):
        for dirpath, _dirs, files in os.walk(os.path.join(unit.root, phase)):
            for name in sorted(files):
                if name.endswith(".md") and not name.endswith("-questions.md"):
                    scan(os.path.join(dirpath, name))
    return found


# ---------------------------------------------------------------- the person's answers

def parse_questions(path):
    """[{n, title, answer, proposed}] of a questions file; the summary-confirmation block is not a question."""
    out = []
    text = read(path)
    for block in re.split(r"(?m)^(?=## )", text):
        head = re.match(r"## Question (\d+)\s*[:.—-]\s*(.+)", block)
        if not head:
            continue
        answer = re.search(r"^\[Answer\]:[ \t]*(.*)$", block, re.M)
        proposed = re.search(r"^\*\*Proposed:\*\*\s*([A-Z])\b", block, re.M)
        out.append({"n": int(head.group(1)), "title": head.group(2).strip(),
                     "answer": (answer.group(1).strip() if answer else ""),
                     "proposed": proposed.group(1) if proposed else None})
    return out


def answer_groups(unit, stages):
    groups = []
    for stage in stages:
        folder = unit.stage_folder(stage)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith("-questions.md"):
                continue
            path = os.path.join(folder, name)
            abbr = STAGE_SHORT.get(stage, (stage[:2].upper(), ""))[0].lower()
            qs = []
            for q in parse_questions(path):
                if not q["answer"]:
                    continue
                item = {"id": f"Q{q['n']}", "anchor": f"{abbr}-q{q['n']}", "text": one_line(q["title"], 150), "answer": q["answer"][:600]}
                if q["proposed"]:
                    item["proposed"] = q["proposed"]
                qs.append(item)
            if qs:
                key = abbr + "-answers" if name == f"{stage}-questions.md" else gate_bundle.slugify(name[:-3])
                groups.append({"key": key, "stage": stage, "title": unit.stage_name(stage), "file": rel(path, unit.project), "questions": qs})
    return groups


def question_index(groups):
    """{(stage, 'Q3'): (anchor, text, answer, proposed)} for answer-reference tips."""
    out = {}
    for g in groups:
        for q in g["questions"]:
            out[(g["stage"], q["id"])] = (q["anchor"], q["text"], q["answer"], q.get("proposed"))
    return out


# ---------------------------------------------------------------- references

def make_refs(text, defs, stage, questions, limit=6):
    """References for the ids a piece of text names: design ids with their text, and Q<n> of the stage's questions file."""
    refs, seen = [], set()
    for token in ID_TOKEN.findall(text):
        if token in seen or len(refs) >= limit:
            continue
        seen.add(token)
        if token.startswith("Q") and (stage, token) in questions:
            anchor, qtext, answer, proposed = questions[(stage, token)]
            abbr = STAGE_SHORT.get(stage, ("", ""))[0]
            tip = f"{STAGE_NAME.get(stage, stage)} {token}: {qtext}. Your answer: {answer[:80]}"
            if proposed and proposed != answer[:1]:
                tip += f", proposed {proposed}"
            refs.append({"label": f"{abbr}-{token}", "tip": clip(tip, 400), "target": "#" + anchor})
        elif token in defs:
            refs.append({"label": token, "tip": defs[token], "target": f"path:{defs_path(token)}"})
    return refs


_DEF_PATHS = {}


def defs_path(token):
    return _DEF_PATHS.get(token, "aidlc") + f"#{token}"


def index_definition_paths(unit):
    """Which record defines each id, for `path:` targets (the same scan order as definitions())."""
    _DEF_PATHS.clear()
    paths = []
    for stage in DESIGN_STAGES + ("code-generation",):
        paths += unit.documents(stage)
    for phase in ("inception", "ideation"):
        for dirpath, _dirs, files in os.walk(os.path.join(unit.root, phase)):
            paths += [os.path.join(dirpath, n) for n in sorted(files) if n.endswith(".md") and not n.endswith("-questions.md")]
    for path in paths:
        try:
            text = read(path)
        except OSError:
            continue
        for token in set(re.findall(r"(?m)^(?:\|\s*\**|#{2,4}\s+|\s*[-*]\s+\*\*)([A-Z][A-Za-z0-9.-]*\d)\b", text)):
            if DEFINED_ID.match(token):
                _DEF_PATHS.setdefault(token, rel(path, unit.project))


# ---------------------------------------------------------------- plan page rows

def assumptions(unit, stages, defs, questions):
    rows, n = [], 0
    for stage in stages:
        for path in unit.documents(stage):
            text = read(path)
            block = re.search(r"(?ms)^## Assumptions[^\n]*\n(.*?)(?=^## |\Z)", text)
            if not block:
                continue
            for i, item in enumerate(re.findall(r"(?m)^\s*[-*]\s+\[assumption\]\s*(.+(?:\n(?!\s*[-*]\s|\s*$).+)*)", block.group(1)), 1):
                n += 1
                body = plain(item)
                rows.append({
                    "id": f"A-{n}", "title": one_line(body), "label": None, "body": body,
                    "where": STAGE_SHORT.get(stage, ("", unit.stage_name(stage)))[1],
                    "refs": make_refs(item, defs, stage, questions),
                    "source": {"path": rel(path, unit.project), "key": f"assumption-{i}", "digest": digest(body)},
                })
    return rows


def newest_review(unit, stage):
    found = gate_bundle.newest_review(unit.stage_folder(stage))
    return found[0] if found else None


def review_findings(path):
    """[{id, severity, location, finding, action, status}] from a review's findings table."""
    out = []
    lines = read(path).splitlines()
    header = None
    for line in lines:
        if not line.startswith("|"):
            header = None if not line.strip() else header
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            low = [c.lower() for c in cells]
            if "id" in low and "finding" in low:
                header = low
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        row = dict(zip(header, cells))
        if not re.match(r"^R-\d+$", row.get("id", "")):
            continue
        out.append({"id": row["id"], "severity": row.get("severity", ""), "location": row.get("location", ""),
                    "finding": row.get("finding", ""), "action": row.get("required action", row.get("action", "")),
                    "status": row.get("status", "")})
    return out


def covered_by(steps_raw, finding_id, stage):
    """'Step 7 settles it' when a code-plan sub-step names the finding with its stage, else None."""
    word = {"functional-design": "functional", "nfr-requirements": "nfr requirements", "nfr-design": "nfr design",
            "infrastructure-design": "infrastructure"}.get(stage, stage)
    hits = [st["n"] for st in steps_raw for sub in st["subs"]
            if re.search(r"\b" + re.escape(finding_id) + r"\b", sub) and word in sub.lower()]
    if not hits:
        return None
    hits = sorted(set(hits))
    names = f"Step {hits[0]}" if len(hits) == 1 else "Steps " + ", ".join(map(str, hits[:-1])) + f" and {hits[-1]}"
    return {"text": f"{names} {'settles' if len(hits) == 1 else 'settle'} it", "settled": True}


def findings(unit, stages, defs, questions, steps_raw):
    rows = []
    for stage in stages:
        path = newest_review(unit, stage)
        if not path:
            continue
        abbr = STAGE_SHORT.get(stage, (stage[:2].upper(), ""))[0]
        for f in review_findings(path):
            status = plain(f["status"])
            if SETTLED.match(status):
                continue
            body = plain(f["finding"])
            if f["action"]:
                body += " Asked for: " + plain(f["action"])
            row = {
                "id": f"{abbr} {f['id']}", "title": one_line(f["finding"]),
                "label": SEVERITY_HINT.get(plain(f["severity"]).lower().split(" ")[0]), "body": body,
                "where": STAGE_SHORT.get(stage, ("", unit.stage_name(stage)))[1],
                "refs": make_refs(f["location"] + " " + f["finding"], defs, stage, questions),
                "source": {"path": rel(path, unit.project), "key": f["id"], "digest": digest(f["finding"], f["action"], status)},
            }
            cover = covered_by(steps_raw, f["id"], stage)
            if cover:
                row["coveredBy"] = cover
            elif WAIVED.match(status):
                row["coveredBy"] = {"text": "waived by the reviewer", "settled": True}
            else:
                row["coveredBy"] = {"text": "not in the plan", "settled": False}
            rows.append(row)
    return rows


def parse_steps(path):
    """[{n, title, subs: [text]}] of a code plan's `### Step N: title` headings and their `- [ ]` items."""
    steps = []
    for block in re.split(r"(?m)^(?=### Step )", read(path)):
        head = re.match(r"### Step (\d+)\s*[:.—-]\s*(.+)", block)
        if not head:
            continue
        block = re.split(r"(?m)^## ", block, maxsplit=1)[0]
        subs = [plain(s) for s in re.findall(r"(?m)^\s*[-*]\s+(?:\[[ xX]\]\s+)?(.+)$", block)]
        steps.append({"n": int(head.group(1)), "title": head.group(2).strip(), "subs": subs})
    return steps


def layer_of(title):
    for pattern, layer in LAYERS:
        if pattern.search(title):
            return layer
    return "other"


def plan_steps(path, unit, defs, questions):
    raw = parse_steps(path)
    out = []
    for i, st in enumerate(raw, 1):
        text = " ".join(st["subs"])
        files = {m for m in FILE_TOKEN.findall(read_step_source(path, st["n"])) if "/" in m or "." in m}
        implements = [r for r in make_refs(text, defs, "code-generation", questions, limit=8)]
        out.append({
            "n": i, "title": one_line(st["title"], 120), "layer": layer_of(st["title"]), "files": len(files),
            "subs": [{"text": s[:4000]} for s in st["subs"]] or [{"text": st["title"]}],
            "implements": implements,
            "source": {"path": rel(path, unit.project), "key": f"step-{st['n']}", "digest": digest(st["title"], *st["subs"])},
        })
    return out, raw


def read_step_source(path, n):
    found = re.search(r"(?ms)^### Step " + str(n) + r"\b.*?(?=^### |^## |\Z)", read(path))
    return found.group(0) if found else ""


# ---------------------------------------------------------------- unit-end rows

def summary_sections(path):
    """{H2 title: body} of a markdown file."""
    out = {}
    for block in re.split(r"(?m)^(?=## )", read(path)):
        head = re.match(r"## (.+)", block)
        if head:
            out[head.group(1).strip().lower()] = block.split("\n", 1)[1] if "\n" in block else ""
    return out


def bullets(text):
    return [plain(b) for b in re.findall(r"(?m)^\s*[-*]\s+(.+(?:\n(?!\s*[-*]\s|\s*$).+)*)", text)]


def table_rows(text):
    rows, header = [], None
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def unit_end_sections(unit, defs, questions):
    path = os.path.join(unit.stage_folder("code-generation"), "code-summary.md")
    if not os.path.isfile(path):
        raise BundleError(f"the unit-end page is built from the code summary, and there is none: {path}")
    parts = summary_sections(path)
    src = rel(path, unit.project)

    def pick(*names):
        for name in names:
            for key, body in parts.items():
                if key.startswith(name):
                    return body
        return ""

    changes = []
    for i, b in enumerate(bullets(pick("deviations")), 1):
        changes.append({"id": f"D-{i}", "title": one_line(b), "label": None, "body": b, "refs": make_refs(b, defs, "code-generation", questions),
                        "source": {"path": src, "key": f"deviation-{i}", "digest": digest(b)}})
    unverified = []
    for i, b in enumerate(bullets(pick("not verified")), 1):
        unverified.append({"id": f"V-{i}", "title": one_line(b), "label": None, "body": b, "refs": make_refs(b, defs, "code-generation", questions),
                           "source": {"path": src, "key": f"unverified-{i}", "digest": digest(b)}})
    built = []
    for i, r in enumerate(table_rows(pick("files created", "files")), 1):
        area = plain(r.get("area", "") or f"Piece {i}")
        what = plain(r.get("what they do", r.get("what it does", "")))
        files = FILE_TOKEN.findall(r.get("files", "")) or [plain(r.get("files", ""))]
        built.append({"id": f"B-{i}", "title": one_line(f"{area}: {what}" if what else area), "label": None,
                      "body": what or area, "where": files[0][:48] if files and files[0] else "", "whereIsPath": True,
                      "refs": make_refs(what, defs, "code-generation", questions),
                      "source": {"path": src, "key": f"built-{i}", "digest": digest(area, what, r.get("files", ""))}})
    return [
        {"key": "changes", "kind": "changes", "title": "Changed after plan approval", "short": "Changed",
         "hint": "The design stays as approved, except these", "refsLabel": "Was", "rows": changes,
         **({"asApproved": True} if not changes else {})},
        {"key": "unverified", "kind": "unverified", "title": "Not verified yet", "short": "Not verified",
         "hint": "Left for Build and Test or CI", "refsLabel": "For", "rows": unverified},
        {"key": "built", "kind": "built", "title": "What was built", "short": "Built",
         "hint": "One line per piece that matters; open a row for where it lives and what it uses", "refsLabel": "Uses", "rows": built},
    ]


def folded_design(plan_bundle):
    rows = []
    for s in plan_bundle.get("sections") or []:
        for r in validate_bundle.sort_rows(s.get("rows") or []):
            rows.append({"id": r["id"], "title": r["title"], "label": r["label"]})
    rows = validate_bundle.sort_rows(rows)
    steps = len((plan_bundle.get("plan") or {}).get("steps") or [])
    answers = sum(len(g.get("questions") or []) for g in plan_bundle.get("answers") or [])
    return {"bundle": plan_bundle.get("id", ""), "rows": rows,
            "counts": f"{len(rows)} rows · {answers} answers · {steps} steps"}


# ---------------------------------------------------------------- carrying the agent's work over

def carry_over(draft, previous):
    """Rows whose source is unchanged come back as the agent left them; hand-written rows and sections come back too."""
    if not previous:
        return
    prev_rows = {}
    for s in previous.get("sections") or []:
        for r in s.get("rows") or []:
            if r.get("source"):
                prev_rows[(r["source"]["path"], r["source"]["key"])] = r
    by_key = {s["key"]: s for s in draft["sections"]}
    for s in previous.get("sections") or []:
        mine = by_key.get(s["key"])
        hand = [r for r in s.get("rows") or [] if not r.get("source")]
        if mine is None:
            by_key[s["key"]] = copy.deepcopy(dict(s, rows=hand))
            draft["sections"].append(by_key[s["key"]])
            continue
        for field in ("title", "short", "hint", "refsLabel"):
            if field in s:
                mine[field] = s[field]
        rows = []
        for r in mine["rows"]:
            old = prev_rows.get((r["source"]["path"], r["source"]["key"])) if r.get("source") else None
            if old and old["source"]["digest"] == r["source"]["digest"]:
                rows.append(copy.deepcopy(old))
            elif old:
                kept = copy.deepcopy(old)  # the agent's wording stays as a starting point; the label is asked again
                kept.update(body=r["body"], source=r["source"], label=None)
                kept.pop("revNote", None)
                rows.append(kept)
            else:
                rows.append(r)
        mine["rows"] = rows + [copy.deepcopy(r) for r in hand]
        if mine.get("rows") and mine.get("asApproved"):
            mine.pop("asApproved")
    if draft.get("plan") and previous.get("plan"):
        prev_steps = {st["source"]["key"]: st for st in previous["plan"].get("steps") or [] if st.get("source")}
        steps = []
        for st in draft["plan"]["steps"]:
            old = prev_steps.get(st["source"]["key"])
            if old and old["source"]["digest"] == st["source"]["digest"]:
                steps.append(dict(copy.deepcopy(old), n=st["n"]))
            else:
                steps.append(st)
        draft["plan"]["steps"] = steps
    head, prev_head = draft["header"], previous.get("header") or {}
    for field in ("lede", "title", "footer", "links"):
        if field in prev_head:
            head[field] = prev_head[field]
    head["revisions"] = [r for r in prev_head.get("revisions") or [] if r.get("n", 0) < head["revision"]] + \
        [r for r in head["revisions"] if r.get("n") == head["revision"]]


# ---------------------------------------------------------------- draft

def draft(args):
    project = os.path.abspath(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    unit = Unit(project, args.unit)
    index_definition_paths(unit)
    defs = definitions(unit)
    label, name = unit.names()
    ran = [s for s in DESIGN_STAGES if unit.ran(s)]
    previous = load_json(args.previous) if args.previous else latest(unit.intent, args.unit, args.page)
    revision = 1
    if previous:
        revision = previous["header"]["revision"] + (0 if args.same_revision else 1)
    groups = answer_groups(unit, ran + ["code-generation"])
    questions = question_index(groups)
    stamp = now_utc()
    header = {
        "project": humanize(unit.space), "intent": unit.intent, "intentName": humanize(unit.intent),
        "unit": args.unit, "unitName": name, "title": (f"{label} · " if label else "") + name + (" — built" if args.page == "unit-end" else ""),
        "lede": "", "status": "Plan approval · answer in chat" if args.page == "plan" else "End of Unit · answer in chat",
        "revision": revision,
        "revisions": [{"n": revision, "note": "first draft" if revision == 1 else "revision", "at": stamp.isoformat().replace("+00:00", "Z")}],
        "facts": [],
        "stages": [{"slug": s, "name": unit.stage_name(s), "ran": s in ran} for s in DESIGN_STAGES],
    }
    if label:
        header["unitLabel"] = label
    bundle = {"schema": "aidlc-gate-bundle/1", "page": args.page, "id": "", "createdAt": "", "header": header,
              "sections": [], "answers": groups if args.page == "plan" else [],
              "provenance": {"builder": "approval-gates unit_bundle.py", "records": []}}
    todo = []
    if args.page == "plan":
        plan_path = os.path.join(unit.stage_folder("code-generation"), "code-generation-plan.md")
        if not os.path.isfile(plan_path):
            raise BundleError(f"the plan page is built with the code plan, and there is none yet: {plan_path}")
        steps, raw = plan_steps(plan_path, unit, defs, questions)
        summary = summary_sections(plan_path).get("summary", "")
        builds = re.search(r"(?m)^\s*-\s+Builds:\s*(.+)$", summary)
        header["lede"] = sentence(plain(builds.group(1))) if builds else ""
        files = sum(st["files"] for st in steps)
        bundle["plan"] = {"title": "Code plan", "path": rel(plan_path, project), "steps": steps,
                          "hint": f"{len(steps)} steps · ~{files} files"}
        bundle["sections"] = [
            {"key": "narrows", "kind": "narrows", "title": "Narrows what you approved", "short": "Narrows",
             "hint": "An earlier approved record now reads differently", "rows": []},
            {"key": "visible", "kind": "visible", "title": "What people see, data, API, dependencies", "short": "Visible",
             "hint": "Changes a person would notice or a contract would feel", "rows": []},
            {"key": "assumptions", "kind": "assumptions", "title": "Assumptions made without asking", "short": "Assumptions",
             "hint": "Ranked by what it costs if one is wrong", "rows": assumptions(unit, ran + ["code-generation"], defs, questions)},
            {"key": "findings", "kind": "findings", "title": "Reviewer findings left open", "short": "Findings",
             "hint": "Not settled in the design; what in the plan settles each", "rows": findings(unit, ran, defs, questions, raw)},
            {"key": "tests", "kind": "tests", "title": "Tests", "short": "Tests",
             "hint": "Grouped; open only when something matters", "rows": []},
        ]
        bundle["provenance"]["records"] = sorted({rel(p, project) for s in ran + ["code-generation"] for p in unit.documents(s)})
        todo += [f"write `{key}`: {what}" for key, what in (
            ("narrows", "every place the design narrows something already approved (an inception record, an earlier Unit, an answer)"),
            ("visible", "changes to what the person sees, stored data, API/MCP shape, security, dependencies"),
            ("tests", "the plan's tests, grouped (a row per group), each labelled by what it costs if it is wrong"))]
    else:
        approved = latest(unit.intent, args.unit, "plan")
        if not approved:
            raise BundleError("the unit-end page folds the approved plan page, and none was built for this Unit here "
                              f"(no {os.path.join(store_dir(unit.intent, args.unit), 'plan-latest.json')})")
        bundle["sections"] = unit_end_sections(unit, defs, questions)
        bundle["design"] = folded_design(approved)
        summary = read(os.path.join(unit.stage_folder("code-generation"), "code-summary.md"))
        first = re.search(r"(?ms)^# .*?\n\s*\n(.+?)(?:\n\s*\n|\Z)", summary)
        header["lede"] = plain(first.group(1)) if first else ""
        bundle["provenance"]["records"] = [rel(os.path.join(unit.stage_folder("code-generation"), "code-summary.md"), project)]
        bundle["provenance"]["previous"] = approved.get("id", "")
        todo += ["`changes`: keep the rows that change behaviour or the approved design; when none does, empty it and set asApproved",
                 "`built`: say each piece in plain words, label it core, main or minor, and add a `map` of how the pieces connect",
                 "header.facts: the test count, coverage and the other figures of the code summary"]
    carry_over(bundle, previous)
    filled = {s["key"] for s in bundle["sections"] if s["rows"]}
    todo = [t for t in todo if not any(t.startswith(f"write `{k}`") for k in filled)]
    bundle["id"] = f"{gate_bundle.slugify(unit.intent + '-' + args.unit)}-{args.page}-v{revision}-{stamp.strftime('%Y%m%dT%H%M')}"
    bundle["createdAt"] = stamp.isoformat().replace("+00:00", "Z")
    if previous:
        bundle["provenance"]["previous"] = previous.get("id", "")
    unlabelled = [r["id"] for _s, r in validate_bundle.all_rows(bundle) if not r.get("label")]
    if unlabelled:
        todo.insert(0, f"label {len(unlabelled)} row(s) ({', '.join(unlabelled[:12])}{' …' if len(unlabelled) > 12 else ''}): "
                       "critical, high, medium, low (core, main, minor on built rows); pick look first")
    if not header["lede"]:
        todo.insert(0, "write header.lede: what the Unit does, in plain words")
    else:
        todo.insert(0, "check header.lede reads as plain words")
    if revision > 1:
        todo.append(f"header.revisions: say in one line what v{revision} changes")
    todo.append("rewrite every title and body the script took from the records in plain words (titles one line)")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)
        f.write("\n")
    rows = sum(len(s["rows"]) for s in bundle["sections"])
    print(json.dumps({"draft": os.path.abspath(args.out), "page": args.page, "revision": revision, "rows": rows,
                      "carriedFrom": (previous or {}).get("id"), "todo": todo}, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- finalize

def content(item, fields):
    return json.dumps({k: item.get(k) for k in fields}, sort_keys=True, ensure_ascii=False)


ROW_FIELDS = ("title", "label", "body", "refs", "coveredBy", "suggestion", "where", "lookFirst")


def mark_revisions(bundle, previous):
    revision = bundle["header"]["revision"]
    if revision == 1 or not previous:
        for _s, r in validate_bundle.all_rows(bundle):
            for k in ("rev", "revKind", "revNote"):
                r.pop(k, None)
        return []
    missing = []
    old_rows = {r["id"]: r for _s, r in validate_bundle.all_rows(previous)}
    for _s, r in validate_bundle.all_rows(bundle):
        old = old_rows.get(r["id"])
        if old and content(old, ROW_FIELDS) == content(r, ROW_FIELDS):
            for k in ("rev", "revKind", "revNote"):
                if old.get(k) is not None:
                    r[k] = old[k]
                else:
                    r.pop(k, None)
            continue
        if r.get("rev") and r["rev"] != revision:
            r.pop("revNote", None)  # the note of an earlier revision; this one needs its own
        r["rev"], r["revKind"] = revision, ("changed" if old else "new")
        if not r.get("revNote"):
            missing.append(f"row {r['id']}")
    old_steps = {st["title"]: st for st in (previous.get("plan") or {}).get("steps") or []}
    old_by_n = {st["n"]: st for st in (previous.get("plan") or {}).get("steps") or []}
    for st in (bundle.get("plan") or {}).get("steps") or []:
        old = old_steps.get(st["title"]) or old_by_n.get(st["n"])
        old_subs = {s["text"]: s for s in (old or {}).get("subs") or []}
        for sub in st["subs"]:
            if sub["text"] in old_subs:
                if old_subs[sub["text"]].get("rev"):
                    sub["rev"] = old_subs[sub["text"]]["rev"]
                else:
                    sub.pop("rev", None)
            else:
                sub["rev"] = revision
        same = old and content(old, ("title", "layer", "files", "implements")) == content(st, ("title", "layer", "files", "implements")) \
            and [s["text"] for s in old["subs"]] == [s["text"] for s in st["subs"]]
        if same:
            for k in ("rev", "revKind", "revNote"):
                if old.get(k) is not None:
                    st[k] = old[k]
                else:
                    st.pop(k, None)
            continue
        if st.get("rev") and st["rev"] != revision:
            st.pop("revNote", None)
        st["rev"], st["revKind"] = revision, ("changed" if old else "new")
        if not old:
            for sub in st["subs"]:
                sub.pop("rev", None)
        if not st.get("revNote"):
            missing.append(f"step {st['n']}")
    return missing


def default_facts(bundle):
    head = bundle["header"]
    if head.get("facts"):
        return
    look = sum(1 for _s, r in validate_bundle.all_rows(bundle) if r.get("lookFirst"))
    facts = [{"label": "Look first", "value": f"{look} row{'s' if look != 1 else ''}"}]
    if bundle["page"] == "plan":
        stages = head.get("stages") or []
        facts.append({"label": "Design stages", "value": f"{sum(1 for s in stages if s['ran'])} of {len(stages)} ran"})
        facts.append({"label": "This plan", "value": f"v{head['revision']}"})
    head["facts"] = facts


def finalize(args):
    bundle = load_json(args.bundle)
    if not isinstance(bundle, dict):
        raise BundleError(f"cannot read the bundle {args.bundle}")
    head = bundle.get("header") or {}
    intent, unit = head.get("intent", ""), head.get("unit", "")
    revision = head.get("revision", 1) if isinstance(head.get("revision"), int) else 1
    if args.previous:
        previous = load_json(args.previous)
    elif revision > 1:
        previous = load_json(os.path.join(store_dir(intent, unit), f"{bundle.get('page')}-v{revision - 1}.json"))
    else:
        previous = None
    missing = mark_revisions(bundle, previous)
    default_facts(bundle)
    problems = validate_bundle.validate(bundle)
    if missing:
        problems.append(f"say what changed in v{head.get('revision')} (revNote) for: {', '.join(missing)}")
    if problems:
        print("\n".join(problems))
        print(f"unit_bundle.py: the bundle does not hold to the contract ({len(problems)} problem(s)); fix {args.bundle} and run finalize again",
              file=sys.stderr)
        return 1
    row = {"bundle": bundle, "page": bundle["page"], "unit": unit, "intent": intent, "title": head["title"],
           "createdAt": bundle["createdAt"], "status": "open"}
    size = len(json.dumps(row, ensure_ascii=False).encode("utf-8"))
    if size > MAX_ROW_BYTES:
        raise BundleError(f"the bundle is {size} bytes, over the {MAX_ROW_BYTES}-byte row limit: shorten the bodies")
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    paths = {}
    for name, value in (("bundle.json", bundle), ("row.json", row)):
        paths[name] = os.path.join(out, name)
        with open(paths[name], "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, ensure_ascii=False)
            f.write("\n")
    writes = [{"op": "set", "collection": "bundles", "doc_id": bundle["id"], "file_path": paths["row.json"]}]
    paths["writes.json"] = os.path.join(out, "writes.json")
    with open(paths["writes.json"], "w", encoding="utf-8") as f:
        json.dump(writes, f, indent=2)
        f.write("\n")
    keep = store_dir(intent, unit)
    os.makedirs(keep, exist_ok=True)
    for name in (f"{bundle['page']}-latest.json", f"{bundle['page']}-v{head['revision']}.json"):
        with open(os.path.join(keep, name), "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2, ensure_ascii=False)
            f.write("\n")
    rows = sum(len(s["rows"]) for s in bundle["sections"])
    look = [r["id"] for _s, r in validate_bundle.all_rows(bundle) if r.get("lookFirst")]
    print(json.dumps({"id": bundle["id"], "page": bundle["page"], "unit": unit, "revision": head["revision"],
                      "bundle": paths["bundle.json"], "writes": paths["writes.json"], "lookFirst": look, "rows": rows,
                      "order": validate_bundle.order(bundle)}, ensure_ascii=False))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="unit_bundle.py", description="Build a Unit's gate bundle (unit-end rhythm).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft")
    d.add_argument("--page", choices=("plan", "unit-end"), required=True)
    d.add_argument("--unit", required=True)
    d.add_argument("--project-dir")
    d.add_argument("--previous")
    d.add_argument("--same-revision", action="store_true")
    d.add_argument("--out", required=True)
    f = sub.add_parser("finalize")
    f.add_argument("--bundle", required=True)
    f.add_argument("--project-dir")
    f.add_argument("--previous")
    f.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    try:
        return draft(args) if args.cmd == "draft" else finalize(args)
    except (BundleError, gate_bundle.BundleError) as why:
        print(f"unit_bundle.py: {why}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
