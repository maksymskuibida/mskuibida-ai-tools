#!/usr/bin/env python3
"""The diagrams of a stage's records: a second view of what the documents already say, derived the same way every time.

gate_bundle.py calls `build(docs, ids)` and stores the result as the gate row's `diagrams`; the page only draws it
(shared/gate-viz). A diagram is offered only when the structure is really there, never to decorate a text.

    diagrams: [{id, doc, kind, title, alt, ...}]       doc is the document's key; id is stable between rounds
    kind "trace"   {cols: [{key, label}], nodes: [{id, col, label, ok?}], edges: [[from, to]], more?}
                   requirement -> rule -> story -> unit -> step -> test, from traceability.json, a table's Source / Implements /
                   Refs / Covers column, a YAML entry's implements / refs, and the ids written next to a numbered step
    kind "layers"  {layers: [{name, items: [{id, label, note?}]}], edges: [[from, to]], map: "components" | "units"}
                   the components of a `components:` YAML block by group, or the Units of a `units:` block by build layer
    kind "sequence" {actors: [..], messages: [{from, to, text}]}   a table with from / to columns, or numbered `A -> B: text` steps
    kind "states"  {states: [..], transitions: [{from, to, text}]}  a from / to table whose columns say state, event or trigger
    kind "steps"   {steps: [{n, text}]}                              a numbered list under a heading about a flow or process
    kind "flow"    {dir, nodes: [{id, label, shape, group?}], edges: [{from, to, text?, style?}]}   a ```mermaid flowchart
    kind "list"    {heading, items: [{text, note?}]}                 a ```mermaid diagram outside what is drawn (shown as a list)
    A mermaid diagram also carries `fence`: its number among the document's ```mermaid blocks, so the page draws it where it stands.

Standard library only."""

import json
import re

import map_bundle

MAX_PER_DOC = 4
MAX_NODES = 60
COLS = (
    ("requirement", "Requirements", re.compile(r"^(?:NFR|FR|REQ)\d+(?:\.\d+)*$")),
    ("rule", "Rules", re.compile(r"^(?:BR|SR|DR|VR|ADR-?)\d+(?:\.\d+)*$|^ADR-\d+$")),
    ("story", "Stories", re.compile(r"^(?:US|AC)\d+(?:\.\d+)*$")),
    ("unit", "Units", re.compile(r"^U\d+$")),
    ("step", "Steps", re.compile(r"^Step \d+$")),
    ("test", "Tests", re.compile(r"^(?:TC|TEST|V)-?\d+(?:\.\d+)*$")),
)
ID_TOKEN = re.compile(r"(?<![\w.-])((?:NFR|FR|REQ|BR|SR|DR|VR|US|AC|TC|TEST|V)-?\d+(?:\.\d+)*|ADR-\d+|U\d+|Step \d+)(?![\w-])")
UP_COLUMN = re.compile(r"^(source|implements?|refs?|references?|covers?|traces?|satisfies|verifies|tests?|story|stories|requirement|requirements|derived from|from requirement|rules?)$", re.I)
FLOW_HEADING = re.compile(r"flow|process|procedure|sequence|lifecycle|journey|steps|workflow|how it works|\bWF\d", re.I)
STATE_HEAD = re.compile(r"state|status|event|trigger|transition", re.I)
FROM_HEAD = re.compile(r"^(from|source state|from state|current state|current|caller|sender|actor|source)$", re.I)
TO_HEAD = re.compile(r"^(to|target state|to state|next state|next|callee|receiver|target)$", re.I)
LABEL_HEAD = re.compile(r"^(event|trigger|action|message|call|transition|when|on|guard|operation|what|step)$", re.I)
ORDER = ("presentation", "ui", "interface", "api", "application", "service", "domain", "data", "infrastructure", "external")


def plain(text, limit=0):
    t = re.sub(r"`([^`]*)`", r"\1", str(text or ""))
    t = re.sub(r"\*\*([^*]+)\*\*|__([^_]+)__", lambda m: m.group(1) or m.group(2), t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t if not limit or len(t) <= limit else t[:limit - 1].rstrip() + "…"


def col_of(ident):
    for key, _label, rx in COLS:
        if rx.match(ident):
            return key
    return None


def label_of(ident, ids):
    d = (ids or {}).get(ident)
    t = plain(d.get("title"), 60) if isinstance(d, dict) else ""
    return t


def doc_texts(docs):
    out = {}
    for d in docs:
        if d.get("kind") == "review" or str(d.get("key", "")).startswith("review-"):
            continue
        out[d["key"]] = out.get(d["key"], "") + ("\n\n" if d["key"] in out else "") + str(d.get("text") or "")
    return out


def js_hash(text):
    """The page's hash(): djb2 over UTF-16 code units, base 36, then "." and the length; a mermaid block is found by it."""
    units = text.encode("utf-16-le")
    h = 5381
    for i in range(0, len(units), 2):
        h = (h * 33 + units[i] + (units[i + 1] << 8)) & 0xFFFFFFFF
    digits, n = "", h
    while n:
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"[n % 36] + digits
        n //= 36
    return (digits or "0") + "." + str(len(units) // 2)


def norm_source(src):
    return re.sub(r"\s+", " ", src).strip()


def heading_before(text, pos):
    found = None
    for m in re.finditer(r"^#{1,4}\s+(.+?)\s*$", text[:pos], re.M):
        found = plain(m.group(1), 80)
    return found or ""


# ------------------------------------------------------------------ trace
def trace_edges(texts):
    """({(from, to): ok}, {doc key: how many edges it gave})"""
    edges, weight = {}, {}

    def add(doc, a, b, ok=True):
        if a == b or not (col_of(a) and col_of(b)) or col_of(a) == col_of(b):
            return
        if (b, a) in edges:
            return
        edges[(a, b)] = edges.get((a, b), True) and ok
        weight[doc] = weight.get(doc, 0) + 1

    for key, text in texts.items():
        if key.startswith("traceability"):
            try:
                data = json.loads(text)
            except ValueError:
                data = None
            for row in (data.get("coverage") or []) if isinstance(data, dict) else []:
                if isinstance(row, dict) and row.get("id"):
                    ok = str(row.get("status", "")).strip().upper() in ("OK", "COVERED", "MET", "DONE")
                    for t in ID_TOKEN.findall(str(row.get("target") or "")):
                        a, b = str(row["id"]).strip(), t
                        # requirement-ish ids come first in the ribbon
                        order = [c[0] for c in COLS]
                        if col_of(a) and col_of(b) and order.index(col_of(a)) > order.index(col_of(b)):
                            a, b = b, a
                        add(key, a, b, ok)
            continue
        for header, rows in map_bundle.tables(text):
            names = [h.strip() for h in header]
            ups = [i for i, h in enumerate(names) if UP_COLUMN.match(re.sub(r"[*`]", "", h))]
            if not ups:
                continue
            for row in rows:
                lead = ID_TOKEN.fullmatch(plain(row[0])) if row else None
                if not lead:
                    continue
                for i in ups:
                    if i < len(row):
                        for ref in ID_TOKEN.findall(row[i]):
                            add(key, ref, lead.group(1))
        for block in map_bundle.fenced_yaml(text):
            for listed in block.values():
                for item in listed if isinstance(listed, list) else []:
                    if not (isinstance(item, dict) and item.get("id")):
                        continue
                    for field in ("implements", "refs", "source", "sources", "covers", "verifies"):
                        v = item.get(field)
                        for ref in ID_TOKEN.findall(" ".join(str(x) for x in (v if isinstance(v, list) else [v])) if v else ""):
                            add(key, ref, str(item["id"]).strip())
        if re.search(r"plan|steps", key, re.I):
            for m in re.finditer(r"^\s*(\d+)[.)]\s+(.*)$", text, re.M):
                refs = ID_TOKEN.findall(m.group(2))
                if refs:
                    for ref in refs:
                        add(key, ref, "Step " + m.group(1))
    return edges, weight


def trace(texts, ids):
    edges, weight = trace_edges(texts)
    if not edges:
        return None
    nodes = {}
    for (a, b), ok in edges.items():
        for n in (a, b):
            nodes.setdefault(n, {"id": n, "col": col_of(n), "label": label_of(n, ids)})
    cols = [c for c in COLS if any(n["col"] == c[0] for n in nodes.values())]
    if len(cols) < 2 or len(nodes) < 3 or len(edges) < 2:
        return None
    keep = sorted(nodes, key=lambda n: (-sum(1 for e in edges if n in e), n))[:MAX_NODES]
    more = len(nodes) - len(keep)
    keepset = set(keep)
    out_nodes = [dict(nodes[n]) for n in sorted(keepset, key=lambda n: ([c[0] for c in COLS].index(nodes[n]["col"]), n))]
    for n in out_nodes:
        if not n["label"]:
            n.pop("label")
        bad = [e for e, ok in edges.items() if not ok and n["id"] in e]
        if bad:
            n["ok"] = False
    out_edges = [[a, b] for (a, b) in edges if a in keepset and b in keepset]
    doc = max(weight, key=lambda k: (k.startswith("traceability"), weight[k]))
    counts = ", ".join(f"{sum(1 for n in out_nodes if n['col'] == c[0])} {c[1].lower()}" for c in cols)
    d = {"id": doc + ":trace", "doc": doc, "kind": "trace", "title": "Trace from " + cols[0][1].lower() + " to " + cols[-1][1].lower(),
         "alt": f"Trace ribbon: {counts}, {len(out_edges)} links, left to right.",
         "cols": [{"key": c[0], "label": c[1]} for c in cols], "nodes": out_nodes, "edges": out_edges}
    if more > 0:
        d["more"] = more
    return d


# ------------------------------------------------------------------ layers
def layers(texts):
    out = []
    for key, text in texts.items():
        for block in map_bundle.fenced_yaml(text):
            if isinstance(block.get("components"), list):
                comps = [c for c in block["components"] if isinstance(c, dict) and c.get("name")]
                names = {str(c["name"]).strip() for c in comps}
                groups = {}
                for c in comps:
                    g = str(c.get("group") or c.get("layer") or c.get("kind") or c.get("type") or "").strip().lower()
                    groups.setdefault(g or "components", []).append(c)
                if len(groups) < 2 or len(comps) < 3 or len(comps) > MAX_NODES:
                    continue
                rank = {name: i for i, name in enumerate(ORDER)}
                names_sorted = sorted(groups, key=lambda g: (rank.get(g, 50), list(groups).index(g)))
                edges = []
                for c in comps:
                    for dep in c.get("depends_on") or c.get("dependencies") or []:
                        to = str(dep.get("component") if isinstance(dep, dict) else dep).strip()
                        if to in names and to != str(c["name"]).strip():
                            edges.append([str(c["name"]).strip(), to])
                out.append({"id": key + ":layers", "doc": key, "kind": "layers", "title": "Components by layer", "map": "components",
                            "alt": f"Layered diagram: {len(comps)} components in {len(groups)} layers ({', '.join(names_sorted)}), {len(edges)} dependencies.",
                            "layers": [{"name": g, "items": [{"id": str(c["name"]).strip(), "label": str(c["name"]).strip(), "note": plain(c.get("summary"), 90)}
                                                              for c in groups[g]]} for g in names_sorted], "edges": edges})
            elif isinstance(block.get("units"), list):
                units = [u for u in block["units"] if isinstance(u, dict) and (u.get("name") or u.get("id"))]
                nm = lambda u: str(u.get("name") or u.get("id")).strip()  # noqa: E731
                by = {nm(u): [str(x.get("component") if isinstance(x, dict) else x).strip() for x in (u.get("depends_on") or [])] for u in units}
                if len(units) < 3 or len(units) > MAX_NODES:
                    continue
                depth = {}

                def lay(n, seen=()):
                    if n in depth:
                        return depth[n]
                    if n in seen:
                        return 0
                    depth[n] = 1 + max([lay(d, seen + (n,)) for d in by.get(n, []) if d in by] or [-1])
                    return depth[n]
                for n in by:
                    lay(n)
                if max(depth.values()) < 1:
                    continue
                ls = [[] for _ in range(max(depth.values()) + 1)]
                for u in units:
                    ls[depth[nm(u)]].append({"id": nm(u), "label": nm(u), "note": plain(u.get("kind") or u.get("summary"), 60)})
                edges = [[n, d] for n, ds in by.items() for d in ds if d in by]
                out.append({"id": key + ":layers", "doc": key, "kind": "layers", "title": "Units by build order", "map": "units",
                            "alt": f"Build order: {len(units)} Units in {len(ls)} layers, {len(edges)} dependencies.",
                            "layers": [{"name": "First, no dependencies" if i == 0 else f"Layer {i + 1}", "items": items} for i, items in enumerate(ls)], "edges": edges})
    return out[:MAX_PER_DOC]


# ------------------------------------------------------------------ sequences, states, steps
def sequences(texts):
    out = []
    for key, text in texts.items():
        n = 0
        for header, rows in map_bundle.tables(text):
            names = [re.sub(r"[*`]", "", h).strip() for h in header]
            fi = next((i for i, h in enumerate(names) if FROM_HEAD.match(h)), None)
            ti = next((i for i, h in enumerate(names) if TO_HEAD.match(h) and i != fi), None)
            if fi is None or ti is None or len(rows) < 2:
                continue
            li = next((i for i, h in enumerate(names) if LABEL_HEAD.match(h) and i not in (fi, ti)), None)
            if li is None:
                li = next((i for i in range(len(names)) if i not in (fi, ti) and not re.match(r"^(#|no\.?|id|n)$", names[i], re.I)), None)
            rowsx = [(plain(r[fi], 50), plain(r[ti], 50), plain(r[li], 70) if li is not None and li < len(r) else "") for r in rows if len(r) > max(fi, ti)]
            rowsx = [r for r in rowsx if r[0] and r[1]]
            if len(rowsx) < 2 or len(rowsx) > 40:
                continue
            states = bool(STATE_HEAD.search(" ".join(names)))
            n += 1
            if states:
                st = list(dict.fromkeys([x for r in rowsx for x in r[:2]]))
                if len(st) < 3 or len(st) > 24:
                    continue
                out.append({"id": f"{key}:states{n}", "doc": key, "kind": "states", "title": "States and transitions",
                            "alt": f"State diagram: {len(st)} states ({', '.join(st[:8])}{'…' if len(st) > 8 else ''}), {len(rowsx)} transitions.",
                            "states": st, "transitions": [{"from": a, "to": b, "text": t} for a, b, t in rowsx]})
            else:
                actors = list(dict.fromkeys([x for r in rowsx for x in r[:2]]))
                if len(actors) < 2 or len(actors) > 10:
                    continue
                out.append({"id": f"{key}:sequence{n}", "doc": key, "kind": "sequence", "title": "Sequence",
                            "alt": f"Sequence diagram: {len(actors)} participants ({', '.join(actors)}), {len(rowsx)} messages in order.",
                            "actors": actors, "messages": [{"from": a, "to": b, "text": t} for a, b, t in rowsx]})
        for m in re.finditer(r"((?:^[ \t]*\d+[.)][ \t]+.*\n?){3,})", text, re.M):
            items = [re.sub(r"^\s*\d+[.)]\s+", "", ln) for ln in m.group(1).splitlines() if ln.strip()]
            head = heading_before(text, m.start())
            arrows = [re.match(r"^(.{1,40}?)\s*(?:->|→|=>|-->)\s*(.{1,40}?)\s*:\s*(.+)$", plain(x)) for x in items]
            n += 1
            if sum(1 for a in arrows if a) >= max(3, int(len(items) * 0.7)):
                msgs = [{"from": a.group(1), "to": a.group(2), "text": plain(a.group(3), 70)} for a in arrows if a]
                actors = list(dict.fromkeys([x for mm in msgs for x in (mm["from"], mm["to"])]))
                if 2 <= len(actors) <= 10:
                    out.append({"id": f"{key}:sequence{n}", "doc": key, "kind": "sequence", "title": head or "Sequence",
                                "alt": f"Sequence diagram: {len(actors)} participants ({', '.join(actors)}), {len(msgs)} messages in order.",
                                "actors": actors, "messages": msgs[:40]})
            elif FLOW_HEADING.search(head) and len(items) >= 4:
                out.append({"id": f"{key}:steps{n}", "doc": key, "kind": "steps", "title": head,
                            "alt": f"Flow of {len(items)} steps, in order: " + "; ".join(plain(x, 40) for x in items[:6]) + ("…" if len(items) > 6 else "") + ".",
                            "steps": [{"n": i + 1, "text": plain(x, 90)} for i, x in enumerate(items[:20])]})
    return out


# ------------------------------------------------------------------ mermaid
NODE = re.compile(r"([A-Za-z_]\w*)(?:\[\[(.*?)\]\]|\[\((.*?)\)\]|\(\((.*?)\)\)|\(\[(.*?)\]\)|\[(.*?)\]|\((.*?)\)|\{(.*?)\})?")
SHAPES = ("sub", "cyl", "circle", "stadium", "box", "round", "diamond")
INLINE_EDGE = re.compile(r"(--|==|-\.)\s+(.+?)\s+(-->|---|==>|===|\.->|\.-)")
PLAIN_EDGE = re.compile(r"(<?)(-{2,}|={2,}|-\.+-?|\.+-)([>xo]?)")


def clean_label(s):
    return plain(re.sub(r"<br\s*/?>", " ", str(s or "").strip().strip('"').strip("'")), 60)


def parse_flow(src):
    lines = [re.sub(r"%%.*$", "", ln).rstrip() for ln in src.splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    head = re.match(r"\s*(?:graph|flowchart)\s*(TD|TB|BT|LR|RL)?\s*;?\s*$", lines[0]) if lines else None
    if not head:
        return None
    nodes, order, edges, group = {}, [], [], ""

    def add(m):
        i = m.group(1)
        n = nodes.setdefault(i, {"id": i, "label": i, "shape": "box"})
        for k, g in enumerate(m.groups()[1:]):
            if g is not None:
                n["label"], n["shape"] = clean_label(g) or i, SHAPES[k]
                break
        if group and "group" not in n:
            n["group"] = group
        if i not in order:
            order.append(i)
        return i

    for ln in lines[1:]:
        s = ln.strip().rstrip(";").strip()
        if re.match(r"(classDef|class|style|linkStyle|click|direction)\b", s):
            continue
        sub = re.match(r"subgraph\s+(?:([\w.-]+)\s*\[(.*?)\]|(.+))$", s)
        if sub:
            group = clean_label(sub.group(2) or sub.group(3) or sub.group(1))
            continue
        if s == "end":
            group = ""
            continue
        pos, prev = 0, None
        while pos < len(s):
            m = NODE.match(s, pos)
            if not m:
                return None
            ids = [add(m)]
            pos = m.end()
            while True:
                am = re.compile(r"\s*&\s*").match(s, pos)
                m2 = NODE.match(s, am.end()) if am else None
                if not m2:
                    break
                ids.append(add(m2))
                pos = m2.end()
            for a in prev[0] if prev else []:
                for b in ids:
                    edges.append(dict(prev[1], **{"from": a, "to": b}))
            while pos < len(s) and s[pos] == " ":
                pos += 1
            if pos >= len(s):
                break
            em = INLINE_EDGE.match(s, pos)
            if em:
                tok, text, pos = em.group(3), em.group(2), em.end()
            else:
                em = PLAIN_EDGE.match(s, pos)
                if not em:
                    return None
                tok, text, pos = em.group(2) + em.group(3), "", em.end()
                tm = re.compile(r"\s*\|(.*?)\|").match(s, pos)
                if tm:
                    text, pos = tm.group(1), tm.end()
            e = {}
            if text.strip():
                e["text"] = clean_label(text)
            if "." in tok:
                e["style"] = "dashed"
            elif "=" in tok:
                e["style"] = "thick"
            prev = (ids, e)
            while pos < len(s) and s[pos] == " ":
                pos += 1
        if prev and not edges:
            return None
    if not nodes:
        return None
    return {"dir": head.group(1) or "TD", "nodes": [nodes[i] for i in order][:MAX_NODES],
            "edges": [e for e in edges if e["from"] in nodes and e["to"] in nodes][:120]}


def parse_mermaid_sequence(src):
    lines = [ln.strip() for ln in src.splitlines()[1:] if ln.strip() and not ln.strip().startswith("%%")]
    actors, msgs = [], []
    for ln in lines:
        p = re.match(r"(?:participant|actor)\s+(\S+)(?:\s+as\s+(.+))?$", ln)
        if p:
            name = clean_label(p.group(2) or p.group(1))
            actors.append((p.group(1), name))
            continue
        m = re.match(r"(\S+?)\s*(?:-->>|->>|-->|->|--x|-x|--\)|-\))\s*[+-]?(\S+?)\s*:\s*(.*)$", ln)
        if m:
            msgs.append((m.group(1), m.group(2), clean_label(m.group(3))))
    names = dict(actors)
    order = list(dict.fromkeys([a for a, _n in actors] + [x for mm in msgs for x in mm[:2]]))
    if len(order) < 2 or not msgs:
        return None
    return {"actors": [names.get(a, a) for a in order][:10], "messages": [{"from": names.get(a, a), "to": names.get(b, b), "text": t} for a, b, t in msgs[:40]]}


def parse_mermaid_state(src):
    trans, states = [], []
    for ln in src.splitlines()[1:]:
        m = re.match(r"\s*(\[\*\]|[\w.-]+)\s*-->\s*(\[\*\]|[\w.-]+)\s*(?::\s*(.*))?$", ln)
        if m:
            a, b = ("start" if x == "[*]" and i == 0 else "end" if x == "[*]" else x for i, x in enumerate(m.groups()[:2]))
            trans.append({"from": a, "to": b, "text": clean_label(m.group(3) or "")})
            states += [a, b]
    states = list(dict.fromkeys(states))
    return {"states": states[:24], "transitions": trans[:60]} if len(states) >= 2 else None


def parse_mermaid_list(src):
    """Anything else, as a structured list: the diagram's kind, then what each line says."""
    lines = [ln.rstrip() for ln in src.splitlines() if ln.strip() and not ln.strip().startswith("%%")]
    kind = (lines[0].split() or ["diagram"])[0] if lines else "diagram"
    names = {"erDiagram": "Entities and relationships", "classDiagram": "Classes", "gantt": "Schedule", "pie": "Shares", "journey": "Journey",
             "mindmap": "Outline", "timeline": "Timeline", "gitGraph": "History", "quadrantChart": "Quadrants", "requirementDiagram": "Requirements"}
    items = []
    for ln in lines[1:]:
        s = ln.strip()
        m = re.match(r"(\S+)\s+([|}o{]+--[|}o{]+)\s+(\S+)\s*:\s*(.*)$", s)
        if m:
            items.append({"text": f"{m.group(1)} relates to {m.group(3)}", "note": clean_label(m.group(4))})
        elif re.match(r"(title|section|dateFormat|axisFormat)\b", s):
            items.append({"text": clean_label(re.sub(r"^(title|section)\s+", "", s))})
        elif s in ("{", "}"):
            continue
        else:
            items.append({"text": clean_label(s)})
    return {"heading": names.get(kind, kind), "items": [i for i in items if i["text"]][:60]}


def mermaid(texts):
    out = []
    for key, text in texts.items():
        for n, m in enumerate(re.finditer(r"```mermaid[^\n]*\n(.*?)```", text, re.S)):
            src = m.group(1)
            head = heading_before(text, m.start())
            first = (src.strip().splitlines() or [""])[0].strip()
            d = {"id": f"{key}:mermaid{n}", "doc": key, "fence": n, "h": js_hash(norm_source(src)), "title": head or "Diagram"}
            flow = parse_flow(src.strip()) if re.match(r"(graph|flowchart)\b", first) else None
            seq = parse_mermaid_sequence(src.strip()) if first.startswith("sequenceDiagram") else None
            st = parse_mermaid_state(src.strip()) if first.startswith("stateDiagram") else None
            if flow:
                d.update(kind="flow", **flow)
                d["alt"] = f"Flow diagram: {len(flow['nodes'])} boxes, {len(flow['edges'])} arrows, {flow['dir']}."
            elif seq:
                d.update(kind="sequence", **seq)
                d["alt"] = f"Sequence diagram: {len(seq['actors'])} participants, {len(seq['messages'])} messages."
            elif st:
                d.update(kind="states", **st)
                d["alt"] = f"State diagram: {len(st['states'])} states, {len(st['transitions'])} transitions."
            else:
                lst = parse_mermaid_list(src.strip())
                d.update(kind="list", **lst)
                d["alt"] = f"{lst['heading']}: {len(lst['items'])} lines, shown as a list."
            out.append(d)
    return out


# ------------------------------------------------------------------ build
def build(docs, ids=None):
    """The gate row's `diagrams`, [] when no record holds a structure worth drawing."""
    texts = doc_texts(docs)
    found = []
    t = trace(texts, ids or {})
    if t:
        found.append(t)
    found += layers(texts) + sequences(texts) + mermaid(texts)
    per, out = {}, []
    for d in found:  # a mermaid block is drawn where it stands, so it is always kept; the derived ones are capped
        if d.get("fence") is None:
            per[d["doc"]] = per.get(d["doc"], 0) + 1
            if per[d["doc"]] > MAX_PER_DOC or sum(1 for x in out if x.get("fence") is None) >= 12:
                continue
        out.append(d)
    return out
