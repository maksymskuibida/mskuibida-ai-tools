#!/usr/bin/env python3
"""Builds the rows of the "AI-DLC maps" artifact from an intent's records: the component map, the Unit map, the story
map and the entity map. Standard library only.

    map_bundle.py draft    --kind components|units|stories|entities|all --out <folder> [--project-dir <dir>]
    map_bundle.py finalize --kind ... --out <folder> [--previous <row.json>] [--project-dir <dir>]
    map_bundle.py check    [--kind ...] [--project-dir <dir>]

`draft` reads the records and writes, per kind, into `<out>/<kind>/`:

    records.json    what the records give, deterministic: blocks, edges, waves, points, stories, status
    judgment.json   what they cannot give, for the agent to fill: a one-line plain summary per block and its group
                    (kept from the last finalize of the same kind, so only new blocks are asked about)

and prints `{"kind", "subject", "blocks", "digest", "todo", "warnings", "judgment"}`. A project whose records hold no
components, or no Units, has nothing to map: draft says so (`subject: false`) and the guard does not ask for that map.

`finalize` merges the judgment into the row, marks the revision (the row carries the previous revision's blocks, the page
shows what is new, changed or removed since) and writes `<out>/<kind>/row.json` and `<out>/writes.json`, the `writes`
array for one ArtifactData batch into the "AI-DLC maps" artifact (`maps/<intent>-<kind>`). It refuses, in the house shape
(`Refused: … because …`, numbered steps, `It worked when: …`), until every block has a summary and a group.

Where the records come from (inception/**, the intent's folder):

    Units       unit-of-work.md (a Units table, or a heading `### U1 — u1-core` / `## Unit: u1-core` per Unit with bullets
                Kind / Points / Wave / Needs merged first / Stories), unit-of-work-dependency.md (a fenced yaml `units:`
                list with `depends_on`, or a table `| Unit | Needs | Why |`), unit-of-work-story-map.md (a table
                `| Story | Unit |`, or Unit headings holding story headings), unit-points.csv (`unit,points,source`)
    Status      the `## Unit Progress` table of aidlc-state.md and the UNIT_* receipts of aidlc-state.md and audit/: a
                UNIT_MERGED receipt, or a UNIT_COMPLETED receipt of code-generation, means landed even when the table
                cell is empty; a UNIT_STARTED after it means built again
    Components  components.md (a fenced yaml `components:` list, or `### Name` sections with Responsibility / Dependencies)

The state (the last row of each map, the judgment, the link each map was published under) is kept outside the project in
~/.claude/approval-gates/maps/<intent>-<checkout hash>/ ($APPROVAL_GATES_DIR moves it). The contract of the row is
contract/map.schema.json.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SCHEMA = "aidlc-map/1"
JUDGMENT_SCHEMA = "aidlc-map-judgment/1"
KINDS = ("components", "units", "stories", "entities")
GRAPH = ("components", "units")
TITLES = {"components": "Component map", "units": "Unit map", "stories": "Story map", "entities": "Entity map"}
# The stages whose gate needs a map (the engine's stage slugs): the stage that settles the components, in either of
# its names, and the stage that settles the Units. The Unit map also gates a Unit's last gate (see UNIT_MAP_STAGES).
COMPONENT_STAGES = ("domain-design", "application-design")
UNIT_STAGES = ("units-generation",)
UNIT_LAST_STAGE = "code-generation"
SUMMARY_MAX = 240
LANDED, BUILDING, PLANNED = "landed", "building", "planned"
SLUG = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$|^[a-z][a-z0-9]*[0-9][a-z0-9]*$")
UNIT_ID = re.compile(r"^U\d+$")
STORY_ID = re.compile(r"\b(?:US|S)\d+(?:\.\d+)*\b")
ELLIPSIS = re.compile(r"…|\.\.\.\s*$")


class MapError(Exception):
    pass


# ---------------------------------------------------------------- small readers

def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def read_line(path):
    text = read(path)
    return text.splitlines()[0].strip() if text.strip() else ""


def write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=False)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return len(text.encode("utf-8"))


def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as why:
        raise MapError(f"cannot read {what} {path}: {why}") from None


def one_line(text, limit=0):
    out = re.sub(r"\s+", " ", str(text or "")).strip()
    out = re.sub(r"[*_`]+", "", out)
    return out[: limit - 1].rstrip() + "…" if limit and len(out) > limit else out


def first_sentence(text, limit=200):
    text = one_line(text)
    cut = re.search(r"(?<=[.!?])\s", text)
    text = text[: cut.start()] if cut else text
    return one_line(text, limit)


# ---------------------------------------------------------------- the record folder

def record_root(project):
    """(space, intent, root) of the active intent."""
    space = read_line(os.path.join(project, "aidlc", "active-space"))
    if not space:
        raise MapError(f"no active space: {os.path.join(project, 'aidlc', 'active-space')} is missing or empty")
    intents = os.path.join(project, "aidlc", "spaces", space, "intents")
    intent = read_line(os.path.join(intents, "active-intent"))
    root = os.path.join(intents, intent) if intent else ""
    if not intent or not os.path.isdir(root):
        raise MapError(f"no active intent under {intents}")
    return space, intent, root


def find_files(root, name, under=("inception",)):
    """Paths of every file called `name` under the intent's phase folders, sorted, so the same records give the same map."""
    found = []
    for top in under:
        base = os.path.join(root, top)
        for folder, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in ("reviews", ".aidlc-engine"))
            if name in files:
                found.append(os.path.join(folder, name))
    return sorted(found)


def first_file(root, name):
    found = find_files(root, name)
    return found[0] if found else ""


# ---------------------------------------------------------------- a small YAML reader (the subset the records use)

def _split_flow(text):
    out, depth, quote, cur = [], 0, "", ""
    for ch in text:
        if quote:
            cur += ch
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch in "[{":
            depth += 1
            cur += ch
        elif ch in "]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out


def _scalar(text):
    s = text.strip()
    if not s or s in ("null", "~"):
        return None if s else ""
    if s[0] == "[" and s[-1] == "]":
        return [_scalar(p) for p in _split_flow(s[1:-1])]
    if s[0] == "{" and s[-1] == "}":
        out = {}
        for part in _split_flow(s[1:-1]):
            k, _, v = part.partition(":")
            out[k.strip().strip("\"'")] = _scalar(v)
        return out
    if len(s) > 1 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    if s in ("true", "false"):
        return s == "true"
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    return s


KEY = re.compile(r"^([\w.\-]+|\"[^\"]*\"|'[^']*'):(?:\s+(.*))?$")


def parse_yaml(text):
    """The YAML the records use: nested maps and lists, flow lists, quoted and folded (`>`, `|`) scalars. Anything else
    is read as a plain string. Returns None for an empty text."""
    lines = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append([len(raw) - len(raw.lstrip(" ")), stripped])
    if not lines:
        return None
    value, _ = _block(lines, 0, lines[0][0])
    return value


def _block(lines, i, indent):
    return _list(lines, i, indent) if lines[i][1] == "-" or lines[i][1].startswith("- ") else _map(lines, i, indent)


def _map(lines, i, indent):
    out = {}
    while i < len(lines) and lines[i][0] == indent and not (lines[i][1] == "-" or lines[i][1].startswith("- ")):
        found = KEY.match(lines[i][1])
        if not found:
            i += 1
            continue
        key, rest = found.group(1).strip("\"'"), (found.group(2) or "").strip()
        i += 1
        if rest in (">", "|", ">-", "|-", ">+", "|+"):
            parts = []
            while i < len(lines) and lines[i][0] > indent:
                parts.append(lines[i][1])
                i += 1
            out[key] = (" " if rest[0] == ">" else "\n").join(parts)
        elif rest == "":
            if i < len(lines) and (lines[i][0] > indent or (lines[i][0] == indent and (lines[i][1] == "-" or lines[i][1].startswith("- ")))):
                out[key], i = _block(lines, i, lines[i][0])
            else:
                out[key] = None
        else:
            out[key] = _scalar(rest)
    return out, i


def _list(lines, i, indent):
    out = []
    while i < len(lines) and lines[i][0] == indent and (lines[i][1] == "-" or lines[i][1].startswith("- ")):
        body = lines[i][1][1:]
        rest = body.lstrip()
        if not rest:
            i += 1
            if i < len(lines) and lines[i][0] > indent:
                value, i = _block(lines, i, lines[i][0])
            else:
                value = None
            out.append(value)
        elif KEY.match(rest) and not rest.startswith(("[", "{", "\"", "'")):
            lines[i] = [indent + 1 + (len(body) - len(rest)), rest]
            value, i = _map(lines, i, lines[i][0])
            out.append(value)
        else:
            out.append(_scalar(rest))
            i += 1
    return out, i


def fenced_yaml(text):
    blocks = []
    for found in re.finditer(r"```(?:yaml|yml)[^\n]*\n(.*?)```", text, re.S):
        try:
            value = parse_yaml(found.group(1))
        except (IndexError, ValueError):
            value = None
        if isinstance(value, dict):
            blocks.append(value)
    return blocks


def tables(text):
    """[(header cells, [row cells])] of every Markdown table in the text."""
    out, cur = [], None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cur is None:
                cur = [cells, None, []]
            elif cur[1] is None and all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c):
                cur[1] = cells
            elif cur[1] is not None:
                cur[2].append(cells)
        else:
            if cur and cur[1] is not None:
                out.append((cur[0], cur[2]))
            cur = None
    if cur and cur[1] is not None:
        out.append((cur[0], cur[2]))
    return out


def col(header, *names):
    for i, h in enumerate(header):
        if any(re.search(n, h.lower()) for n in names):
            return i
    return -1


def cell(row, i):
    return row[i].strip() if 0 <= i < len(row) else ""


def clean(text):
    return re.sub(r"[`*]", "", str(text or "")).strip()


# ---------------------------------------------------------------- Units

class Units:
    """The Units of an intent, as the Units Generation documents and the build records give them."""

    def __init__(self, root):
        self.root = root
        self.by_slug = {}
        self.labels = {}  # U-id -> slug
        self.warnings = []
        self.sources = []
        self.waves_doc = {}
        self._load()

    # -- identity
    def unit(self, slug, label=""):
        u = self.by_slug.get(slug)
        if u is None:
            u = {"id": slug, "label": "", "title": "", "kind": "", "points": None, "pointsSource": "", "wave": None,
                 "needs": {}, "stories": [], "hint": "", "status": PLANNED}
            self.by_slug[slug] = u
        if label and UNIT_ID.match(label):
            u["label"] = u["label"] or label
            self.labels[label] = slug
        return u

    def resolve(self, token):
        """The slug a token names: a slug, a U-id, or a cell like `U2 u2-accounts`."""
        for part in re.findall(r"[A-Za-z][\w-]*", clean(token)):
            if part in self.by_slug:
                return part
            if part in self.labels:
                return self.labels[part]
        for part in re.findall(r"U\d+", clean(token)):
            if part in self.labels:
                return self.labels[part]
        return ""

    def refs(self, text):
        out = []
        for part in re.split(r"[,;]| and ", clean(text)):
            slug = self.resolve(part)
            if slug and slug not in out:
                out.append(slug)
        return out

    # -- loading
    def _load(self):
        work = first_file(self.root, "unit-of-work.md")
        if not work:
            return
        self.sources.append(os.path.relpath(work, self.root))
        text = read(work)
        self._from_tables(text)
        self._from_headings(text)
        if not self.by_slug:
            return
        for path in find_files(self.root, "unit-of-work-dependency.md"):
            self.sources.append(os.path.relpath(path, self.root))
            self._dependencies(read(path))
            break
        for path in find_files(self.root, "unit-of-work-story-map.md"):
            self.sources.append(os.path.relpath(path, self.root))
            self._stories(read(path))
            break
        self._points()
        self._waves()
        self._status()

    def _from_tables(self, text):
        for header, rows in tables(text):
            hl = [h.lower() for h in header]
            if not any(re.search(r"unit|name|dir|slug", h) for h in hl):
                continue
            kind_i, pts_i = col(header, r"^kind", r"^type"), col(header, r"point", r"^pts", r"^size")
            wave_i, need_i = col(header, r"^wave"), col(header, r"need", r"depend")
            title_i = col(header, r"^unit$", r"^title", r"^name", r"^what")
            for row in rows:
                slug = next((clean(c) for c in row if SLUG.match(clean(c))), "")
                label = next((clean(c) for c in row if UNIT_ID.match(clean(c))), "")
                if not slug:
                    continue
                u = self.unit(slug, label)
                u["kind"] = u["kind"] or clean(cell(row, kind_i)).lower()
                title = clean(cell(row, title_i))
                if title and not SLUG.match(title) and not UNIT_ID.match(title):
                    u["title"] = u["title"] or title
                    u["hint"] = u["hint"] or first_sentence(title)
                m = re.search(r"\d+", clean(cell(row, pts_i)))
                if m and u["points"] is None:
                    u["points"], u["pointsSource"] = int(m.group(0)), "units table"
                m = re.search(r"\d+", clean(cell(row, wave_i)))
                if m and u["wave"] is None:
                    u["wave"] = int(m.group(0))
                if need_i >= 0:
                    self._pending_needs = getattr(self, "_pending_needs", [])
                    self._pending_needs.append((slug, cell(row, need_i)))
        for slug, needs_text in getattr(self, "_pending_needs", []):
            for dep in self.refs(needs_text):
                if dep != slug:
                    self.by_slug[slug]["needs"].setdefault(dep, "")

    HEADING = re.compile(r"^(#{2,5})\s+(?:Unit(:)?\s+)?(?:(U\d+)\s*[—–:\-]+\s*)?`?([a-z][a-z0-9]*(?:-[a-z0-9]+)*)`?\s*$")

    def _from_headings(self, text):
        lines = text.splitlines()
        starts = []
        for n, line in enumerate(lines):
            m = self.HEADING.match(line.strip())
            if m and (m.group(3) or m.group(2) or m.group(4) in self.by_slug) and "-" in m.group(4) + "-":
                starts.append((n, len(m.group(1)), m.group(3) or "", m.group(4)))
        for k, (n, level, label, slug) in enumerate(starts):
            end = len(lines)
            for m2 in range(n + 1, len(lines)):
                h = re.match(r"^(#{1,5})\s", lines[m2])
                if h and len(h.group(1)) <= level:
                    end = m2
                    break
            u = self.unit(slug, label)
            body = "\n".join(lines[n + 1:end])
            self._body(u, body)

    def _body(self, u, body):
        def field(*names):
            for name in names:
                m = re.search(r"\*\*" + name + r"[^*\n]*?:?\*\*:?\s*([^\n]*)", body, re.I)
                if m:
                    return m.group(1).strip()
            return ""
        flat = body.replace("·", "\n")
        for label, key in (("Kind", "kind"),):
            m = re.search(r"\*\*Kind[^*]*\*\*:?\s*([A-Za-z][\w-]*)", flat)
            if m and not u["kind"]:
                u["kind"] = m.group(1).lower()
        m = re.search(r"\*\*Points?[^*]*\*\*:?\s*(\d+)", flat)
        if m and u["points"] is None:
            u["points"], u["pointsSource"] = int(m.group(1)), "unit-of-work.md"
        m = re.search(r"\*\*Wave[^*]*\*\*:?\s*(\d+)", flat)
        if m and u["wave"] is None:
            u["wave"] = int(m.group(1))
        needs = re.search(r"\*\*(?:Needs[^*]*|Depends[^*]*)\*\*:?\s*([^\n]*)", flat)
        self._heading_needs = getattr(self, "_heading_needs", [])
        if needs:
            self._heading_needs.append((u["id"], needs.group(1)))
        stories = re.search(r"\*\*Stories[^*]*\*\*:?\s*([^\n]*)", flat)
        if stories:
            for sid in STORY_ID.findall(stories.group(1)):
                if sid not in u["stories"]:
                    u["stories"].append(sid)
        hint = field("What it delivers", "Description", "Purpose", "Summary")
        if not hint:
            m = re.search(r"^### Description\s*\n+([^\n]+)", body, re.M)
            hint = m.group(1) if m else ""
        if hint and not u["hint"]:
            u["hint"] = first_sentence(hint)
        for dep_slug, needs_text in self._heading_needs:
            for dep in self.refs(needs_text):
                if dep != dep_slug and dep_slug in self.by_slug:
                    self.by_slug[dep_slug]["needs"].setdefault(dep, "")
        self._heading_needs = []

    def _dependencies(self, text):
        for block in fenced_yaml(text):
            listed = block.get("units")
            if not isinstance(listed, list):
                continue
            for item in listed:
                if not isinstance(item, dict):
                    continue
                slug = self.resolve(str(item.get("name", "")))
                if not slug:
                    self.warnings.append(f"the dependency document names a Unit that unit-of-work.md does not: {item.get('name')}")
                    continue
                u = self.by_slug[slug]
                u["kind"] = u["kind"] or str(item.get("kind") or "").lower()
                deps = item.get("depends_on") or []
                for d in deps if isinstance(deps, list) else [deps]:
                    dep = self.resolve(str(d))
                    if dep and dep != slug:
                        u["needs"].setdefault(dep, "")
                    elif not dep:
                        self.warnings.append(f"{slug} depends on {d}, which is not a Unit of unit-of-work.md")
        for header, rows in tables(text):
            a, b, why = col(header, r"^unit"), col(header, r"need", r"depends"), col(header, r"why|reason")
            if a < 0 or b < 0:
                continue
            for row in rows:
                slug, dep = self.resolve(cell(row, a)), self.resolve(cell(row, b))
                if slug and dep and slug != dep:
                    self.by_slug[slug]["needs"][dep] = one_line(clean(cell(row, why)), 200) or self.by_slug[slug]["needs"].get(dep, "")
                elif slug and cell(row, b) and not dep:
                    self.warnings.append(f"{slug} needs {clean(cell(row, b))}, which is not a Unit of unit-of-work.md")
        for m in re.finditer(r"^#{2,4}\s*Wave\s+(\d+)[^\n]*\n(.*?)(?=^#{1,4}\s|\Z)", text, re.S | re.M):
            for slug in self.refs(re.sub(r"[\n|]", ",", m.group(2))):
                self.waves_doc.setdefault(slug, int(m.group(1)))

    def _stories(self, text):
        for header, rows in tables(text):
            s_i, u_i = col(header, r"story"), col(header, r"unit")
            if s_i < 0 or u_i < 0:
                continue
            for row in rows:
                sids = STORY_ID.findall(clean(cell(row, s_i)))
                for slug in self.refs(cell(row, u_i)):
                    for sid in sids:
                        if sid not in self.by_slug[slug]["stories"]:
                            self.by_slug[slug]["stories"].append(sid)
        cur = ""
        for line in text.splitlines():
            h = self.HEADING.match(line.strip())
            if h and h.group(4) in self.by_slug:
                cur = h.group(4)
                continue
            if cur and re.match(r"^#{3,6}\s", line):
                m = STORY_ID.search(line)
                if m and m.group(0) not in self.by_slug[cur]["stories"]:
                    self.by_slug[cur]["stories"].append(m.group(0))
            elif re.match(r"^#{1,2}\s", line) and not h:
                cur = ""

    def _points(self):
        path = first_file(self.root, "unit-points.csv") or os.path.join(self.root, "unit-points.csv")
        text = read(path)
        if not text:
            return
        self.sources.append(os.path.relpath(path, self.root))
        rows = [r.split(",") for r in text.splitlines() if r.strip()]
        head = [c.strip().lower() for c in rows[0]] if rows else []
        if "unit" not in head or "points" not in head:
            return
        ui, pi, si = head.index("unit"), head.index("points"), head.index("source") if "source" in head else -1
        for r in rows[1:]:  # a later row for a Unit is a newer estimate
            slug = self.resolve(r[ui]) if ui < len(r) else ""
            if slug and pi < len(r) and re.fullmatch(r"\d+", r[pi].strip()):
                u = self.by_slug[slug]
                u["points"], u["pointsSource"] = int(r[pi].strip()), (r[si].strip() if 0 <= si < len(r) else "") or "unit-points.csv"

    def _waves(self):
        for slug, wave in self.waves_doc.items():
            if self.by_slug[slug]["wave"] is None:
                self.by_slug[slug]["wave"] = wave
        depth = {}

        def lay(slug, seen=()):
            if slug in depth:
                return depth[slug]
            if slug in seen:
                self.warnings.append(f"the Units depend on each other in a circle through {slug}; the circle's last edge is ignored when laying out")
                return 1
            ds = [lay(d, seen + (slug,)) for d in self.by_slug[slug]["needs"] if d in self.by_slug]
            depth[slug] = 1 + max(ds, default=0)
            return depth[slug]
        for slug in self.by_slug:
            lay(slug)
        for slug, u in self.by_slug.items():
            if u["wave"] is None:
                u["wave"] = depth[slug]

    # -- status
    def _status(self):
        progress = unit_progress(self.root)
        receipts = unit_receipts(self.root)
        for slug, u in self.by_slug.items():
            row = progress.get(slug)
            land, build = False, False
            if row:
                if row.get("merged") == "x" or row.get("code-generation") == "x":
                    land = True
                if any(v in ("-", "?", "R") for k, v in row.items() if k not in ("unit", "owner")) \
                        or any(v == "x" for k, v in row.items() if k not in ("unit", "owner", "gate", "merged")):
                    build = True
            last = None
            for ev in receipts.get(slug, []):
                if ev["event"] in ("UNIT_MERGED",) or (ev["event"] == "UNIT_COMPLETED" and ev["stage"] == UNIT_LAST_STAGE):
                    last = LANDED
                elif ev["event"] == "UNIT_STARTED":
                    if last == LANDED:
                        last = BUILDING  # built again after it landed: a redo
                    elif last is None:
                        last = BUILDING
            if last == LANDED:
                land = True
            elif last == BUILDING:
                land, build = (row is not None and row.get("merged") == "x"), True
            u["status"] = LANDED if land else (BUILDING if build else PLANNED)


def unit_progress(root):
    """{unit slug: {column: 'x' | ' ' | '-' | '?' | 'R' | 'S'}} of the `## Unit Progress` table of aidlc-state.md."""
    text = read(os.path.join(root, "aidlc-state.md"))
    m = re.search(r"^## Unit Progress[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    out = {}
    if not m:
        return out
    for header, rows in tables(m.group(1)):
        names = [h.strip().lower() for h in header]
        if "unit" not in names:
            continue
        for row in rows:
            d = {}
            for n, name in enumerate(names):
                v = cell(row, n)
                b = re.fullmatch(r"\[(.)\]", v)
                d[name] = (b.group(1) if b else v)
            out[d["unit"]] = d
    return out


def unit_receipts(root):
    """{unit slug: [{event, stage, at}]} in time order, from the UNIT_* receipts of aidlc-state.md and audit/."""
    texts = [read(os.path.join(root, "aidlc-state.md"))]
    audit = os.path.join(root, "audit")
    if os.path.isdir(audit):
        for folder, _dirs, files in sorted(os.walk(audit)):
            texts += [read(os.path.join(folder, f)) for f in sorted(files) if f.endswith(".md")]
    events = []
    for text in texts:
        for block in re.split(r"\n-{3,}\s*\n|\n(?=##\s)", text):
            ev = re.search(r"\*\*Event\*\*:\s*(UNIT_[A-Z]+)", block)
            unit = re.search(r"\*\*Unit\*\*:\s*([\w.-]+)", block)
            if not ev or not unit:
                continue
            stage = re.search(r"\*\*Stage\*\*:\s*([\w-]+)", block)
            at = re.search(r"\*\*Timestamp\*\*:\s*(\S+)", block)
            events.append((at.group(1) if at else "", len(events), {"event": ev.group(1), "stage": stage.group(1) if stage else "", "at": at.group(1) if at else ""}, unit.group(1)))
    out = {}
    for _at, _n, ev, unit in sorted(events, key=lambda e: (e[0], e[1])):
        out.setdefault(unit, []).append(ev)
    return out


# ---------------------------------------------------------------- Components

def load_components(root):
    """(components, warnings, sources): [{id, summary, detail, group, responsibilities, needs:{name: why}, external, entities}]"""
    warnings, sources, comps = [], [], {}
    path = first_file(root, "components.md")
    if not path:
        return [], warnings, sources
    sources.append(os.path.relpath(path, root))
    text = read(path)
    order = []
    for block in fenced_yaml(text):
        listed = block.get("components")
        if not isinstance(listed, list):
            continue
        for item in listed:
            if isinstance(item, dict) and item.get("name"):
                name = str(item["name"]).strip()
                order.append(name)
                c = comps.setdefault(name, new_component(name))
                c["summary"] = one_line(item.get("summary") or "", 400)
                c["detail"] = one_line(item.get("behaviour") or item.get("behavior") or "", 1500)
                c["group"] = str(item.get("group") or item.get("kind") or item.get("type") or "").lower()
                resp = item.get("responsibilities") or []
                c["responsibilities"] = [one_line(r, 220) for r in (resp if isinstance(resp, list) else [resp]) if r][:10]
                for key in ("depends_on", "dependencies"):
                    for d in item.get(key) or []:
                        n, why = (d.get("component"), d.get("interaction")) if isinstance(d, dict) else (d, "")
                        if n:
                            c["needs"].setdefault(str(n).strip(), one_line(why or "", 200))
                for d in item.get("dependents") or []:
                    n, why = (d.get("component"), d.get("interaction")) if isinstance(d, dict) else (d, "")
                    if n:
                        c["used_by"].setdefault(str(n).strip(), one_line(why or "", 200))
                for e in item.get("external_deps") or item.get("external") or []:
                    nm = e.get("name") if isinstance(e, dict) else e
                    if nm:
                        c["external"].append(one_line(nm, 80))
                for e in item.get("entities") or []:
                    nm = e.get("name") if isinstance(e, dict) else e
                    if nm:
                        c["entities"].append(one_line(nm, 80))
    if not comps:  # prose form: `### Name` sections with Responsibility / Dependencies bullets
        for m in re.finditer(r"^#{3,4}\s+`?([A-Za-z][\w .-]*?)`?\s*\n(.*?)(?=^#{1,4}\s|\Z)", text, re.S | re.M):
            name, body = m.group(1).strip(), m.group(2)
            resp = re.search(r"\*\*Responsibilit(?:y|ies)\*\*:?\s*([^\n]+)", body)
            deps = re.search(r"\*\*(?:Dependencies|Depends on)\*\*:?\s*([^\n]+)", body)
            if not (resp or deps):
                continue
            order.append(name)
            c = comps.setdefault(name, new_component(name))
            c["summary"] = first_sentence(resp.group(1)) if resp else ""
            c["responsibilities"] = [one_line(resp.group(1), 220)] if resp else []
            kind = re.search(r"\*\*Type\*\*:?\s*([^\n]+)", body)
            c["group"] = kind.group(1).strip().lower() if kind else ""
            c["_deps_text"] = deps.group(1) if deps else ""
            ent = re.search(r"\*\*Entities\*\*:?\s*([^\n]+)", body)
            if ent:
                c["entities"] = [one_line(e, 80) for e in re.split(r"[,;]", ent.group(1)) if e.strip()]
        for name in order:
            c = comps[name]
            for other in order:
                if other != name and re.search(r"(?<![\w-])" + re.escape(other) + r"(?![\w-])", c.pop("_deps_text", "") or c.get("_x", "")):
                    c["needs"].setdefault(other, "")
            c.pop("_deps_text", None)
    # one edge set: A needs B is also B used by A
    for name in order:
        for n, why in list(comps[name]["used_by"].items()):
            if n in comps:
                comps[n]["needs"].setdefault(name, why)
    out = []
    for name in dict.fromkeys(order):
        c = comps[name]
        for d in list(c["needs"]):
            if d not in comps:
                warnings.append(f"{name} depends on {d}, which components.md does not define")
                del c["needs"][d]
        c.pop("used_by", None)
        out.append(c)
    return out, warnings, sources


def new_component(name):
    return {"id": name, "summary": "", "detail": "", "group": "", "responsibilities": [], "needs": {}, "used_by": {},
            "external": [], "entities": []}


def layers(blocks):
    """layer = 1 + the longest path of Needs below a block; a circle is cut where it is found."""
    by = {b["id"]: b for b in blocks}
    depth, warnings = {}, []

    def lay(i, seen=()):
        if i in depth:
            return depth[i]
        if i in seen:
            warnings.append(f"the components depend on each other in a circle through {i}; the circle's last edge is ignored when laying out")
            return 1
        depth[i] = 1 + max([lay(d, seen + (i,)) for d in by[i]["needs"] if d in by] or [0])
        return depth[i]
    for b in blocks:
        lay(b["id"])
    return depth, warnings


# ---------------------------------------------------------------- the records of each kind

def story_titles(root):
    titles = {}
    for path in find_files(root, "stories.md"):
        for m in re.finditer(r"^#{2,5}\s*(?:Story\s+)?((?:US|S)\d+(?:\.\d+)*)\s*[:—–.\-]*\s*(.*)$", read(path), re.M):
            titles.setdefault(m.group(1), one_line(m.group(2), 160))
    return titles


def records(root, kind):
    """The deterministic part of a map: {kind, blocks, waves?, rows?, cols?, cells?, sources, warnings}. blocks is empty
    when the records hold nothing to map."""
    if kind == "units":
        units = Units(root)
        blocks = []
        for slug in sorted(units.by_slug, key=lambda s: (units.by_slug[s]["wave"] or 0, _num(units.by_slug[s]["label"]), s)):
            u = units.by_slug[slug]
            blocks.append({"id": slug, "label": u["label"] or slug, "title": u["title"] or slug, "kind": u["kind"],
                           "layer": u["wave"] or 1, "points": u["points"], "pointsSource": u["pointsSource"],
                           "status": u["status"], "stories": sorted(u["stories"], key=_story_key),
                           "needs": [{"id": d, "why": w} for d, w in sorted(u["needs"].items())], "hint": u["hint"]})
        waves = []
        for n in sorted({b["layer"] for b in blocks}):
            members = [b for b in blocks if b["layer"] == n]
            waves.append({"n": n, "title": f"Wave {n}", "units": [b["id"] for b in members],
                          "points": sum(b["points"] or 0 for b in members),
                          "landed": sum(1 for b in members if b["status"] == LANDED)})
        return {"kind": kind, "blocks": blocks, "waves": waves, "sources": units.sources, "warnings": units.warnings}
    if kind == "components":
        comps, warnings, sources = load_components(root)
        depth, more = layers(comps)
        blocks = []
        for c in sorted(comps, key=lambda c: (depth[c["id"]], c["id"])):
            blocks.append({"id": c["id"], "label": c["id"], "title": c["id"], "kind": c["group"], "layer": depth[c["id"]],
                           "status": "", "needs": [{"id": d, "why": w} for d, w in sorted(c["needs"].items())],
                           "hint": c["summary"], "detail": c["detail"], "responsibilities": c["responsibilities"],
                           "external": sorted(dict.fromkeys(c["external"])), "entities": sorted(dict.fromkeys(c["entities"]))})
        return {"kind": kind, "blocks": blocks, "waves": [], "sources": sources, "warnings": warnings + more}
    if kind == "stories":
        units = records(root, "units")
        titles = story_titles(root)
        covered = {}
        for b in units["blocks"]:
            for s in b["stories"]:
                covered.setdefault(s, []).append(b["id"])
        rows = [{"id": s, "label": s, "title": titles.get(s, ""), "uncovered": False} for s in sorted(covered, key=_story_key)]
        for s in sorted(set(titles) - set(covered), key=_story_key):
            rows.append({"id": s, "label": s, "title": titles[s], "uncovered": True})
        if not units["blocks"]:
            rows = []
        cols = [{"id": b["id"], "label": b["label"], "title": b["title"], "layer": b["layer"], "status": b["status"]} for b in units["blocks"]]
        return {"kind": kind, "blocks": [], "rows": rows, "cols": cols, "cells": {s: sorted(covered.get(s, [])) for s in (r["id"] for r in rows)},
                "sources": units["sources"], "warnings": units["warnings"]}
    if kind == "entities":
        comps = records(root, "components")
        owners = {}
        for b in comps["blocks"]:
            for e in b["entities"]:
                owners.setdefault(e, []).append(b["id"])
        rows = [{"id": e, "label": e, "title": "", "uncovered": False} for e in sorted(owners)]
        cols = [{"id": b["id"], "label": b["label"], "title": b["title"], "layer": b["layer"], "status": ""} for b in comps["blocks"]
                if any(b["id"] in v for v in owners.values())]
        return {"kind": kind, "blocks": [], "rows": rows, "cols": cols, "cells": {e: sorted(v) for e, v in sorted(owners.items())},
                "sources": comps["sources"], "warnings": comps["warnings"]}
    raise MapError(f"unknown map kind {kind}: use one of {', '.join(KINDS)}")


def _num(label):
    m = re.search(r"\d+", label or "")
    return int(m.group(0)) if m else 10 ** 6


def _story_key(s):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", s) if p]


def has_subject(rec):
    return bool(rec["blocks"] or rec.get("rows"))


def digest_of(rec):
    """A short hash of what the records say (not of the judgment): it changes when a block, an edge, a point count, a
    story or a Unit's status changes."""
    body = {k: rec[k] for k in ("kind", "blocks", "rows", "cols", "cells") if k in rec}
    return hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def subject_digest(root, kind):
    """(digest, number of blocks) of the records now, or (None, 0) when there is nothing to map."""
    rec = records(root, kind)
    return (digest_of(rec), len(rec["blocks"]) or len(rec.get("rows") or [])) if has_subject(rec) else (None, 0)


# ---------------------------------------------------------------- the state outside the project

def state_folder(project, intent):
    base = os.environ.get("APPROVAL_GATES_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "approval-gates")
    return os.path.join(base, "maps", re.sub(r"[^\w.-]", "_", intent) + "-" + hashlib.sha1(os.path.abspath(project).encode("utf-8")).hexdigest()[:8])


def published(project, intent):
    """{kind: {id, url, digest, revision, at}} of the maps written to the artifact for this intent."""
    try:
        with open(os.path.join(state_folder(project, intent), "published.json"), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_published(project, intent, kind, row_id, url, digest, revision, at=None):
    folder = state_folder(project, intent)
    data = published(project, intent)
    data[kind] = {"id": row_id, "url": str(url or "").rstrip("/"), "digest": digest, "revision": revision,
                  "at": at if at is not None else datetime.datetime.now(datetime.timezone.utc).timestamp()}
    write_json(os.path.join(folder, "published.json"), data)
    return data[kind]


def links(project, intent, kinds=None):
    """[{kind, url}] of the published maps, for a gate row's header: `<artifact url>#<row id>`."""
    out = []
    for kind, p in published(project, intent).items():
        if kinds and kind not in kinds:
            continue
        if isinstance(p, dict) and p.get("url") and p.get("id"):
            out.append({"kind": kind, "url": p["url"].split("#")[0] + "#" + p["id"], "title": TITLES.get(kind, kind)})
    return sorted(out, key=lambda x: KINDS.index(x["kind"]) if x["kind"] in KINDS else 9)


def required_kinds(stage, page=None, rhythm=None):
    """The map kinds the gate of this stage needs. `page` is the Unit page of a unit-end rhythm gate (plan | unit-end)."""
    kinds = []
    if stage in COMPONENT_STAGES:
        kinds.append("components")
    if stage in UNIT_STAGES:
        kinds.append("units")
    if page == "unit-end" or (stage == UNIT_LAST_STAGE and page is None):
        kinds.append("units")
    return kinds


def freshness(project, kind):
    """What the guard holds a gate to: {subject, digest, published, fresh, revision, url}. A map is fresh when the row
    published last was built from the records as they are now."""
    _space, intent, root = record_root(project)
    digest, n = subject_digest(root, kind)
    p = published(project, intent).get(kind) or {}
    return {"kind": kind, "subject": digest is not None, "blocks": n, "digest": digest, "published": bool(p),
            "fresh": digest is None or p.get("digest") == digest, "revision": p.get("revision"), "url": (p.get("url") or "") + (("#" + p["id"]) if p.get("id") else "")}


# ---------------------------------------------------------------- judgment

def skeleton(rec, previous):
    """judgment.json for a graph map: a summary and a group per block. What the records hold is filled in as a start
    (`_from` says where it came from); what an earlier finalize of the map settled is kept for the blocks that remain."""
    old = previous or {}
    old_blocks = old.get("blocks") if isinstance(old.get("blocks"), dict) else {}
    groups = {g["key"]: g for g in old.get("groups", []) if isinstance(g, dict) and g.get("key")}
    blocks = {}
    for b in rec["blocks"]:
        kept = old_blocks.get(b["id"]) if isinstance(old_blocks.get(b["id"]), dict) else {}
        key = kept.get("group") or slug_of(b["kind"]) or ""
        entry = {"summary": kept.get("summary") or (b["hint"] if 0 < len(b["hint"]) <= SUMMARY_MAX else ""), "group": key}
        entry["_from"] = "your last judgment" if kept.get("summary") else ("the records" if entry["summary"] else "")
        if not entry["summary"] and b["hint"]:
            entry["_records_say"] = one_line(b["hint"], 400)
        blocks[b["id"]] = entry
        if key and key not in groups:
            groups[key] = {"key": key, "label": key.replace("-", " ").capitalize()}
    return {"schema": JUDGMENT_SCHEMA, "kind": rec["kind"],
            "_how": ("Per block: summary = one plain sentence (at most %d characters, no ellipsis) saying what it is for, in the "
                     "words of someone who has not read the design; group = a key of groups. groups = the lanes the map is "
                     "coloured and filtered by (3 to 7 reads best), each {key, label}. Keys starting with _ are notes; "
                     "finalize drops them." % SUMMARY_MAX),
            "groups": list(groups.values()), "blocks": blocks}


def slug_of(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")


def problems_of(rec, j):
    out = []
    if not isinstance(j, dict) or j.get("schema") != JUDGMENT_SCHEMA:
        return [f"judgment.json is not the file draft wrote (its schema is not {JUDGMENT_SCHEMA}): run draft again"]
    if j.get("kind") != rec["kind"]:
        out.append(f"judgment.json is for the {j.get('kind')} map, not the {rec['kind']} map: run draft again")
    groups = {g.get("key"): g for g in j.get("groups") or [] if isinstance(g, dict)}
    for key, g in groups.items():
        if not key or not str(g.get("label") or "").strip():
            out.append(f"group {key!r} has no label")
    blocks = j.get("blocks") if isinstance(j.get("blocks"), dict) else {}
    for b in rec["blocks"]:
        e = blocks.get(b["id"]) if isinstance(blocks.get(b["id"]), dict) else {}
        s = str(e.get("summary") or "").strip()
        if not s:
            out.append(f"{b['id']}: no summary" + (f" (the records say: {one_line(b['hint'], 120)})" if b["hint"] else ""))
        elif len(s) > SUMMARY_MAX:
            out.append(f"{b['id']}: the summary is {len(s)} characters, over {SUMMARY_MAX}")
        elif ELLIPSIS.search(s):
            out.append(f"{b['id']}: the summary ends in an ellipsis; write the whole sentence")
        g = e.get("group")
        if not g:
            out.append(f"{b['id']}: no group")
        elif g not in groups:
            out.append(f"{b['id']}: group {g!r} is not in groups")
    extra = sorted(set(blocks) - {b["id"] for b in rec["blocks"]})
    if extra:
        out.append("judgment.json holds blocks the records no longer have (" + ", ".join(extra[:6]) + ("…" if len(extra) > 6 else "") + "): delete them, or run draft again")
    return out


# ---------------------------------------------------------------- the row

def snapshot(row):
    """What the next revision is compared with: the visible fields of every block, or the cells of a matrix."""
    if row["view"] == "matrix":
        return {"rows": {r["id"]: {"title": r.get("title", ""), "uncovered": bool(r.get("uncovered"))} for r in row["rows"]},
                "cols": {c["id"]: {"title": c.get("title", ""), "status": c.get("status", "")} for c in row["cols"]},
                "cells": sorted(f"{r}|{c}" for r, cs in row["cells"].items() for c in cs)}
    return {"blocks": {b["id"]: {"label": b["label"], "title": b["title"], "summary": b["summary"], "group": b["group"],
                                 "status": b.get("status", ""), "points": b.get("points"), "layer": b["layer"],
                                 "needs": sorted(n["id"] for n in b["needs"])} for b in row["blocks"]}}


def build_row(project, intent, root, kind, rec, j, previous, ids):
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    digest = digest_of(rec)
    row = {"schema": SCHEMA, "id": f"{intent}-{kind}", "intent": intent, "kind": kind, "title": TITLES[kind],
           "view": "graph" if kind in GRAPH else "matrix", "digest": digest, "sources": rec["sources"],
           "builtAt": now.isoformat().replace("+00:00", "Z")}
    if row["view"] == "graph":
        groups = [{"key": g["key"], "label": g["label"]} for g in j["groups"]]
        used = {j["blocks"][b["id"]]["group"] for b in rec["blocks"]}
        row["groups"] = [g for g in groups if g["key"] in used]
        row["layerName"] = "Wave" if kind == "units" else "Layer"
        row["blocks"] = []
        by_id = {b["id"] for b in rec["blocks"]}
        users = {}
        for b in rec["blocks"]:
            for n in b["needs"]:
                users.setdefault(n["id"], []).append(b["id"])
        for b in rec["blocks"]:
            e = j["blocks"][b["id"]]
            block = {"id": b["id"], "label": b["label"], "title": b["title"], "group": e["group"], "summary": e["summary"].strip(),
                     "layer": b["layer"], "needs": [n for n in b["needs"] if n["id"] in by_id], "usedBy": sorted(users.get(b["id"], []))}
            for k in ("status", "points", "pointsSource", "stories", "detail", "responsibilities", "external", "entities"):
                if b.get(k) not in (None, "", []):
                    block[k] = b[k]
            row["blocks"].append(block)
        row["waves"] = rec.get("waves") or []
    else:
        row["rowsTitle"] = "Story" if kind == "stories" else "Entity"
        row["colsTitle"] = "Unit" if kind == "stories" else "Component"
        row["rows"], row["cols"], row["cells"] = rec["rows"], rec["cols"], rec["cells"]
    snap = snapshot(row)
    prev_row = previous
    if prev_row and isinstance(prev_row.get("revision"), int):
        before = snapshot(prev_row) if prev_row.get("view") == row["view"] and (prev_row.get("blocks") is not None or prev_row.get("rows") is not None) else None
        if before is not None and before == snap:
            row["revision"] = prev_row["revision"]
            if prev_row.get("previous"):
                row["previous"] = prev_row["previous"]
            row["builtAt"] = prev_row.get("builtAt", row["builtAt"]) if prev_row.get("digest") == digest else row["builtAt"]
        else:
            row["revision"] = prev_row["revision"] + 1
            row["previous"] = {"revision": prev_row["revision"], "builtAt": prev_row.get("builtAt", ""), **(before or {})}
    else:
        row["revision"] = 1
    if ids:
        row["ids"] = ids
    return row


def row_text(row):
    parts = []
    for b in row.get("blocks", []):
        parts += [b["label"], b["title"], b["summary"], b.get("detail", "")] + b.get("stories", []) + b.get("responsibilities", [])
        parts += [n.get("why", "") for n in b["needs"]]
    for r in row.get("rows", []):
        parts += [r["label"], r.get("title", "")]
    for c in row.get("cols", []):
        parts += [c["label"], c.get("title", "")]
    return "\n".join(p for p in parts if p)


def id_map(root, text, near):
    try:
        import aidlc_ids
        aidlc_ids.sync(root)
        return aidlc_ids.refs(root, text, near)
    except Exception as why:  # the map still shows its ids; it must not fail over its tooltips
        print(f"approval-gates: the id map could not be built ({why}); the map links only the ids it shows", file=sys.stderr)
        return {}


# ---------------------------------------------------------------- commands

SELF = os.path.abspath(__file__)


def refuse(what, why, problems, steps, check):
    lines = [f"Refused: {what}, because {why}.", "Do this:"]
    for n, step in enumerate(steps, 1):
        lines.append(f"{n}. {step}")
        if n == 1 and problems:
            lines += [f"   - {p}" for p in problems]
    lines.append(f"It worked when: {check}")
    print("\n".join(lines), file=sys.stderr)
    return 1


def project_of(args):
    return os.path.abspath(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def kinds_of(args, root):
    if args.kind in (None, "all"):
        return [k for k in KINDS if has_subject(records(root, k))]
    return [args.kind]


def draft(args):
    project = project_of(args)
    _space, intent, root = record_root(project)
    out = os.path.abspath(args.out)
    report = []
    for kind in kinds_of(args, root):
        rec = records(root, kind)
        folder = os.path.join(out, kind) if args.kind in (None, "all") else out
        subject = has_subject(rec)
        entry = {"kind": kind, "subject": subject, "blocks": len(rec["blocks"]) or len(rec.get("rows") or []),
                 "digest": digest_of(rec) if subject else None, "warnings": rec["warnings"], "sources": rec["sources"]}
        if not subject:
            entry["todo"] = [f"Nothing to map: the records hold no {'components' if kind in ('components', 'entities') else 'Units'}. "
                             "The guard does not ask for this map."]
            report.append(entry)
            continue
        write_json(os.path.join(folder, "records.json"), rec)
        entry["records"] = os.path.join(folder, "records.json")
        if kind in GRAPH:
            memory = os.path.join(state_folder(project, intent), kind + ".judgment.json")
            previous = None
            for candidate in (os.path.join(folder, "judgment.json"), memory):
                if os.path.isfile(candidate):
                    try:
                        previous = read_json(candidate, "the last judgment")
                        break
                    except MapError:
                        previous = None
            j = skeleton(rec, previous)
            write_json(os.path.join(folder, "judgment.json"), j)
            entry["judgment"] = os.path.join(folder, "judgment.json")
            missing = [k for k, e in j["blocks"].items() if not e["summary"] or not e["group"]]
            entry["todo"] = ([f"In judgment.json, give each of these {len(missing)} blocks a one-sentence plain summary and a group: "
                              + ", ".join(missing[:12]) + ("…" if len(missing) > 12 else "")] if missing else [])
            entry["todo"].append("Read the rest of judgment.json once: groups are the lanes the map is coloured and filtered by "
                                 "(3 to 7), and each summary should tell someone who has not read the design what the block is for.")
        else:
            entry["todo"] = ["Nothing to judge: this map is drawn from the records as they are."]
        report.append(entry)
    print(json.dumps(report if args.kind in (None, "all") else report[0], ensure_ascii=False, indent=1))
    return 0


def finalize(args):
    project = project_of(args)
    _space, intent, root = record_root(project)
    out = os.path.abspath(args.out)
    writes, results = [], []
    for kind in kinds_of(args, root):
        rec = records(root, kind)
        folder = os.path.join(out, kind) if args.kind in (None, "all") else out
        if not has_subject(rec):
            results.append({"kind": kind, "subject": False})
            continue
        cmd = f'python3 "{SELF}" finalize --kind {args.kind or "all"} --out {out}'
        j = None
        if kind in GRAPH:
            jpath = os.path.join(folder, "judgment.json")
            if not os.path.isfile(jpath):
                return refuse(f"the {kind} map", "judgment.json is missing",
                              [], [f"Run `python3 \"{SELF}\" draft --kind {kind} --out {out}`.", f"Do its todo list in {jpath}.", f"Run `{cmd}`."],
                              "finalize prints the row's id and the path of writes.json.")
            j = read_json(jpath, "the judgment")
            problems = problems_of(rec, j)
            if problems:
                return refuse(f"the {kind} map", f"{len(problems)} part(s) of the judgment are missing or break its rules", problems,
                              [f"In {jpath}, fix each line below.", f"Run `{cmd}` again.",
                               "Send the `writes` array of the writes.json it names with one ArtifactData batch."],
                              "finalize prints the row's id and the path of writes.json, with no Refused line.")
        previous = None
        prev_path = args.previous or os.path.join(state_folder(project, intent), kind + ".row.json")
        if os.path.isfile(prev_path):
            previous = read_json(prev_path, "the previous row")
            if previous.get("id") != f"{intent}-{kind}":
                previous = None
        near = [os.path.join(root, s) for s in rec["sources"]]
        stub = build_row(project, intent, root, kind, rec, j or {}, previous, None)
        ids = id_map(root, row_text(stub), near)
        row = build_row(project, intent, root, kind, rec, j or {}, previous, ids)
        path = os.path.join(folder, "row.json")
        size = write_json(path, row)
        if size > 900_000:
            return refuse(f"the {kind} map", f"its row is {size} bytes, over the 900000 a row may hold", [],
                          ["Shorten the longest summaries in judgment.json.", f"Run `{cmd}` again."], "finalize prints the row's id.")
        writes.append({"op": "set", "collection": "maps", "doc_id": row["id"], "file_path": path})
        # what the next finalize compares with and starts the judgment from
        write_json(os.path.join(state_folder(project, intent), kind + ".row.json"), row)
        if j is not None:
            write_json(os.path.join(state_folder(project, intent), kind + ".judgment.json"), j)
        results.append({"kind": kind, "id": row["id"], "revision": row["revision"], "blocks": len(row.get("blocks") or row.get("rows") or []),
                        "changed": changes_of(row), "digest": row["digest"]})
    wpath = os.path.join(out, "writes.json")
    write_json(wpath, writes)
    print(json.dumps({"maps": results, "writes": wpath}, ensure_ascii=False, indent=1))
    return 0


def changes_of(row):
    """{new, changed, removed} counts against the previous revision, as the page shows them."""
    prev = row.get("previous")
    if not prev:
        return None
    now = snapshot(row)
    if row["view"] == "graph":
        a, b = prev.get("blocks", {}), now["blocks"]
        return {"new": len(set(b) - set(a)), "removed": len(set(a) - set(b)), "changed": sum(1 for k in set(a) & set(b) if a[k] != b[k])}
    a, b = set(prev.get("cells", [])), set(now["cells"])
    return {"new": len(b - a), "removed": len(a - b), "changed": 0}


def check(args):
    project = project_of(args)
    _space, _intent, root = record_root(project)
    kinds = [args.kind] if args.kind and args.kind != "all" else list(KINDS)
    print(json.dumps([freshness(project, k) for k in kinds], ensure_ascii=False, indent=1))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="map_bundle.py", description="Build the rows of the AI-DLC maps artifact.")
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("draft", "finalize", "check"):
        p = sub.add_parser(name)
        p.add_argument("--kind", choices=KINDS + ("all",))
        p.add_argument("--project-dir")
        if name != "check":
            p.add_argument("--out", required=True)
        if name == "finalize":
            p.add_argument("--previous", help="the row published last, when this machine kept none")
    args = ap.parse_args(argv)
    try:
        return {"draft": draft, "finalize": finalize, "check": check}[args.command](args)
    except MapError as why:
        print(f"map_bundle.py: {why}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
