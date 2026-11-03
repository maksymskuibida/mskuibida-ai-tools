#!/usr/bin/env python3
"""The registry of the artifact pages and forms published for an AI-DLC project's stages, so the project panel can
show each stage's links where the stage is.

    aidlc_links.py record   --project-dir <dir> --kind <kind> --url <artifact url> --row <row id> --stage <s> ...
                            add one entry (a plugin's hook calls the module's `record`; this is the same by hand)
    aidlc_links.py list     [--project-dir <dir>] [--intent <name>]
                            the registry's entries as JSON
    aidlc_links.py backfill [--project-dir <dir>] [--transcripts <glob> ...] [--artifact <url> ...] [--dry-run]
                            read session transcripts for ArtifactData writes to the known artifacts and record the ones
                            a script can tie to a stage with certainty; the rest are listed, never guessed

One JSON file per checkout and intent, kept outside the project, in
~/.claude/plugins/data/aidlc-artifacts/links/<checkout path, non-word characters as _>/<space>--<intent>.json
($AIDLC_ARTIFACTS_DIR moves the folder). Every plugin's copy of this file reads and writes that one folder; the panel
reads it. The name of the checkout is its path as the session sees it (`os.path.abspath`, no symlinks resolved), spelled
so that the panel, which has no hash, finds the same file.

    {"schema": "aidlc-artifact-links/1", "checkout": "...", "space": "default", "intent": "261027-demo",
     "entries": [{"url": "<artifact url>#<row id>", "artifact": "<artifact url>", "row": "<row id>",
                  "kind": "gate" | "unit-plan" | "unit-end" | "test-plan" | "questions-form" | "findings-form",
                  "intent": "...", "phase": "inception", "stage": "user-stories", "unit": "u3-day-page"?,
                  "rhythm": "per-stage" | "unit-end"?, "round": 2, "revision": 6?, "title": "...",
                  "createdAt": "2026-11-03T10:15:00Z", "session": "<session id>", "judged": {...}?}]}

`round` counts the entries of the same kind, stage and Unit (a gate page's Request Changes round); `revision` is the
version in a page's own id (`-v6-`). A row written again (`update`, a second `set`) replaces its entry's title only: the
entry keeps its place and createdAt. `judged` is set only on an entry a model, not a script, tied to its stage.

This file is shared: the canonical copy is shared/aidlc-links/aidlc_links.py in mskuibida-ai-tools, copied into each
plugin by scripts/sync-shared.py. Edit it there. Standard library only.
"""

import argparse
import contextlib
import datetime
import glob
import json
import os
import re
import sys
import tempfile

try:
    import fcntl
except ImportError:  # not on Windows; a write there is not locked
    fcntl = None

SCHEMA = "aidlc-artifact-links/1"
KINDS = ("gate", "unit-plan", "unit-end", "test-plan", "questions-form", "findings-form")
RHYTHMS = ("per-stage", "unit-end")
UNIT_END_STAGE = "code-generation"
# The kinds a Unit's unit-end gate has: only the Unit's last stage (code-generation) holds them.
UNIT_PAGES = ("unit-plan", "unit-end", "test-plan")
PER_UNIT_STAGES = ("functional-design", "nfr-requirements", "nfr-design", "infrastructure-design", "code-generation")
PHASES = ("initialization", "ideation", "inception", "construction", "operation")
INTENT_PATH = re.compile(r"^(?P<project>.+?)/aidlc/spaces/(?P<space>[^/]+)/intents/(?P<intent>[^/]+)/(?P<rest>.*)$")
BUNDLE_ID = re.compile(r"^(?P<head>[a-z0-9][a-z0-9._-]*)-(?P<page>plan|unit-end)-v(?P<v>\d+)-(?P<stamp>\d{8}[Tt]\d{4})$")
TEST_PLAN_ID = re.compile(r"^(?P<head>[a-z0-9][a-z0-9._-]*)-test-v(?P<v>\d+)-(?P<stamp>\d{8}[Tt]\d{4})$")
GATE_STAMP = re.compile(r"-\d{8}[Tt]\d{4}$")


def data_dir():
    """One folder for every plugin's copy of this file (not $CLAUDE_PLUGIN_DATA, which differs per plugin)."""
    return os.environ.get("AIDLC_ARTIFACTS_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "plugins", "data", "aidlc-artifacts")


def checkout_key(project):
    return re.sub(r"[^A-Za-z0-9._-]", "_", os.path.abspath(project))


def registry_path(project, space, intent):
    name = re.sub(r"[^A-Za-z0-9._-]", "_", f"{space}--{intent}")
    return os.path.join(data_dir(), "links", checkout_key(project), name + ".json")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _blank(project, space, intent):
    return {"schema": SCHEMA, "checkout": os.path.abspath(project), "space": space, "intent": intent, "entries": []}


def load(project, space, intent):
    """The registry's document; a blank one when the file is missing or unreadable."""
    try:
        with open(registry_path(project, space, intent), encoding="utf-8") as f:
            doc = json.load(f)
        if isinstance(doc, dict) and isinstance(doc.get("entries"), list):
            return doc
    except (OSError, ValueError):
        pass
    return _blank(project, space, intent)


def entries(project, space, intent):
    return [e for e in load(project, space, intent)["entries"] if isinstance(e, dict)]


@contextlib.contextmanager
def _locked(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle = open(path + ".lock", "w")
    try:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        handle.close()


def _write(path, doc):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def record(project, space, intent, kind, artifact, row, stage, phase="", unit=None, rhythm=None, revision=None,
           title="", session="", judged=None):
    """Add the entry of one publication (a page or form row written to an artifact). Returns the entry, or None when
    it cannot be one (no artifact url, no row, an unknown kind, no stage). Never raises: a registry that cannot be
    written costs the panel a link, never a hook its call."""
    try:
        artifact = str(artifact or "").strip().split("#", 1)[0].rstrip("/")
        row = str(row or "").strip()
        if kind not in KINDS or not artifact or not row or not stage or not intent or not space:
            return None
        url = f"{artifact}#{row}"
        path = registry_path(project, space, intent)
        with _locked(path):
            doc = load(project, space, intent)
            for known in doc["entries"]:
                if isinstance(known, dict) and known.get("url") == url:
                    if title:
                        known["title"] = title
                    _write(path, doc)
                    return known
            same = [e for e in doc["entries"] if isinstance(e, dict) and e.get("kind") == kind
                    and e.get("stage") == stage and e.get("unit") == unit]
            made = {"url": url, "artifact": artifact, "row": row, "kind": kind, "intent": intent, "space": space,
                    "phase": phase or "", "stage": stage}
            if unit:
                made["unit"] = unit
            if rhythm in RHYTHMS:
                made["rhythm"] = rhythm
            made["round"] = len(same) + 1
            if isinstance(revision, int):
                made["revision"] = revision
            made.update({"title": title or "", "createdAt": now_iso(), "session": session or ""})
            if judged:
                made["judged"] = judged
            doc["entries"].append(made)
            _write(path, doc)
            return made
    except Exception:
        return None


# ---------------------------------------------------------------- what a hook knows how to derive

def locate(path):
    """(project, space, intent, rest) of a path inside an intent's record folder, or None."""
    found = INTENT_PATH.match(os.path.abspath(path).replace(os.sep, "/"))
    return (found["project"], found["space"], found["intent"], found["rest"]) if found else None


def questions_location(path):
    """(project, space, intent, phase, stage, unit) of a questions file's path, or None when it is not under a stage's
    folder: `<intent>/<phase>/<stage>/<file>` or `<intent>/construction/<unit>/<stage>/<file>`."""
    where = locate(path)
    if not where:
        return None
    project, space, intent, rest = where
    parts = rest.split("/")
    if len(parts) == 3 and parts[0] in PHASES:
        return project, space, intent, parts[0], parts[1], None
    if len(parts) == 4 and parts[0] == "construction":
        return project, space, intent, "construction", parts[2], parts[1]
    return None


def state_stages(intent_dir):
    """{stage slug: phase} of the intent's aidlc-state.md: the `### <NAME> PHASE` sections and their `- [m] slug` rows."""
    out = {}
    try:
        with open(os.path.join(intent_dir, "aidlc-state.md"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return out
    phase = ""
    for line in text.splitlines():
        head = re.match(r"^###\s+([A-Z]+)\s+PHASE", line)
        if head:
            phase = head.group(1).lower()
            continue
        row = re.match(r"^\s*-\s*\[[^\]]\]\s+([a-z0-9][a-z0-9-]*)\b", line)
        if row and phase:
            out.setdefault(row.group(1), phase)
    return out


def phase_of(intent_dir, stage):
    """The phase the state file lists the stage under; a per-Unit stage the state does not list is Construction's."""
    known = state_stages(intent_dir).get(stage)
    if known:
        return known
    return "construction" if stage in PER_UNIT_STAGES else ""


def intent_dir_of(project, space, intent):
    return os.path.join(project, "aidlc", "spaces", space, "intents", intent)


def units_of(intent_dir):
    """The Unit names with a folder under construction/."""
    try:
        return sorted(n for n in os.listdir(os.path.join(intent_dir, "construction"))
                      if os.path.isdir(os.path.join(intent_dir, "construction", n)))
    except OSError:
        return []


def bundle_page(doc_id):
    """(kind, revision, head) of a `bundles/<id>` row id, or None."""
    found = BUNDLE_ID.match(doc_id or "")
    if not found:
        return None
    return ("unit-plan" if found["page"] == "plan" else "unit-end"), int(found["v"]), found["head"]


def test_plan_revision(doc_id):
    found = TEST_PLAN_ID.match(doc_id or "")
    return (int(found["v"]), found["head"]) if found else None


def split_gate_id(doc_id, intent, stages, units):
    """(stage, unit) of a per-stage gate row id `<intent>-<stage>[-<unit>]-<stamp>`, or None when no known stage and Unit
    fit it with certainty (the longest stage that leaves a known Unit or nothing wins)."""
    if not doc_id or not intent or not doc_id.startswith(intent + "-") or not GATE_STAMP.search(doc_id):
        return None
    middle = GATE_STAMP.sub("", doc_id)[len(intent) + 1:]
    fits = []
    for stage in stages:
        if middle == stage:
            fits.append((stage, None))
        elif middle.startswith(stage + "-") and middle[len(stage) + 1:] in units:
            fits.append((stage, middle[len(stage) + 1:]))
    fits.sort(key=lambda f: -len(f[0]))
    return fits[0] if fits else None


# ---------------------------------------------------------------- backfill from transcripts

def writes_in(tool_input):
    """[(op, collection, doc_id, data or None)] of an ArtifactData write call."""
    action = (tool_input or {}).get("action")
    if action == "batch":
        items = [w for w in tool_input.get("writes") or [] if isinstance(w, dict)]
        return [(w.get("op"), w.get("collection", ""), w.get("doc_id", ""), w.get("data") if isinstance(w.get("data"), dict) else None)
                for w in items]
    if action in ("set", "update"):
        data = tool_input.get("data")
        return [(action, tool_input.get("collection", ""), tool_input.get("doc_id", ""), data if isinstance(data, dict) else None)]
    return []


def transcript_calls(path):
    """[(session id, timestamp, tool_input)] of the ArtifactData calls in a transcript."""
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                message = entry.get("message") if isinstance(entry, dict) else None
                content = message.get("content") if isinstance(message, dict) else None
                for block in content if isinstance(content, list) else []:
                    if isinstance(block, dict) and block.get("type") == "tool_use" and str(block.get("name", "")).endswith("ArtifactData"):
                        out.append((entry.get("sessionId", ""), entry.get("timestamp", ""), block.get("input") or {}))
    except OSError:
        pass
    return out


def backfill(project, space, intent, transcripts, artifacts=(), dry_run=False):
    """Record what the transcripts' ArtifactData writes say with certainty. Returns (recorded, undecided): the entries
    made (or that would be), and [(row id, why)] for writes a script could not tie to a stage. Nothing is guessed: a
    row id that fits no known stage and Unit is left to the person (or a judge that records `judged`)."""
    intent_dir = intent_dir_of(project, space, intent)
    stages = state_stages(intent_dir)
    units = set(units_of(intent_dir))
    recorded, undecided = [], []
    for path in transcripts:
        for session, stamp, ti in transcript_calls(path):
            url = str(ti.get("url", "")).split("#", 1)[0].rstrip("/")
            if not url or (artifacts and url not in artifacts):
                continue
            for op, collection, doc_id, data in writes_in(ti):
                if op not in ("set", "update") or not doc_id:
                    continue
                made = _backfill_row(collection, doc_id, data, intent, stages, units, project)
                if made is None:
                    continue
                if isinstance(made, str):
                    undecided.append((doc_id, made))
                    continue
                made.update({"project": project, "space": space, "intent": intent, "artifact": url, "row": doc_id, "session": session})
                recorded.append(made)
                if not dry_run:
                    record(project, space, intent, made["kind"], url, doc_id, made["stage"], made.get("phase", ""), made.get("unit"),
                           made.get("rhythm"), made.get("revision"), made.get("title", ""), session)
    return recorded, undecided


def _backfill_row(collection, doc_id, data, intent, stages, units, project):
    title = str((data or {}).get("title") or "")
    if collection == "gates":
        split = split_gate_id(doc_id, intent, stages, units)
        if not split:
            return "no known stage and Unit fit this gate row id"
        stage, unit = split
        return {"kind": "gate", "stage": stage, "unit": unit, "phase": stages.get(stage, ""), "rhythm": "per-stage", "title": title}
    if collection == "bundles":
        found = bundle_page(doc_id)
        if not found:
            return "not a unit plan or unit-end row id"
        kind, revision, head = found
        unit = next((u for u in units if head.endswith("-" + u.lower()) or head == u.lower()), None)
        if not unit:
            return "the row id names no known Unit"
        return {"kind": kind, "stage": UNIT_END_STAGE, "unit": unit, "phase": "construction", "rhythm": "unit-end",
                "revision": revision, "title": title}
    if collection == "plans":
        found = test_plan_revision(doc_id)
        if not found:
            return "not a test plan row id"
        revision, head = found
        unit = (data or {}).get("unit") or next((u for u in units if head.endswith("-" + u.lower())), None)
        if not unit or unit not in units:
            return "the test plan names no known Unit"
        return {"kind": "test-plan", "stage": UNIT_END_STAGE, "unit": unit, "phase": "construction", "rhythm": "unit-end",
                "revision": revision, "title": title}
    if collection == "forms":
        file = (data or {}).get("file")
        where = questions_location(file if os.path.isabs(str(file or "")) else os.path.join(project, str(file or ""))) if file else None
        if not where or where[2] != intent:
            return "the form names no questions file of this intent's stage"
        return {"kind": "questions-form", "stage": where[4], "unit": where[5], "phase": where[3], "title": title}
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(prog="aidlc_links.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record")
    for name in ("project-dir", "space", "intent", "kind", "url", "row", "stage", "phase", "unit", "rhythm", "title", "session"):
        rec.add_argument("--" + name, default="")
    rec.add_argument("--revision", type=int)
    lst = sub.add_parser("list")
    lst.add_argument("--project-dir", default=os.getcwd())
    lst.add_argument("--space", default="")
    lst.add_argument("--intent", default="")
    back = sub.add_parser("backfill")
    back.add_argument("--project-dir", default=os.getcwd())
    back.add_argument("--space", default="")
    back.add_argument("--intent", default="")
    back.add_argument("--transcripts", action="append", default=[])
    back.add_argument("--artifact", action="append", default=[])
    back.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    def where():
        project = os.path.abspath(args.project_dir or os.getcwd())
        space = args.space or _first_line(os.path.join(project, "aidlc", "active-space"))
        intent = args.intent or _first_line(os.path.join(project, "aidlc", "spaces", space, "intents", "active-intent"))
        return project, space, intent

    if args.cmd == "record":
        project, space, intent = where()
        made = record(project, space, intent, args.kind, args.url, args.row, args.stage, args.phase, args.unit or None,
                      args.rhythm or None, args.revision, args.title, args.session)
        print(json.dumps(made, indent=2))
        return 0 if made else 1
    if args.cmd == "list":
        print(json.dumps(entries(*where()), indent=2))
        return 0
    project, space, intent = where()
    patterns = args.transcripts or [os.path.join(os.path.expanduser("~"), ".claude", "projects", re.sub(r"[^A-Za-z0-9]", "-", project) + "*", "*.jsonl")]
    paths = sorted(p for pattern in patterns for p in glob.glob(os.path.expanduser(pattern)))
    recorded, undecided = backfill(project, space, intent, paths, tuple(a.rstrip("/") for a in args.artifact), args.dry_run)
    print(json.dumps({"recorded": [r["row"] for r in recorded], "undecided": [{"row": r, "why": w} for r, w in undecided]}, indent=2))
    return 0


def _first_line(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.readline().strip()
    except OSError:
        return ""


if __name__ == "__main__":
    sys.exit(main())
