"""Tests for the unit-end branch of hooks/gate_guard.py: a Unit claimed with the unit-end rhythm has a plan page and a
unit-end page (`bundles/<id>` rows) instead of a page per stage. Per-stage gates keep their own tests in
test_gate_guard.py; the last class here checks a per-stage claim still goes that way.
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import datetime
import json
import os
import unittest

from test_gate_guard import INTENT, URL, Case, gate_question

UNIT = "u2-pickup-slots"
OLD_PLAN_ID = f"{INTENT}-{UNIT}-plan-v1-20260101T0900"


class UnitCase(Case):
    def setUp(self):
        super().setUp()
        self.stamp("unit-end")
        self.now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M")  # a bundle is stamped when it is built
        self.plan_id = f"{INTENT}-{UNIT}-plan-v1-{self.now}"
        self.end_id = f"{INTENT}-{UNIT}-unit-end-v1-{self.now}"

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
        self.write_bundle(self.plan_id)
        code, _out, err = self.plan_question()
        self.assertEqual(code, 2)
        self.assertIn(f"{URL}#{self.plan_id}", err)
        self.said(f"**Read:** {URL}#{self.plan_id}")
        code, _out, err = self.plan_question()
        self.assertEqual(code, 0, err)

    def test_a_per_stage_gates_row_does_not_unlock_the_plan_page(self):
        self.open_plan()
        self.publish(f"{INTENT}-code-generation-{UNIT}-20260101T0900")
        code, _out, err = self.plan_question()
        self.assertEqual(code, 2, err)

    def test_the_unit_end_bundle_does_not_unlock_the_plan_page(self):
        self.open_plan()
        self.write_bundle(self.end_id)
        self.said(f"**Read:** {URL}#{self.end_id}")
        self.assertEqual(self.plan_question()[0], 2)

    def test_a_bundle_built_before_the_gate_opened_does_not_count(self):
        self.open_plan()
        _code, out = self.write_bundle(OLD_PLAN_ID)
        self.assertIn("built before this gate opened", self.context(out))
        self.said(f"**Read:** {URL}#{OLD_PLAN_ID}")
        self.assertEqual(self.plan_question()[0], 2)

    def test_a_bundle_of_another_unit_does_not_count(self):
        self.open_plan()
        other = f"{INTENT}-u9-other-plan-v1-{self.now}"
        self.write_bundle(other)
        self.said(f"**Read:** {URL}#{other}")
        self.assertEqual(self.plan_question()[0], 2)

    def test_the_question_carries_no_link(self):
        self.open_plan()
        self.write_bundle(self.plan_id)
        self.said(f"**Read:** {URL}#{self.plan_id}")
        code, _out, err = self.pre("AskUserQuestion", gate_question(f"Approve? {URL}#{self.plan_id}", labels=("Approve Plan",)))
        self.assertEqual(code, 2)
        self.assertIn("message of its own", err)


class TestPlanAskOfTheEngine(UnitCase):
    """The engine asks for the plan approval itself (`orchestrate next` returns an `ask` with `ask_type:
    "plan-approval"`), and the agent may give the question any header: the u5-commenting session asked under "Plan" and
    never sent the plan page's link."""

    def ask_plan(self):
        with open(os.path.join(self.record, ".aidlc-engine", "active-directive.json"), "w", encoding="utf-8") as f:
            json.dump({"kind": "ask", "ask_type": "plan-approval", "stage": "code-generation", "unit": UNIT,
                       "question": f"Approve the code plan for {UNIT}?"}, f)

    def plan_question(self, header="Plan"):
        return self.pre("AskUserQuestion", gate_question(f"Approve the code plan for {UNIT}?", header=header,
                                                         labels=("Approve Plan", "Request Changes", "I'll edit the files")))

    def test_the_engines_ask_opens_the_plan_gate_under_any_header(self):
        self.ask_plan()
        code, _out, err = self.plan_question()
        self.assertEqual(code, 2)
        self.assertIn("plan page", err)
        self.write_bundle(self.plan_id)
        code, _out, err = self.plan_question()
        self.assertEqual(code, 2)
        self.assertIn(f"{URL}#{self.plan_id}", err)
        self.said(f"**Read:** {URL}#{self.plan_id}")
        code, _out, err = self.plan_question()
        self.assertEqual(code, 0, err)

    def test_the_next_call_that_returns_the_ask_says_to_publish_the_plan_page(self):
        self.ask_plan()
        code, out, err = self.post("Bash", {"command": "aidlc engine orchestrate next"}, {"stdout": '{"kind":"ask"}'})
        self.assertEqual(code, 0, err)
        said = self.context(out)
        self.assertIn("draft --page plan --unit u2-pickup-slots", said)
        self.assertEqual(self.state_of()["pending"]["kind"], "plan")

    def test_the_bundle_write_is_answered_once_with_the_link_to_send(self):
        self.ask_plan()
        _code, out = self.write_bundle(self.plan_id)
        said = self.context(out)
        self.assertIn(f"{URL}#{self.plan_id}", said)

    def test_request_changes_reopens_the_plan_for_its_revision(self):
        self.ask_plan()
        self.write_bundle(self.plan_id)
        self.said(f"**Read:** {URL}#{self.plan_id}")
        self.assertEqual(self.plan_question()[0], 0)
        self.post("Bash", {"command": 'aidlc engine log answer --stage code-generation --checkpoint plan-approval --details "Request Changes"'},
                  {"stdout": "{}"})
        self.assertIsNone(self.state_of()["pending"])
        os.utime(os.path.join(self.record, ".aidlc-engine", "active-directive.json"))  # the revised plan's ask
        later = time_after(self.state_of()["published"])
        os.utime(os.path.join(self.record, ".aidlc-engine", "active-directive.json"), (later, later))
        code, _out, err = self.plan_question()
        self.assertEqual(code, 2)
        self.assertIn("plan page", err)

    def test_an_approve_plan_question_with_no_gate_open_is_left_alone(self):
        self.assertEqual(self.plan_question()[0], 0)


class TestRefusedReport(UnitCase):
    def test_a_report_the_engine_refused_opens_nothing(self):
        refused = '{"message":"Unit-end gate for \\"u2\\" must be reported against \\"code-generation\\".","kind":"error"}'
        code, _out, err = self.post("Bash", {"command": f"aidlc engine orchestrate report --stage functional-design --unit {UNIT} --result awaiting-approval"},
                                    {"stdout": refused})
        self.assertEqual(code, 0, err)
        self.assertIsNone((self.state_of() or {}).get("pending"))


def time_after(published):
    return max([p.get("at", 0) for p in published.values()] + [0]) + 5


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
        self.write_bundle(self.plan_id)  # the plan page is not this gate's page
        self.assertEqual(self.pre("Bash", report)[0], 2)
        self.write_bundle(self.end_id)
        self.said(f"**Read:** {URL}#{self.end_id}")
        code, _out, err = self.ask("Unit complete. How would you like to proceed?")
        self.assertEqual(code, 0, err)
        code, _out, err = self.pre("Bash", report)
        self.assertEqual(code, 0, err)

    def test_another_stage_of_the_unit_keeps_its_page_per_stage(self):
        code, out, err = self.post("Bash", {"command": f"aidlc engine orchestrate report --stage functional-design --unit {UNIT} --result revised"},
                                   {"stdout": ""})
        self.assertEqual(code, 0, err)
        self.assertEqual(self.state_of()["pending"]["rhythm"], "per-stage")
        self.assertIn("gate_bundle.py", self.context(out))

    def test_the_directive_alone_marks_the_unit_end_gate(self):
        os.remove(os.path.join(self.project, "aidlc", ".aidlc-unit-scope.json"))
        with open(os.path.join(self.record, ".aidlc-engine", "active-directive.json"), "w", encoding="utf-8") as f:
            json.dump({"stage": "code-generation", "unit": UNIT, "unit_gate": "unit-end", "gate": True}, f)
        self.open_end()
        self.assertEqual(self.state_of()["pending"]["rhythm"], "unit-end")


class TestUnitEndGateTheStateDidNotSee(UnitCase):
    """The u12-local-git session: the plan was approved, the Unit was built and its unit-end gate came without a
    `report --result awaiting-approval` this session's state saw. The unit-end bundle was written and the developer
    approved in chat, yet the closing report was refused with a demand for a per-stage gates page."""

    REPORT = f"aidlc engine orchestrate report --stage code-generation --unit {UNIT} --result approved --user-input Approve"

    def approve_plan(self):
        self.open_plan()
        self.write_bundle(self.plan_id)
        self.said(f"**Read:** {URL}#{self.plan_id}")
        self.post("Bash", {"command": 'aidlc engine log answer --stage code-generation --checkpoint plan-approval --details "Approve Plan"'},
                  {"stdout": "{}"})

    def test_an_approved_plan_closes_the_plan_gate(self):
        self.approve_plan()
        self.assertIsNone(self.state_of()["pending"])

    def test_the_unit_end_bundle_counts_with_no_gate_open(self):
        self.approve_plan()
        _code, out = self.write_bundle(self.end_id)
        self.assertIn(f"{URL}#{self.end_id}", self.context(out))
        code, _out, err = self.pre("Bash", {"command": self.REPORT})
        self.assertEqual(code, 0, err)

    def test_with_no_gate_open_the_report_asks_for_the_unit_end_page_not_a_gates_page(self):
        code, _out, err = self.pre("Bash", {"command": self.REPORT})
        self.assertEqual(code, 2)
        self.assertIn("draft --page unit-end", err)
        self.assertNotIn("gate_bundle.py", err)

    def test_a_closing_report_the_engine_refused_keeps_the_gate_open(self):
        self.open_end()
        self.write_bundle(self.end_id)
        refused = '{"message":"report --result approved requires --user-input with the human\'s reply.","kind":"error"}'
        self.post("Bash", {"command": f"aidlc engine orchestrate report --stage code-generation --unit {UNIT} --result approved"},
                  {"stdout": refused})
        self.assertIsNotNone(self.state_of()["pending"])
        code, _out, err = self.pre("Bash", {"command": self.REPORT})
        self.assertEqual(code, 0, err)


class TestRowsAndAnswers(UnitCase):
    def test_notes_and_picks_are_the_developers(self):
        self.open_plan()
        for field in ("notes", "picks"):
            code, err = self.write_bundle(self.plan_id, {field: {"E-1": "x"}})
            self.assertEqual(code, 2)
            self.assertIn("written by the developer", err)

    def test_a_bundle_row_is_written_once_and_whole(self):
        self.open_plan()
        self.write_bundle(self.plan_id)
        for call in ({"action": "update", "url": URL, "collection": "bundles", "doc_id": self.plan_id, "data": {"status": "x"}},
                     {"action": "delete", "url": URL, "collection": "bundles", "doc_id": self.plan_id},
                     {"action": "str_replace", "url": URL, "collection": "bundles", "doc_id": self.plan_id, "field": "notes", "old_str": "a", "new_str": "b"},
                     {"action": "set", "url": URL, "collection": "bundles", "doc_id": self.plan_id, "data": {"notes.E-1": "x"}}):
            code, _out, err = self.pre("ArtifactData", call)
            self.assertEqual(code, 2, call)

    def test_request_changes_says_to_quote_notes_and_picks(self):
        self.open_plan()
        self.write_bundle(self.plan_id)
        q = gate_question("Approve the code plan?", labels=("Approve Plan", "Request Changes"))
        code, out, err = self.post("AskUserQuestion", q, {"answers": {"Approve the code plan?": "Request Changes"}})
        self.assertEqual(code, 0, err)
        said = self.context(out)
        self.assertIn(f"bundles/{self.plan_id}", said)
        self.assertIn("picks", said)
        self.assertIn("--reason", said)

    def test_approve_still_says_to_read_the_row(self):
        self.open_plan()
        self.write_bundle(self.plan_id)
        q = gate_question("Approve the code plan?", labels=("Approve Plan", "Request Changes"))
        _code, out, _err = self.post("AskUserQuestion", q, {"answers": {"Approve the code plan?": "Approve Plan"}})
        said = self.context(out)
        self.assertIn(f"bundles/{self.plan_id}", said)
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
