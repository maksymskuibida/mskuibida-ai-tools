"""Synthetic Unit pages, a test plan and a project for the maps, for dev/preview.py. Everything is invented (a neighbourhood
bakery's pre-order app); the bundles are checked with scripts/validate_bundle.py and the maps are built by scripts/map_bundle.py.
Standard library only."""

import copy
import io
import json
import os
import sys
import contextlib

import preview_content as pc

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import map_bundle  # noqa: E402
import unit_bundle  # noqa: E402
import validate_bundle  # noqa: E402

INTENT = "260101-bakery-preorder"
UNIT = "u2-pickup-slots"
MAPS = [{"kind": "units", "url": "https://example.com/preview/maps-units#260101-bakery-preorder-units", "title": "Unit map"}, {"kind": "components", "url": "https://example.com/preview/maps-components#260101-bakery-preorder-components", "title": "Component map"}]
LABELS = ["critical", "high", "medium", "medium", "low", "high", "low"]
LAYERS = ["setup", "data", "logic", "logic", "api", "api", "UI", "UI", "tests", "tests", "checks", "docs"]


def row(rid, title, label, rev, extra=None):
    r = {"id": rid, "title": title.rstrip(".")[:150], "label": label, "body": pc.para((rid, title, rev), 2), "refs": []}
    if extra:
        r.update(extra)
    return r


def refs(rid, n=2):
    return [{"label": f"Q{(pc.rnd_of(rid, i) % 6) + 1}", "tip": "Your answer to a question in an earlier stage: " + pc.sentence((rid, i, "tip"))[:80], "target": f"#fd-q{(pc.rnd_of(rid, i) % 6) + 1}"} for i in range(n)]


def suggested(rows):
    """Two rows that propose something the person may take or leave: they carry Do it / Leave it."""
    for r in rows[:2]:
        r["suggestion"] = True
    return rows


def sections_plan(rev):
    def rows(prefix, n, kind_seed, stagger=0, new=False):
        """`new`: the section that gets the two rows later rounds add (each such row lives in one section, not five)."""
        out = []
        for i in range(1, n + 1):
            r = row(f"{prefix}-{i}", pc.sentence((kind_seed, i))[:110], pc.pick(LABELS, kind_seed, i), rev, {"refs": refs(f"{prefix}{i}")})
            if pc.rnd_of(kind_seed, i) % 5 == 0 and r["label"] in ("critical", "high"):
                r["lookFirst"] = True
            out.append(r)
        if rev >= 2:
            out[1]["title"] = out[1]["title"] + " (now also on Saturdays)"
            out[1]["body"] += " " + pc.sentence((kind_seed, "r2"))
            if new:
                out.insert(2, row(f"{prefix}-{n + 1}", "Saturday pickups open at 07:00", "high", rev))
            out.pop(-1)
        if rev >= 3:
            out[min(3, len(out) - 1)]["body"] = pc.para((kind_seed, "r3"), 3)
            if new:
                out.append(row(f"{prefix}-{n + 2}", "An order after 23:00 counts for the day after next", "medium", rev))
        return out
    findings = rows("F", 8, "find")
    for i, r in enumerate(findings):
        r["coveredBy"] = {"text": f"Step {i % 8 + 1} settles it", "settled": True, "link": {"kind": "step", "target": f"#step-{i % 8 + 1}"}}
    return [
        {"key": "narrows", "kind": "narrows", "title": "Narrows what you approved", "short": "Narrows", "hint": "An earlier approved record now reads differently", "rows": rows("N", 4, "narrow")},
        {"key": "visible", "kind": "visible", "title": "What people see, data, API, dependencies", "short": "Visible", "hint": "Changes a person would notice or a contract would feel", "rows": suggested(rows("V", 5, "vis"))},
        {"key": "assumptions", "kind": "assumptions", "title": "Assumptions made without asking", "short": "Assumptions", "hint": "Ranked by what it costs if one is wrong", "rows": rows("A", 14, "assume", new=True)},
        {"key": "findings", "kind": "findings", "title": "Reviewer findings left open", "short": "Findings", "hint": "Not settled in the design; what in the plan settles each", "rows": findings},
        {"key": "tests", "kind": "tests", "title": "Tests", "short": "Tests", "hint": "Grouped; open only when something matters", "rows": rows("T", 6, "tests")}]


def steps_plan(rev):
    out = []
    for n in range(1, 17 + (2 if rev >= 2 else 0)):
        layer = LAYERS[(n - 1) * len(LAYERS) // 17 % len(LAYERS)] if n <= 17 else "UI"
        out.append({"n": n, "title": pc.pick(["Slot rules", "Order endpoint", "Slot calendar", "Stock check", "Baker list query", "Reminder job", "Order page", "List page", "Seed data"], "st", n) + f" {n}",
                    "layer": layer, "files": 1 + n % 4, "subs": [{"text": pc.sentence(("sub", n, k))[:100]} for k in range(3)],
                    "implements": [{"label": f"FR{n % 14 + 1}", "tip": pc.sentence(("imp", n))[:80], "target": f"path:aidlc/x/requirements.md#FR{n % 14 + 1}"},
                                   {"label": f"SR{n % 8 + 1}", "tip": pc.sentence(("imp2", n))[:80], "target": f"path:aidlc/x/functional-spec.md#SR{n % 8 + 1}"}]})
    layer_order = {}
    for st in out:  # the plan is in build order: a layer's place is where it first appears
        layer_order.setdefault(st["layer"], len(layer_order))
    out.sort(key=lambda s: (s["n"]))
    if rev >= 2:
        out[2]["title"] += " (with Saturdays)"
    if rev >= 3:
        out[5]["subs"].append({"text": "Check the midnight case."})
    return out


def answers():
    groups = []
    for key, stage, title in (("fd-answers", "functional-design", "Functional Design"), ("nfr-answers", "nfr-requirements", "NFR Requirements"), ("code-answers", "code-generation", "Code Generation")):
        groups.append({"key": key, "stage": stage, "title": title, "file": f"aidlc/x/{stage}-questions.md",
                       "questions": [{"id": f"Q{i}", "anchor": f"fd-q{i}" if key == "fd-answers" else f"{key[:3]}-q{i}", "text": pc.sentence((key, i))[:100], "answer": pc.pick("ABCD", key, i), "proposed": pc.pick("ABCD", key, i, "p")} for i in range(1, 7)]})
    return groups


def header(page, rev, title):
    return {"project": "Bakery pre-order", "intent": INTENT, "intentName": "Bakery pre-order", "unit": UNIT, "unitName": "Pick-up slots", "title": title,
            "lede": "Customers pick a pick-up slot for tomorrow's loaves; the baker sees one list.", "status": "Plan approval · answer in chat" if page == "plan" else "End of Unit · answer in chat",
            "revision": rev, "revisions": [{"n": n, "note": "first draft" if n == 1 else "revision", "at": f"2026-01-0{n}T09:00:00Z"} for n in range(1, rev + 1)],
            "facts": []}


def with_facts(b):
    """The tiles are numbers the page shows: the steps of the plan, the rows to look at first."""
    rows = [r for s in b["sections"] for r in s["rows"]]
    look = sum(1 for r in rows if r.get("lookFirst"))
    facts = ([{"label": "Steps", "value": str(len(b["plan"]["steps"]))}] if b.get("plan") else []) + ([{"label": "Look first", "value": f"{look} row" + ("" if look == 1 else "s")}] if look else [])
    b["header"]["facts"] = facts
    return b


def plan_bundle(rev):
    b = {"schema": "aidlc-gate-bundle/1", "page": "plan", "id": f"{INTENT}-{UNIT}-plan-v{rev}-2026010{rev}T0900", "createdAt": f"2026-01-0{rev}T09:00:00Z",
         "header": header("plan", rev, "U2 · Pick-up slots · plan approval"), "sections": sections_plan(rev), "plan": {"title": "Code plan", "hint": "", "steps": steps_plan(rev)},
         "answers": answers(), "maps": MAPS}
    b["plan"]["hint"] = f"{len(b['plan']['steps'])} steps · ~{sum(s['files'] for s in b['plan']['steps'])} files"
    return with_facts(b)


def end_bundle(rev, tested=False):
    def rows(prefix, n, seed, weight=False):
        return [row(f"{prefix}-{i}", pc.sentence((seed, i))[:110], pc.pick(["core", "main", "main", "minor"] if weight else LABELS, seed, i), rev) for i in range(1, n + 1)]
    changes = rows("D", 3, "dev")
    unverified, verified, failed = rows("V", 8, "unv"), rows("V", 6, "ver"), rows("V", 3, "fail")
    for i, r in enumerate(verified):
        r["id"] = f"V-{i + 9}"
    for i, r in enumerate(failed):
        r["id"] = f"V-{i + 15}"
        r["body"] = "Failed in the test plan, left as known: " + r["body"]
    built = rows("B", 12, "built", True)
    if rev >= 2:
        built[1]["title"] += " (Saturdays too)"
        built.append(row("B-13", "Saturday slots", "main", rev))
        unverified.pop()
    if rev >= 3:
        changes.append(row("D-4", "The midnight case counts for the day after next", "high", rev))
    secs = [{"key": "changes", "kind": "changes", "title": "Changed after plan approval", "short": "Changed", "hint": "The design stays as approved, except these", "refsLabel": "Was", "rows": changes}]
    if tested:
        secs += [{"key": "unverified", "kind": "unverified", "title": "Still not verified", "short": "Not verified", "hint": "Left for Build and Test or CI", "refsLabel": "For", "rows": unverified[:4]},
                 {"key": "verified", "kind": "verified", "title": "Verified by you", "short": "Verified", "hint": "Passed in your test plan", "refsLabel": "For", "rows": verified},
                 {"key": "failed", "kind": "failed", "title": "Failed, left as known", "short": "Failed", "hint": "Failed in your test plan, accepted as known", "refsLabel": "For", "rows": failed}]
    else:
        secs.append({"key": "unverified", "kind": "unverified", "title": "Not verified yet", "short": "Not verified", "hint": "Left for Build and Test or CI", "refsLabel": "For", "rows": unverified})
    nodes = [{"id": f"n{i}", "title": r["title"][:30], "weight": r["label"], "target": f"#{r['id']}"} for i, r in enumerate(built[:8])]
    secs.append({"key": "built", "kind": "built", "title": "What was built", "short": "Built", "hint": "One line per piece that matters", "refsLabel": "Uses", "rows": built,
                 "map": {"nodes": nodes, "edges": [{"from": f"n{i}", "to": f"n{i + 1}"} for i in range(len(nodes) - 1)]}})
    b = {"schema": "aidlc-gate-bundle/1", "page": "unit-end", "id": f"{INTENT}-{UNIT}-unit-end-v{rev}-2026010{rev}T1000", "createdAt": f"2026-01-0{rev}T10:00:00Z",
         "header": header("unit-end", rev, "U2 · Pick-up slots · end of Unit"), "sections": secs, "answers": [],
         "design": {"bundle": plan_bundle(1)["id"], "rows": [{"id": r["id"], "title": r["title"], "label": r["label"]} for s in plan_bundle(1)["sections"] for r in s["rows"]][:16], "counts": "36 rows · 18 answers · 17 steps"},
         "verification": {"auto": 14}, "maps": MAPS}
    return with_facts(b)


def revised(make, upto):
    """The bundles of revisions 1..upto, each marked against the one before."""
    out, prev = [], None
    for rev in range(1, upto + 1):
        b = make(rev)
        unit_bundle.mark_revisions(b, prev)
        for _s, r in validate_bundle.all_rows(b):
            if r.get("rev") == rev and not r.get("revNote"):
                r["revNote"] = "Reworded after your request." if r.get("revKind") == "changed" else "Added because you asked for it."
        for st in (b.get("plan") or {}).get("steps") or []:
            if st.get("rev") == rev and not st.get("revNote"):
                st["revNote"] = "Added for Saturdays." if st.get("revKind") == "new" else "Reworded after your request."
        out.append(b)
        prev = b
    return out


def checked(b):
    bad = validate_bundle.validate(b)
    if bad:
        raise SystemExit("preview: a synthetic Unit page breaks its contract:\n  " + "\n  ".join(bad[:8]))
    return b


def bundles():
    """[(name, group, description, [bundles of the artifact], the one to open)]"""
    plans = [checked(b) for b in revised(plan_bundle, 3)]
    ends = [checked(b) for b in revised(end_bundle, 3)]
    tested = checked(end_bundle(2, tested=True))
    tested["id"] = tested["id"].replace("-v2-2026010", "-v4-2026010")
    tested["header"]["revision"] = 4
    tested["header"]["revisions"] = tested["header"]["revisions"] + [{"n": 4, "note": "after your test plan", "at": "2026-01-04T10:00:00Z"}]
    tested["createdAt"] = "2026-01-04T10:00:00Z"
    unit_bundle.mark_revisions(tested, ends[-1])  # the rows carry the round that changed them, as a real page's do
    for _s, r in validate_bundle.all_rows(tested):
        if r.get("rev") == 4 and not r.get("revNote"):
            r["revNote"] = "Moved after your test plan." if r.get("revKind") == "changed" else "Added after your test plan."
    return [
        ("unit-plan-r1", "Unit pages", "The plan page, first presentation: assumptions, findings, the code plan as lanes by layer and as steps, your answers.", plans[:1], plans[0]),
        ("unit-plan-r3", "Unit pages", "The plan page in version 3: rows and steps new, changed and removed, the version timeline, the Changes and Clean views.", plans, plans[2]),
        ("unit-end-r1", "Unit pages", "The unit-end page, first presentation: what changed after approval, the verification funnel, what was built with its map.", ends[:1], ends[0]),
        ("unit-end-r3", "Unit pages", "The unit-end page in version 3: the version timeline and the marks of each round.", ends, ends[2]),
        ("unit-end-after-test-plan", "Unit pages", "The unit-end page after a test plan: Verification with verified, still not verified and failed points, and the funnel over them.", ends + [tested], tested),
    ]


def test_plan_row():
    plan = {"schema": "aidlc-test-plan/1", "id": f"{INTENT}-{UNIT}-test-v1-20260101T1100", "intent": INTENT, "unit": UNIT, "bundle": end_bundle(1)["id"], "title": "Unit u2-pickup-slots: test plan",
            "now": [f"V-{i}" for i in range(1, 7)], "allByDefault": False, "rows": {f"V-{i}": pc.sentence(("unv", i))[:110].rstrip(".") for i in range(1, 9)},
            "sections": [{"key": "A", "title": "Run the app", "agent": "Start the dev server and seed three days of orders.",
                          "steps": [{"id": f"A.{n}", "do": pc.sentence(("do", n)), "expect": pc.sentence(("ex", n)), "criteria": [pc.sentence(("c", n))[:80], pc.sentence(("c2", n))[:80]], "verifies": [f"V-{n % 6 + 1}"]} for n in range(1, 5)]},
                         {"key": "B", "title": "Reset the data", "agent": "Wipe and seed the test database, then restart the app.",
                          "steps": [{"id": f"B.{n}", "do": pc.sentence(("dob", n)), "expect": pc.sentence(("exb", n)), "criteria": [pc.sentence(("cb", n))[:80]], "verifies": [f"V-{n + 3}"]} for n in range(1, 4)]}]}
    return plan["id"], {"plan": plan, "intent": INTENT, "unit": UNIT, "title": plan["title"], "createdAt": "2026-01-01T11:00:00Z", "status": "open", "agentDone": ["A"],
                        "results": {"A.1": {"result": "pass", "note": "", "at": "2026-01-01T11:10:00Z"}, "A.2": {"result": "fail", "note": "The full slot stays clickable on a phone.", "at": "2026-01-01T11:12:00Z"}}}


# ---------------------------------------------------------------- maps

def phrase(seed):
    """A short whole name for a Unit (never a sentence cut in the middle)."""
    return f"{pc.pick(pc.TOPICS, seed, 't').capitalize()} for {pc.pick(pc.LOAVES, seed, 'l')}"


def map_project(tmp, rev):
    """A bakery project with 50 Units, 24 components and what the maps read; rev 2 adds Units, changes some and lands more."""
    units = [(f"u{i}-{pc.pick(['orders', 'slots', 'stock', 'list', 'mail', 'pay', 'stamps', 'bake'], i, 'u')}", f"U{i}") for i in range(1, 51 + (3 if rev >= 2 else 0))]
    if rev >= 2:
        units = units[:48] + units[50:]  # the last two of the first fifty are gone, three new ones come
    root = os.path.join(tmp, "mapproject", "aidlc", "spaces", "default", "intents", INTENT)
    project = os.path.join(tmp, "mapproject")  # one project in both revisions: the second one is compared with the first

    def put(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    put(os.path.join(project, "aidlc", "active-space"), "default\n")
    put(os.path.join(root, "..", "active-intent"), INTENT + "\n")
    base = os.path.join(root, "inception", "units-generation")
    rows = "".join(f"| {uid} | {slug} | {phrase((slug, 'name'))} | {pc.pick(['service', 'ui'], slug)} | {pc.pick([1, 2, 3, 5, 8], slug)} | {1 + i * 7 // len(units)} |\n" for i, (slug, uid) in enumerate(units))
    put(os.path.join(base, "unit-of-work.md"), "# Units of Work\n\n## Units\n\n| Unit ID | Dir | Unit | Kind | Points | Wave |\n|---|---|---|---|---|---|\n" + rows)
    def needs_of(i, slug):
        if not i:
            return set()
        if i >= 26 and i % 4 == 1:  # a few later Units rest only on work that has landed: they are ready to start
            return {pc.rnd_of(slug, "early") % 20}
        return {max(0, i - 1 - pc.rnd_of(slug, k) % 4) for k in range(1 + i % 3)} - {i}
    dep = "".join(f"  - name: {slug}\n    kind: {pc.pick(['service', 'ui'], slug)}\n    depends_on: [{', '.join(units[j][0] for j in sorted(needs_of(i, slug)))}]\n" for i, (slug, _u) in enumerate(units))
    put(os.path.join(base, "unit-of-work-dependency.md"), "# Unit Dependencies\n\n```yaml\nunits:\n" + dep + "```\n")
    stories = [f"US{i}.{k}" for i in range(1, 19) for k in (1, 2)]
    smap = "".join(f"| {s} | {units[(i * 3 + k) % len(units)][1]} | {units[(i * 3 + k) % len(units)][0]} |\n" for i, s in enumerate(stories) for k in range(1 + i % 2))
    put(os.path.join(base, "unit-of-work-story-map.md"), "# Story map\n\n## Story to Unit\n\n| Story | Unit ID | Dir |\n|---|---|---|\n" + smap)
    put(os.path.join(root, "inception", "user-stories", "stories.md"), "# Stories\n\n" + "".join(f"### {s} {pc.pick(pc.TOPICS, s).capitalize()}\n" for s in stories))
    put(os.path.join(root, "unit-points.csv"), "unit,points,source\n" + "".join(f"{slug},{pc.pick([1, 2, 3, 5, 8], slug, rev if i % 6 == 0 else 0)},{pc.pick(['ai', 'human'], slug)}\n" for i, (slug, _u) in enumerate(units)))
    landed = 14 + (6 if rev >= 2 else 0)
    prog = "| unit | owner | functional-design | code-generation | gate | merged |\n| --- | --- | --- | --- | --- | --- |\n" + "".join(
        f"| {slug} | max | [{'x' if i < landed + 6 else ' '}] | [{'x' if i < landed else ' '}] | [{'x' if i < landed else ' '}] | [{'x' if i < landed else ' '}] |\n" for i, (slug, _u) in enumerate(units))
    put(os.path.join(root, "aidlc-state.md"), "# AI-DLC State Tracking\n\n## Current Status\n- **Current Stage**: functional-design\n\n## Unit Progress\n" + prog)
    ents = ["Customer", "Order", "OrderLine", "Loaf", "Slot", "StockDay", "Reminder", "Payment"]
    names = [f"{pc.pick(['Order', 'List', 'Slot', 'Stock', 'Mail', 'Pay', 'Stamp', 'Bake'], i)}{pc.pick(['Service', 'Store', 'Page', 'Job', 'Rules'], i, 'c')}{i}" for i in range(24)]
    comps = "".join(f"  - name: {n}\n    summary: {pc.sentence((n, 's'))}\n    group: {pc.pick(['presentation', 'application', 'domain', 'data'], n)}\n" +
                    (f"    depends_on:\n" + "".join(f"      - component: {names[j]}\n        interaction: reads from it\n" for j in sorted({max(0, i - 1 - pc.rnd_of(n, k) % 5) for k in range(1 + i % 3)} - {i})) if i else "") +
                    "    entities:\n" + "".join(f"      - name: {e}\n" for e in {pc.pick(ents, n, k) for k in range(2)}) for i, n in enumerate(names))
    put(os.path.join(root, "inception", "domain-design", "components.md"), "# Components\n\n```yaml\ncomponents:\n" + comps + "```\n")
    return project


def map_rows(tmp):
    """The map rows of the made-up project, revision 1 then revision 2 (the page shows what is new, changed or removed)."""
    rows = {}
    env = {"APPROVAL_GATES_DIR": os.path.join(tmp, "map-state")}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        for rev in (1, 2):
            project = map_project(tmp, rev)
            out = os.path.join(tmp, f"map-out{rev}")
            for step in ("draft", "finalize"):
                if step == "finalize":
                    fill_map_judgment(out)
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
                    code = map_bundle.main([step, "--kind", "all", "--out", out, "--project-dir", project])
                if code:
                    raise SystemExit(f"preview: map_bundle {step} failed: {err.getvalue()}")
            for kind in map_bundle.KINDS:
                path = os.path.join(out, kind, "row.json")
                if os.path.isfile(path):
                    with open(path, encoding="utf-8") as f:
                        rows[f"maps/{INTENT}-{kind}"] = json.load(f)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return rows


def fill_map_judgment(out):
    for kind in map_bundle.GRAPH:
        path = os.path.join(out, kind, "judgment.json")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            j = json.load(f)
        groups = ["Ordering", "Slots", "The baker", "Messages", "Money"]
        for i, (k, e) in enumerate(j["blocks"].items()):
            e["summary"] = e.get("summary") or pc.sentence((k, "sum"))
            e["group"] = e.get("group") or groups[i % len(groups)]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(j, f)
