#!/usr/bin/env python3
"""The digest of a per-stage gate: what the stage's documents say, item by item, for a page read in minutes.

gate_bundle.py calls `build(docs, ids, folder, handling)` and stores the result as the gate row's `digest`:

    digest: {items[], trace[], counts {<kind>: n}, settled: n}
    item:   {key, kind, id, title, body?, format?, doc, settled?, coveredBy?, mentions[]}
    trace:  {from, to, ok}

- **Items** are the things a reviewer checks one by one: requirements (FR, REQ), NFRs, business rules (BR), decisions
  (ADR) and stories (US, with their AC folded into the body). They are read from the entries of a fenced ```yaml block
  (`- id: BR1.1`, the source of truth of rules.md; `format: "yaml"`, the body is the entry as written), a document's id
  tables (first column an id), `- **ID** text` bullets and `### ID Title` headings (the body is the lines under it, as
  written, criteria included). Nothing is clipped: the page shows the item whole when it is opened. Anything else stays
  in the documents as written.
- **Settled** items are ids the project defines in a document outside this stage's folder (from the gate's `ids` map):
  approved in an earlier stage and only quoted here. The page folds them under a count.
- **Trace** is what the stage's traceability.json says covers what. A coverage row that is not OK, and a requirement or
  NFR item of a stage with a traceability.json that no row covers, must say where it is handled or why not
  (scripts/handling.py): from `handling` ({id: {link} | {acceptanceReason}}), the agent's `--handling` file. `build`
  raises ValueError naming every one left, so the gate is never published with something unhandled in silence.

Standard library only.
"""

import json
import re

import handling

KINDS = (("NFR", "nfr"), ("FR", "requirement"), ("REQ", "requirement"), ("BR", "rule"), ("ADR", "decision"), ("US", "story"))
ITEM_ID = re.compile(r"^(?:NFR|FR|REQ|BR|US)\d+(?:\.\d+)*$|^ADR-\d+$")
ID_TOKEN = re.compile(r"(?<![\w.-])((?:NFR|FR|REQ|BR|US|AC)\d+(?:\.\d+)*|ADR-\d+|R-\d+)(?![\w-])")
HEADING = re.compile(r"^#{2,4}\s+((?:NFR|FR|REQ|BR|US)\d+(?:\.\d+)*|ADR-\d+)\b[\s:.—-]*(.*)$")
BULLET = re.compile(r"^\s*[-*]\s+\*\*((?:NFR|FR|REQ|BR|US)\d+(?:\.\d+)*|ADR-\d+)\b[^*]*\*\*:?\s*(.*)$")
CRITERION = re.compile(r"^\s*[-*]\s+(AC\d+(?:\.\d+)*)\s+(.*)$")
TRACE_STAGE_KINDS = ("requirement", "nfr")
YAML_ENTRY = re.compile(r"^(\s*)-\s+id:\s*[\"']?((?:NFR|FR|REQ|BR|US)\d+(?:\.\d+)*|ADR-\d+)[\"']?\s*$")
YAML_TITLE = ("statement", "title", "name", "summary", "description", "decision", "story")


def kind_of(item_id):
    return next((kind for prefix, kind in KINDS if item_id.startswith(prefix)), None)


def plain(text):
    text = re.sub(r"`([^`]*)`", r"\1", str(text or ""))
    text = re.sub(r"\*\*([^*]+)\*\*|__([^_]+)__", lambda m: m.group(1) or m.group(2), text)
    return re.sub(r"\s+", " ", text).strip()


def cells(line):
    body = line.strip().strip("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def from_tables(text):
    """(id, title, body) of every table row whose first cell is an item id; the title is the widest text column."""
    out, head = [], None
    for line in text.splitlines() + [""]:
        if not line.strip().startswith("|"):
            head = None
            continue
        row = cells(line)
        if head is None:
            head = [c.lower() for c in row]
            continue
        if all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) or not c for c in row):
            continue
        rid = plain(row[0]).strip("*")
        if not ITEM_ID.match(rid) or len(row) < 2:
            continue
        rest = list(zip(head[1:], row[1:]))
        pick = next((v for h, v in rest if h in ("requirement", "rule", "decision", "story", "title", "description", "name",
                                                   "summary", "statement")), "")
        facts = "; ".join(f"{h.capitalize()}: {plain(v)}" for h, v in rest if v and v != pick and h)
        out.append((rid, plain(pick), facts))
    return out


def from_yaml(text):
    """(id, title, body) of every `- id: <item id>` entry of a fenced ```yaml block; the body is the entry as written."""
    out, fence, cur, indent = [], None, None, 0
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("```"):
            fence = None if fence else (s[3:].strip().lower() or "text")
            cur = None
            continue
        if fence not in ("yaml", "yml"):
            continue
        head = YAML_ENTRY.match(line)
        if head:
            indent = len(head.group(1))
            cur = [head.group(2), "", [line[indent:]]]
            out.append(cur)
            continue
        if cur is None:
            continue
        lead = len(line) - len(line.lstrip())
        if s and lead <= indent:
            cur = None
            continue
        cur[2].append(line[indent:])
        found = re.match(r"^\s+(\w+):\s*(.+)$", line)
        if found and found.group(1) in YAML_TITLE and not cur[1] and lead == indent + 2:
            cur[1] = found.group(2).strip().strip("\"'>|")
    return [(i, plain(t), "\n".join(b).rstrip()) for i, t, b in out]


def from_lines(text):
    """(id, title, body) of `### ID Title` headings (the lines under one, criteria included, are its body) and of
    `- **ID** text` bullets."""
    out, current, fence = [], None, False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        head = HEADING.match(line)
        if head:
            current = [head.group(1), plain(head.group(2)), []]
            out.append(current)
            continue
        if re.match(r"^#{1,4}\s", line):
            current = None
            continue
        bullet = BULLET.match(line)
        if bullet:
            out.append([bullet.group(1), plain(bullet.group(2)), []])
            current = None
            continue
        if current is not None and line.strip() and not line.strip().startswith(("|", "```")):
            crit = CRITERION.match(line)
            current[2].append(f"- {crit.group(1)}: {crit.group(2).strip()}" if crit else line.rstrip())
    return [(i, t, "\n".join(b).strip()) for i, t, b in out]


def traceability(docs):
    """[{from, to, ok}] from the stage's traceability.json documents (`coverage: [{id, status, target}]`)."""
    out = []
    for d in docs:
        if not d["key"].startswith("traceability"):
            continue
        try:
            data = json.loads(d["text"])
        except ValueError:
            continue
        for row in data.get("coverage") or [] if isinstance(data, dict) else []:
            if isinstance(row, dict) and row.get("id"):
                out.append({"from": str(row["id"]), "to": str(row.get("target") or ""),
                            "ok": str(row.get("status", "")).strip().upper() in ("OK", "COVERED", "MET", "DONE")})
    return out


def settled_ids(ids, stage_folder):
    """Ids the project defines in a document outside this stage's folder (`stage_folder`, relative to the intent's record,
    as the `ids` map's `doc` is): approved earlier, only quoted here."""
    inside = stage_folder.strip("/") + "/"
    return {key for key, entry in (ids or {}).items()
            if str((entry or {}).get("doc") or "") and not str(entry["doc"]).startswith(inside)}


def anchor(text):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(text)).strip("-")


def build(docs, ids, stage_folder, given=None):
    """The `digest` field of a gate row. `docs` are the gate's document rows ({key, title, text}); `given` the agent's
    handling of the trace rows the stage leaves uncovered. Raises ValueError naming every one left unhandled."""
    given = given or {}
    settled = settled_ids(ids, stage_folder)
    items, seen = [], {}
    for d in docs:
        if d.get("kind") == "review" or d["key"].startswith("traceability"):
            continue
        yaml_ids = {i for i, _t, _b in from_yaml(d["text"])}
        for rid, title, body in from_yaml(d["text"]) + from_lines(d["text"]) + from_tables(d["text"]):
            kind = kind_of(rid)
            if not kind:
                continue
            if rid in seen:  # the heading and the table name the same item: keep the fuller one
                item = seen[rid]
                if not item.get("body") and body:
                    item["body"] = body
                if item["title"] == rid and title:
                    item["title"] = plain(title)
                continue
            item = {"key": anchor(rid), "kind": kind, "id": rid, "title": plain(title) or rid, "doc": d["key"]}
            if body:
                item["body"] = body
            if rid in yaml_ids:
                item["format"] = "yaml"
            if rid in settled:
                item["settled"] = True
            mentions = sorted({m for m in ID_TOKEN.findall(title + " " + body) if m != rid and not m.startswith(rid + ".")})
            if mentions:
                item["mentions"] = mentions
            seen[rid] = item
            items.append(item)
    trace = traceability(docs)
    covered = {t["from"]: t for t in trace if t["ok"]}
    keys = {i["id"]: i["key"] for i in items}
    for item in items:
        t = covered.get(item["id"])
        if t:
            target = f"#item-{keys[t['to']]}" if t["to"] in keys else f"path:{t['to']}"
            item["coveredBy"] = {"text": f"covered by {t['to']}", "settled": True,
                                 "link": {"kind": "doc", "target": target, "label": t["to"] or "traceability"}}
    need = [t["from"] for t in trace if not t["ok"]]
    if trace:
        need += [i["id"] for i in items if i["kind"] in TRACE_STAGE_KINDS and not i.get("settled") and i["id"] not in covered
                 and i["id"] not in need]
    problems, by_id = [], {i["id"]: i for i in items}
    for rid in need:
        covered_by = dict(given.get(rid) or {}, text=(given.get(rid) or {}).get("text") or "not covered by this stage")
        covered_by.setdefault("settled", bool(covered_by.get("link")))
        found = handling.problems(rid, covered_by)
        if found:
            problems += found
            continue
        item = by_id.get(rid)
        if item is None:
            item = {"key": anchor(rid), "kind": kind_of(rid) or "requirement", "id": rid, "title": rid, "doc": "traceability"}
            items.append(item)
            by_id[rid] = item
        item["coveredBy"] = covered_by
    if problems:
        raise ValueError("; ".join(problems))
    counts = {}
    for item in items:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    return {"items": items, "trace": trace, "counts": counts, "settled": sum(1 for i in items if i.get("settled"))}
