#!/usr/bin/env python3
"""The test plan of a Unit's not-verified points, for a Unit claimed with the unit-end rhythm.

    test_plan.py now      --bundle <unit-end bundle.json> [--picks-file <picks.json>]
    test_plan.py validate --plan <plan.json> --bundle <unit-end bundle.json>
    test_plan.py publish  --plan <plan.json> --bundle <unit-end bundle.json> --out <dir>
    test_plan.py finish   --plan <plan.json> --results <results.json> --bundle <unit-end bundle.json>
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
PLAN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*-test-v\d+-\d{8}T\d{4}$")
LINE_MAX = 160
TEXT_MAX = 1500


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
    picked = [r["id"] for r in rows if picks.get(validate_bundle.anchor(r["id"])) == "now"]
    return (picked, False) if picked else ([r["id"] for r in rows], True)


def blank(value):
    return not isinstance(value, str) or not value.strip()


def problems_of(plan, bundle):
    out = []
    if not isinstance(plan, dict):
        return ["the plan is not a JSON object"]
    if plan.get("schema") != SCHEMA:
        out.append(f"schema must be {SCHEMA}")
    if not isinstance(plan.get("id"), str) or not PLAN_ID.match(plan["id"]):
        out.append("id must look like <intent>-<unit>-test-v<n>-<YYYYMMDDTHHMM>")
    for field in ("intent", "unit", "bundle", "title"):
        if blank(plan.get(field)):
            out.append(f"{field} is required")
    if isinstance(bundle, dict) and plan.get("bundle") and plan["bundle"] != bundle.get("id"):
        out.append(f"bundle must be the unit-end bundle's id ({bundle.get('id')})")
    rows = {r["id"] for r in unverified_rows(bundle or {})}
    now = plan.get("now")
    if not isinstance(now, list) or not now or not all(isinstance(x, str) for x in now):
        out.append("now must list the V rows the plan covers")
        now = []
    for rid in now:
        if not ROW_ID.match(rid) or rid not in rows:
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
    for r in unverified_rows(bundle):
        if r["id"] not in rows:
            rows[r["id"]] = {"state": "later", "steps": [], "notes": []}
    return {"schema": OUTCOME_SCHEMA, "plan": plan["id"], "unit": plan["unit"], "intent": plan["intent"],
            "bundle": plan["bundle"], "rows": rows}


def markdown(plan, results, outcome, bundle, date):
    titles = {r["id"]: r["title"] for r in unverified_rows(bundle)}
    lines = [f"# Test plan: {plan['title']}", "", f"- Unit: {plan['unit']}", f"- Date: {date}",
             f"- Unit-end page tested: {plan['bundle']}", f"- Plan: {plan['id']}"]
    if plan.get("allByDefault"):
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
    for rid in sorted(outcome["rows"], key=lambda x: int(x.split("-")[1])):
        row = outcome["rows"][rid]
        extra = {"fix": " (to be fixed)", "left": " (left as known)"}.get(row.get("decision"), "")
        lines.append(f"- {rid} {titles.get(rid, '')}: {names[row['state']]}{extra}")
    lines.append("")
    return "\n".join(lines)


def read_input(args):
    plan = load_json(args.plan)
    bundle = load_json(args.bundle)
    if not isinstance(bundle, dict) or bundle.get("page") != "unit-end":
        raise PlanError(f"{args.bundle} is not a unit-end bundle")
    return plan, bundle


def cmd_now(args):
    bundle = load_json(args.bundle)
    picks = load_json(args.picks_file) if args.picks_file else {}
    if isinstance(picks, dict) and isinstance(picks.get("picks"), dict):
        picks = picks["picks"]
    now, default = now_rows(bundle, picks)
    if not now:
        raise PlanError("the unit-end page has no not-verified rows, so there is nothing to test")
    print(json.dumps({"now": now, "allByDefault": default}))
    return 0


def cmd_validate(args):
    plan, bundle = read_input(args)
    problems = problems_of(plan, bundle)
    if problems:
        print("\n".join(problems))
        print(f"test_plan.py: the plan does not hold ({len(problems)} problem(s)); fix {args.plan} and run it again", file=sys.stderr)
        return 1
    print(json.dumps({"id": plan["id"], "sections": len(plan["sections"]), "steps": len(step_list(plan)), "now": plan["now"]}))
    return 0


def cmd_publish(args):
    plan, bundle = read_input(args)
    problems = problems_of(plan, bundle)
    if problems:
        print("\n".join(problems))
        print(f"test_plan.py: the plan does not hold ({len(problems)} problem(s)); fix {args.plan} and run it again", file=sys.stderr)
        return 1
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
    import unit_bundle
    project = os.path.abspath(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    return unit_bundle.Unit(project, plan["unit"]).stage_folder("code-generation")


def cmd_finish(args):
    plan, bundle = read_input(args)
    problems = problems_of(plan, bundle)
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
    print(json.dumps({"markdown": md, "outcome": js, "passedRows": count("passed"), "failedRows": count("failed"),
                      "laterRows": count("later"), "failedSteps": failed, "decided": fix is not None}, ensure_ascii=False))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="test_plan.py", description="The test plan of a Unit's not-verified points.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("now")
    n.add_argument("--bundle", required=True)
    n.add_argument("--picks-file")
    for name in ("validate", "publish", "finish"):
        p = sub.add_parser(name)
        p.add_argument("--plan", required=True)
        p.add_argument("--bundle", required=True)
        if name == "publish":
            p.add_argument("--out", required=True)
        if name == "finish":
            p.add_argument("--results", required=True)
            p.add_argument("--stage-dir")
            p.add_argument("--project-dir")
            p.add_argument("--fix")
    args = ap.parse_args(argv)
    try:
        return {"now": cmd_now, "validate": cmd_validate, "publish": cmd_publish, "finish": cmd_finish}[args.cmd](args)
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
