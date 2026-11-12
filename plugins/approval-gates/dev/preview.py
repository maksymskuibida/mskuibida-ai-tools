#!/usr/bin/env python3
"""Look at the approval-gates pages without an account: one self-contained HTML file per page and scenario, all synthetic.

    python3 plugins/approval-gates/dev/preview.py [--out DIR] [--only WORDS] [--stage-graph FILE]

Writes into DIR (default ./approval-gates-preview) one file per scenario and an index.html that links them all with a line on
what to look at. Open DIR/index.html in a browser (file:// is enough; add ?theme=dark to any page for the dark theme).
Each file is the real template, unchanged, with a small stand-in for `window.claude` in front of it: `claude.use("db")` and
`claude.use("user")` answer from the rows embedded in the file, a write stays in memory (a reload forgets it), and a snapshot
listener fires once. Nothing is sent anywhere; the pages' fonts and Markdown libraries load from their CDNs when online.

The rows are built with the plugin's own scripts from a made-up bakery project (scripts/gate_bundle.py draft and finalize for
the per-stage gates, scripts/map_bundle.py for the maps), so a page shows what a real gate would, only longer and fuller:

  per-stage gates   every stage of every phase of the engine's stage list (dev/stage-graph.json, or --stage-graph), each in round 1
                    and in round 3 with changes, additions and removals; Build and Test with 48 targets over four Units and a
                    target two files disagree on; a gate with findings to sort, one with unhandled items, one with nothing pending
  Unit pages        the plan page and the unit-end page in round 1 and in a later round; the unit-end page after a test plan
  test plan, maps   the test-plan page; the maps page with components, 50 Units (some landed, new, changed) and each matrix
  list views        each artifact's list (no hash)

Standard library only; the template files are read from skills/approval-gates/ next to this folder."""

import argparse
import contextlib
import copy
import datetime
import io
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
SKILL = os.path.join(PLUGIN, "skills", "approval-gates")
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
sys.path.insert(0, HERE)
import gate_bundle  # noqa: E402
import map_bundle  # noqa: E402
import unit_bundle  # noqa: E402
import validate_bundle  # noqa: E402
import preview_content as pc  # noqa: E402
import preview_units  # noqa: E402

INTENT = "260101-bakery-preorder"
UNIT = "u1-core"
TEMPLATES = {"gate": "approval-gate.html", "unit": "unit-gate.html", "plan": "test-plan.html", "maps": "maps.html"}

STUB = r"""<script>
/* preview stub: the artifact's db and user capabilities, answered from the rows below */
(function () {
  var rows = %ROWS%;
  var store = new Map(Object.keys(rows).map(function (k) { return [k, rows[k]]; }));
  var copy = function (v) { return v === undefined ? undefined : JSON.parse(JSON.stringify(v)); };
  var snapDoc = function (path) { var d = store.get(path); return { id: path.split("/").pop(), exists: d !== undefined, data: function () { return copy(d); } }; };
  function children(coll) {
    var pre = coll + "/", out = [];
    store.forEach(function (v, k) { if (k.indexOf(pre) === 0 && k.slice(pre.length).indexOf("/") < 0) out.push(k); });
    return out;
  }
  function query(coll, f) {
    f = f || { where: [], order: null, max: 0 };
    function result() {
      var ds = children(coll).filter(function (p) { return f.where.every(function (w) { return store.get(p)[w[0]] === w[1]; }); });
      if (f.order) ds.sort(function (a, b) { var x = store.get(a)[f.order[0]], y = store.get(b)[f.order[0]]; return (x > y ? 1 : x < y ? -1 : 0) * (f.order[1] === "desc" ? -1 : 1); });
      if (f.max) ds = ds.slice(0, f.max);
      var docs = ds.map(snapDoc);
      return { empty: !docs.length, size: docs.length, docs: docs, forEach: function (cb) { docs.forEach(cb); } };
    }
    var q = {
      where: function (k, op, v) { return query(coll, { where: f.where.concat([[k, v]]), order: f.order, max: f.max }); },
      orderBy: function (k, dir) { return query(coll, { where: f.where, order: [k, dir || "asc"], max: f.max }); },
      limit: function (n) { return query(coll, { where: f.where, order: f.order, max: n }); },
      get: function () { return Promise.resolve(result()); },
      onSnapshot: function (cb) { setTimeout(function () { cb(result()); }, 0); return function () {}; },
      doc: function (id) { return docRef(coll + "/" + id); }
    };
    return q;
  }
  function docRef(path) {
    return {
      get: function () { return Promise.resolve(snapDoc(path)); },
      set: function (v) { store.set(path, copy(v)); return Promise.resolve(); },
      update: function (v) { var cur = copy(store.get(path)) || {}; Object.keys(v).forEach(function (k) { cur[k] = copy(v[k]); }); store.set(path, cur); return Promise.resolve(); },
      onSnapshot: function (cb) { setTimeout(function () { cb(snapDoc(path)); }, 0); return function () {}; },
      collection: function (sub) { return query(path + "/" + sub); }
    };
  }
  var db = { collection: function (name) { return query(name); }, doc: docRef };
  window.claude = { use: function (what) { return Promise.resolve(what === "db" ? db : what === "user" ? { id: function () { return Promise.resolve("preview-viewer"); } } : null); } };
  window.__PREVIEW__ = %META%;
  var m = /[?&]theme=(dark|light)/.exec(location.search); if (m) document.documentElement.setAttribute("data-theme", m[1]);
  %HASH%
})();
</script>
"""


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def quiet(fn, *args):
    """fn(*args) with its output captured: (return value, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = fn(*args)
    return code, out.getvalue(), err.getvalue()


def page(kind, rows, hash_id, meta):
    """The template with the stub in front: a whole HTML document."""
    stub = (STUB.replace("%ROWS%", json.dumps(rows).replace("</", "<\\/")).replace("%META%", json.dumps(meta).replace("</", "<\\/"))
            .replace("%HASH%", f'if (!location.hash) location.hash = "{hash_id}";' if hash_id else ""))
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n' + stub +
            read(os.path.join(SKILL, TEMPLATES[kind])) + "\n</html>\n")


class Scenario:
    def __init__(self, name, group, desc, kind, rows, hash_id=""):
        self.name, self.group, self.desc, self.kind, self.rows, self.hash_id = name, group, desc, kind, rows, hash_id

    @property
    def file(self):
        return self.name + ".html"

    def html(self):
        return page(self.kind, self.rows, self.hash_id, {"name": self.name, "desc": self.desc})


# ---------------------------------------------------------------- the per-stage gates

class Bakery:
    """A made-up project on disk, and the real scripts run on it."""

    def __init__(self, tmp, graph):
        self.tmp = tmp
        self.project = os.path.join(tmp, "project")
        self.root = os.path.join(self.project, "aidlc", "spaces", "default", "intents", INTENT)
        self.state = os.path.join(tmp, "state")
        self.ids = os.path.join(tmp, "ids")
        write(os.path.join(self.project, "aidlc", "active-space"), "default\n")
        write(os.path.join(self.project, "aidlc", "spaces", "default", "intents", "active-intent"), INTENT + "\n")
        write(os.path.join(self.root, "aidlc-state.md"), "# AI-DLC State Tracking\n\n## Project Information\n- **Project**: A pre-order app for a neighbourhood bakery: customers reserve loaves for the next morning and the baker sees one pick-up list.\n\n"
                                                      "## Current Status\n- **Current Stage**: user-stories\n- **Next Stage**: delivery-planning\n")
        write(os.path.join(self.root, "audit", "session-a.md"), "# Audit\n")
        write(os.path.join(self.project, ".claude", "tools", "data", "stage-graph.json"), json.dumps(graph))
        self.write_rules(graph)
        self.env = {"APPROVAL_GATES_DIR": self.state, "AIDLC_IDS_DIR": self.ids}
        self.graph = {s["slug"]: s for s in graph}

    def write_rules(self, graph):
        """What a stage is judged against: its definition, the reviewer's checklist, the project's rules (scripts/criteria.py)."""
        for st in graph:
            keys = [k for k in (st.get("produces") or []) if not k.endswith("-timestamp")] or [st["slug"] + "-summary"]
            steps = "".join(f"- **{k}.md**: {pc.sentence((st['slug'], k, 'def'))} {pc.sentence((st['slug'], k, 'def2'))}\n" for k in keys[:4])
            write(os.path.join(self.project, ".claude", "aidlc-common", "stages", st["phase"], st["slug"] + ".md"),
                  f"---\nslug: {st['slug']}\nphase: {st['phase']}\n" + (f"reviewer: {st['reviewer']}\n" if st.get("reviewer") else "") + "---\n\n"
                  f"# {st['name']}\n\n## Constraints\n\n{pc.sentence((st['slug'], 'con'), 2)}\n\n## Steps\n\n### Step 1: Write the records\n\n{steps}\n"
                  f"### Step 2: Check them\n\n- Every id in a record is defined once.\n- Each record names who it is for.\n")
            if st.get("reviewer"):
                write(os.path.join(self.project, ".claude", "agents", st["reviewer"] + ".md"),
                      "# Reviewer\n\n## Core Review Questions\n\n1. **Would a developer know exactly what to build from this?**\n2. **Could QA write a test from each requirement?**\n"
                      "3. **Does it say who sees what, and when?**\n\n## What to Check\n\n### " + st["name"] + "\n- Every record is complete.\n- Nothing contradicts an earlier stage.\n")
        write(os.path.join(self.project, "aidlc", "spaces", "default", "memory", "project.md"),
              "# Project rules\n\n## Rules\n\n- Every user-facing word comes from the sheet, never from code.\n- A slot is 15 minutes unless a Unit says otherwise.\n- Every id is written once and linked everywhere else.\n"
              "- A requirement without a story is a gap, not a note.\n")

    def folder(self, stage, unit):
        phase = stage["phase"]
        return os.path.join(self.root, "construction", unit, stage["slug"]) if unit else os.path.join(self.root, phase, stage["slug"])

    def write_docs(self, stage, unit, docs):
        folder = self.folder(stage, unit)
        shutil.rmtree(folder, ignore_errors=True)
        for key, text in docs.items():
            write(os.path.join(folder, key + (".json" if key.endswith("traceability") and text.lstrip().startswith("{") else ".md")), text)

    def reject(self, stage, unit, n):
        block = (f"\n## Gate Rejected\n**Timestamp**: 2026-01-0{n + 1}T08:00:00Z\n**Event**: GATE_REJECTED\n**Stage**: {stage['slug']}\n"
                 + (f"**Unit**: {unit}\n" if unit else "") +
                 "**Feedback**: Fix the open findings, add Saturday pickups, and say what happens across midnight.\n"
                 "**Conductor Summary**: Three changes: Saturday pickups, the midnight case, and the findings sorted Fix.\n**Message Id**: preview" + str(n) + "\n\n---\n")
        with open(os.path.join(self.root, "audit", "session-a.md"), "a", encoding="utf-8") as f:
            f.write(block)

    def run(self, argv):
        old = {k: os.environ.get(k) for k in list(self.env) + ["CLAUDE_PROJECT_DIR"]}
        os.environ.update(self.env)
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        try:
            return quiet(gate_bundle.main, argv)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def gate(self, stage, unit, rnd, out, clean=False, findings=None, handled=True):
        """Draft, judge and finalize one presentation; (row, {doc id: doc row})."""
        shutil.rmtree(out, ignore_errors=True)
        argv = ["draft", "--project-dir", self.project, "--stage", stage["slug"], "--no-brief", "--out", out] + (["--unit", unit] if unit else [])
        if findings:
            fpath = os.path.join(self.tmp, "findings.json")
            write(fpath, json.dumps(findings))
            argv += ["--findings", fpath]
        code, so, se = self.run(argv)
        if code:
            raise SystemExit(f"preview: draft of {stage['slug']} failed:\n{se}{so}")
        drafted = json.loads(so)
        judge(drafted["judgment"], rnd, clean)
        code, so, se = self.run(["finalize", "--out", out])
        if code:
            raise SystemExit(f"preview: finalize of {stage['slug']} failed:\n{se}{so}")
        row = json.loads(read(os.path.join(out, "row.json")))
        docs = {}
        for name in sorted(os.listdir(os.path.join(out, "documents"))):
            docs[name[:-5]] = json.loads(read(os.path.join(out, "documents", name)))
        return row, docs


def judge(path, rnd, clean=False):
    """What an agent writes into judgment.json, mechanically but with variety: most criteria hold, one fails (named in a risk),
    a few are not relevant, every item has a plain sentence and a label, the critical and high ones are looked at first."""
    j = json.loads(read(path))
    crit = list(j["criteria"])
    fail = None if clean else (crit[3] if len(crit) > 3 else None)
    for i, k in enumerate(crit):
        c = j["criteria"][k]
        c["verdict"] = "fails" if k == fail else ("n/a" if i % 7 == 6 else "holds")
        c["note"] = "The wording does not say who sees it, so the baker cannot be sure." if k == fail else (c.get("note") or "")
    labels = ["critical", "high", "medium", "medium", "low", "high", "low", "medium"]
    looked = 0
    for i, (k, it) in enumerate(j["items"].items()):
        lab = labels[i % len(labels)]
        text = re.sub(r"\s+", " ", re.sub(r"[`*#|]", "", it.get("_asWritten") or k)).strip()
        text = re.split(r"(?<=[.!?])\s", text)[0][:200].rstrip(" …,;:") or "A thing this stage settles."
        it.update(summary=text if text.endswith((".", "!", "?")) else text + ".", label=lab)
        if lab in ("critical", "high") and looked < 3:
            it["lookFirst"] = True
            looked += 1
    first = fail or (crit[0] if crit else None) or next(iter(j["items"]), None) or "doc:" + next(iter(j["documents"]))
    second = (next(iter(j["items"]), None) or first)
    j["evaluation"].update(
        verdict="ready" if clean else "risks",
        decides="Approving fixes what a customer can order and when, and what the baker prints each morning." if not clean else "Approving settles the wording; nothing here needs a second look.",
        lookFirst=[{"text": "Pick-up slots are fixed at 15 minutes; a bakery that bakes in 30-minute batches cannot use them as they are.", "why": "It decides the booking model and is hard to change once code exists.", "sources": [first]}],
        solid=[{"text": "Every requirement has a story and every story has a check.", "sources": [second]}, {"text": "The words match the shop's own: loaf, slot, list.", "sources": [first]}])
    if not clean:
        j["evaluation"]["risks"] = [{"text": "A late order made after 23:00 has no day to count for.", "severity": "high", "sources": [first]}]
        j["evaluation"]["gaps"] = [{"text": "Nothing says what the baker sees when two slots are both full.", "sources": [second]}]
        if len(crit) > 5:
            j["evaluation"]["conflicts"] = [{"text": "The earlier stage allows cancelling until midnight; this one stops at 21:00.", "sources": [crit[5]]}]
    if "revision" in j:
        changed = [c.get("where") for c in j["revision"].get("_changed") or [] if c.get("where")]
        j["revision"]["feedback"] = "Fix the open findings, add Saturday pickups, and say what happens across midnight."
        j["revision"]["changes"] = [{"asked": "Add Saturday pickups.", "what": "A Saturday section now says the slot opens at 07:00 and the baker can close it by hand.", "where": (changed[:1] or ["evaluation"])},
                                    {"asked": "Say what happens across midnight.", "what": "A late order counts for the day after next, and the list says so beside the order.", "where": (changed[1:2] or ["summary"])}]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(j, f)


def sample_of(bakery, stage, unit, rounds, tmp, **kw):
    """The rows of `rounds` presentations of one stage: {id, row, documents, others[]}."""
    made = []
    for rnd in range(1, rounds + 1):
        docs = pc.documents(stage["slug"], stage.get("produces") or [], rnd)
        bakery.write_docs(stage, unit, docs)
        if rnd > 1:
            bakery.reject(stage, unit, rnd - 1)
        row, drows = bakery.gate(stage, unit, rnd, os.path.join(tmp, f"out-{stage['slug']}-{rnd}"), **(kw if rnd == rounds else {"clean": False}))
        gid = f"{INTENT}-{stage['slug']}" + (f"-{unit}" if unit else "") + f"-2026010{rnd}T0900"
        row["createdAt"] = f"2026-01-0{rnd}T09:00:00Z"
        row["round"] = rnd
        made.append({"id": gid, "row": row, "documents": drows})
    cur = made[-1]
    return {"id": cur["id"], "row": cur["row"], "documents": cur["documents"], "others": made[:-1]}


def gate_rows(sample):
    rows = {}
    for item in [sample] + sample["others"]:
        rows["gates/" + item["id"]] = item["row"]
        for did, d in item["documents"].items():
            rows[f"gates/{item['id']}/documents/{did}"] = d
    return rows


def stage_scenarios(bakery, graph, tmp, only):
    out = []
    for st in graph:
        unit = UNIT if st.get("for_each") else None
        label = f"{st['number']} {st['name']}" + (f" (Unit {unit})" if unit else "")
        if st["slug"] == "build-and-test":
            continue
        for rounds in (1, 3):
            s = sample_of(bakery, st, unit, rounds, tmp)
            what = ("Round 1: the evaluation, the items, the records, the diagrams a record's structure gives." if rounds == 1 else
                    "Round 3, after two Request Changes: What changed block, round colours, the timeline, additions and removals in the records.")
            out.append(Scenario(f"stage-{st['number'].replace('.', '-')}-{st['slug']}-r{rounds}", "Per-stage gates, " + st["phase"], f"{label}. {what}", "gate", gate_rows(s), s["id"]))
    return out


def build_test_scenarios(bakery, graph, tmp):
    st = next(s for s in graph if s["slug"] == "build-and-test")
    out = []
    for rounds in (1, 3):
        made = []
        for rnd in range(1, rounds + 1):
            summary, results = pc.build_and_test(rnd)
            docs = {"build-instructions": pc.build_instructions(), "build-and-test-summary": summary, "build-test-results": results}
            bakery.write_docs(st, None, docs)
            if rnd > 1:
                bakery.reject(st, None, rnd - 1)
            row, drows = bakery.gate(st, None, rnd, os.path.join(tmp, f"out-bt-{rnd}"))
            gid = f"{INTENT}-build-and-test-2026010{rnd}T0900"
            row["createdAt"] = f"2026-01-0{rnd}T09:00:00Z"
            row["round"] = rnd
            made.append({"id": gid, "row": row, "documents": drows})
        s = {"id": made[-1]["id"], "row": made[-1]["row"], "documents": made[-1]["documents"], "others": made[:-1]}
        out.append(Scenario(f"build-and-test-r{rounds}", "Per-stage gates, construction",
                            "Build and Test with 48 targets over four Units (the heat grid, one list of targets, Not Met first) and u2:NFR7 in two files that disagree (Met in the summary, Not Met in the results)."
                            + (" Round 3: targets added, removed and re-verified." if rounds == 3 else ""), "gate", gate_rows(s), s["id"]))
    return out


def special_scenarios(bakery, graph, tmp):
    """A gate with findings to sort, one with unhandled items, one with nothing pending."""
    st = next(s for s in graph if s["slug"] == "user-stories")
    findings = {"source": "aidlc", "stage": "user-stories", "stage_name": "User Stories", "artifact": "reviews/review-01.md",
                "findings": [{"id": f"R-0{i}", "severity": sev, "where": f"stories.md, US{i}.1", "finding": f"{pc.sentence(('f', i))} {pc.sentence(('f2', i))}",
                              "action": pc.sentence(("act", i))[:110], "status": "New", "blocking": sev in ("Critical", "Major"),
                              "title": pc.sentence(("t", i))[:70].rstrip(".")}
                             for i, sev in enumerate(["Critical", "Major", "Major", "Minor", "Minor", "Minor"], 1)], "carried": []}
    out = []
    s = sample_of(bakery, st, None, 1, tmp, findings=findings)
    out.append(Scenario("gate-findings-to-sort", "Per-stage gates, special", "User Stories with six review findings to sort Fix / Accept / Reject (Accept is not offered on the blocking ones).", "gate", gate_rows(s), s["id"]))
    s = sample_of(bakery, st, None, 1, tmp)
    for it in s["row"]["digest"]["items"][:4]:
        it["coveredBy"] = {"text": "No stage covers it", "settled": False}
    out.append(Scenario("gate-unhandled-items", "Per-stage gates, special", "User Stories where four items are handled nowhere: they sit in Needs you with the reason missing.", "gate", gate_rows(s), s["id"]))
    s = sample_of(bakery, st, None, 1, tmp, clean=True)
    out.append(Scenario("gate-nothing-pending", "Per-stage gates, special", "User Stories with every criterion holding and nothing to decide: the Needs you filter is empty, the readiness counter says so.", "gate", gate_rows(s), s["id"]))
    return out


# ---------------------------------------------------------------- the rest

def unit_scenarios():
    out = []
    for name, group, desc, bundles, current in preview_units.bundles():
        rows = {}
        for b in bundles:
            h = b["header"]
            rows["bundles/" + b["id"]] = {"bundle": b, "page": b["page"], "title": h["title"], "createdAt": b["createdAt"], "status": "open", "intent": h["intent"], "unit": h["unit"]}
        out.append(Scenario(name, group, desc, "unit", rows, current["id"]))
    return out


def plan_scenarios():
    plan_id, row = preview_units.test_plan_row()
    return [Scenario("test-plan", "Test plan", "The test plan of the not-verified points: sections, steps, one agent step done, Pass / Fail with notes.", "plan", {"plans/" + plan_id: row}, plan_id)]


def map_scenarios(tmp):
    rows = preview_units.map_rows(tmp)
    out = []
    for kind, desc in (("components", "The component map: 24 components in layers, pick one for what it needs and what waits for it."),
                       ("units", "The Unit map: 50 Units as waves, some landed, some new or changed since the last revision."),
                       ("stories", "Stories by Units, the matrix with a cell per link."), ("entities", "Entities by components, the matrix of who owns what.")):
        out.append(Scenario(f"maps-{kind}", "Maps", desc, "maps", rows, f"{INTENT}-{kind}"))
    return out


def list_scenarios(by_name):
    out = []
    for kind, name, desc, source in (("gate", "list-gates", "The list of gates, no hash: every stage and round, newest first.", "stage-2-4-user-stories-r3"),
                                     ("unit", "list-unit-pages", "The list of Unit pages (plan and unit-end), no hash.", "unit-plan-r3"),
                                     ("plan", "list-test-plans", "The list of test plans, no hash.", "test-plan"),
                                     ("maps", "list-maps", "The list of maps, no hash.", "maps-units")):
        src = by_name.get(source)
        if src:
            out.append(Scenario(name, "List views", desc, kind, src.rows, ""))
    return out


INDEX = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>approval-gates preview</title>
<style>:root{color-scheme:light dark;--bg:#F5F6F8;--surface:#fff;--fg:#171A21;--muted:#5A6170;--line:#E4E7EC;--accent:#2F49C4}@media(prefers-color-scheme:dark){:root{--bg:#111318;--surface:#1A1D24;--fg:#E6E8EE;--muted:#9AA1AF;--line:#2A2E38;--accent:#8FA2FF}}
body{font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);color:var(--fg);margin:0}main{max-width:980px;margin:0 auto;padding:24px 16px 64px}h1{font-size:22px;margin:0 0 4px}
p.lede{color:var(--muted);margin:0 0 20px}h2{font-size:15px;margin:28px 0 8px}ul{list-style:none;margin:0;padding:0;background:var(--surface);border:1px solid var(--line);border-radius:10px}
li{display:flex;gap:12px;padding:8px 12px;border-top:1px solid var(--line);align-items:baseline;flex-wrap:wrap}li:first-child{border-top:0}a{color:var(--accent);font-weight:600;min-width:240px;text-decoration:none}a:hover{text-decoration:underline}.d{color:var(--muted);flex:1 1 380px}
.dk{font-size:12px}</style></head><body><main><h1>approval-gates preview</h1><p class="lede">%N% pages, all synthetic. Add <code>?theme=dark</code> to any address for the dark theme. Each link opens the real template with its data embedded; a reload forgets what you wrote.</p>%BODY%</main></body></html>
"""


def write_index(out, scenarios):
    groups = {}
    for s in scenarios:
        groups.setdefault(s.group, []).append(s)
    body = "".join(f"<h2>{g} ({len(items)})</h2><ul>" + "".join(
        f'<li><a href="{s.file}">{s.name}</a><span class="d">{s.desc}</span><a class="dk" href="{s.file}?theme=dark">dark</a></li>' for s in items) + "</ul>" for g, items in groups.items())
    write(os.path.join(out, "index.html"), INDEX.replace("%N%", str(len(scenarios))).replace("%BODY%", body))


def build(out, only="", stage_graph=None, say=print):
    """Write every scenario into `out`; the list of Scenario."""
    graph = json.loads(read(stage_graph or os.path.join(HERE, "stage-graph.json")))
    tmp = tempfile.mkdtemp(prefix="approval-gates-preview-")
    try:
        bakery = Bakery(tmp, graph)
        scenarios = []
        for label, make in (("per-stage gates", lambda: stage_scenarios(bakery, graph, tmp, only)),
                            ("Build and Test", lambda: build_test_scenarios(bakery, graph, tmp)),
                            ("special gates", lambda: special_scenarios(bakery, graph, tmp)),
                            ("Unit pages", unit_scenarios), ("test plan", plan_scenarios), ("maps", lambda: map_scenarios(tmp))):
            say(f"  {label}…")
            scenarios += make()
        scenarios += list_scenarios({s.name: s for s in scenarios})
        wanted = [w.strip().lower() for w in (only or "").split(",") if w.strip()]
        if wanted:
            scenarios = [s for s in scenarios if any(w in s.name.lower() or w in s.group.lower() for w in wanted)]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    for s in scenarios:
        write(os.path.join(out, s.file), s.html())
    write_index(out, scenarios)
    return scenarios


def main(argv=None):
    ap = argparse.ArgumentParser(prog="preview.py", description="Write the approval-gates pages with synthetic data, to look at without an account.")
    ap.add_argument("--out", default="approval-gates-preview", help="the folder to write into (default ./approval-gates-preview)")
    ap.add_argument("--only", default="", help="only the scenarios whose name or group holds one of these words, comma separated (e.g. user-stories,maps,unit)")
    ap.add_argument("--stage-graph", help="the engine's stage-graph.json (default dev/stage-graph.json)")
    args = ap.parse_args(argv)
    out = os.path.abspath(args.out)
    print(f"Writing the preview into {out}")
    scenarios = build(out, args.only, args.stage_graph)
    print(f"{len(scenarios)} pages. Open {os.path.join(out, 'index.html')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
