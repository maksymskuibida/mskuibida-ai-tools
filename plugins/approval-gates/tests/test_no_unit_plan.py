"""The Code Generation plan approval of an intent with no Units is the unit approvals plan page (`bundles/<id>` built
by unit_bundle.py --unit intent); its completion gate, and every gate of an intent with Units, keep their own flow.
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import datetime
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from no_unit_project import make_no_unit  # noqa: E402
from test_gate_guard import INTENT, URL, Case  # noqa: E402
from test_gate_guard import gate_question  # noqa: E402
from test_unit_bundle import Base  # noqa: E402

NO_UNIT = "intent"
UNIT = "u2-pickup-slots"


class NoUnitCase(Case):
    def setUp(self):
        super().setUp()
        make_no_unit(self.project)
        self.now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M")
        self.plan_id = f"{INTENT}-{NO_UNIT}-plan-v1-{self.now}"

    def directive(self, **data):
        with open(os.path.join(self.record, ".aidlc-engine", "active-directive.json"), "w", encoding="utf-8") as f:
            json.dump(dict({"kind": "ask", "ask_type": "plan-approval", "stage": "code-generation"}, **data), f)

    def write_bundle(self, doc_id):
        path = os.path.join(self.tmp, f"row-{self.counter}.json")
        self.counter += 1
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"bundle": {"id": doc_id}, "page": "plan", "status": "open"}, f)
        call = {"action": "batch", "url": URL, "writes": [{"op": "set", "collection": "bundles", "doc_id": doc_id, "file_path": path}]}
        self.assertEqual(self.pre("ArtifactData", call)[0], 0)
        self.assertEqual(self.post("ArtifactData", call, {"ok": True})[0], 0)

    def plan_question(self):
        return self.pre("AskUserQuestion", gate_question("Approve the code plan?", labels=("Approve Plan", "Request Changes")))


class TestGuardSelection(NoUnitCase):
    def test_no_unit_plan_approval_takes_the_plan_page(self):
        self.directive()
        code, out, err = self.post("Bash", {"command": "aidlc engine orchestrate next"}, {"stdout": '{"kind":"ask"}'})
        self.assertEqual(code, 0, err)
        said = self.context(out)
        self.assertIn("draft --page plan --unit intent", said)
        self.assertIn("no Units", said)
        pending = self.state_of()["pending"]
        self.assertEqual((pending["kind"], pending["rhythm"], pending["unit"]), ("plan", "unit-end", NO_UNIT))
        # the same ask seen again does not reopen the gate
        opened = pending["opened_at"]
        self.post("Bash", {"command": "aidlc engine orchestrate next"}, {"stdout": '{"kind":"ask"}'})
        self.assertEqual(self.state_of()["pending"]["opened_at"], opened)

    def test_question_needs_the_plan_bundle_and_its_link(self):
        self.directive()
        code, _out, err = self.plan_question()
        self.assertEqual(code, 2)
        self.assertIn("plan page", err)
        self.assertIn("--unit intent", err)
        self.write_bundle(self.plan_id)
        self.assertEqual(self.plan_question()[0], 2)  # the link was not sent yet
        self.said(f"**Read:** {URL}#{self.plan_id}")
        code, _out, err = self.plan_question()
        self.assertEqual(code, 0, err)

    def test_a_per_stage_gates_row_is_the_wrong_page_for_the_plan(self):
        self.directive()
        self.plan_question()
        call = self.batch(f"{INTENT}-code-generation-20260101T0900")
        code, _out, err = self.pre("ArtifactData", call)
        self.assertEqual(code, 2)
        self.assertIn("no Units", err)

    def test_the_completion_gate_stays_per_stage(self):
        report = "aidlc engine orchestrate report --stage code-generation --result awaiting-approval"
        code, out, err = self.post("Bash", {"command": report}, {"stdout": "ok"})
        self.assertEqual(code, 0, err)
        pending = self.state_of()["pending"]
        self.assertEqual((pending["kind"], pending["rhythm"], pending["unit"]), ("gate", "per-stage", None))
        self.assertIn("gate_bundle.py", self.context(out))

    def test_the_completion_gate_after_the_plan_is_per_stage(self):
        self.directive()
        self.post("Bash", {"command": "aidlc engine orchestrate next"}, {"stdout": '{"kind":"ask"}'})
        self.post("Bash", {"command": 'aidlc engine log answer --stage code-generation --checkpoint plan-approval --details "Approve Plan"'},
                  {"stdout": "{}"})
        self.assertIsNone(self.state_of()["pending"])
        report = "aidlc engine orchestrate report --stage code-generation --result awaiting-approval"
        self.post("Bash", {"command": report}, {"stdout": "ok"})
        self.assertEqual(self.state_of()["pending"]["rhythm"], "per-stage")


class TestIntentsWithUnits(Case):
    """The fixture project has Units: nothing moves for them."""

    def ask(self, **data):
        with open(os.path.join(self.record, ".aidlc-engine", "active-directive.json"), "w", encoding="utf-8") as f:
            json.dump(dict({"kind": "ask", "ask_type": "plan-approval", "stage": "code-generation", "unit": UNIT}, **data), f)
        self.post("Bash", {"command": "aidlc engine orchestrate next"}, {"stdout": '{"kind":"ask"}'})
        return self.state_of()["pending"]

    def stamp(self, rhythm):
        with open(os.path.join(self.project, "aidlc", ".aidlc-unit-scope.json"), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "unit": UNIT, "gate_rhythm": rhythm, "space": "default"}, f)

    def test_unit_without_a_claim_stays_per_stage(self):
        pending = self.ask()
        self.assertEqual((pending["unit"], pending["rhythm"]), (UNIT, "per-stage"))

    def test_unit_end_claim_takes_the_plan_page_with_its_own_unit(self):
        self.stamp("unit-end")
        pending = self.ask()
        self.assertEqual((pending["unit"], pending["rhythm"]), (UNIT, "unit-end"))

    def test_the_missing_unit_of_a_unit_intent_is_not_no_unit(self):
        pending = self.ask(unit=None)  # a directive that names no Unit, in an intent that has them
        self.assertIsNone(pending["unit"])
        self.assertEqual(pending["rhythm"], "per-stage")


class TestNoUnitBundle(Base):
    def setUp(self):
        super().setUp()
        make_no_unit(self.project)

    def test_draft_finds_the_plan_and_the_design_records(self):
        _path, b, _info = self.draft("plan", NO_UNIT)
        h = b["header"]
        self.assertEqual((h["unit"], h["title"]), (NO_UNIT, "Approve plan"))
        self.assertNotIn("unitLabel", h)
        self.assertEqual(h["intentName"], "Bakery preorder")
        ran = {s["slug"]: s["ran"] for s in h["stages"]}
        self.assertTrue(ran["functional-design"] and ran["nfr-requirements"])
        self.assertEqual([g["key"] for g in b["answers"]], ["fd-answers", "nr-answers"])
        self.assertTrue(b["plan"]["steps"])
        self.assertIn("construction/code-generation/code-generation-plan.md", b["plan"]["path"])

    def test_finalize_writes_a_bundles_row_with_the_intent_id(self):
        _path, bundle, info = self.finished("plan", NO_UNIT)
        self.assertIn("-intent-plan-v1-", info["id"])
        self.assertEqual(bundle["header"]["title"], "Approve plan")
        with open(info["writes"], encoding="utf-8") as f:
            writes = json.load(f)
        writes = writes["writes"] if isinstance(writes, dict) else writes
        self.assertEqual([w["collection"] for w in writes], ["bundles"])
        self.assertEqual(writes[0]["doc_id"], info["id"])

    def test_the_unit_end_page_is_refused_for_no_unit(self):
        out = os.path.join(self.tmp, "x.json")
        done = self.run_script("draft", "--page", "unit-end", "--unit", NO_UNIT, "--project-dir", self.project, "--out", out)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("per-stage", done.stderr + done.stdout)


if __name__ == "__main__":
    unittest.main()
