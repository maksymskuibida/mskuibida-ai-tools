#!/usr/bin/env python3
"""The agent's judgment of a per-stage gate: what gate_bundle.py draft asks for, and what finalize refuses without.

`draft` writes `judgment.json` next to the draft row. The agent fills it; `finalize` merges it into the row and refuses
with one line per problem until every part holds. The guard (hooks/gate_guard.py) holds a written `gates/<id>` row to
the same rules, with `row_problems`. The contract is contract/README.md § "Per-stage gate judgment" and
contract/stage-judgment.schema.json.

    judgment.json
      evaluation  {verdict: ready|risks|not-ready, decides,
                   lookFirst[] {text, why, sources[]}, solid[] {text, sources[]}, risks[] {text, severity, sources[]},
                   gaps[] {text, sources[]}, conflicts[] {text, sources[]}}
      criteria    {<criterion key>: {verdict: holds|fails|n/a, note}}        every criterion of criteria.json
      items       {<item id>: {summary, label: critical|high|medium|low, lookFirst, relates[]}}
      documents   {<document key>: covered|shown}

A source is a criterion key (`stage-2`, `review-4`, `rule-7`, `earlier-requirements`), an item id the page lists
(`FR2.1`), `doc:<document key>`, or a review finding id on the page (`R-03`). Keys starting with `_` are notes for the
agent and are dropped by finalize. Standard library only.
"""

import hashlib
import json
import os
import re

SCHEMA = "aidlc-stage-judgment/1"
VERDICTS = ("ready", "risks", "not-ready")
LABELS = ("critical", "high", "medium", "low")
CRITERION_VERDICTS = ("holds", "fails", "n/a")
LISTS = ("lookFirst", "solid", "risks", "gaps", "conflicts")
CITING = ("lookFirst", "risks", "gaps", "conflicts")  # where a failed criterion must be named
SUMMARY_MAX, POINT_MAX, DECIDES_MAX = 300, 600, 900
ELLIPSIS = re.compile(r"…|\.\.\.\s*$")
DOC_KINDS_SHOWN = ("questions", "review")


# ---------------------------------------------------------------- what needs judging

def judged_items(items):
    """The items the agent writes for: everything but what an earlier stage settled and this stage only quotes."""
    return [i for i in items or [] if not (i.get("settled") and not i.get("coveredBy"))]


def item_hash(item):
    return hashlib.sha1((str(item.get("title", "")) + "\n" + str(item.get("body", ""))).encode("utf-8")).hexdigest()[:16]


def suggest_document(doc, text, items):
    """`covered` when the page's items hold most of what the file says, else `shown`."""
    if doc.get("kind") in DOC_KINDS_SHOWN:
        return "shown"
    if doc["key"].startswith("traceability"):
        return "covered"
    mine = [i for i in items if i.get("doc") == doc["key"]]
    if not mine:
        return "shown"
    said = sum(len(i.get("title", "")) + len(i.get("body", "")) for i in mine)
    prose = len(re.sub(r"(?m)^#.*$|^\s*\|?[-:| ]+\|?\s*$", "", text or ""))
    return "covered" if prose and said / prose >= 0.5 else "shown"


def skeleton(gate_id, gate, criteria, docs_text, previous=None):
    """judgment.json as draft writes it: every slot empty, unchanged items carried from the last finalize of the stage."""
    items = (gate.get("digest") or {}).get("items") or []
    before = (previous or {}).get("items") or {}
    out_items = {}
    for it in judged_items(items):
        entry = {"summary": None, "label": None, "lookFirst": False, "relates": list(it.get("mentions") or []),
                 "_kind": it["kind"], "_asWritten": (it["title"] + ("\n" + it["body"] if it.get("body") else ""))}
        old = before.get(it["id"])
        if old and old.get("hash") == item_hash(it) and old.get("summary") and old.get("label"):
            entry.update(summary=old["summary"], label=old["label"], lookFirst=bool(old.get("lookFirst")),
                         relates=list(old.get("relates") or entry["relates"]), unchanged=True)
            entry["_note"] = f"unchanged since round {previous.get('round', '?')}: carried as you wrote it; check it still reads right"
        if it.get("coveredBy"):
            entry["_handled"] = it["coveredBy"].get("text", "")
        out_items[it["id"]] = entry
    return {
        "schema": SCHEMA, "gate": gate_id, "stage": gate.get("stage"), "unit": gate.get("unit"), "round": gate.get("round"),
        "evaluation": {"verdict": None, "decides": "", "lookFirst": [], "solid": [], "risks": [], "gaps": [], "conflicts": []},
        "criteria": {c["key"]: {"verdict": None, "note": "", "_origin": c["origin"], "_title": c["title"]} for c in criteria},
        "items": out_items,
        "documents": {d["key"]: suggest_document(d, docs_text.get(d["key"], ""), items) for d in gate.get("documents") or []},
        "_example": {
            "lookFirst": [{"text": "Slots are fixed at 15 minutes; a bakery that bakes in 30-minute batches cannot use it.",
                           "why": "It decides the whole booking model and is hard to change after code exists.",
                           "sources": ["FR2.1", "review-3"]}],
            "risks": [{"text": "…", "severity": "high", "sources": ["BR1.2"]}],
            "criteria": {"rule-4": {"verdict": "fails", "note": "BR3.1 shows an error text inside the rule; copy belongs in the sheet."}},
            "items": {"FR2.1": {"summary": "A customer books a pickup slot of 15 minutes.", "label": "high", "lookFirst": True,
                                "relates": ["BR1.2"]}}},
    }


def todo(j, gate):
    """What is left to do in judgment.json, one line per kind of work."""
    out = []
    e = j.get("evaluation") or {}
    if e.get("verdict") not in VERDICTS or not str(e.get("decides", "")).strip():
        out.append("evaluation.verdict (ready | risks | not-ready) and evaluation.decides: in two or three plain sentences, "
                   "what approving this stage decides for the developer")
    open_criteria = [k for k, c in (j.get("criteria") or {}).items() if c.get("verdict") not in CRITERION_VERDICTS]
    if open_criteria:
        out.append(f"check the stage against {len(open_criteria)} criteria (criteria.json has each one's full text and source): "
                   "set criteria.<key>.verdict to holds, fails or n/a; a fails needs a note and must be named in "
                   "lookFirst, risks, gaps or conflicts")
    if not e.get("lookFirst") or not e.get("solid"):
        out.append("evaluation.lookFirst (at least one: what the developer should check first and why) and evaluation.solid "
                   "(at least one: what holds and needs no second look); risks, gaps and conflicts (with earlier stages or "
                   "the project's rules) when there are any. Every point is plain words with sources")
    blank = [k for k, i in (j.get("items") or {}).items() if not i.get("summary") or i.get("label") not in LABELS]
    if blank:
        out.append(f"items: write a one-sentence summary (plain words, whole, at most {SUMMARY_MAX} characters, never an "
                   f"ellipsis) and a label (critical | high | medium | low: what it costs if it is wrong) for {len(blank)} "
                   f"item(s) ({', '.join(blank[:12])}{' …' if len(blank) > 12 else ''}); set lookFirst on the critical and "
                   "high ones the developer must check; keep or fix relates")
    carried = [k for k, i in (j.get("items") or {}).items() if i.get("unchanged")]
    if carried:
        out.append(f"{len(carried)} item(s) are unchanged since the last round and carry your earlier summary and label: "
                   "read them once")
    out.append("documents: covered (the items and the evaluation say everything the file says; the page folds it under "
               "As written) or shown (the page shows it in full). The draft guessed; check each")
    return out


# ---------------------------------------------------------------- the rules

def text_problems(where, text, limit):
    text = str(text or "").strip()
    if not text:
        return [f"{where}: write it"]
    out = []
    if ELLIPSIS.search(text):
        out.append(f"{where}: write it whole, with no ellipsis")
    if len(text) > limit:
        out.append(f"{where}: {len(text)} characters; keep it to {limit} (one plain point; the item or file holds the rest)")
    return out


def sources_known(gate):
    known = {c.get("key") for c in gate.get("criteria") or []}
    known |= {i.get("id") for i in (gate.get("digest") or {}).get("items") or []}
    known |= {"doc:" + d.get("key", "") for d in gate.get("documents") or []}
    known |= {f.get("id") for f in (gate.get("findings") or {}).get("items") or []}
    return {k for k in known if k}


def row_problems(gate):
    """Every way a gate row (the merged row finalize writes, or a row on its way to the artifact) breaks the rules."""
    e = gate.get("evaluation")
    if not isinstance(e, dict):
        return ["evaluation: the row has no evaluation of the stage; run gate_bundle.py draft, do its todo list in "
                "judgment.json, then finalize"]
    out = []
    if e.get("verdict") not in VERDICTS:
        out.append(f"evaluation.verdict: one of {', '.join(VERDICTS)}")
    out += text_problems("evaluation.decides", e.get("decides"), DECIDES_MAX)
    known = sources_known(gate)
    cited = set()
    for name in LISTS:
        points = e.get(name) or []
        if not isinstance(points, list):
            out.append(f"evaluation.{name}: a list of points")
            continue
        if name in ("lookFirst", "solid") and not points:
            out.append(f"evaluation.{name}: at least one point" + (" (what the developer should check first, and why)"
                                                                   if name == "lookFirst" else " (what holds and why)"))
        for n, p in enumerate(points):
            where = f"evaluation.{name}[{n}]"
            if not isinstance(p, dict):
                out.append(f"{where}: an object {{text, sources}}")
                continue
            out += text_problems(where + ".text", p.get("text"), POINT_MAX)
            if name == "lookFirst":
                out += text_problems(where + ".why", p.get("why"), POINT_MAX)
            if name == "risks" and p.get("severity") not in LABELS:
                out.append(f"{where}.severity: one of {', '.join(LABELS)}")
            src = p.get("sources") or []
            if not src:
                out.append(f"{where}.sources: name at least one (a criterion key, an item id, doc:<key> or a finding id)")
            for s in src:
                if s not in known:
                    out.append(f"{where}.sources: {s!r} is no criterion, item, document or finding of this gate")
            if name in CITING:
                cited |= set(src)
    for c in gate.get("criteria") or []:
        where = f"criterion {c.get('key')} ({c.get('title', '')})"
        if c.get("verdict") not in CRITERION_VERDICTS:
            out.append(f"{where}: verdict holds, fails or n/a")
        elif c["verdict"] == "fails":
            if not str(c.get("note", "")).strip():
                out.append(f"{where}: a fails says why in its note")
            if c.get("key") not in cited:
                out.append(f"{where}: it fails, so name it in the sources of a lookFirst, risks, gaps or conflicts point")
    for it in judged_items((gate.get("digest") or {}).get("items")):
        where = f"item {it.get('id')}"
        out += text_problems(where + " summary", it.get("summary"), SUMMARY_MAX)
        if it.get("label") not in LABELS:
            out.append(f"{where}: label one of {', '.join(LABELS)} (what it costs if it is wrong)")
        elif it.get("lookFirst") and it["label"] not in ("critical", "high"):
            out.append(f"{where}: lookFirst is for critical and high items; raise the label or drop lookFirst")
    return out


# ---------------------------------------------------------------- finalize

def clean(value):
    """The value with every `_`-key dropped, at any depth."""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def shape_problems(j):
    if not isinstance(j, dict) or j.get("schema") != SCHEMA:
        return [f"judgment.json: not a judgment file of {SCHEMA}; run gate_bundle.py draft again"]
    out = []
    for key in ("evaluation", "criteria", "items", "documents"):
        if not isinstance(j.get(key), dict):
            out.append(f"judgment.json: {key} is an object")
    for key, v in (j.get("documents") or {}).items():
        if v not in ("covered", "shown"):
            out.append(f"documents.{key}: covered or shown")
    return out


def merge(gate, criteria, j):
    """The gate row with the judgment in it: evaluation, criteria with verdicts, each item's summary and label, each
    document's `covered`. Never mutates its inputs."""
    row = json.loads(json.dumps(gate))
    j = clean(j)
    row["evaluation"] = j.get("evaluation") or {}
    verdicts = j.get("criteria") or {}
    row["criteria"] = [dict(c, verdict=(verdicts.get(c["key"]) or {}).get("verdict"),
                            **({"note": verdicts[c["key"]]["note"]} if str((verdicts.get(c["key"]) or {}).get("note", "")).strip() else {}))
                       for c in criteria]
    given = j.get("items") or {}
    for it in (row.get("digest") or {}).get("items") or []:
        mine = given.get(it["id"])
        if not mine:
            continue
        for k in ("summary", "label"):
            if mine.get(k) is not None:
                it[k] = str(mine[k]).strip() if k == "summary" else mine[k]
        if mine.get("lookFirst"):
            it["lookFirst"] = True
        if mine.get("unchanged"):
            it["unchanged"] = True
        rel = [r for r in mine.get("relates") or [] if isinstance(r, str) and r.strip() and r != it["id"]]
        if rel:
            it["relates"] = rel
    docs = j.get("documents") or {}
    for d in row.get("documents") or []:
        d["covered"] = docs.get(d["key"]) == "covered"
    return row


def memory(row):
    """What the next draft of this stage carries over: each judged item's hash, summary and label."""
    return {"gate": row.get("gate"), "round": row.get("round"),
            "items": {i["id"]: {"hash": item_hash(i), "summary": i.get("summary"), "label": i.get("label"),
                                "lookFirst": bool(i.get("lookFirst")), "relates": i.get("relates") or []}
                      for i in judged_items((row.get("digest") or {}).get("items")) if i.get("summary")}}


def store_path(intent, stage, unit):
    base = os.environ.get("APPROVAL_GATES_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "approval-gates")
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", stage + ("--" + unit if unit else ""))
    return os.path.join(base, "stage-judgments", re.sub(r"[^A-Za-z0-9._-]+", "-", intent or "intent"), name + ".json")
