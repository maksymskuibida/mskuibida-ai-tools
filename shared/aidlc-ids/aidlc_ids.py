#!/usr/bin/env python3
"""The ids an AI-DLC project's documents define (US1.1, AC1.1.2, FR1.4, NFR3, BR1.2, Q4, U31, C2, E1, ADR-009, R-01, ...),
for the pages the plugins draw: every id a page shows gets a tooltip with what it is, and a link.

    aidlc_ids.py sync   [--project-dir <dir>] [--intent-dir <dir>] [--force]
                        create or bring up to date the checkout's id map; only the documents changed since the last
                        sync are read again. Run before building any page.
    aidlc_ids.py index  [--project-dir <dir>] [--intent-dir <dir>]
                        the map's definitions, as JSON: {id: [definition, ...]} (syncs first)
    aidlc_ids.py refs   (--text <s> | --text-file <path>) [--near <path> ...] [--project-dir <dir>] [--intent-dir <dir>]
                        the ids the text mentions, one definition each, as JSON: {id: definition}. The page gets this map.

The map is built from the project's own documents and kept outside the project, in
~/.claude/plugins/data/aidlc-ids/maps/<checkout key>/<intent>.json ($AIDLC_IDS_DIR moves the folder): one map per
checkout, as a worktree's branch may hold other documents. Every plugin's copy of this file reads the same folder.

A definition is {"id", "kind", "title", "text", "doc", "line"}: `doc` is the path relative to the intent folder. The
same id may be defined in several documents (every stage has its own Q1 and R-01; Units have their own BR1.1), so
`refs` picks, for each id, the definition nearest the `--near` paths (the documents the page shows): same file, then
same folder, then the closest parent folder, and among equals the strongest form (a heading, then a bold lead, then a
table's first cell). A definition inside another Unit's folder (construction/<unit>/) is never picked.

An id the text mentions that no document defines is left out: the page shows it as a link whose tooltip says it is not
found. This file is shared: the canonical copy is shared/aidlc-ids/aidlc_ids.py in mskuibida-ai-tools, copied into each
plugin by scripts/sync-shared.py. Edit it there. Standard library only.
"""

import argparse
import hashlib
import json
import os
import re
import sys

# An id: an upper-case prefix (ADR, NFR, US, SD, ...), an optional dash, a number, then dotted or dashed parts and a
# letter suffix: US1.1, US1.1a, AC1.1a.2, FR1.4, NFR3, BR1.2, R-01, ADR-009, U31, Q4, SD-3, U3-SD2.
ID = r"(?<![\w-])([A-Z][A-Z]{0,4}-?\d+[a-z]?(?:[.-]\d+[a-z]?)*(?:-[A-Z]{1,4}\d+[a-z]?)?)(?![\w-])"
ID_RE = re.compile(ID)
# Upper-case-and-digit words that are not ids.
NOT_IDS = re.compile(r"^(UTF-?\d+|SHA-?\d+|ISO-?\d+|RFC-?\d+|HTTP-?\d+|TLS-?\d|H[1-6]|V\d+|X\d+|P\d|ES\d+|ID\d*)$")

KINDS = {
    "US": "Story",
    "AC": "Acceptance criterion",
    "FR": "Functional requirement",
    "NFR": "Non-functional requirement",
    "BR": "Business rule",
    "Q": "Question",
    "U": "Unit",
    "C": "Contract",
    "E": "External interface",
    "ADR": "Decision record",
    "R": "Review finding",
    "D": "Decision",
    "DR": "Design rule",
    "S": "Screen",
    "M": "Mockup",
    "T": "Task",
}
STRENGTH = {"heading": 3, "bold": 2, "table": 1}
# Kinds every stage numbers afresh (its own Q1, its own R-01): resolved only inside the page's own stage folder.
STAGE_LOCAL = {"Q", "R"}
# Kinds Inception defines for the whole intent: its definition wins over a Unit document that restates one.
INTENT_WIDE = {"U", "US", "AC", "FR", "NFR", "ADR", "C", "E"}

HEADING = re.compile(r"^(#{1,6})\s+(?:\*\*)?" + ID + r"(?:\*\*)?\s*(?:[:.—–-]\s*)?(.*)$")
BOLD = re.compile(r"^\s*(?:[-*+]|\d+\.)?\s*\*\*" + ID + r"(?:\s+([^*]*?))?:?\*\*\s*:?\s*(.*)$")
ROW = re.compile(r"^\s*\|\s*(?:\*\*)?" + ID + r"(?:\*\*)?\s*\|(.*)$")


def prefix(ident):
    return re.match(r"[A-Z]+", ident).group(0)


def kind_of(ident):
    return KINDS.get(prefix(ident), "")


def plain(text):
    """Markdown down to readable text: no links' targets, no emphasis marks, no code ticks, one line."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"</?(?:br|span|div|p|a|b|i|em|strong|sup|sub|code|small|details|summary)\b[^>]*>", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" |-—:")


def clip(text, limit=320):
    text = plain(text)
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def definitions(path, rel):
    """[definition] of the ids the Markdown file at `path` defines."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    out = []
    for i, line in enumerate(lines):
        found = None
        heading = HEADING.match(line)
        if heading:
            ident, title = heading.group(2), heading.group(3)
            body = []
            for nxt in lines[i + 1:]:
                if re.match(r"^#{1,6}\s", nxt):
                    break
                if nxt.strip():
                    body.append(nxt)
                if len(" ".join(body)) > 400:
                    break
            found = (ident, title, " ".join(body), "heading")
        else:
            bold = BOLD.match(line)
            if bold:
                ident, title, rest = bold.group(1), bold.group(2) or "", bold.group(3) or ""
                found = (ident, title or rest, rest if title else "", "bold")
            else:
                row = ROW.match(line)
                if row:
                    cells = [plain(c) for c in row.group(2).split("|")]
                    cells = [c for c in cells if c]
                    # The first cell that says something, not a tag such as "Major" or "Accepted".
                    words = [c for c in cells[:4] if len(c) > 12 and not re.search(r"\w/\w.*\.md\b", c)]
                    title = words[0] if words else (cells[0] if cells else "")
                    found = (row.group(1), title, " · ".join(c for c in cells[:4] if c != title), "table")
        if not found:
            continue
        ident, title, text, form = found
        if NOT_IDS.match(ident):
            continue
        kind = kind_of(ident)
        if prefix(ident) == "R" and re.search(r"raid|risk", rel, re.I):
            kind = "Risk"
        out.append({"id": ident, "kind": kind, "title": clip(title, 160), "text": clip(text),
                    "doc": rel, "line": i + 1, "form": form})
    return out


# ---------------------------------------------------------------- the intent

def first_line(path):
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    return line.strip()
    except OSError:
        pass
    return ""


def main_checkout(folder):
    """The main checkout of a linked git worktree, else `folder` (a worktree lacks the gitignored cursors)."""
    line = first_line(os.path.join(folder, ".git"))
    if not line.startswith("gitdir:"):
        return folder
    gitdir = os.path.join(folder, line[len("gitdir:"):].strip())
    common = first_line(os.path.join(gitdir, "commondir"))
    common = os.path.normpath(os.path.join(gitdir, common)) if common else ""
    return os.path.dirname(common) if os.path.basename(common) == ".git" else folder


def project_dir(given=None):
    if given:
        return os.path.abspath(given)
    folder = os.path.abspath(os.getcwd())
    while True:
        if os.path.isdir(os.path.join(folder, "aidlc", "spaces")):
            return folder
        parent = os.path.dirname(folder)
        if parent == folder:
            return os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
        folder = parent


def intent_dir(project):
    def cursor(*parts):
        for place in (project, main_checkout(project)):
            found = first_line(os.path.join(place, "aidlc", *parts))
            if found:
                return found
        return ""
    space = cursor("active-space") or "default"
    intent = cursor("spaces", space, "intents", "active-intent")
    return os.path.join(project, "aidlc", "spaces", space, "intents", intent) if intent else ""


MAP_VERSION = 1


def data_dir():
    """One folder for every plugin's copy of this file (not $CLAUDE_PLUGIN_DATA, which differs per plugin)."""
    return os.environ.get("AIDLC_IDS_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "plugins", "data", "aidlc-ids")


def map_path(folder):
    """Where the map of the intent folder <checkout>/aidlc/spaces/<space>/intents/<intent> is kept."""
    intents = os.path.dirname(os.path.realpath(folder))
    space_dir = os.path.dirname(intents)
    checkout = os.path.dirname(os.path.dirname(os.path.dirname(space_dir)))
    key = hashlib.sha256(checkout.encode("utf-8")).hexdigest()[:12]
    name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(space_dir) + "--" + os.path.basename(folder.rstrip(os.sep)))
    return os.path.join(data_dir(), "maps", key, name + ".json")


def documents(folder):
    """{relative path: mtime} of the intent's Markdown documents."""
    out = {}
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if name.endswith(".md"):
                path = os.path.join(root, name)
                out[os.path.relpath(path, folder)] = os.path.getmtime(path)
    return out


def load_map(folder):
    try:
        with open(map_path(folder), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) and data.get("version") == MAP_VERSION else None
    except (OSError, ValueError):
        return None


def sync(folder, force=False):
    """Bring the intent's id map up to date. Returns (map, {"read": n, "kept": n, "dropped": n, "written": bool})."""
    old = None if force else load_map(folder)
    docs = documents(folder)
    seen = (old or {}).get("documents", {})
    by_doc = {}
    for d in [d for defs in (old or {}).get("ids", {}).values() for d in defs]:
        by_doc.setdefault(d["doc"], []).append(d)
    read = kept = 0
    for rel, mtime in docs.items():
        if rel in seen and seen[rel] == mtime:
            kept += 1
            continue
        by_doc[rel] = definitions(os.path.join(folder, rel), rel)
        read += 1
    dropped = [rel for rel in by_doc if rel not in docs]
    for rel in dropped:
        by_doc.pop(rel)
    ids = {}
    for rel in sorted(by_doc):
        for d in by_doc[rel]:
            ids.setdefault(d["id"], []).append(d)
    data = {"version": MAP_VERSION, "intent": os.path.realpath(folder), "documents": docs, "ids": ids}
    changed = old is None or read or dropped
    if changed:
        path = map_path(folder)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    return data, {"read": read, "kept": kept, "dropped": len(dropped), "written": bool(changed), "ids": len(ids)}


def index(folder):
    """{id: [definition, ...]} of the intent's documents, from its id map (brought up to date first)."""
    return sync(folder)[0]["ids"]


def mentioned(text):
    """The ids a text mentions, in order of first mention."""
    seen = []
    for m in ID_RE.finditer(text or ""):
        ident = m.group(1)
        if not NOT_IDS.match(ident) and ident not in seen:
            seen.append(ident)
    return seen


def nearness(doc, near):
    """How close `doc` is to the nearest of the `near` paths: the number of path parts they share, a whole file more."""
    best = 0
    parts = doc.split(os.sep)
    for n in near:
        other = os.path.normpath(n).split(os.sep)
        if os.path.normpath(n) == doc:
            return 10_000
        shared = 0
        for a, b in zip(parts[:-1], other[:-1] if n.endswith(".md") else other):
            if a != b:
                break
            shared += 1
        best = max(best, shared)
    return best


def unit_of(doc):
    """The Unit folder a document sits in (construction/<unit>/...), or None for a document of the whole intent."""
    parts = doc.split(os.sep)
    return parts[1] if len(parts) > 2 and parts[0] == "construction" and parts[1] not in KIND_FOLDERS else None


def stage_of(path):
    """The stage folder of a path: its folder (the path itself when it names no .md file), less a trailing reviews/."""
    folder = os.path.dirname(path) if path.endswith(".md") else os.path.normpath(path)
    return os.path.dirname(folder) if os.path.basename(folder) == "reviews" else folder


# Folders under construction/ that hold a stage for every Unit at once, not one Unit.
KIND_FOLDERS = {"functional-design", "nfr-requirements", "nfr-design", "infrastructure-design", "code-generation",
                "build-and-test", "reviews"}


def pick(candidates, near):
    """The definition the page means: one of its own Unit's when it has one, else one of the whole intent. Another
    Unit's definition never: every Unit has its own BR1.1 and every stage its own Q1."""
    units = {unit_of(n) for n in near} - {None}
    stages = {stage_of(n) for n in near}
    usable = [d for d in candidates if not near or (
        (unit_of(d["doc"]) is None or unit_of(d["doc"]) in units)
        and (prefix(d["id"]) not in STAGE_LOCAL or stage_of(d["doc"]) in stages))]
    if not usable:
        return None
    # The page's own file first; then a real definition (a heading) over a mention in a table; then the nearest.
    return max(usable, key=lambda d: (nearness(d["doc"], near) == 10_000,
                                      prefix(d["id"]) in INTENT_WIDE and d["doc"].startswith("inception" + os.sep),
                                      STRENGTH[d["form"]], nearness(d["doc"], near), -len(d["doc"])))


def refs(folder, text, near=()):
    """{id: definition} of the ids `text` mentions that the intent defines, the nearest definition each."""
    near = [os.path.relpath(os.path.abspath(n), folder) if os.path.isabs(n) else n for n in near]
    every = index(folder)
    out = {}
    for ident in mentioned(text):
        chosen = pick(every.get(ident, []), near)
        if chosen:
            d = dict(chosen)
            d.pop("form", None)
            out[ident] = d
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="aidlc_ids.py", description="The ids an AI-DLC intent's documents define.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("sync", "index", "refs"):
        p = sub.add_parser(name)
        p.add_argument("--project-dir")
        p.add_argument("--intent-dir")
        if name == "sync":
            p.add_argument("--force", action="store_true")
        if name == "refs":
            src = p.add_mutually_exclusive_group(required=True)
            src.add_argument("--text")
            src.add_argument("--text-file")
            p.add_argument("--near", action="append", default=[])
    args = ap.parse_args(argv)
    folder = os.path.abspath(args.intent_dir) if args.intent_dir else intent_dir(project_dir(args.project_dir))
    if not folder or not os.path.isdir(folder):
        print("aidlc_ids.py: no active intent folder found; pass --intent-dir", file=sys.stderr)
        return 1
    if args.cmd == "sync":
        _data, done = sync(folder, args.force)
        state = "written" if done["written"] else "up to date"
        print(f"{os.path.basename(folder.rstrip(os.sep))}: id map {state} ({map_path(folder)}); {done['ids']} ids; {done['read']} documents read, "
              f"{done['kept']} unchanged, {done['dropped']} gone")
        return 0
    if args.cmd == "index":
        print(json.dumps(index(folder), indent=1, ensure_ascii=False))
        return 0
    if args.text_file:
        with open(args.text_file, encoding="utf-8") as f:
            text = f.read()
    else:
        text = args.text
    print(json.dumps(refs(folder, text, args.near), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
