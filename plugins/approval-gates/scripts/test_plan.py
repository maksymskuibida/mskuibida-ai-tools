#!/usr/bin/env python3
"""The test plan of a Unit's not-verified points, for a Unit claimed with the unit-end rhythm.

    test_plan.py now      --bundle <unit-end bundle.json> [--picks-file <picks.json>]
    test_plan.py defer    --bundle <unit-end bundle.json> [--picks-file <picks.json>] [--all] [--stage-dir <dir> | --project-dir <dir>]
    test_plan.py collect  [--project-dir <dir>]
    test_plan.py validate --plan <plan.json> [--bundle <unit-end bundle.json>] [--project-dir <dir>]
    test_plan.py publish  --plan <plan.json> [--bundle <unit-end bundle.json>] [--project-dir <dir>] --out <dir>
    test_plan.py finish   --plan <plan.json> --results <results.json> [--bundle <unit-end bundle.json>]
                          [--stage-dir <dir> | --project-dir <dir>] [--fix <step ids>|none]

`now` reads the developer's Test now / Later picks (the `picks` map of the unit-end page's `bundles/<id>` row) and prints
which V rows the plan covers: the rows picked Test now, or every row when none is (`allByDefault`: say so to the
developer). `validate` checks the plan the agent wrote against the unit-end bundle and prints one problem per line.
`publish` validates, then writes into <dir> the `plans/<id>` row (`row.json`) and the `writes.json` for one ArtifactData
batch. `finish` is run when the last section is completed: it checks the page's results (`results.json`: the row's
`results` map) are complete, then writes `test-plan.md` (plan, per-step result, notes, date) and `test-plan.json` (the
outcome that `unit_bundle.py draft --tested` reads) into the Unit's code-generation stage folder. Run it again with
`--fix` once the developer has decided which failed steps to fix (`--fix A.2,B.1`, or `--fix none` for none); the rows of
the steps not fixed are then "left as known".

`defer` records, in the Unit's code-generation folder (`deferred-to-build-and-test.json`), the not-verified points the
developer picked "At Build and Test" (every point with --all) and lists the others as still not verified; it is run when
the Unit is approved. `collect` reads those records of every Unit of the active intent, for the Build and Test plan.

A Build and Test plan (`kind: "build-and-test"`, `unit: "build-and-test"`, no `bundle`) has a `sources` list instead of a
unit-end bundle: {id: "<unit>:<point>", unit, point, title}, a Unit's V point or one of the stage's own manual checks
(`build-and-test:M-1`). `now` and each step's `verifies` hold source ids. `validate` takes --project-dir to check that
every point the Units deferred is in the plan. `finish` writes the outcome into the Build and Test stage folder and, for
each Unit, a `build-and-test-outcome.json` in its code-generation folder that `unit_bundle.py draft --tested` reads.

The plan (`aidlc-test-plan/1`): {schema, id, intent, unit, bundle, title, createdAt, now[], allByDefault, sections[]
{key: "A", title, agent, steps[] {id: "A.1", do, criteria[], verifies[]}}}.
A step's `criteria` are short checkable sentences (at least one); the page and test-plan.md number them under the step
(A.1.1, A.1.2 …). `expect` is optional; plans published before criteria existed carry only `expect` and still render.
The developer passes or fails a step as a whole; a step may hold only a note (`{"result": "", "note": …}`: written before
Pass or Fail was picked). It is not run, never a pass: `finish` refuses it and reports "not run, note: …". Notes are stored
untrimmed; `finish` trims them when it uses them.
The developer passes or fails a step as a whole; results may carry `failed: ["A.1.2"]` to name the criteria. The script never touches the artifact.
Standard library only.
"""

import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import validate_bundle  # noqa: E402

SCHEMA = "aidlc-test-plan/1"
OUTCOME_SCHEMA = "aidlc-test-outcome/1"
ROW_ID = re.compile(r"^V-\d+$")
POINT_ID = re.compile(r"^(V|M)-\d+$")
KIND_BT = "build-and-test"
BT_UNIT = "build-and-test"
DEFERRED_FILE = "deferred-to-build-and-test.json"
DEFERRED_SCHEMA = "aidlc-deferred-points/1"
BT_OUTCOME_FILE = "build-and-test-outcome.json"
BUILDTEST_PICK = "buildtest"
PLAN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*-test-v\d+-\d{8}T\d{4}$")
LINE_MAX = 160
TEXT_MAX = 1500
# A section after A exists only where the agent must do something first. An agent step that says it does nothing
# (or is empty / "-") means the section was split by not-verified point; its steps belong at the end of section A.
IDLE_AGENT = re.compile(
    r"nothing to (prepare|do|set ?up)|no (preparation|agent step|setup)|stays open from (section|the)|already open|^[\s\-–—.]*$",
    re.IGNORECASE)


class PlanError(Exception):
    pass


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as why:
        raise PlanError(f"cannot read {path}: {why}") from None


def unverified_rows(bundle):
    """[row] of the bundle's `unverified` section(s), in page order."""
    return [r for s in bundle.get("sections") or [] if s.get("kind") == "unverified" for r in s.get("rows") or []]


def now_rows(bundle, picks):
    """({V ids to test now}, allByDefault). The rows picked Test now, or every row when none is."""
    rows = unverified_rows(bundle)
    picks = picks or {}
    pick = lambda r: picks.get(validate_bundle.anchor(r["id"]))  # noqa: E731
    picked = [r["id"] for r in rows if pick(r) == "now"]
    # Rows picked At Build and Test are not tested here, even when nothing was picked Test now.
    return (picked, False) if picked else ([r["id"] for r in rows if pick(r) != BUILDTEST_PICK], True)


def is_bt(plan):
    return isinstance(plan, dict) and plan.get("kind") == KIND_BT


def blank(value):
    return not isinstance(value, str) or not value.strip()


def source_problems(plan):
    """(problems, {source id}) of a Build and Test plan's `sources`."""
    out, ids = [], set()
    src = plan.get("sources")
    if not isinstance(src, list) or not src:
        return ["sources must list every point the plan covers: {id: \"<unit>:<point>\", unit, point, title}"], ids
    for i, s in enumerate(src, 1):
        if not isinstance(s, dict):
            out.append(f"source {i} is not an object")
            continue
        unit, point, title = s.get("unit"), s.get("point"), s.get("title")
        if blank(unit) or not isinstance(point, str) or not POINT_ID.match(point):
            out.append(f"source {i}: unit and a point id (V-<n> of a Unit, M-<n> of the stage's own checks) are required")
            continue
        if s.get("id") != f"{unit}:{point}":
            out.append(f"source {i}: id must be {unit}:{point}, not {s.get('id')!r}")
        if (unit == BT_UNIT) != point.startswith("M-"):
            out.append(f"source {s.get('id')}: M points belong to {BT_UNIT} and V points to a Unit")
        if blank(title) or len(title) > LINE_MAX:
            out.append(f"source {s.get('id')}: title is one line of at most {LINE_MAX} characters")
        if s.get("id") in ids:
            out.append(f"source {s.get('id')} is listed twice")
        ids.add(s.get("id"))
    return out, ids


def problems_of(plan, bundle, deferred=None):
    """The problems of a plan. A Build and Test plan has no bundle; `deferred` (optional) is the [{id, ...}] the Units
    recorded: each must be in the plan's sources."""
    out = []
    if not isinstance(plan, dict):
        return ["the plan is not a JSON object"]
    bt = is_bt(plan)
    if plan.get("schema") != SCHEMA:
        out.append(f"schema must be {SCHEMA}")
    if plan.get("kind") is not None and not bt:
        out.append(f"kind is absent (a Unit's plan) or \"{KIND_BT}\"")
    if not isinstance(plan.get("id"), str) or not PLAN_ID.match(plan["id"]):
        out.append("id must look like <intent>-<unit>-test-v<n>-<YYYYMMDDTHHMM>")
    for field in ("intent", "unit", "title") + (() if bt else ("bundle",)):
        if blank(plan.get(field)):
            out.append(f"{field} is required")
    if bt:
        if plan.get("unit") != BT_UNIT:
            out.append(f"unit must be {BT_UNIT} in a Build and Test plan")
        if plan.get("bundle"):
            out.append("a Build and Test plan has no bundle (leave it out): its points are named in sources")
        found, rows = source_problems(plan)
        out += found
        for d in deferred or []:
            if d not in rows:
                out.append(f"{d} was deferred to Build and Test but is not in the plan's sources")
        pattern = None
    else:
        if isinstance(bundle, dict) and plan.get("bundle") and plan["bundle"] != bundle.get("id"):
            out.append(f"bundle must be the unit-end bundle's id ({bundle.get('id')})")
        rows = {r["id"] for r in unverified_rows(bundle or {})}
        pattern = ROW_ID
    now = plan.get("now")
    if not isinstance(now, list) or not now or not all(isinstance(x, str) for x in now):
        out.append("now must list the " + ("source ids" if bt else "V rows") + " the plan covers")
        now = []
    for rid in now:
        if bt and rid not in rows:
            out.append(f"now names {rid}, which is not in the plan's sources")
        elif not bt and (not pattern.match(rid) or rid not in rows):
            out.append(f"now names {rid}, which is not a not-verified row of the unit-end page")
    if len(set(now)) != len(now):
        out.append("now lists a row twice")
    if not isinstance(plan.get("allByDefault"), bool):
        out.append("allByDefault must be true or false")
    sections = plan.get("sections")
    if not isinstance(sections, list) or not sections:
        out.append("the plan needs at least one section")
        return out
    covered, seen = set(), set()
    for i, sec in enumerate(sections):
        want = chr(ord("A") + i) if i < 26 else None
        if not isinstance(sec, dict):
            out.append(f"section {i + 1} is not an object")
            continue
        key = sec.get("key")
        if key != want:
            out.append(f"section {i + 1} must be keyed {want}, not {key!r} (A, B, C … in order)")
        for field, size in (("title", LINE_MAX), ("agent", TEXT_MAX)):
            v = sec.get(field)
            if blank(v):
                out.append(f"section {key}: {field} is required" + (" (what the agent does first)" if field == "agent" else ""))
            elif size == LINE_MAX and ("\n" in v or len(v) > size):
                out.append(f"section {key}: title is one line of at most {size} characters")
            elif len(v) > size:
                out.append(f"section {key}: {field} is over {size} characters")
        agent = sec.get("agent")
        if i > 0 and isinstance(agent, str) and IDLE_AGENT.search(agent):
            out.append(f"section {key}: its agent step does nothing (\"{agent.strip()}\"). A new section starts only where you must do something first; "
                       f"move its steps to the end of section A (as A.{len(sections[0].get('steps') or []) + 1}, …), keeping their verifies.")
        steps = sec.get("steps")
        if not isinstance(steps, list) or not steps:
            out.append(f"section {key}: needs at least one developer step")
            continue
        for j, st in enumerate(steps, 1):
            if not isinstance(st, dict):
                out.append(f"section {key}: step {j} is not an object")
                continue
            sid = st.get("id")
            if sid != f"{key}.{j}":
                out.append(f"section {key}: step {j} must have id {key}.{j}, not {sid!r}")
            if sid in seen:
                out.append(f"step id {sid} is used twice")
            seen.add(sid)
            if blank(st.get("do")):
                out.append(f"step {sid}: do is required (what to do)")
            elif len(st["do"]) > TEXT_MAX:
                out.append(f"step {sid}: do is over {TEXT_MAX} characters")
            if st.get("expect") is not None and (not isinstance(st["expect"], str) or len(st["expect"]) > TEXT_MAX):
                out.append(f"step {sid}: expect is a text of at most {TEXT_MAX} characters")
            crit = st.get("criteria")
            if not isinstance(crit, list) or not crit:
                out.append(f"step {sid}: criteria is required (at least one short checkable sentence; they are numbered {sid}.1, {sid}.2 …)")
            else:
                for n, c in enumerate(crit, 1):
                    if blank(c):
                        out.append(f"step {sid}: criterion {sid}.{n} is empty")
                    elif len(c) > LINE_MAX:
                        out.append(f"step {sid}: criterion {sid}.{n} is over {LINE_MAX} characters (a short checkable sentence)")
            ver = st.get("verifies")
            if not isinstance(ver, list) or not ver or not all(isinstance(x, str) for x in ver):
                out.append(f"step {sid}: verifies must name at least one V row")
                continue
            for rid in ver:
                if rid not in now:
                    out.append(f"step {sid}: verifies {rid}, which is not one of the rows the plan covers")
                covered.add(rid)
    for rid in now:
        if rid not in covered:
            out.append(f"{rid} is to be tested now but no step verifies it")
    return out


def stamp():
    return datetime.datetime.now(datetime.timezone.utc)


def criteria_of(st):
    """{"A.1.1": "text", …} of a step; empty for a plan published without criteria."""
    return {f"{st['id']}.{n}": c for n, c in enumerate(st.get("criteria") or [], 1)}


def failed_ids(st, r):
    """The criterion ids a failure names: those the results give, else none known."""
    return [x for x in (r.get("failed") or []) if x in criteria_of(st)] if r.get("result") == "fail" else []


def step_list(plan):
    return [st for sec in plan["sections"] for st in sec["steps"]]


def results_problems(plan, results):
    out = []
    if not isinstance(results, dict):
        return ["the results are not a JSON object"]
    for st in step_list(plan):
        r = results.get(st["id"])
        if not isinstance(r, dict) or r.get("result") not in ("pass", "fail"):
            note = r.get("note") if isinstance(r, dict) else None
            out.append(f"step {st['id']} has no Pass or Fail yet (not run" + (f", note: {note.strip()}" if not blank(note) else "") + ")")
        elif r["result"] == "fail" and blank(r.get("note")):
            out.append(f"step {st['id']} failed with no note")
        elif r["result"] == "fail" and r.get("failed") is not None:
            ids = criteria_of(st)
            bad = [x for x in r["failed"] if x not in ids] if isinstance(r["failed"], list) else ["?"]
            if bad:
                out.append(f"step {st['id']}: failed names {', '.join(map(str, bad))}, which are not its criteria")
    return out


def outcome_of(plan, results, bundle, fix=None):
    """The per-row outcome. `fix` is None (not decided yet) or the set of failed step ids the developer wants fixed."""
    rows = {}
    for st in step_list(plan):
        r = results[st["id"]]
        for rid in st["verifies"]:
            row = rows.setdefault(rid, {"state": "passed", "steps": [], "notes": []})
            row["steps"].append(st["id"])
            if r["result"] == "fail":
                row["state"] = "failed"
            if (r.get("note") or "").strip():
                named = failed_ids(st, r)
                label = st["id"] + (f" ({', '.join(named)})" if named else "")
                row["notes"].append(f"{label} {'failed' if r['result'] == 'fail' else 'passed'}: {r['note'].strip()}")
    if fix is not None:
        for rid, row in rows.items():
            if row["state"] == "failed":
                row["decision"] = "fix" if any(s in fix and results[s]["result"] == "fail" for s in row["steps"]) else "left"
    if is_bt(plan):
        for src in plan["sources"]:
            if src["id"] in rows:
                rows[src["id"]].update(unit=src["unit"], point=src["point"])
        return {"schema": OUTCOME_SCHEMA, "kind": KIND_BT, "plan": plan["id"], "unit": plan["unit"], "intent": plan["intent"],
                "rows": rows}
    for r in unverified_rows(bundle):
        if r["id"] not in rows:
            rows[r["id"]] = {"state": "later", "steps": [], "notes": []}
    return {"schema": OUTCOME_SCHEMA, "plan": plan["id"], "unit": plan["unit"], "intent": plan["intent"],
            "bundle": plan["bundle"], "rows": rows}


def markdown(plan, results, outcome, bundle, date):
    bt = is_bt(plan)
    if bt:
        titles = {s["id"]: f"{s['unit']} {s['point']} {s['title']}" for s in plan["sources"]}
        lines = [f"# Build and Test plan: {plan['title']}", "", f"- Stage: Build and Test", f"- Date: {date}", f"- Plan: {plan['id']}"]
    else:
        titles = {r["id"]: r["title"] for r in unverified_rows(bundle)}
        lines = [f"# Test plan: {plan['title']}", "", f"- Unit: {plan['unit']}", f"- Date: {date}",
                 f"- Unit-end page tested: {plan['bundle']}", f"- Plan: {plan['id']}"]
    if plan.get("allByDefault") and not bt:
        lines.append("- Nothing was picked Test now, so every not-verified point is covered.")
    lines += ["", "## Results", ""]
    for sec in plan["sections"]:
        lines += [f"### {sec['key']}. {sec['title']}", "", f"Agent step: {sec['agent']}", ""]
        for st in sec["steps"]:
            r = results[st["id"]]
            lines += [f"- **{st['id']}** {'PASS' if r['result'] == 'pass' else 'FAIL'}: {st['do']}",
                      ]
            crit = criteria_of(st)
            if st.get("expect") and not crit:
                lines.append(f"  - Expected: {st['expect']}")
            named = failed_ids(st, r)
            for cid, text in crit.items():
                lines.append(f"  - {cid}{' FAIL' if cid in named else ''}: {text}")
            if r["result"] == "fail":
                lines.append(f"  - Failed criteria: {', '.join(named) if named else 'not named (the step failed as a whole)'}")
            lines.append(f"  - Verifies: {', '.join(st['verifies'])}")
            if (r.get("note") or "").strip():
                lines.append(f"  - Note: {r['note'].strip()}")
        lines.append("")
    lines += ["## Not-verified points", ""]
    names = {"passed": "Verified by you", "failed": "Failed", "later": "Still not verified (Later)"}
    for rid in sorted(outcome["rows"], key=(lambda x: list(titles).index(x)) if bt else (lambda x: int(x.split("-")[1]))):
        row = outcome["rows"][rid]
        extra = {"fix": " (to be fixed)", "left": " (left as known)"}.get(row.get("decision"), "")
        lines.append(f"- {rid} {titles.get(rid, '')}: {names[row['state']]}{extra}")
    lines.append("")
    return "\n".join(lines)


def project_of(args):
    return os.path.abspath(getattr(args, "project_dir", None) or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def read_input(args):
    """(plan, bundle, deferred): a Build and Test plan has no bundle; `deferred` is the source ids the Units recorded
    (only when --project-dir is given and the project has an active intent)."""
    plan = load_json(args.plan)
    if is_bt(plan):
        deferred = None
        if args.project_dir:
            deferred = [f"{u['unit']}:{p['id']}" for u in collect(project_of(args))["units"] for p in u["points"] if p["choice"] == BUILDTEST_PICK]
        return plan, None, deferred
    if not args.bundle:
        raise PlanError("--bundle is required for a Unit's test plan")
    bundle = load_json(args.bundle)
    if not isinstance(bundle, dict) or bundle.get("page") != "unit-end":
        raise PlanError(f"{args.bundle} is not a unit-end bundle")
    return plan, bundle, None


def deferral_path(unit_obj):
    return os.path.join(unit_obj.stage_folder("code-generation"), DEFERRED_FILE)


def cmd_now(args):
    bundle = load_json(args.bundle)
    picks = load_json(args.picks_file) if args.picks_file else {}
    if isinstance(picks, dict) and isinstance(picks.get("picks"), dict):
        picks = picks["picks"]
    now, default = now_rows(bundle, picks)
    if not now:
        raise PlanError("the unit-end page has no not-verified rows to test here (none, or all are picked At Build and Test), so there is nothing to test")
    print(json.dumps({"now": now, "allByDefault": default}))
    return 0


def cmd_defer(args):
    """Record the Unit's not-verified points: those picked At Build and Test (or all, with --all) as deferred, the
    rest as still not verified. Run when the Unit is approved."""
    bundle = load_json(args.bundle)
    if not isinstance(bundle, dict) or bundle.get("page") != "unit-end":
        raise PlanError(f"{args.bundle} is not a unit-end bundle")
    picks = load_json(args.picks_file) if args.picks_file else {}
    if isinstance(picks, dict) and isinstance(picks.get("picks"), dict):
        picks = picks["picks"]
    rows = unverified_rows(bundle)
    if not rows:
        raise PlanError("the unit-end page has no not-verified rows, so nothing is deferred")
    points = [{"id": r["id"], "title": r["title"], "body": r.get("body", ""),
               "choice": BUILDTEST_PICK if args.all or (picks or {}).get(validate_bundle.anchor(r["id"])) == BUILDTEST_PICK else "later"}
              for r in rows]
    header = bundle.get("header") or {}
    unit = args.unit or header.get("unit")
    intent = header.get("intent")
    if args.stage_dir:
        folder = args.stage_dir
    else:
        import unit_bundle
        u = unit_bundle.Unit(project_of(args), unit)
        folder, unit, intent = u.stage_folder("code-generation"), u.unit, intent or u.intent
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, DEFERRED_FILE)
    record = {"schema": DEFERRED_SCHEMA, "intent": intent, "unit": unit, "bundle": bundle.get("id"),
              "date": stamp().strftime("%Y-%m-%d"), "points": points}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(json.dumps({"file": path, "deferred": [p["id"] for p in points if p["choice"] == BUILDTEST_PICK],
                      "stillNotVerified": [p["id"] for p in points if p["choice"] != BUILDTEST_PICK]}))
    return 0


def construction_folder(project):
    import gate_bundle
    _space, intent, root = gate_bundle.record_root(project)
    return intent, os.path.join(root, "construction")


def collect(project):
    """{intent, stageDir, units: [{unit, file, points: [{id, title, body, choice, state?}]}]}: the deferral records of
    every Unit of the active intent. `choice` is "buildtest" (deferred) or "later" (still not verified)."""
    intent, construction = construction_folder(project)
    units = []
    for name in sorted(os.listdir(construction)) if os.path.isdir(construction) else []:
        path = os.path.join(construction, name, "code-generation", DEFERRED_FILE)
        if not os.path.isfile(path):
            continue
        rec = load_json(path)
        if not isinstance(rec, dict) or rec.get("schema") != DEFERRED_SCHEMA or not isinstance(rec.get("points"), list):
            raise PlanError(f"{path} is not a deferral record ({DEFERRED_SCHEMA})")
        units.append({"unit": rec.get("unit") or name, "file": path, "points": rec["points"]})
    return {"intent": intent, "stageDir": os.path.join(construction, "build-and-test"), "units": units}


def cmd_collect(args):
    found = collect(project_of(args))
    if not any(u["points"] for u in found["units"]):
        raise PlanError("no Unit recorded a deferred point (deferred-to-build-and-test.json in its code-generation folder)")
    print(json.dumps(found, ensure_ascii=False))
    return 0


def cmd_validate(args):
    plan, bundle, deferred = read_input(args)
    problems = problems_of(plan, bundle, deferred)
    if problems:
        print("\n".join(problems))
        print(f"test_plan.py: the plan does not hold ({len(problems)} problem(s)); fix {args.plan} and run it again", file=sys.stderr)
        return 1
    print(json.dumps({"id": plan["id"], "sections": len(plan["sections"]), "steps": len(step_list(plan)), "now": plan["now"]}))
    return 0


def cmd_publish(args):
    plan, bundle, deferred = read_input(args)
    problems = problems_of(plan, bundle, deferred)
    if problems:
        print("\n".join(problems))
        print(f"test_plan.py: the plan does not hold ({len(problems)} problem(s)); fix {args.plan} and run it again", file=sys.stderr)
        return 1
    if is_bt(plan):
        titles = {s["id"]: s["title"] for s in plan["sources"] if s["id"] in plan["now"]}
    else:
        titles = {r["id"]: r["title"] for r in unverified_rows(bundle) if r["id"] in plan["now"]}
    row = {"plan": dict(plan, rows=titles), "intent": plan["intent"], "unit": plan["unit"], "title": plan["title"],
           "createdAt": plan.get("createdAt") or stamp().isoformat().replace("+00:00", "Z"), "status": "open", "agentDone": []}
    os.makedirs(args.out, exist_ok=True)
    row_path, writes_path = os.path.join(args.out, "row.json"), os.path.join(args.out, "writes.json")
    with open(row_path, "w", encoding="utf-8") as f:
        json.dump(row, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(writes_path, "w", encoding="utf-8") as f:
        json.dump([{"op": "set", "collection": "plans", "doc_id": plan["id"], "file_path": os.path.abspath(row_path)}], f, indent=2)
        f.write("\n")
    print(json.dumps({"id": plan["id"], "row": os.path.abspath(row_path), "writes": os.path.abspath(writes_path)}))
    return 0


def stage_dir_of(args, plan):
    if args.stage_dir:
        return args.stage_dir
    if is_bt(plan):
        return collect_stage_dir(project_of(args))
    import unit_bundle
    return unit_bundle.Unit(project_of(args), plan["unit"]).stage_folder("code-generation")


def collect_stage_dir(project):
    return os.path.join(construction_folder(project)[1], "build-and-test")


def write_unit_outcomes(plan, outcome, results, project, date):
    """Per Unit, build-and-test-outcome.json in its code-generation folder: the rows of that Unit's points, keyed by
    V id, in the shape `unit_bundle.py draft --tested` reads. The Unit's deferral record gets each point's state."""
    _intent, construction = construction_folder(project)
    written = []
    for unit in sorted({s["unit"] for s in plan["sources"] if s["unit"] != BT_UNIT}):
        folder = os.path.join(construction, unit, "code-generation")
        mine = {s["point"]: outcome["rows"][s["id"]] for s in plan["sources"] if s["unit"] == unit and s["id"] in outcome["rows"]}
        if not mine:
            continue
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, BT_OUTCOME_FILE)
        rows = {pid: {k: v for k, v in row.items() if k not in ("unit", "point")} for pid, row in mine.items()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"schema": OUTCOME_SCHEMA, "plan": plan["id"], "unit": unit, "intent": plan["intent"], "bundle": None,
                       "fromBuildAndTest": True, "rows": rows, "date": date}, f, indent=2, ensure_ascii=False)
            f.write("\n")
        rec_path = os.path.join(folder, DEFERRED_FILE)
        if os.path.isfile(rec_path):
            rec = load_json(rec_path)
            for p in rec.get("points") or []:
                if p.get("id") in rows:
                    p["state"] = rows[p["id"]]["state"]
            with open(rec_path, "w", encoding="utf-8") as f:
                json.dump(rec, f, indent=2, ensure_ascii=False)
                f.write("\n")
        written.append(path)
    return written


def cmd_finish(args):
    plan, bundle, deferred = read_input(args)
    problems = problems_of(plan, bundle, deferred)
    results = load_json(args.results)
    if isinstance(results, dict) and isinstance(results.get("results"), dict):
        results = results["results"]
    problems += results_problems(plan, results)
    if problems:
        print("\n".join(problems))
        print("test_plan.py: the test plan is not complete; go back to the page", file=sys.stderr)
        return 1
    fix = None
    if args.fix is not None:
        fix = set() if args.fix.strip().lower() == "none" else {x.strip() for x in args.fix.split(",") if x.strip()}
        known = {s["id"] for s in step_list(plan) if results[s["id"]]["result"] == "fail"}
        if fix - known:
            raise PlanError(f"--fix names {', '.join(sorted(fix - known))}, which did not fail")
    outcome = outcome_of(plan, results, bundle, fix)
    folder = stage_dir_of(args, plan)
    os.makedirs(folder, exist_ok=True)
    date = stamp().strftime("%Y-%m-%d")
    md, js = os.path.join(folder, "test-plan.md"), os.path.join(folder, "test-plan.json")
    with open(md, "w", encoding="utf-8") as f:
        f.write(markdown(plan, results, outcome, bundle, date))
    with open(js, "w", encoding="utf-8") as f:
        json.dump(dict(outcome, results=results, date=date), f, indent=2, ensure_ascii=False)
        f.write("\n")
    failed = [{"step": st["id"], "verifies": st["verifies"], "do": st["do"], "note": results[st["id"]]["note"].strip()}
              for st in step_list(plan) if results[st["id"]]["result"] == "fail"]
    count = lambda state: sorted(r for r, v in outcome["rows"].items() if v["state"] == state)  # noqa: E731
    units = write_unit_outcomes(plan, outcome, results, project_of(args), date) if is_bt(plan) else []
    print(json.dumps({"markdown": md, "outcome": js, "unitOutcomes": units, "passedRows": count("passed"), "failedRows": count("failed"),
                      "laterRows": count("later"), "failedSteps": failed, "decided": fix is not None}, ensure_ascii=False))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="test_plan.py", description="The test plan of a Unit's not-verified points.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("now")
    n.add_argument("--bundle", required=True)
    n.add_argument("--picks-file")
    d = sub.add_parser("defer")
    d.add_argument("--bundle", required=True)
    d.add_argument("--picks-file")
    d.add_argument("--all", action="store_true")
    d.add_argument("--unit")
    d.add_argument("--stage-dir")
    d.add_argument("--project-dir")
    c = sub.add_parser("collect")
    c.add_argument("--project-dir")
    for name in ("validate", "publish", "finish"):
        p = sub.add_parser(name)
        p.add_argument("--plan", required=True)
        p.add_argument("--bundle")
        p.add_argument("--project-dir")
        if name == "publish":
            p.add_argument("--out", required=True)
        if name == "finish":
            p.add_argument("--results", required=True)
            p.add_argument("--stage-dir")
            p.add_argument("--fix")
    args = ap.parse_args(argv)
    try:
        return {"now": cmd_now, "defer": cmd_defer, "collect": cmd_collect, "validate": cmd_validate, "publish": cmd_publish, "finish": cmd_finish}[args.cmd](args)
    except PlanError as why:
        print(f"test_plan.py: {why}", file=sys.stderr)
        return 1
    except Exception as why:  # unit_bundle's own errors (no such Unit)
        if type(why).__name__ in ("BundleError",):
            print(f"test_plan.py: {why}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
