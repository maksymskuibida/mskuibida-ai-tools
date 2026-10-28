"""Tests for scripts/unit_bundle.py: a Unit's plan and unit-end bundles drafted from its stage records, carried over
across revisions, finalized, and rendered by the page under Node.

Two sources of records:
  - the fixture Unit u2-pickup-slots (tests/fixtures/project), always;
  - the real U4 "day navigation" records of the Dayboard workspace, when that checkout is on this machine. They are read
    from its git branch (APPROVAL_GATES_U4_REPO, default ~/dayboard, ref APPROVAL_GATES_U4_REF, default
    origin/unit/u4-day-navigation) into a temporary folder and never copied into this repository; elsewhere (CI) the
    class is skipped.
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from bundle_helpers import NODE, SCRIPTS, agent_pass, render

sys.path.insert(0, SCRIPTS)
import validate_bundle  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "project")
SCRIPT = os.path.join(SCRIPTS, "unit_bundle.py")
UNIT = "u2-pickup-slots"


class Base(unittest.TestCase):
    project_source = FIXTURE

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.project = os.path.join(self.tmp, "project")
        shutil.copytree(self.project_source, self.project)
        self.store = os.path.join(self.tmp, "store")
        self.n = 0

    def run_script(self, *args):
        env = dict(os.environ, APPROVAL_GATES_DIR=self.store, AIDLC_IDS_DIR=os.path.join(self.tmp, "ids"))
        env.pop("CLAUDE_PROJECT_DIR", None)
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=env, timeout=60)

    def draft(self, page="plan", unit=UNIT, *extra):
        self.n += 1
        out = os.path.join(self.tmp, f"draft-{self.n}.json")
        done = self.run_script("draft", "--page", page, "--unit", unit, "--project-dir", self.project, "--out", out, *extra)
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(out, encoding="utf-8") as f:
            return out, json.load(f), json.loads(done.stdout)

    def save(self, path, bundle):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bundle, f)

    def finalize(self, path, ok=True):
        out = os.path.join(self.tmp, f"out-{self.n}")
        done = self.run_script("finalize", "--bundle", path, "--project-dir", self.project, "--out", out)
        if ok:
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            return json.loads(done.stdout)
        self.assertEqual(done.returncode, 1, done.stdout)
        return done.stdout

    def finished(self, page="plan", unit=UNIT):
        path, bundle, _info = self.draft(page, unit)
        self.save(path, agent_pass(bundle))
        info = self.finalize(path)
        with open(info["bundle"], encoding="utf-8") as f:
            return path, json.load(f), info


def rows_of(bundle, key):
    return next(s for s in bundle["sections"] if s["key"] == key)["rows"]


class TestPlanDraft(Base):
    def setUp(self):
        super().setUp()
        _path, self.b, self.info = self.draft()

    def test_header(self):
        h = self.b["header"]
        self.assertEqual((h["unitLabel"], h["unitName"], h["title"]), ("U2", "Pick-up slots", "Unit u2-pickup-slots: Approve plan"))
        self.assertEqual(h["intentName"], "Bakery preorder")
        self.assertEqual(h["lede"], "The slot list with full slots marked, and moving an order to another slot.")
        ran = {s["slug"]: s["ran"] for s in h["stages"]}
        self.assertEqual(ran, {"functional-design": True, "nfr-requirements": True, "nfr-design": False, "infrastructure-design": False})
        self.assertEqual(h["revision"], 1)

    def test_answers_one_group_per_questions_file(self):
        groups = {g["key"]: g for g in self.b["answers"]}
        self.assertEqual(list(groups), ["fd-answers", "nr-answers"])
        fd = groups["fd-answers"]["questions"]
        self.assertEqual([(q["id"], q["answer"], q.get("proposed"), q["anchor"]) for q in fd],
                         [("Q1", "A", "B", "fd-q1"), ("Q2", "A", "A", "fd-q2")])
        self.assertEqual(groups["nr-answers"]["questions"][0]["answer"], "X Within 500 ms on a phone, 200 ms on a laptop")

    def test_every_assumption_of_the_design_and_the_plan(self):
        rows = rows_of(self.b, "assumptions")
        self.assertEqual(len(rows), 4)
        self.assertEqual([r["where"] for r in rows], ["Functional", "Functional", "NFR Req.", "Code plan"])
        self.assertTrue(all(r["label"] is None for r in rows))
        self.assertEqual(rows[0]["title"], "The bakery's clock is the server's clock; a customer in another time zone sees the bakery's times (SR1)")
        sr1 = rows[0]["refs"][0]
        self.assertEqual((sr1["label"], sr1["tip"]), ("SR1", "Slots. The day runs from 07:00 to 10:00 in slots of 15 minutes."))
        self.assertTrue(sr1["target"].startswith("path:aidlc/spaces/default/intents/260101-bakery-preorder/construction/u2-pickup-slots/functional-design/functional-spec.md#SR1"))

    def test_findings_left_open_or_waived_with_what_settles_them(self):
        rows = {r["id"]: r for r in rows_of(self.b, "findings")}
        self.assertEqual(sorted(rows), ["FD R-02", "FD R-03", "NR R-01"])  # FD R-01 was resolved
        self.assertEqual(rows["FD R-02"]["coveredBy"], {"text": "Step 3 settles it", "settled": True})
        self.assertEqual(rows["FD R-03"]["coveredBy"], {"text": "waived by the reviewer", "settled": True})
        self.assertEqual(rows["NR R-01"]["coveredBy"], {"text": "not in the plan", "settled": False})
        self.assertEqual(rows["FD R-02"]["label"], "low")  # a hint from the severity, for the agent to judge

    def test_code_plan_steps(self):
        steps = self.b["plan"]["steps"]
        self.assertEqual([(s["n"], s["layer"], s["files"]) for s in steps], [(1, "setup", 0), (2, "logic", 2), (3, "UI", 2), (4, "tests", 1)])
        self.assertEqual([r["label"] for r in steps[1]["implements"]], ["SR1", "SR2", "SR3"])
        self.assertEqual(len(steps[3]["subs"]), 1, "the plan's later sections are not sub-steps")

    def test_the_sections_left_for_the_agent(self):
        self.assertEqual([s["key"] for s in self.b["sections"] if not s["rows"]], ["narrows", "visible", "tests"])
        todo = " ".join(self.info["todo"])
        for word in ("label 4 row(s)", "`narrows`", "`visible`", "`tests`", "plain words"):
            self.assertIn(word, todo)

    def test_a_draft_does_not_finalize_until_the_agent_did_its_part(self):
        path, _b, _i = self.draft()
        out = self.finalize(path, ok=False)
        self.assertIn("is not one of", out)


class TestPlanStepForms(Base):
    """The code plan's steps, in each form a plan is written in."""

    def plan_with(self, text):
        path = os.path.join(self.project, "aidlc", "spaces", "default", "intents", "260101-bakery-preorder", "construction",
                            UNIT, "code-generation", "code-generation-plan.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return self.draft()

    def test_checkbox_steps_in_bold(self):
        _p, b, info = self.plan_with(
            "# Code plan\n\n## Steps\n\n"
            "- [ ] **Step 1: Slot model and capacity.**\n  - [ ] add `src/slots.py`\n  - [ ] check capacity\n"
            "- [ ] **Step 2: Pickup endpoint.** wire `src/api.py`\n  - [x] return 409 when full\n"
            "- [ ] **Step 3: Tests**\n\n## Notes\n\n  - not a sub-step\n")
        steps = b["plan"]["steps"]
        self.assertEqual([(s["n"], s["title"]) for s in steps],
                         [(1, "Slot model and capacity"), (2, "Pickup endpoint"), (3, "Tests")])
        self.assertEqual([s["text"] for s in steps[0]["subs"]], ["add src/slots.py", "check capacity"])
        self.assertEqual([s["text"] for s in steps[1]["subs"]], ["wire src/api.py", "return 409 when full"])
        self.assertEqual([s["text"] for s in steps[2]["subs"]], ["Tests"], "a step with no sub-items takes its title")
        self.assertEqual(steps[0]["files"], 1)
        self.assertEqual(b["plan"]["hint"].split(" ")[0], "3")

    def test_heading_steps_still_parse(self):
        _p, b, _i = self.plan_with("# Plan\n\n### Step 1: One\n- [ ] a\n- [ ] b\n\n### Step 2 - Two\n- c\n")
        self.assertEqual([(s["n"], s["title"], len(s["subs"])) for s in b["plan"]["steps"]], [(1, "One", 2), (2, "Two", 1)])

    def test_a_draft_of_checkbox_steps_finalizes(self):
        path, b, _i = self.plan_with("# Plan\n\n- [ ] **Step 1: Only step.**\n  - [ ] do it\n")
        self.save(path, agent_pass(b))
        self.finalize(path)

    def test_the_todo_states_what_finalize_enforces(self):
        _p, _b, info = self.plan_with("# Plan\n\n### Step 1: One\n- [ ] a\n")
        todo = " ".join(info["todo"])
        self.assertIn("at least one sub-item", todo)
        self.assertIn("32 characters or fewer", todo)

    def test_finalize_refuses_a_long_fact_value_and_a_step_without_subs(self):
        path, b, _i = self.draft()
        b = agent_pass(b)
        b["header"]["facts"] = [{"label": "Tests", "value": "x" * 33}]
        b["plan"]["steps"][0]["subs"] = []
        self.save(path, b)
        out = self.finalize(path, ok=False)
        self.assertIn("32", out)
        self.assertIn("at least 1 item", out)


class TestFinalize(Base):
    def test_ids_say_what_each_id_of_the_page_is_from_this_units_records(self):
        _path, b, _info = self.finished()
        ids = b["ids"]
        self.assertEqual(ids["SR1"]["doc"], os.path.join("construction", UNIT, "functional-design", "functional-spec.md"))
        self.assertIn("15 minutes", ids["SR1"]["title"] + ids["SR1"].get("text", ""))
        self.assertTrue(all(not d["doc"].startswith(os.path.join("construction", "u1-core")) for d in ids.values()),
                        "never another Unit's definition")
        self.assertEqual(validate_bundle.validate(b), [])

    def test_ids_with_an_unknown_field_are_refused(self):
        _path, b, _info = self.finished()
        b["ids"]["SR1"]["colour"] = "red"
        self.assertTrue(any("unknown field `colour`" in p for p in validate_bundle.validate(b)))
        b["ids"]["SR1"].pop("colour")
        b["ids"]["SR1"].pop("title")
        self.assertTrue(any("`title` is missing" in p for p in validate_bundle.validate(b)))

    def test_writes_one_row_and_keeps_a_copy(self):
        _path, b, info = self.finished()
        self.assertEqual(validate_bundle.validate(b), [])
        with open(info["writes"], encoding="utf-8") as f:
            writes = json.load(f)
        self.assertEqual(len(writes), 1)
        self.assertEqual((writes[0]["op"], writes[0]["collection"], writes[0]["doc_id"]), ("set", "bundles", b["id"]))
        with open(writes[0]["file_path"], encoding="utf-8") as f:
            row = json.load(f)
        self.assertEqual((row["page"], row["unit"], row["status"], row["bundle"]["id"]), ("plan", UNIT, "open", b["id"]))
        self.assertNotIn("notes", row)
        self.assertTrue(os.path.exists(os.path.join(self.store, "bundles", "260101-bakery-preorder", UNIT, "plan-v1.json")))
        self.assertRegex(b["id"], r"^260101-bakery-preorder-u2-pickup-slots-plan-v1-\d{8}T\d{4}$")
        self.assertEqual([f["label"] for f in b["header"]["facts"]], ["Look first", "Design stages", "This plan"])
        self.assertEqual(b["header"]["facts"][1]["value"], "2 of 4 ran")

    def test_a_revision_keeps_the_agents_rows_and_marks_only_what_changed(self):
        _path, v1, _info = self.finished()
        path, d2, info = self.draft()
        self.assertEqual((d2["header"]["revision"], info["carriedFrom"]), (2, v1["id"]))
        self.assertEqual(rows_of(d2, "assumptions")[0]["label"], "high", "the agent's label came back")
        self.assertEqual(rows_of(d2, "narrows")[0]["id"], "N-1", "a hand-written row came back")
        self.assertNotIn("`narrows`", " ".join(info["todo"]))
        rows_of(d2, "assumptions")[1]["body"] = "Eight orders per slot every day, Saturdays included."
        d2["plan"]["steps"][1]["subs"].append({"text": "A move into a slot that just filled is refused."})
        d2["header"]["revisions"][-1]["note"] = "after your note on A-2"
        self.save(path, d2)
        out = self.finalize(path, ok=False)
        self.assertIn("row A-2", out)
        self.assertIn("step 2", out)
        rows_of(d2, "assumptions")[1]["revNote"] = "Changed in v2: Saturdays too."
        d2["plan"]["steps"][1]["revNote"] = "Changed in v2: a move into a full slot."
        self.save(path, d2)
        info = self.finalize(path)
        with open(info["bundle"], encoding="utf-8") as f:
            v2 = json.load(f)
        marked = {r["id"]: (r.get("rev"), r.get("revKind")) for s in v2["sections"] for r in s["rows"] if r.get("rev")}
        self.assertEqual(marked, {"A-2": (2, "changed")})
        step = v2["plan"]["steps"][1]
        self.assertEqual((step["rev"], [s.get("rev") for s in step["subs"]]), (2, [None, None, 2]))
        self.assertEqual([r["n"] for r in v2["header"]["revisions"]], [1, 2])

    def test_a_changed_record_asks_for_the_label_again(self):
        self.finished()
        spec = os.path.join(self.project, "aidlc/spaces/default/intents/260101-bakery-preorder/construction", UNIT, "functional-design/functional-spec.md")
        with open(spec, encoding="utf-8") as f:
            text = f.read()
        with open(spec, "w", encoding="utf-8") as f:
            f.write(text.replace("a busier Saturday comes later", "Saturdays hold twelve"))
        _path, d2, info = self.draft()
        a2 = rows_of(d2, "assumptions")[1]
        self.assertIsNone(a2["label"])
        self.assertIn("Saturdays hold twelve", a2["body"])
        self.assertIn("A-2", " ".join(info["todo"]))

    def test_an_assumption_added_in_front_takes_a_new_id(self):
        _p, v1, _i = self.finished()
        labels = {r["id"]: (r["label"], r["body"]) for r in rows_of(v1, "assumptions")}
        spec = os.path.join(self.project, "aidlc/spaces/default/intents/260101-bakery-preorder/construction", UNIT, "functional-design/functional-spec.md")
        with open(spec, encoding="utf-8") as f:
            text = f.read()
        with open(spec, "w", encoding="utf-8") as f:
            f.write(text.replace("## Assumptions & Open Questions\n\n", "## Assumptions & Open Questions\n\n- [assumption] Pick-up is at the shop only.\n"))
        path, d2, _info = self.draft()
        rows = rows_of(d2, "assumptions")
        ids = [r["id"] for r in rows]
        self.assertEqual(len(ids), len(set(ids)), ids)
        for r in rows:
            if r["id"] in labels and r["body"] == labels[r["id"]][1]:
                self.assertEqual(r["label"], labels[r["id"]][0], "a carried row keeps the agent's label")
        new = next(r for r in rows if r["body"] == "Pick-up is at the shop only.")
        self.assertEqual((new["id"], new["label"]), ("A-5", None))
        new.update(label="low", revNote="New in v2: pick-up at the shop only.")
        d2["header"]["revisions"][-1]["note"] = "one more assumption"
        self.save(path, d2)
        info = self.finalize(path)
        with open(info["bundle"], encoding="utf-8") as f:
            marked = {r["id"]: r.get("revKind") for r in rows_of(json.load(f), "assumptions") if r.get("rev")}
        self.assertEqual(marked, {"A-5": "new"})

    def test_a_revision_without_its_previous_presentation_is_refused(self):
        self.finished()
        path, d2, _info = self.draft()
        self.save(path, agent_pass(d2))
        shutil.rmtree(os.path.join(self.store, "bundles"))
        out = self.run_script("finalize", "--bundle", path, "--out", os.path.join(self.tmp, "o"))
        self.assertEqual(out.returncode, 1)
        self.assertIn("pass it with --previous", out.stderr)

    def test_unit_end_title(self):
        self.finished()
        _path, end, _info = self.finished("unit-end")
        self.assertEqual(end["header"]["title"], f"Unit {UNIT}: Approve Unit-end")

    def test_unit_end_page_folds_the_approved_plan(self):
        _p, plan, _i = self.finished()
        _path, end, _info = self.finished("unit-end")
        self.assertEqual([s["key"] for s in end["sections"]], ["changes", "unverified", "built"])
        self.assertEqual(rows_of(end, "changes")[0]["title"], "Moving closes at 20:00: the baker asked for an hour more to plan the dough")
        self.assertEqual(rows_of(end, "unverified")[0]["title"], "The 500 ms target on a real phone")
        built = rows_of(end, "built")
        self.assertEqual([(r["id"], r["where"]) for r in built], [("B-1", "src/slots/rules.ts"), ("B-2", "src/slots/SlotList.tsx")])
        self.assertEqual(end["design"]["bundle"], plan["id"])
        self.assertEqual(len(end["design"]["rows"]), sum(len(s["rows"]) for s in plan["sections"]))
        self.assertEqual(end["design"]["rows"][0]["label"], "high", "the folded design is sorted by label")
        self.assertEqual(validate_bundle.order(end), ["built", "changes", "unverified", "design"])

    def test_unit_end_needs_the_plan_page_first(self):
        done = self.run_script("draft", "--page", "unit-end", "--unit", UNIT, "--project-dir", self.project, "--out", os.path.join(self.tmp, "x.json"))
        self.assertEqual(done.returncode, 1)
        self.assertIn("approved plan page", done.stderr)

    def test_a_unit_without_a_folder(self):
        done = self.run_script("draft", "--page", "plan", "--unit", "u9-none", "--project-dir", self.project, "--out", os.path.join(self.tmp, "x.json"))
        self.assertEqual(done.returncode, 1)
        self.assertIn("no record folder", done.stderr)


@unittest.skipUnless(NODE, "node is not installed")
class TestRender(Base):
    def test_an_old_title_reads_as_what_the_page_is(self):
        _path, b, _info = self.finished()
        b["header"]["title"] = "U2 · Pick-up slots"
        page = render(b)["summary"]
        self.assertIn(f"<h1>Unit {UNIT}: Approve plan</h1>", page)
        self.assertNotIn("<h1>U2 · Pick-up slots</h1>", page)

    def test_the_plan_page_renders(self):
        _path, b, _info = self.finished()
        out = render(b, {"default": {}, "summary": {"mode": "summary"}, "full": {"mode": "full"}, "v1read": {"read": {"A-1": 1}}})
        page = out["summary"]
        self.assertIn("Unit u2-pickup-slots: Approve plan", page)
        for key in ("narrows", "assumptions", "findings", "plan", "tests", "answers"):
            self.assertIn(f'id="{key}"', page)
        self.assertIn('id="FD-R-02"', page)
        self.assertNotIn('class="rowbody"', page, "rows are folded in the Summary view")
        self.assertIn('class="rowbody"', out["default"], "everything starts open")
        read_row = out["v1read"].split('class="row read"', 1)[1].split('class="row', 1)[0]
        self.assertNotIn('class="rowbody"', read_row, "a row marked read stays folded")
        self.assertIn("look first", page)
        self.assertIn("differs from proposal", page)
        self.assertIn("Step 3 settles it", out["full"])
        self.assertIn('<span class="refid">SR1</span>', out["full"], "a design id among the references is left to the shared linker")
        self.assertIn('data-aidlc-id="R-02" data-anchor="FD-R-02"', page, "a folded row's id is still a live link")
        self.assertNotIn('data-aidlc-id="Q1"', page, "Q1 is in two stages' answers: no one row defines it")
        self.assertIn('class="row read"', out["v1read"])
        self.assertEqual(out["order"], validate_bundle.order(b))
        self.assertIn(b["id"], out["list"])

    def test_a_revision_marks_and_filters(self):
        self.finished()
        path, d2, _info = self.draft()
        rows_of(d2, "assumptions")[1].update(body="Changed.", revNote="Changed in v2: Saturdays too.")
        d2["header"]["revisions"][-1]["note"] = "after your note"
        self.save(path, d2)
        info = self.finalize(path)
        with open(info["bundle"], encoding="utf-8") as f:
            v2 = json.load(f)
        out = render(v2, {"read": {"read": {"A-1": 1, "A-2": 1}}, "v2": {"filter": "v2"}})
        self.assertIn("v2 · 1 change (current)", out["read"])
        self.assertIn('class="row read" id="A-1"', out["read"])
        self.assertIn('class="row" id="A-2"', out["read"], "a row changed in v2 turns unread")
        self.assertIn(' id="A-2"', out["v2"])
        self.assertNotIn(' id="A-1"', out["v2"])

    def test_a_steps_read_mark_follows_the_step_not_its_number(self):
        _path, b, _info = self.finished()
        key = b["plan"]["steps"][1]["source"]["key"]
        self.assertTrue(key.startswith("step:"))
        b["plan"]["steps"].insert(0, dict(b["plan"]["steps"][0], title="A new first step", source={"path": "x", "key": "step:new", "digest": "0" * 12}))
        for n, st in enumerate(b["plan"]["steps"], 1):
            st["n"] = n
        page = render(b, {"read": {"read": {key: 1}}})["read"]
        self.assertIn('class="row step read" id="step-3"', page)
        self.assertIn('class="row step" id="step-2"', page)

    def test_bundle_values_cannot_inject_links(self):
        _path, b, _info = self.finished()
        b["header"]["links"] = {"records": "javascript:alert(1)//"}
        b["sections"][2]["rows"][0]["refs"] = [{"label": "x", "tip": "<b>t</b>", "target": "path:a.md"}]
        b["sections"][2]["rows"][0]["rev"] = "1<script>"
        page = render(b, {"full": {"mode": "full"}})["full"]
        self.assertNotIn("javascript:", page)
        self.assertNotIn("<script>", page)
        self.assertNotIn("<b>t</b>", page)

    def test_the_unit_end_page_renders(self):
        self.finished()
        _path, end, _info = self.finished("unit-end")
        end_built = rows_of(end, "built")
        next(s for s in end["sections"] if s["key"] == "built")["map"] = {
            "nodes": [{"id": "r", "title": "Slot rules", "weight": "core", "target": "#B-1"}, {"id": "l", "title": "Slot list", "weight": "main", "target": "#B-2"}],
            "edges": [{"from": "r", "to": "l", "label": "full slots"}]}
        self.assertEqual(validate_bundle.validate(end), [], end_built)
        page = render(end)["summary"]
        self.assertIn("The design you approved", page)
        self.assertIn('class="node core"', page)
        self.assertIn("full slots", page)
        self.assertIn("High and core", page)
        self.assertLess(page.index('id="built"'), page.index('id="design"'))


U4_REPO = os.path.expanduser(os.environ.get("APPROVAL_GATES_U4_REPO", "~/dayboard"))
U4_REF = os.environ.get("APPROVAL_GATES_U4_REF", "origin/unit/u4-day-navigation")
U4_INTENT = "aidlc/spaces/dayboard/intents/261016-daily-page-mvp"


def u4_available():
    if not os.path.isdir(os.path.join(U4_REPO, ".git")) and not os.path.isfile(os.path.join(U4_REPO, ".git")):
        return False
    done = subprocess.run(["git", "-C", U4_REPO, "cat-file", "-e", f"{U4_REF}:{U4_INTENT}/construction/u4-day-navigation"],
                          capture_output=True, text=True)
    return done.returncode == 0


@unittest.skipUnless(u4_available(), f"the Dayboard U4 records are not on this machine ({U4_REPO} {U4_REF})")
class TestRealU4Records(Base):
    """The real U4 records: 4 design stages, 37 record files, 6 stops under per-stage; here 2 pages."""

    @classmethod
    def setUpClass(cls):
        cls.src = tempfile.mkdtemp()
        archive = subprocess.run(["git", "-C", U4_REPO, "archive", U4_REF, f"{U4_INTENT}/construction/u4-day-navigation",
                                  f"{U4_INTENT}/inception", f"{U4_INTENT}/aidlc-state.md", ".claude/tools/data/stage-graph.json"],
                                 capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", cls.src], input=archive.stdout, check=True)
        with open(os.path.join(cls.src, "aidlc", "active-space"), "w") as f:
            f.write("dayboard\n")
        with open(os.path.join(cls.src, "aidlc", "spaces", "dayboard", "intents", "active-intent"), "w") as f:
            f.write("261016-daily-page-mvp\n")
        cls.project_source = cls.src

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.src, ignore_errors=True)

    def test_the_plan_page_from_the_u4_records(self):
        _path, d, _info = self.draft("plan", "u4-day-navigation")
        self.assertEqual((d["header"]["unitLabel"], d["header"]["unitName"]), ("U4", "Moving between days"))
        self.assertTrue(all(s["ran"] for s in d["header"]["stages"]))
        self.assertEqual([(g["title"], len(g["questions"])) for g in d["answers"]],
                         [("Functional Design", 7), ("NFR Requirements", 2), ("NFR Design", 2), ("Infrastructure Design", 1)])
        differ = [(g["key"], q["id"]) for g in d["answers"] for q in g["questions"] if q.get("proposed") and q["answer"][0] != q["proposed"]]
        self.assertEqual(differ, [("fd-answers", "Q3"), ("nr-answers", "Q1")])
        self.assertEqual(len(rows_of(d, "assumptions")), 14)
        findings = {r["id"]: r for r in rows_of(d, "findings")}
        self.assertEqual(sorted(findings), ["FD R-02", "FD R-03", "FD R-04", "FD R-05", "FD R-06", "FD R-07", "ID R-01", "ID R-02", "ID R-03"])
        self.assertEqual(findings["FD R-05"]["coveredBy"]["text"], "Step 7 settles it")
        steps = d["plan"]["steps"]
        self.assertEqual(len(steps), 12)
        self.assertEqual([s["layer"] for s in steps], ["setup", "tests", "data", "tests", "logic", "tests", "UI", "tests", "UI", "tests", "checks", "docs"])
        nr13 = [r for s in steps for r in s["implements"] if r["label"] == "NR13"][0]
        self.assertTrue(nr13["tip"].startswith("Moving."), nr13["tip"])

    def test_both_pages_build_validate_and_render(self):
        _p, plan, info = self.finished("plan", "u4-day-navigation")
        self.assertEqual(validate_bundle.validate(plan), [])
        self.assertEqual(info["rows"], 26)
        _p, end, _i = self.finished("unit-end", "u4-day-navigation")
        self.assertEqual(validate_bundle.validate(end), [])
        self.assertEqual([len(rows_of(end, k)) for k in ("changes", "unverified", "built")], [9, 2, 10])
        if NODE:
            out = render(plan, {"summary": {}, "full": {"mode": "full"}})
            self.assertEqual(out["summary"].count('class="row step'), 12)
            self.assertIn('id="nr-q1"', render(plan, {"open": {"open": {"ans-nr-answers": True}}})["open"])
            self.assertIn("The design you approved", render(end)["summary"])


if __name__ == "__main__":
    unittest.main()
