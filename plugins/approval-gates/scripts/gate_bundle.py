#!/usr/bin/env python3
"""Build the rows for one AI-DLC approval gate: a draft the agent judges, then the rows it sends.

    gate_bundle.py draft --stage <slug> [--unit <u>] [--why first|revision|stale] [--summary-file <path>]
                   [--project-dir <dir>] [--no-brief] [--findings <file>] [--handling <file>] --out <dir>
    gate_bundle.py finalize --out <dir> [--judgment <file>]
    (with no command, the arguments are draft's)

draft writes into <dir>:
    gate.json               the draft `gates/<id>` row (never sent as it is: it has no evaluation)
    documents/<key>.json    one `gates/<id>/documents/<key>` row per document
    criteria.json           what the stage is judged against (scripts/criteria.py): the engine's stage definition, the
                            reviewer's checklist, the project's rules, what earlier stages settled
    judgment.json           the agent's part, empty (scripts/judgment.py): the evaluation, a verdict per criterion, a
                            summary and a label per item, covered or shown per document
and removes any writes.json an earlier finalize left there. It prints {"id", "stage", "unit", "documents", "round",
"judgment", "criteria", "items", "todo": [what is left to do], "next": "<the finalize command>"}.

finalize merges judgment.json into the row and refuses, in the recipe shape (Refused … because …, numbered steps with one
line per problem, It worked when …), while any part of the judgment is missing. Then it writes into <dir>:
    row.json                the `gates/<id>` row, judged
    writes.json             the `writes` array for one ArtifactData batch (set, file_path entries, no
                            if_version: every row is new)
    writes-<n>.json         only when writes.json is over one batch (50 writes or 1 MiB): the same
                            writes in order, in batches that fit; the gate row is in the first
keeps each item's summary and label for the next round (`$APPROVAL_GATES_DIR/stage-judgments/`; a draft of the same stage
carries them over for items whose text did not change), and prints
    {"id", "stage", "unit", "round", "verdict", "lookFirst", "items", "criteria", "writes", "batches"}

The script never touches the artifact: the agent makes the ArtifactData call.

Where things are read from. The project directory is --project-dir, else $CLAUDE_PROJECT_DIR, else the
current directory. The space is `aidlc/active-space`, the intent `aidlc/spaces/<space>/intents/active-intent`,
and the record <R> is `aidlc/spaces/<space>/intents/<intent>/`. The stage's folder is
<R>/<phase>/<stage>, or <R>/construction/<unit>/<stage> with --unit. The phase comes from
`.claude/tools/data/stage-graph.json` when it is there, else the first of ideation, inception,
construction, operation that holds the folder. The graph is optional: without it everything still works.

Documents: the stage graph's `produces` keys first, in that order (`<key>.md`, else `<key>.json`), then every
other *.md and *.json of the folder by name. `memory.md`, hidden files and *.lock* are never shown. The
newest `reviews/review-NN.md` is added as kind `review`. A document over 200 000 bytes is cut and ends with
a line that says how much is missing.

Round: 1 plus the number of `GATE_REJECTED` entries of this stage in <R>/audit/*.md (an entry is the block
that holds `**Event**: GATE_REJECTED` and `**Stage**: <slug>`). With --unit an entry counts only when it also
has a `**Unit**: <u>` line; without --unit only an entry with no Unit line counts.

Review brief: for a stage with a reviewer (in the graph, or, when the graph does not know the stage, a
`reviews/` folder) the script runs `aidlc engine review-brief review --stage <slug> [--unit <u>] --why <why>`
in the project directory and keeps its stdout as `brief`. The program is `aidlc` on PATH, or the executable
that $APPROVAL_GATES_AIDLC names (the tests use that). A failure omits `brief` and warns on stderr.
Ids: the gate row's `ids` says what each id its texts mention is (US1.1, FR1.4, BR1.2, Q3, R-01, ADR-009, ...), for the
page's links and tooltips. The script brings the checkout's id map up to date (`aidlc_ids.py sync`, the shared copy next
to this file) and asks it for the ids of the summary, the brief and every document, nearest the documents shown
(`aidlc_ids.py refs --near`), so a Q1 or R-01 is this stage's and a BR1.1 this Unit's. A failure leaves `ids` out and warns.
Build and Test: for the stage `build-and-test` the gate row also carries `buildTest`, the stage's tables read into
data for the page's results view: `commands` (every `Check | Command | Result` row of the test results), `coverage`
(the line coverage and floor a result names), `counts`, `targets` (the Target Verification Matrix, one entry per row,
the Unit from its `###` heading) and `evidence` (the legend of evidence codes). Columns are found by header name;
what a file does not have is left out, and when nothing is found the field is left out and the page shows the
stage as any other. Its contract is `contract/build-test.schema.json`.
Findings: with --findings (the findings file the guard saved when the review brief was printed, after the agent fixed
what it could fix for certain and recorded the model's suggestions) the gate row carries `findings`, the cards the
developer sorts on the page (Fix, Accept, Reject with a note); `findings.py cards` is its shape. The script refuses a file
whose findings lack a suggested action or a finding text. The page writes the developer's sort as `findingPicks`.
Digest: the gate row's `digest` holds the stage's items one by one (requirements, NFRs, rules, decisions, stories), what
is settled in an earlier stage, and the stage's traceability (scripts/digest.py). A traced id the stage leaves uncovered
needs a link or a reason (--handling <file>); the script refuses until every one has.
Standard library only.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aidlc_ids  # noqa: E402  (the shared copy, next to this file)
import criteria as criteria_mod  # noqa: E402  (what the stage is judged against)
import digest  # noqa: E402  (the stage's items, for the page's digest)
import findings  # noqa: E402  (the review findings that go on the page as cards)
import judgment  # noqa: E402  (the agent's evaluation of the stage, and the rules finalize holds it to)
import validate_bundle  # noqa: E402

MAX_DOC_BYTES = 200_000
MAX_BATCH_WRITES = 50
MAX_BATCH_BYTES = 1_000_000  # the limit is 1 MiB; stay under it
PHASES = ("ideation", "inception", "construction", "operation")
SKIPPED = {"memory.md"}
ACRONYMS = {"nfr": "NFR", "ci": "CI"}
BRIEF_TIMEOUT = 20


class BundleError(Exception):
    pass


# ---------------------------------------------------------------- reading the project

def read_line(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    return line.strip()
    except OSError:
        pass
    return ""


def record_root(project):
    """(space, intent, R) of the active intent, or raise BundleError."""
    space = read_line(os.path.join(project, "aidlc", "active-space"))
    if not space:
        raise BundleError(f"no active space: {os.path.join(project, 'aidlc', 'active-space')} is missing or empty")
    intents = os.path.join(project, "aidlc", "spaces", space, "intents")
    intent = read_line(os.path.join(intents, "active-intent"))
    if not intent:
        raise BundleError(f"no active intent: {os.path.join(intents, 'active-intent')} is missing or empty")
    root = os.path.join(intents, intent)
    if not os.path.isdir(root):
        raise BundleError(f"the active intent has no record folder: {root}")
    return space, intent, root


def load_graph(project):
    """The stage graph as {slug: stage}, or None when it is absent or unreadable."""
    path = os.path.join(project, ".claude", "tools", "data", "stage-graph.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    return {s["slug"]: s for s in data if isinstance(s, dict) and isinstance(s.get("slug"), str)}


def stage_dir(root, slug, unit, graph_stage):
    if unit:
        path = os.path.join(root, "construction", unit, slug)
        if os.path.isdir(path):
            return path, "construction"
        raise BundleError(f"stage folder not found: {path}")
    phases = list(PHASES)
    if graph_stage and graph_stage.get("phase") in PHASES:
        phases.remove(graph_stage["phase"])
        phases.insert(0, graph_stage["phase"])
    for phase in phases:
        path = os.path.join(root, phase, slug)
        if os.path.isdir(path):
            return path, phase
    raise BundleError(f"stage folder not found: {slug} is in none of {', '.join(os.path.join(root, p) for p in phases)}")


def state_field(root, label):
    """The value of `- **<label>**: …` in aidlc-state.md, or ''."""
    try:
        with open(os.path.join(root, "aidlc-state.md"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ""
    found = re.search(r"^\s*-\s*\*\*" + re.escape(label) + r"\*\*:[ \t]*(.*)$", text, re.M)
    return found.group(1).strip() if found else ""


# ---------------------------------------------------------------- names

def stage_name(slug, graph_stage):
    if graph_stage and isinstance(graph_stage.get("name"), str) and graph_stage["name"].strip():
        return graph_stage["name"].strip()
    return " ".join(ACRONYMS.get(w, w.capitalize()) for w in slug.split("-") if w)


def gate_title(name, unit):
    """What the gate is, for its H1, tab title and list row: `Unit u2-accounts: Approve Functional Design`, or
    `Approve Requirements Analysis` without a Unit. approval-gate.html derives the same string for older rows."""
    return (f"Unit {unit}: " if unit else "") + f"Approve {name}"


def slugify(name):
    return re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("-") or "doc"


def humanize(key):
    words = re.sub(r"[-_.]+", " ", key).split()
    return " ".join(ACRONYMS.get(w, w.capitalize()) for w in words) or key


def clip(text, size):
    text = " ".join(text.split())
    return text if len(text) <= size else text[: size - 1].rstrip() + "…"


# ---------------------------------------------------------------- documents

def split_parts(text):
    """[text] when the text fits a row, else the text in parts of at most MAX_DOC_BYTES each, split at its
    `## ` headings (the page joins the parts back in order); a single section longer than a row is cut."""
    if len(text.encode("utf-8")) <= MAX_DOC_BYTES:
        return [text]
    sections = re.split(r"(?m)^(?=## )", text)
    parts, current = [], ""
    for section in sections:
        if current and len((current + section).encode("utf-8")) > MAX_DOC_BYTES:
            parts.append(current)
            current = ""
        current += section
        if len(current.encode("utf-8")) > MAX_DOC_BYTES:
            parts.append(cut(current))
            current = ""
    if current:
        parts.append(current)
    return [p for p in parts if p.strip()] or [cut(text)]


def cut(text):
    """The text, cut to MAX_DOC_BYTES when longer, with a closing line that says how much is missing."""
    raw = text.encode("utf-8")
    if len(raw) <= MAX_DOC_BYTES:
        return text
    kept = raw[:MAX_DOC_BYTES].decode("utf-8", errors="ignore")
    missing = len(raw) - len(kept.encode("utf-8"))
    return kept + f"\n… (truncated, {missing} bytes more; open the file)"


def read_document(path, kind):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as why:
        raise BundleError(f"cannot read {path}: {why}") from None
    if kind == "json":
        try:
            text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        except ValueError:
            pass  # shown as it is
    return text


def kind_of(name):
    if name.endswith("-questions.md"):
        return "questions"
    return "json" if name.endswith(".json") else "markdown"


def candidate_files(folder):
    names = []
    for name in sorted(os.listdir(folder)):
        full = os.path.join(folder, name)
        if name.startswith(".") or ".lock" in name or name in SKIPPED or not os.path.isfile(full):
            continue
        if name.endswith(".md") or name.endswith(".json"):
            names.append(name)
    return names


def ordered_names(folder, produces):
    names = candidate_files(folder)
    first = []
    for key in produces or []:
        for ext in (".md", ".json"):
            if key + ext in names and key + ext not in first:
                first.append(key + ext)
                break
    return first + [n for n in names if n not in first]


def newest_review(folder):
    """(path, NN) of the highest reviews/review-NN.md, or None."""
    reviews = os.path.join(folder, "reviews")
    best = None
    try:
        for name in os.listdir(reviews):
            found = re.fullmatch(r"review-(\d+)\.md", name)
            if found and (best is None or int(found.group(1)) > best[1]):
                best = (os.path.join(reviews, name), int(found.group(1)), found.group(1))
    except OSError:
        return None
    return (best[0], best[2]) if best else None


def parse_review(text):
    def field(label):
        found = re.search(r"^\*\*" + label + r":\*\*[ \t]*(.+?)\s*$", text, re.M)
        return found.group(1).strip() if found else ""

    out = {"verdict": field("Verdict"), "reviewer": field("Reviewer")}
    iteration = field("Iteration")
    out["iteration"] = int(iteration) if iteration.isdigit() else iteration
    return {k: v for k, v in out.items() if v != ""}


def build_documents(folder, project, produces):
    """[(row, index entry)] in display order."""
    docs, used = [], set()
    entries = [(n, os.path.join(folder, n), kind_of(n)) for n in ordered_names(folder, produces)]
    review = newest_review(folder)
    if review:
        entries.append((f"review-{review[1]}.md", review[0], "review"))
    for name, path, kind in entries:
        key = slugify(os.path.splitext(name)[0])
        if key in used:
            key = slugify(name.replace(".", "-"))
        used.add(key)
        text = read_document(path, kind)
        rel = os.path.relpath(path, project)
        parts = split_parts(text) if kind != "json" else [cut(text)]
        n = len(docs) + 1
        index = {"key": key, "title": humanize(key), "path": rel, "kind": kind, "bytes": os.path.getsize(path)}
        if len(parts) > 1:
            index["parts"] = len(parts)
        for number, part in enumerate(parts, 1):
            row = {"n": n, "key": key, "title": index["title"], "path": rel, "kind": kind, "text": part}
            doc_id = key
            if len(parts) > 1:
                row.update(part=number, parts=len(parts))
                doc_id = f"{key}-p{number}"
            docs.append((dict(row, id=doc_id), index if number == 1 else None, path))
    return docs


# ---------------------------------------------------------------- round and brief

def count_rejections(root, slug, unit):
    """How many GATE_REJECTED entries of this stage (and Unit) the audit trail holds."""
    audit = os.path.join(root, "audit")
    total = 0
    try:
        names = sorted(os.listdir(audit))
    except OSError:
        return 0
    for name in names:
        if not name.endswith(".md"):
            continue
        try:
            with open(os.path.join(audit, name), encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        for block in re.split(r"^(?:---\s*|## .*)$", text, flags=re.M):
            if not re.search(r"^\*\*Event\*\*:\s*GATE_REJECTED\s*$", block, re.M):
                continue
            stage = re.search(r"^\*\*Stage\*\*:\s*(\S+)", block, re.M)
            if not stage or stage.group(1) != slug:
                continue
            unit_line = re.search(r"^\*\*Unit\*\*:\s*(\S+)", block, re.M)
            if (unit_line.group(1) if unit_line else None) == (unit or None):
                total += 1
    return total


NOT_ANSWERED = re.compile(r"\[User did not answer this question[^\]]*\]\s*")


def last_feedback(root, slug, unit):
    """What the developer asked for at the last Request Changes of this stage (and Unit), from the audit trail:
    {feedback, said, summary, at}, or {} when the trail has none."""
    audit = os.path.join(root, "audit")
    try:
        names = sorted(os.listdir(audit))
    except OSError:
        return {}
    last = {}
    for name in names:
        if not name.endswith(".md"):
            continue
        try:
            with open(os.path.join(audit, name), encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        for block in re.split(r"^(?:---\s*|## .*)$", text, flags=re.M):
            if not re.search(r"^\*\*Event\*\*:\s*GATE_REJECTED\s*$", block, re.M):
                continue
            stage = re.search(r"^\*\*Stage\*\*:\s*(\S+)", block, re.M)
            unit_line = re.search(r"^\*\*Unit\*\*:\s*(\S+)", block, re.M)
            if not stage or stage.group(1) != slug or (unit_line.group(1) if unit_line else None) != (unit or None):
                continue
            field = lambda name: (re.search(r"^\*\*" + name + r"\*\*:[ \t]*(.*)$", block, re.M) or [None, ""])[1].strip()
            at = field("Timestamp")
            if last and at and at < last.get("at", ""):
                continue
            said = NOT_ANSWERED.sub("", field("Feedback").replace("\\n", "\n")).strip()
            summary = field("Conductor Summary")
            if said.lower() in ("request changes", "changes"):
                said = ""  # the button alone: the substance is in the page's notes and sorted findings
            last = {"at": at, "said": said, "summary": summary, "feedback": summary or said}
    return last


def has_reviewer(graph, graph_stage, folder):
    if graph_stage is not None:
        return bool(graph_stage.get("reviewer"))
    return os.path.isdir(os.path.join(folder, "reviews"))


def run_brief(project, slug, unit, why):
    """stdout of `aidlc engine review-brief review …`, or None (with a warning) on any failure."""
    program = os.environ.get("APPROVAL_GATES_AIDLC") or "aidlc"
    cmd = [program, "engine", "review-brief", "review", "--stage", slug]
    if unit:
        cmd += ["--unit", unit]
    cmd += ["--why", why]
    try:
        done = subprocess.run(cmd, cwd=project, capture_output=True, text=True, timeout=BRIEF_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as why_not:
        print(f"approval-gates: the review brief was left out ({why_not})", file=sys.stderr)
        return None
    out = done.stdout.strip()
    if done.returncode != 0 or not out:
        print(f"approval-gates: the review brief was left out (exit {done.returncode}: "
              f"{clip(done.stderr or 'no output', 160)})", file=sys.stderr)
        return None
    return out


# ---------------------------------------------------------------- Build and Test

def split_cells(line):
    """The cells of a Markdown table row; a `|` inside backticks or escaped as `\\|` stays in its cell."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    cells, cur, tick, i = [], "", False, 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and line[i + 1:i + 2] == "|":
            cur += "|"
            i += 2
            continue
        if ch == "`":
            tick = not tick
        if ch == "|" and not tick:
            cells.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    cells.append(cur.strip())
    return cells


def md_tables(text):
    """[(heading, header cells lower-cased, rows as lists of cells)] for every table, with the nearest `###`/`##` heading above it."""
    out, heading, lines, i = [], "", text.splitlines(), 0
    while i < len(lines):
        line = lines[i]
        found = re.match(r"^#{2,3}\s+(.*?)\s*#*\s*$", line)
        if found:
            heading = found.group(1)
        if line.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$", lines[i + 1]):
            header = [c.lower().strip("`* ") for c in split_cells(line)]
            rows, i = [], i + 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(split_cells(lines[i]))
                i += 1
            out.append((heading, header, rows))
            continue
        i += 1
    return out


def column(header, *names):
    for name in names:
        for n, h in enumerate(header):
            if h == name:
                return n
    return None


def cell(row, n):
    return row[n].strip() if n is not None and n < len(row) else ""


def plain(text):
    return re.sub(r"\s+", " ", text.replace("`", "").replace("**", "")).strip()


VERDICTS = {"met": "Met", "not met": "Not Met", "notmet": "Not Met", "unverified": "Unverified", "n/a": "N/A", "na": "N/A"}


def verdict_of(text):
    key = re.sub(r"[\s`*_]+", " ", text).strip().lower()
    return VERDICTS.get(key, plain(text))


def unit_of(heading):
    found = re.match(r"([A-Za-z]+\d+)\b", heading)
    return found.group(1).upper() if found else plain(heading)


def command_ok(result):
    """False when a result reports a failure: `failed`, `error` or `timed out`, unless it is `0 failed` / `no errors`."""
    text = re.sub(r"\b(0|no|zero|without)\s+(failed|failures?|errors?)\b", "", plain(result), flags=re.I)
    return not re.search(r"\b(fail\w*|error\w*|not ok|timed? ?out|crash\w*)\b", text, re.I)


def parse_build_test(folder):
    """The `buildTest` object of a Build and Test stage folder, or None when its files hold none of the tables."""
    commands, coverage, targets, legend, counts = [], [], [], {}, {}
    files = [n for n in candidate_files(folder) if n.endswith(".md")]
    results = [n for n in files if "result" in n.lower()]  # the instruction files list commands too, to run, not run
    for name in files:
        try:
            with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        had_targets = False
        for heading, header, rows in md_tables(text):
            vi, ti = column(header, "verdict"), column(header, "target id", "target")
            if vi is not None and ti is not None:
                cols = {k: column(header, *names) for k, names in (
                    ("source", ("source",)), ("expected", ("expected",)), ("actual", ("actual",)),
                    ("evidence", ("evidence",)), ("owner", ("owning stage", "owner")))}
                for row in rows:
                    ident, verdict = plain(cell(row, ti)), verdict_of(cell(row, vi))
                    if not ident or not verdict:
                        continue
                    entry = {"id": ident, "unit": unit_of(heading) if heading else "", "verdict": verdict}
                    for key, n in cols.items():
                        value = plain(cell(row, n))
                        if value:
                            entry[key] = clip(value, 600)
                    if not entry["unit"]:
                        del entry["unit"]
                    targets.append(entry)
                    had_targets = True
                continue
            ci, ri = column(header, "command"), column(header, "result")
            if ci is not None and ri is not None and (name in results or not results):
                label = column(header, "check", "step", "name")
                for row in rows:
                    command, result = plain(cell(row, ci)), plain(cell(row, ri))
                    check = plain(cell(row, label if label is not None else 0))
                    if not (command or result):
                        continue
                    commands.append({k: v for k, v in (("check", check), ("command", command), ("result", clip(result, 300))) if v} | {"ok": command_ok(result)})
                    pct = re.search(r"\b(?:lines?|coverage|covered)\s+(\d+(?:\.\d+)?)\s*%", result, re.I)
                    if pct:
                        floor = re.search(r"\bfloor\s+(\d+(?:\.\d+)?)\s*%", result, re.I)
                        repo = re.sub(r"\s+(unit\s+)?tests?$", "", check, flags=re.I) or check
                        coverage.append({k: v for k, v in (("repo", repo), ("pct", float(pct.group(1))),
                                                          ("floor", float(floor.group(1)) if floor else None)) if v is not None and v != ""})
                continue
            if column(header, "result") == 0 and len(header) == 2 and column(header, "count") == 1:
                for row in rows:
                    key = re.sub(r"[\s`]+", " ", cell(row, 0)).strip().lower()
                    number = re.match(r"\d+", cell(row, 1))
                    if number and key.startswith("targets") and "matrix" not in key:
                        for label, field in (("met", "met"), ("not met", "notMet"), ("unverified", "unverified"), ("n/a", "na")):
                            if re.match(r"targets " + re.escape(label) + r"\b", key):
                                counts[field] = int(number.group(0))
        if had_targets:
            for line in text.splitlines():
                if re.match(r"^\s*[-*]\s+\*\*[A-Z]{1,4}\*\*\s*:", line):
                    for code, meaning in re.findall(r"\*\*([A-Z]{1,4})\*\*\s*:\s*(.*?)(?=\s+\*\*[A-Z]{1,4}\*\*\s*:|$)", line):
                        legend.setdefault(code, clip(plain(meaning).rstrip(".;"), 300))
    if targets:
        counts = {"met": 0, "notMet": 0, "unverified": 0, "na": 0}
        for t in targets:
            field = {"Met": "met", "Not Met": "notMet", "Unverified": "unverified", "N/A": "na"}.get(t["verdict"])
            if field:
                counts[field] += 1
        counts["total"] = len(targets)
    elif counts:
        counts["total"] = sum(counts.values())
    out = {}
    if commands:
        out["commands"] = commands
    if coverage:
        out["coverage"] = coverage
    if counts:
        out["counts"] = counts
    if targets:
        out["targets"] = targets
    if legend:
        out["evidence"] = legend
    return out or None


# ---------------------------------------------------------------- the rows

def id_map(root, texts, near):
    """{id: {kind, title, text, doc, line}} of the ids the texts mention, as the shared aidlc_ids.py defines them: the
    map synced first, then each id's definition nearest the documents shown. Over MAX_DOC_BYTES the texts are dropped."""
    try:
        aidlc_ids.sync(root)
        ids = aidlc_ids.refs(root, "\n".join(t for t in texts if t), near)
    except Exception as why:  # the page still links what it shows; the gate must not fail over its tooltips
        print(f"approval-gates: the id map could not be built ({why}); the page links only the ids it shows", file=sys.stderr)
        return {}
    if len(json.dumps(ids, ensure_ascii=False).encode("utf-8")) > MAX_DOC_BYTES:
        for d in ids.values():
            d.pop("text", None)
    return ids


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def build(args):
    project = os.path.abspath(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    space, intent, root = record_root(project)
    graph = load_graph(project)
    graph_stage = graph.get(args.stage) if graph else None
    folder, phase = stage_dir(root, args.stage, args.unit, graph_stage)
    docs = build_documents(folder, project, (graph_stage or {}).get("produces"))
    if not docs:
        raise BundleError(f"the stage folder holds no document to show: {folder}")

    rounds = 1 + count_rejections(root, args.stage, args.unit)
    why = args.why or ("first" if rounds == 1 else "revision")
    name = stage_name(args.stage, graph_stage)
    stamp = now_utc()
    parts = [intent, args.stage] + ([args.unit] if args.unit else [])
    # lower-case, except the T of the time stamp (YYYYMMDDTHHMM), which the guard hook and the page expect
    gate_id = slugify("-".join(parts)) + "-" + stamp.strftime("%Y%m%dT%H%M")

    gate = {
        "title": gate_title(name, args.unit),
        "stage": args.stage,
        "stageName": name,
        "phase": phase,
        "intent": intent,
        "round": rounds,
        "why": why,
        "status": "open",
        "createdAt": stamp.isoformat().replace("+00:00", "Z"),
    }
    project_line = state_field(root, "Project")
    if project_line:
        gate["project"] = clip(re.split(r"(?<=[.!?])\s", project_line)[0], 200)
    if args.unit:
        gate["unit"] = args.unit
    if args.summary_file:
        try:
            with open(args.summary_file, encoding="utf-8") as f:
                summary = f.read().strip()
        except OSError as why_not:
            raise BundleError(f"cannot read the summary file {args.summary_file}: {why_not}") from None
        if summary:
            gate["summary"] = summary
    if not args.no_brief and has_reviewer(graph, graph_stage, folder):
        brief = run_brief(project, args.stage, args.unit, why)
        if brief:
            gate["brief"] = brief
    review = newest_review(folder)
    if review:
        with open(review[0], encoding="utf-8", errors="replace") as f:
            found = parse_review(f.read())
        if found:
            gate["review"] = dict(found, file=os.path.relpath(review[0], project))
    next_slug = re.match(r"[a-z0-9][a-z0-9-]*", state_field(root, "Next Stage"))
    next_name = ""
    if next_slug and next_slug.group(0) not in ("none", "n"):
        next_name = stage_name(next_slug.group(0), graph.get(next_slug.group(0)) if graph else None)
        gate["nextStage"] = next_name
    gate["options"] = [
        {"k": "approve", "t": "Approve", "d": f"Continue to {next_name}" if next_name else "Continue"},
        {"k": "changes", "t": "Request Changes", "d": "Provide revision feedback"},
    ]
    if args.stage == "build-and-test":
        found = parse_build_test(folder)
        problems = validate_bundle.validate_build_test(found) if found else []
        if problems:
            print("approval-gates: the Build and Test tables were left out of the row (" + "; ".join(problems[:3]) + ")", file=sys.stderr)
        elif found:
            gate["buildTest"] = found
    if args.findings:
        try:
            gate["findings"] = findings.cards(findings.load_findings(args.findings))
        except (OSError, ValueError) as why_not:
            raise BundleError(f"the findings in {args.findings} cannot go on the page: {why_not}") from None
    card_texts = [" ".join(str(c.get(k, "")) for k in ("title", "plain", "action", "where"))
                  for c in (gate.get("findings") or {}).get("items", [])]
    ids = id_map(root, [gate.get("summary", ""), gate.get("brief", "")] + card_texts + [row["text"] for row, _index, _path in docs],
                 sorted({path for _row, _index, path in docs}))
    if ids:
        gate["ids"] = ids
    given = {}
    if args.handling:
        try:
            with open(args.handling, encoding="utf-8") as f:
                given = json.load(f)
        except (OSError, ValueError) as why_not:
            raise BundleError(f"cannot read the handling file {args.handling}: {why_not}") from None
    try:
        found = digest.build([row for row, _index, _path in docs], ids or {}, os.path.relpath(folder, root), given)
    except ValueError as why_not:
        raise BundleError(
            "something the stage leaves uncovered says neither where it is handled nor why not: " + str(why_not) +
            ". Do this: 1. Write a JSON file {\"<id>\": {\"text\": \"…\", \"settled\": true, \"link\": {\"kind\": \"step|doc|code|test|unit\", "
            "\"target\": \"#<anchor> | path:<file>[#<id>] | unit:<Unit>\"}}} or {\"<id>\": {\"text\": \"…\", \"acceptanceReason\": "
            "{\"text\": \"…\", \"by\": \"agent\"}}} (by \"developer\" adds \"quote\" and \"message\"). 2. Run this again with "
            "--handling <that file>. It worked when: the draft prints its id and todo list") from None
    if found["items"] or found["trace"]:
        gate["digest"] = found
    gate["documents"] = [index for _row, index, _path in docs if index]
    crit = criteria_mod.gather(project, root, space, phase, args.stage, name, folder, graph, graph_stage)
    return gate_id, gate, [row for row, _index, _path in docs], crit


def batches_of(writes, sizes):
    """Split the writes, in order, into batches of at most MAX_BATCH_WRITES writes and MAX_BATCH_BYTES bytes."""
    out, current, weight = [], [], 0
    for write, size in zip(writes, sizes):
        if current and (len(current) >= MAX_BATCH_WRITES or weight + size > MAX_BATCH_BYTES):
            out.append(current)
            current, weight = [], 0
        current.append(write)
        weight += size
    if current:
        out.append(current)
    return out


def write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return os.path.getsize(path)


SELF = os.path.abspath(__file__)
MAX_ROW_BYTES = 900_000  # one row must fit one write; stay under the 1 MiB limit


def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as why_not:
        raise BundleError(f"cannot read {what} {path}: {why_not}") from None


def refuse(what, why, problems, steps, check):
    """A refusal in the guard's recipe shape: what and why on one line, numbered steps, how to tell it worked."""
    lines = [f"Refused: {what}, because {why}.", "Do this:"]
    for n, step in enumerate(steps, 1):
        lines.append(f"{n}. {step}")
        if n == 1 and problems:
            lines += [f"   - {p}" for p in problems]
    lines.append(f"It worked when: {check}")
    print("\n".join(lines), file=sys.stderr)
    return 1


def draft(args):
    gate_id, gate, docs, crit = build(args)
    out = os.path.abspath(args.out)
    for name in os.listdir(out) if os.path.isdir(out) else []:
        if re.fullmatch(r"(writes(-\d+)?|row)\.json", name):  # an earlier finalize's output is never sent with a new draft
            os.remove(os.path.join(out, name))
    gate["gate"] = gate_id
    write_json(os.path.join(out, "gate.json"), gate)
    for row in docs:
        write_json(os.path.join(out, "documents", row["id"] + ".json"), {k: v for k, v in row.items() if k != "id"})
    write_json(os.path.join(out, "criteria.json"), crit)
    previous = None
    store = judgment.store_path(gate.get("intent"), gate.get("stage"), gate.get("unit"))
    if os.path.isfile(store):
        try:
            previous = read_json(store, "the last judgment of this stage")
        except BundleError:
            previous = None
    texts = {}
    for row in docs:
        texts[row["key"]] = texts.get(row["key"], "") + row["text"]
    found = None
    if gate.get("why") == "revision":
        project = os.path.abspath(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
        found = dict(last_feedback(record_root(project)[2], args.stage, args.unit))
        if previous and isinstance(previous.get("documents"), dict):
            found["changed"] = judgment.changed_sections(previous["documents"], texts)
        else:
            found["note"] = ("the last finalize of this stage kept no record of its documents, so the changed sections are "
                             "not listed: compare with the last page or git history")
        if previous:
            found["items"] = judgment.changed_items(previous.get("items"), gate)
    j = judgment.skeleton(gate_id, gate, crit, texts, previous, found)
    path = os.path.join(out, "judgment.json")
    write_json(path, j)
    print(json.dumps({"id": gate_id, "stage": args.stage, "unit": args.unit, "documents": [d["key"] for d in gate["documents"]],
                      "round": gate["round"], "judgment": path, "criteria": os.path.join(out, "criteria.json"),
                      "items": len(j["items"]), "todo": judgment.todo(j, gate),
                      "next": f'python3 "{SELF}" finalize --out {out}'}, ensure_ascii=False))
    return 0


def finalize(args):
    out = os.path.abspath(args.out)
    gate = read_json(os.path.join(out, "gate.json"), "the draft row (run draft first)")
    crit = read_json(os.path.join(out, "criteria.json"), "the criteria (run draft first)")
    jpath = os.path.abspath(args.judgment or os.path.join(out, "judgment.json"))
    j = read_json(jpath, "the judgment")
    cmd = f'python3 "{SELF}" finalize --out {out}'
    problems = judgment.shape_problems(j)
    if not problems and j.get("gate") != gate.get("gate"):
        problems = [f"judgment.json belongs to gate {j.get('gate')}, the draft row to {gate.get('gate')}: run draft again"]
    if problems:
        return refuse("the gate row", "judgment.json is not the file draft wrote", problems,
                      [f"Run draft again (it writes {jpath}), then do its todo list in that file.", f"Run `{cmd}`."],
                      "finalize prints the gate id and the path of writes.json.")
    row = judgment.merge(gate, crit, j)
    texts = {}
    folder = os.path.join(out, "documents")
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if name.endswith(".json"):
            doc = read_json(os.path.join(folder, name), "a document row")
            texts[doc.get("key", name[:-5])] = texts.get(doc.get("key", name[:-5]), "") + str(doc.get("text", ""))
    problems = judgment.row_problems(row, texts)
    if problems:
        return refuse("the gate row", f"{len(problems)} part(s) of your judgment of the stage are missing or break its rules",
                      problems,
                      [f"In {jpath}, fix each line below (criteria.json next to it has every criterion's text):",
                       f"Run `{cmd}` again.",
                       "Send the `writes` array of the writes.json it names with one ArtifactData batch."],
                      "finalize prints the gate id and the path of writes.json, with no Refused line.")
    gate_id = row.pop("gate")
    path = os.path.join(out, "row.json")
    size = write_json(path, row)
    if size > MAX_ROW_BYTES:
        return refuse("the gate row", f"it is {size} bytes, over the {MAX_ROW_BYTES} a row may hold",
                      [], ["Make the longest summaries and points shorter, or set documents you wrote item by item to "
                           "covered, in " + jpath + ".", f"Run `{cmd}` again."], "finalize prints the gate id.")
    writes = [{"op": "set", "collection": "gates", "doc_id": gate_id, "file_path": path}]
    sizes = [size]
    folder = os.path.join(out, "documents")
    rows = []
    for name in os.listdir(folder) if os.path.isdir(folder) else []:
        if name.endswith(".json"):
            rows.append((read_json(os.path.join(folder, name), "a document row"), name))
    for doc, name in sorted(rows, key=lambda x: (x[0].get("n", 0), x[0].get("part", 1))):
        doc_path = os.path.join(folder, name)
        sizes.append(os.path.getsize(doc_path))
        writes.append({"op": "set", "collection": f"gates/{gate_id}/documents", "doc_id": name[:-5], "file_path": doc_path})
    main_path = os.path.join(out, "writes.json")
    write_json(main_path, writes)
    batches = batches_of(writes, sizes)
    paths = [main_path]
    if len(batches) > 1:
        paths = []
        for n, batch in enumerate(batches, 1):
            paths.append(os.path.join(out, f"writes-{n}.json"))
            write_json(paths[-1], batch)
        print(f"approval-gates: {len(writes)} writes do not fit one batch; send {len(paths)} batches, in order "
              f"({', '.join(os.path.basename(p) for p in paths)})", file=sys.stderr)
    store = judgment.store_path(row.get("intent"), row.get("stage"), row.get("unit"))
    try:
        write_json(store, dict(judgment.memory(row, texts), gate=gate_id))
    except OSError as why_not:
        print(f"approval-gates: the next round cannot carry this judgment over ({why_not})", file=sys.stderr)
    e = row["evaluation"]
    print(json.dumps({"id": gate_id, "stage": row.get("stage"), "unit": row.get("unit"), "round": row.get("round"),
                      "verdict": e.get("verdict"), "lookFirst": len(e.get("lookFirst") or []),
                      "items": len(judgment.judged_items((row.get("digest") or {}).get("items"))),
                      "criteria": len(row.get("criteria") or []), "writes": main_path, "batches": paths}, ensure_ascii=False))
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv.pop(0) if argv and argv[0] in ("draft", "finalize") else "draft"
    if command == "finalize":
        ap = argparse.ArgumentParser(prog="gate_bundle.py finalize",
                                     description="Merge the agent's judgment into the gate row and write the batch.")
        ap.add_argument("--out", required=True, help="the folder draft wrote")
        ap.add_argument("--judgment", help="the judgment file (default: <out>/judgment.json)")
        ap.add_argument("--project-dir")
        args = ap.parse_args(argv)
        try:
            return finalize(args)
        except BundleError as why_not:
            print(f"gate_bundle.py: {why_not}", file=sys.stderr)
            return 1
    ap = argparse.ArgumentParser(prog="gate_bundle.py draft", description="Draft the rows for one AI-DLC approval gate.")
    ap.add_argument("--stage", required=True)
    ap.add_argument("--unit")
    ap.add_argument("--why", choices=("first", "revision", "stale"))
    ap.add_argument("--summary-file")
    ap.add_argument("--project-dir")
    ap.add_argument("--no-brief", action="store_true")
    ap.add_argument("--handling", help="JSON {id: coveredBy}: where each traced id the stage leaves uncovered is handled, or why not")
    ap.add_argument("--findings", help="the findings file the guard saved: its open findings become cards on the page")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    try:
        return draft(args)
    except BundleError as why_not:
        print(f"gate_bundle.py: {why_not}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
