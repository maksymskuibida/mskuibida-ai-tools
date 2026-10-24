"""Tests for the unit-end branch of hooks/gate_guard.py: a Unit claimed with the unit-end rhythm has a plan page and a
unit-end page (`bundles/<id>` rows) instead of a page per stage. Per-stage gates keep their own tests in
test_gate_guard.py; the last class here checks a per-stage claim still goes that way.
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import json
import os
import unittest

from test_gate_guard import INTENT, URL, Case, gate_question

UNIT = "u2-pickup-slots"
PLAN_ID = f"{INTENT}-{UNIT}-plan-v1-20260101T0900"
END_ID = f"{INTENT}-{UNIT}-unit-end-v1-20260101T1100"


class UnitCase(Case):
    def setUp(self):
        super().setUp()
        self.stamp("unit-end")

    def stamp(self, rhythm, unit=UNIT):
        with open(os.path.join(self.project, "aidlc", ".aidlc-unit-scope.json"), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "unit": unit, "gate_rhythm": rhythm, "space": "default"}, f)

    def open_plan(self):
        code, out, err = self.post("Bash", {"command": f"aidlc engine log decision --unit {UNIT} --checkpoint plan-approval --value presented"},
                                   {"stdout": ""})
        self.assertEqual(code, 0, err)
        return out

    def open_end(self):
        code, out, err = self.post("Bash", {"command": f"aidlc engine orchestrate report --stage code-generation --unit {UNIT} --result awaiting-approval"},
                                   {"stdout": ""})
        self.assertEqual(code, 0, err)
        return out

    def write_bundle(self, doc_id, extra=None):
        path = os.path.join(self.tmp, f"row-{self.counter}.json")
        self.counter += 1
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dict({"bundle": {"id": doc_id}, "page": "plan", "status": "open"}, **(extra or {})), f)
        call = {"action": "batch", "url": URL, "writes": [{"op": "set", "collection": "bundles", "doc_id": doc_id, "file_path": path}]}
        code, _out, err = self.pre("ArtifactData", call)
        if code:
            return code, err
        code, out, err = self.post("ArtifactData", call, {"ok": True})
        self.assertEqual(code, 0, err)
        return code, out

    def plan_question(self):
        return self.pre("AskUserQuestion", gate_question("Approve the code plan for u2-pickup-slots?", labels=("Approve Plan", "Request Changes")))


class TestPlanPage(UnitCase):
    def test_plan_approval_asks_for_the_plan_bundle(self):
        said = self.context(self.open_plan())
        self.assertIn("unit_bundle.py", said)
        self.assertIn("draft --page plan --unit u2-pickup-slots", said)
        self.assertIn("finalize", said)
        self.assertIn("one look at every design stage", said)
        pending = self.state_of()["pending"]
        self.assertEqual((pending["kind"], pending["rhythm"], pending["unit"]), ("plan", "unit-end", UNIT))

    def test_question_refused_until_the_plan_bundle_and_its_link(self):
        self.open_plan()
        code, _out, err = self.plan_question()
        self.assertEqual(code, 2)
        self.assertIn("plan page", err)
        self.write_bundle(PLAN_ID)
        code, _out, err = self.plan_question()
        self.assertEqual(code, 2)
        self.assertIn(f"{URL}#{PLAN_ID}", err)
        self.said(f"**Read:** {URL}#{PLAN_ID}")
        code, _out, err = self.plan_question()
        self.assertEqual(code, 0, err)

    def test_a_per_stage_gates_row_does_not_unlock_the_plan_page(self):
        self.open_plan()
        self.publish(f"{INTENT}-code-generation-{UNIT}-20260101T0900")
        code, _out, err = self.plan_question()
        self.assertEqual(code, 2, err)

    def test_the_unit_end_bundle_does_not_unlock_the_plan_page(self):
        self.open_plan()
        self.write_bundle(END_ID)
        self.said(f"**Read:** {URL}#{END_ID}")
        self.assertEqual(self.plan_question()[0], 2)

    def test_a_bundle_of_another_unit_does_not_count(self):
        self.open_plan()
        other = f"{INTENT}-u9-other-plan-v1-20260101T0900"
        self.write_bundle(other)
        self.said(f"**Read:** {URL}#{other}")
        self.assertEqual(self.plan_question()[0], 2)

    def test_the_question_carries_no_link(self):
        self.open_plan()
        self.write_bundle(PLAN_ID)
        self.said(f"**Read:** {URL}#{PLAN_ID}")
        code, _out, err = self.pre("AskUserQuestion", gate_question(f"Approve? {URL}#{PLAN_ID}", labels=("Approve Plan",)))
        self.assertEqual(code, 2)
        self.assertIn("message of its own", err)


class TestUnitEndPage(UnitCase):
    def test_the_unit_end_gate_asks_for_the_unit_end_bundle(self):
        said = self.context(self.open_end())
        self.assertIn("draft --page unit-end --unit u2-pickup-slots", said)
        self.assertEqual(self.state_of()["pending"]["rhythm"], "unit-end")

    def test_question_and_report_wait_for_the_unit_end_bundle(self):
        self.open_end()
        self.assertEqual(self.ask("Unit complete. How would you like to proceed?")[0], 2)
        report = {"command": f"aidlc engine orchestrate report --stage code-generation --unit {UNIT} --result approved --user-input Approve"}
        self.assertEqual(self.pre("Bash", report)[0], 2)
        self.write_bundle(PLAN_ID)  # the plan page is not this gate's page
        self.assertEqual(self.pre("Bash", report)[0], 2)
        self.write_bundle(END_ID)
        self.said(f"**Read:** {URL}#{END_ID}")
        code, _out, err = self.ask("Unit complete. How would you like to proceed?")
        self.assertEqual(code, 0, err)
        code, _out, err = self.pre("Bash", report)
        self.assertEqual(code, 0, err)

    def test_the_directive_alone_marks_the_unit_end_gate(self):
        os.remove(os.path.join(self.project, "aidlc", ".aidlc-unit-scope.json"))
        with open(os.path.join(self.record, ".aidlc-engine", "active-directive.json"), "w", encoding="utf-8") as f:
            json.dump({"stage": "code-generation", "unit": UNIT, "unit_gate": "unit-end", "gate": True}, f)
        self.open_end()
        self.assertEqual(self.state_of()["pending"]["rhythm"], "unit-end")


class TestRowsAndAnswers(UnitCase):
    def test_notes_and_picks_are_the_developers(self):
        self.open_plan()
        for field in ("notes", "picks"):
            code, err = self.write_bundle(PLAN_ID, {field: {"E-1": "x"}})
            self.assertEqual(code, 2)
            self.assertIn("written by the developer", err)

    def test_request_changes_says_to_quote_notes_and_picks(self):
        self.open_plan()
        self.write_bundle(PLAN_ID)
        q = gate_question("Approve the code plan?", labels=("Approve Plan", "Request Changes"))
        code, out, err = self.post("AskUserQuestion", q, {"answers": {"Approve the code plan?": "Request Changes"}})
        self.assertEqual(code, 0, err)
        said = self.context(out)
        self.assertIn(f"bundles/{PLAN_ID}", said)
        self.assertIn("picks", said)
        self.assertIn("--reason", said)

    def test_approve_still_says_to_read_the_row(self):
        self.open_plan()
        self.write_bundle(PLAN_ID)
        q = gate_question("Approve the code plan?", labels=("Approve Plan", "Request Changes"))
        _code, out, _err = self.post("AskUserQuestion", q, {"answers": {"Approve the code plan?": "Approve Plan"}})
        said = self.context(out)
        self.assertIn(f"bundles/{PLAN_ID}", said)
        self.assertIn("ask in chat", said)


class TestPerStageStaysAsItWas(UnitCase):
    def setUp(self):
        super().setUp()
        self.stamp("per-stage")

    def test_a_per_stage_claim_keeps_the_page_per_stage(self):
        said = self.context(self.open_plan())
        self.assertIn("gate_bundle.py", said)
        self.assertNotIn("unit_bundle.py", said)
        self.assertEqual(self.state_of()["pending"]["rhythm"], "per-stage")
        self.publish(f"{INTENT}-code-generation-{UNIT}-20260101T0900")
        code, _out, err = self.plan_question()
        self.assertEqual(code, 0, err)

    def test_a_unit_end_stamp_for_another_unit_does_not_apply(self):
        self.stamp("unit-end", unit="u9-other")
        said = self.context(self.open_plan())
        self.assertIn("gate_bundle.py", said)


if __name__ == "__main__":
    unittest.main()
