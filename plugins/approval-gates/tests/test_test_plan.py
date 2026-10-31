"""Tests for the test plan of a Unit's not-verified points: scripts/test_plan.py (validator, publish, finish), the gate
guard letting the Test first answer through, the unit-end page split after testing, and the two pages under Node.
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

from bundle_helpers import NODE, PAGE, PLUGIN, SCRIPTS
from test_gate_guard import URL, gate_question
from test_unit_bundle import Base, UNIT, rows_of
from test_unit_rhythm_guard import UnitCase

sys.path.insert(0, SCRIPTS)
import test_plan  # noqa: E402
import validate_bundle  # noqa: E402

PLAN_PAGE = os.path.join(PLUGIN, "skills", "approval-gates", "test-plan.html")
END_QUESTION = "Unit complete. How would you like to proceed?"


def end_bundle(rows=("V-1", "V-2", "V-3")):
    return {"id": "bakery-u2-unit-end-v1-20260101T0900", "page": "unit-end",
            "sections": [{"key": "unverified", "kind": "unverified", "rows": [{"id": r, "title": f"Point {r}"} for r in rows]}]}


def good_plan(now=("V-1", "V-2", "V-3")):
    return {"schema": "aidlc-test-plan/1", "id": "bakery-u2-test-v1-20260101T1000", "intent": "bakery", "unit": "u2",
            "bundle": "bakery-u2-unit-end-v1-20260101T0900", "title": "Unit u2: test plan", "now": list(now), "allByDefault": False,
            "sections": [
                {"key": "A", "title": "Run the app", "agent": "Start the dev server on port 3000.",
                 "steps": [{"id": "A.1", "do": "Open the slot list.", "criteria": ["Full slots are greyed out.", "Free slots are clickable."], "verifies": ["V-1", "V-2"]},
                           {"id": "A.2", "do": "Move an order.", "criteria": ["It lands in the new slot."], "verifies": ["V-2"]}]},
                {"key": "B", "title": "Reset the data", "agent": "Wipe and seed the test database.",
                 "steps": [{"id": "B.1", "do": "Reload.", "criteria": ["The list is back to the seed."], "verifies": ["V-3"]}]}]}


class TestPlanValidator(unittest.TestCase):
    def problems(self, plan=None, bundle=None):
        return test_plan.problems_of(plan or good_plan(), bundle or end_bundle())

    def test_a_good_plan_holds(self):
        self.assertEqual(self.problems(), [])

    def test_every_test_now_row_must_be_covered(self):
        plan = good_plan()
        plan["sections"][1]["steps"][0]["verifies"] = ["V-2"]
        self.assertIn("V-3 is to be tested now but no step verifies it", self.problems(plan))

    def test_a_step_cannot_verify_a_row_outside_the_plan(self):
        plan = good_plan(now=("V-1", "V-2", "V-3"))
        plan["now"] = ["V-1", "V-2"]
        self.assertTrue(any("V-3, which is not one of the rows the plan covers" in p for p in self.problems(plan)))

    def test_now_must_name_rows_of_the_unit_end_page(self):
        plan = good_plan(now=("V-1", "V-2", "V-3", "V-9"))
        plan["sections"][1]["steps"][0]["verifies"] = ["V-3", "V-9"]
        self.assertTrue(any("V-9, which is not a not-verified row" in p for p in self.problems(plan)))

    def test_sections_and_steps_are_numbered_in_order(self):
        plan = good_plan()
        plan["sections"][1]["key"] = "C"
        plan["sections"][0]["steps"][1]["id"] = "A.3"
        found = "\n".join(self.problems(plan))
        self.assertIn("section 2 must be keyed B", found)
        self.assertIn("step 2 must have id A.2", found)

    def test_a_section_needs_its_agent_step_and_every_step_its_shape(self):
        plan = good_plan()
        plan["sections"][0]["agent"] = " "
        del plan["sections"][0]["steps"][0]["criteria"]
        plan["sections"][1]["steps"][0]["verifies"] = []
        found = "\n".join(self.problems(plan))
        self.assertIn("section A: agent is required", found)
        self.assertIn("step A.1: criteria is required", found)
        self.assertIn("step B.1: verifies must name at least one V row", found)

    def test_empty_criteria_are_refused_and_an_old_plan_with_only_expect_is_not_a_good_new_one(self):
        plan = good_plan()
        plan["sections"][0]["steps"][0]["criteria"] = []
        plan["sections"][0]["steps"][1]["criteria"] = ["ok", " "]
        found = "\n".join(self.problems(plan))
        self.assertIn("step A.1: criteria is required", found)
        self.assertIn("step A.2: criterion A.2.2 is empty", found)
        plan = good_plan()
        del plan["sections"][1]["steps"][0]["criteria"]
        plan["sections"][1]["steps"][0]["expect"] = "old style"
        self.assertEqual(self.problems(plan), ["step B.1: criteria is required (at least one short checkable sentence; they are numbered B.1.1, B.1.2 …)"])

    def test_a_plan_of_another_page_is_refused(self):
        plan = good_plan()
        plan["bundle"] = "bakery-u2-unit-end-v9-20260101T0900"
        self.assertTrue(any("bundle must be the unit-end bundle's id" in p for p in self.problems(plan)))

    def test_the_pick_decides_what_is_tested(self):
        bundle = end_bundle()
        self.assertEqual(test_plan.now_rows(bundle, {"V-2": "now", "V-3": "later"}), (["V-2"], False))
        self.assertEqual(test_plan.now_rows(bundle, {"V-1": "later"}), (["V-1", "V-2", "V-3"], True))

    def test_results_need_a_note_on_a_fail(self):
        plan = good_plan()
        results = {s["id"]: {"result": "pass", "note": ""} for sec in plan["sections"] for s in sec["steps"]}
        self.assertEqual(test_plan.results_problems(plan, results), [])
        results["A.2"] = {"result": "fail", "note": " "}
        del results["B.1"]
        found = test_plan.results_problems(plan, results)
        self.assertEqual(found, ["step A.2 failed with no note", "step B.1 has no Pass or Fail yet"])


class TestScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def file(self, name, value):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(value, f)
        return path

    def run_script(self, *args):
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, "test_plan.py"), *args], capture_output=True, text=True, timeout=60)

    def test_publish_writes_the_plan_row_and_refuses_a_bad_plan(self):
        bundle = self.file("bundle.json", end_bundle())
        out = os.path.join(self.tmp.name, "out")
        done = self.run_script("publish", "--plan", self.file("plan.json", good_plan()), "--bundle", bundle, "--out", out)
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(os.path.join(out, "writes.json"), encoding="utf-8") as f:
            write = json.load(f)[0]
        self.assertEqual((write["op"], write["collection"], write["doc_id"]), ("set", "plans", good_plan()["id"]))
        with open(write["file_path"], encoding="utf-8") as f:
            row = json.load(f)
        self.assertEqual((row["status"], row["agentDone"], row["plan"]["rows"]["V-1"]), ("open", [], "Point V-1"))
        self.assertNotIn("results", row)
        bad = good_plan()
        bad["sections"][0]["agent"] = ""
        done = self.run_script("publish", "--plan", self.file("bad.json", bad), "--bundle", bundle, "--out", out)
        self.assertEqual(done.returncode, 1)
        self.assertIn("section A: agent is required", done.stdout)

    def test_finish_writes_the_markdown_and_the_outcome(self):
        bundle = self.file("bundle.json", end_bundle(("V-1", "V-2", "V-3", "V-4")))
        plan = good_plan()
        results = {"A.1": {"result": "pass", "note": ""}, "A.2": {"result": "fail", "note": "It stayed in the old slot."},
                   "B.1": {"result": "pass", "note": "Seed looked right."}}
        stage = os.path.join(self.tmp.name, "stage")
        args = ["finish", "--plan", self.file("plan.json", plan), "--results", self.file("results.json", results),
                "--bundle", bundle, "--stage-dir", stage]
        done = self.run_script(*args)
        self.assertEqual(done.returncode, 0, done.stderr)
        info = json.loads(done.stdout)
        self.assertEqual((info["passedRows"], info["failedRows"], info["laterRows"], info["decided"]), (["V-1", "V-3"], ["V-2"], ["V-4"], False))
        self.assertEqual(info["failedSteps"][0]["step"], "A.2")
        with open(os.path.join(stage, "test-plan.md"), encoding="utf-8") as f:
            text = f.read()
        for want in ("  - A.2.1: It lands in the new slot.", "  - Failed criteria: not named", "  - A.1.2: Free slots are clickable.", "A.2** FAIL", "Note: It stayed in the old slot.", "Agent step: Wipe and seed", "V-4 Point V-4: Still not verified (Later)"):
            self.assertIn(want, text)
        done = self.run_script(*args, "--fix", "A.2")
        with open(os.path.join(stage, "test-plan.json"), encoding="utf-8") as f:
            outcome = json.load(f)
        self.assertEqual(outcome["rows"]["V-2"]["decision"], "fix")
        done = self.run_script(*args, "--fix", "none")
        with open(os.path.join(stage, "test-plan.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["rows"]["V-2"]["decision"], "left")
        self.assertEqual(self.run_script(*args, "--fix", "B.1").returncode, 1)

    def test_a_failure_names_its_criteria_when_the_results_do(self):
        bundle = self.file("bundle.json", end_bundle(("V-1", "V-2", "V-3")))
        results = {"A.1": {"result": "fail", "note": "Greyed wrong.", "failed": ["A.1.2"]}, "A.2": {"result": "pass"},
                   "B.1": {"result": "pass"}}
        stage = os.path.join(self.tmp.name, "stage")
        args = ["finish", "--plan", self.file("plan.json", good_plan()), "--results", self.file("results.json", results),
                "--bundle", bundle, "--stage-dir", stage]
        done = self.run_script(*args)
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(os.path.join(stage, "test-plan.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("  - A.1.2 FAIL: Free slots are clickable.", text)
        self.assertIn("  - Failed criteria: A.1.2", text)
        with open(os.path.join(stage, "test-plan.json"), encoding="utf-8") as f:
            self.assertIn("A.1 (A.1.2) failed: Greyed wrong.", json.load(f)["rows"]["V-1"]["notes"])
        results["A.1"]["failed"] = ["A.9.9"]
        done = self.run_script("finish", "--plan", self.file("plan.json", good_plan()), "--results", self.file("results.json", results),
                               "--bundle", bundle, "--stage-dir", stage)
        self.assertEqual(done.returncode, 1)

    def test_finish_refuses_an_unfinished_plan(self):
        done = self.run_script("finish", "--plan", self.file("plan.json", good_plan()), "--results", self.file("r.json", {"A.1": {"result": "pass"}}),
                               "--bundle", self.file("bundle.json", end_bundle()), "--stage-dir", self.tmp.name)
        self.assertEqual(done.returncode, 1)
        self.assertIn("step A.2 has no Pass or Fail yet", done.stdout)


class TestTestFirstAtTheGuard(UnitCase):
    """The unit-end gate's third answer. It is neither Approve nor Request Changes: the gate stays open, and it is asked
    again only about a page republished with the outcome."""

    OPTIONS = ("Approve", "Request Changes", "Test first")

    def ask(self):
        return self.pre("AskUserQuestion", gate_question(END_QUESTION, labels=self.OPTIONS))

    def answer(self, text):
        q = gate_question(END_QUESTION, labels=self.OPTIONS)
        return self.post("AskUserQuestion", q, {"answers": {END_QUESTION: text}})

    def open_asked(self):
        self.open_end()
        self.write_bundle(self.end_id)
        self.said(f"**Read:** {URL}#{self.end_id}")
        code, _out, err = self.ask()
        self.assertEqual(code, 0, err)

    def test_the_question_with_three_options_is_guarded_like_the_gate(self):
        self.open_end()
        self.assertEqual(self.ask()[0], 2)
        self.write_bundle(self.end_id)
        self.said(f"**Read:** {URL}#{self.end_id}")
        self.assertEqual(self.ask()[0], 0)

    def test_test_first_points_at_the_test_plan_and_keeps_the_gate_open(self):
        self.open_asked()
        code, out, err = self.answer("Test first")
        self.assertEqual(code, 0, err)
        said = self.context(out)
        self.assertIn("Test first", said)
        self.assertIn("neither Approve nor Request Changes", said)
        self.assertIn("picks.<V row anchor>", said)
        self.assertNotIn("Request Changes. Read", said)
        pending = self.state_of()["pending"]
        self.assertEqual((pending["unit"], pending["rhythm"]), (UNIT, "unit-end"))

    def test_the_gate_is_not_asked_again_until_the_page_is_republished(self):
        self.open_asked()
        self.answer("Test first")
        code, _out, err = self.ask()
        self.assertEqual(code, 2)
        self.assertIn("Test first", err)
        again = self.end_id.replace("-v1-", "-v2-")
        self.write_bundle(again)  # a new presentation of the page
        self.said(f"**Read:** {URL}#{again}")
        code, _out, err = self.ask()
        self.assertEqual(code, 0, err)

    def test_request_changes_after_testing_still_goes_through(self):
        self.open_asked()
        self.answer("Test first")
        report = {"command": f"aidlc engine orchestrate report --stage code-generation --unit {UNIT} --result rejected --reason 'A.2 failed'"}
        code, _out, err = self.pre("Bash", report)
        self.assertEqual(code, 0, err)

    def test_a_plain_approve_answer_is_unchanged(self):
        self.open_asked()
        code, out, _err = self.answer("Approve")
        self.assertEqual(code, 0)
        self.assertNotIn("Test first", self.context(out))
        self.assertEqual(self.ask()[0], 0)

    def test_the_page_may_not_be_given_results_by_the_agent(self):
        call = {"action": "update", "url": URL, "collection": "plans", "doc_id": "x-test-v1-20260101T1000", "data": {"results": {"A.1": {"result": "pass"}}}}
        code, _out, err = self.pre("ArtifactData", call)
        self.assertEqual(code, 2)
        self.assertIn("Never write them", err)
        call["data"] = {"agentDone": ["A"]}
        self.assertEqual(self.pre("ArtifactData", call)[0], 0)


class TestUnitEndSplit(Base):
    """After the test plan the unit-end page is rebuilt from its outcome: Verified by you, Still not verified, Failed."""

    def setUp(self):
        super().setUp()
        self.finished_plan = self.finished("plan")
        # two not-verified points, so the split has something to separate
        path, end, _info = self.draft("unit-end")
        verified = next(s for s in end["sections"] if s["kind"] == "unverified")["rows"]
        self.assertEqual(len(verified), 1, "the fixture's code summary lists one point")

    def outcome(self, state, decision=None):
        info = {"state": state, "steps": ["A.1"], "notes": ["A.1 passed: fine on the real phone"]}
        if decision:
            info["decision"] = decision
        path = os.path.join(self.tmp, f"outcome-{self.n}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"schema": "aidlc-test-outcome/1", "rows": {"V-1": info}}, f)
        return path

    def republish(self, state, decision=None):
        self.finished("unit-end")  # the presentation the developer tested
        path, end, _info = self.draft("unit-end", UNIT, "--tested", self.outcome(state, decision))
        self.save(path, self._label(end))
        info = self.finalize(path)
        with open(info["bundle"], encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _label(bundle):
        for s in bundle["sections"]:
            for r in s["rows"]:
                r["label"] = r.get("label") or ("core" if s["kind"] == "built" else "medium")
            if s["kind"] == "built" and not s["rows"]:
                s["rows"] = []
        for r in rows_of(bundle, "built"):
            r["label"] = r["label"] if r["label"] in ("core", "main", "minor") else "main"
        bundle["header"]["lede"] = bundle["header"]["lede"] or "The slot list."
        return bundle

    def test_a_passed_point_moves_to_verified_by_you(self):
        end = self.republish("passed")
        keys = [s["key"] for s in end["sections"]]
        self.assertEqual(keys[:3], ["changes", "verified", "unverified"])
        verified = next(s for s in end["sections"] if s["key"] == "verified")
        self.assertEqual((verified["title"], verified["kind"]), ("Verified by you", "verified"))
        self.assertEqual([r["id"] for r in verified["rows"]], ["V-1"])
        self.assertIn("You tested this and it passed.", verified["rows"][0]["body"])
        self.assertEqual(rows_of(end, "unverified"), [])
        self.assertEqual(next(s for s in end["sections"] if s["key"] == "unverified")["title"], "Still not verified")
        self.assertEqual(validate_bundle.validate(end), [])
        self.assertIn("1 verified by you", end["header"]["revisions"][-1]["note"])

    def test_a_failed_point_left_as_known_gets_its_own_section(self):
        end = self.republish("failed", "left")
        failed = next(s for s in end["sections"] if s["key"] == "failed")
        self.assertEqual((failed["title"], [r["id"] for r in failed["rows"]]), ("Failed, left as known", ["V-1"]))
        self.assertNotIn("verified", [s["key"] for s in end["sections"]])
        self.assertEqual(validate_bundle.validate(end), [])

    def test_a_failed_point_being_fixed_and_a_later_point_stay_unverified(self):
        for state, decision in (("failed", "fix"), ("later", None)):
            end = self.republish(state, decision)
            self.assertEqual([r["id"] for r in rows_of(end, "unverified")], ["V-1"])
            self.assertEqual({s["kind"] for s in end["sections"]} & {"verified", "failed"}, set())

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_page_renders_the_split_and_the_pick_control(self):
        from bundle_helpers import render
        end = self.republish("passed")
        page = render(end)["summary"]
        self.assertIn("Verified by you", page)
        before = self.finished("unit-end")[1]
        shown = render(before, {"picked": {"picks": {"V-1": "now"}, "mode": "full"}})["picked"]
        self.assertIn('class="testpick"', shown)
        self.assertIn('data-val="now" aria-pressed="true"', shown)
        self.assertIn('data-val="later" aria-pressed="false"', shown)
        self.assertNotIn('class="testpick"', render(self.finished("plan")[1])["summary"])

    @unittest.skipUnless(NODE, "node is not installed")
    def test_picking_test_now_or_later_marks_the_row_read_and_unpicking_does_not(self):
        script = r"""
const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync(process.argv[1], "utf8");
const src = html.split("/* RENDER-START")[1].split("/* RENDER-END */")[0];
const ctx = { module: {} }; vm.createContext(ctx); vm.runInContext("/*" + src, ctx);
const G = ctx.module.exports, item = { id: "V-1", rev: 2 };
const fresh = () => ({ mode: "full", filter: "all", open: {}, sec: {}, read: {}, notes: {}, picks: {}, noteStat: {} });
const out = {};
let st = fresh(); out.now = [G.applyTestPick(st, "V-1", "now", item), st.picks["V-1"], G.isRead(st, "V-1", item), st.open["V-1"]];
out.unpick = [G.applyTestPick(st, "V-1", "now", item), st.picks["V-1"], G.isRead(st, "V-1", item)];
st = fresh(); out.later = [G.applyTestPick(st, "V-1", "later", item), G.isRead(st, "V-1", item)];
st = fresh(); st.read["V-1"] = 1; out.reread = [G.applyTestPick(st, "V-1", "later", item), st.read["V-1"]];
st = fresh(); out.do = [G.applyTestPick(st, "V-1", "do", item), st.picks["V-1"], G.isRead(st, "V-1", item)];
st = fresh(); st.open["V-1"] = false; G.applyTestPick(st, "V-1", "now", item); out.closed = st.open["V-1"];
process.stdout.write(JSON.stringify(out));
"""
        done = subprocess.run([NODE, "-e", script, PAGE], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        got = json.loads(done.stdout)
        self.assertEqual(got["now"], [True, "now", True, True])
        self.assertEqual(got["unpick"], [False, "", True])
        self.assertEqual(got["later"], [True, True])
        self.assertEqual(got["reread"], [True, 2])
        self.assertEqual(got["do"], [False, "do", False])
        self.assertFalse(got["closed"])


@unittest.skipUnless(NODE, "node is not installed")
class TestPlanPage(unittest.TestCase):
    RENDER = r"""
const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync(process.argv[1], "utf8");
const src = html.split("/* RENDER-START")[1].split("/* RENDER-END */")[0];
const ctx = { module: {} }; vm.createContext(ctx); vm.runInContext("/*" + src, ctx);
const G = ctx.module.exports, input = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify({ page: G.render(input.row, input.local), states: G.states(input.row, input.local), tally: G.tally(input.row, input.local), list: G.listHtml([input.row]) }));
"""

    def row(self, **extra):
        plan = dict(good_plan(), rows={"V-1": "Point <1>"})
        return dict({"plan": plan, "id": plan["id"], "unit": "u2", "intent": "bakery", "title": plan["title"], "createdAt": "2026-01-01T10:00:00Z",
                     "status": "open", "agentDone": []}, **extra)

    def render(self, row, local=None):
        done = subprocess.run([NODE, "-e", self.RENDER, PLAN_PAGE], input=json.dumps({"row": row, "local": local or {}}),
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_criteria_render_numbered_under_the_step_and_an_old_plan_shows_its_expected_text(self):
        page = self.render(self.row())["page"]
        for want in ('<ol class="crit"', ">A.1.1<", ">A.1.2<", "Free slots are clickable.", ">A.2.1<"):
            self.assertIn(want, page)
        self.assertNotIn("<b>Expect</b>", page)
        row = self.row()
        for sec in row["plan"]["sections"]:
            for st in sec["steps"]:
                st["expect"] = "Old expectation."
                del st["criteria"]
        old = self.render(row)["page"]
        self.assertIn("<b>Expect</b>Old expectation.", old)
        self.assertNotIn('class="crit"', old)

    def test_the_first_section_is_current_and_waits_for_the_agent(self):
        out = self.render(self.row())
        self.assertEqual(out["states"], {"byKey": {"A": "agent", "B": "agent"}, "current": "A"})
        self.assertIn('id="sec-A" aria-current="step"', out["page"])
        self.assertIn("Waiting for the agent", out["page"])
        self.assertIn("Start the dev server on port 3000.", out["page"])
        self.assertIn("disabled", out["page"])
        self.assertIn("Point &lt;1&gt;", out["page"])

    def test_the_developers_steps_open_after_the_agent_step_and_the_next_section_becomes_current(self):
        row = self.row(agentDone=["A"])
        out = self.render(row)
        self.assertEqual((out["states"]["byKey"]["A"], out["states"]["current"]), ("yours", "A"))
        self.assertIn("Your turn", out["page"])
        row["results"] = {"A.1": {"result": "pass", "note": ""}, "A.2": {"result": "fail", "note": "Wrong slot."}}
        out = self.render(row)
        self.assertEqual((out["states"]["byKey"]["A"], out["states"]["current"]), ("done", "B"))
        self.assertEqual(out["tally"], {"pass": 1, "fail": 1, "total": 3})
        self.assertIn("Wrong slot.", out["page"])

    def test_a_fail_without_a_note_asks_for_one_and_does_not_count(self):
        row = self.row(agentDone=["A"])
        out = self.render(row, {"A.1": {"result": "fail", "note": " "}})
        self.assertEqual(out["tally"]["fail"], 0)
        self.assertIn('class="note need"', out["page"])
        self.assertIn("Say what went wrong", out["page"])
        self.assertIn("What went wrong (required)", out["page"])

    def test_the_list_shows_progress(self):
        self.assertIn("0/3", self.render(self.row())["list"])


if __name__ == "__main__":
    unittest.main()
