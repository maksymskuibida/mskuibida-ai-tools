"""The registry entries hooks/gate_guard.py writes when a gate page, a unit plan or unit-end page, or a test plan is
published (scripts/aidlc_links.py): one entry per publication, written by the hook, not left to the agent.
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import json
import os
import sys
import unittest

from test_gate_guard import INTENT, URL, Case
from test_unit_rhythm_guard import UNIT, UnitCase

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import aidlc_links  # noqa: E402


class Registry:
    def use_registry(self):
        self.links_dir = os.path.join(self.tmp, "links-data")
        os.environ["AIDLC_ARTIFACTS_DIR"] = self.links_dir
        self.addCleanup(os.environ.pop, "AIDLC_ARTIFACTS_DIR", None)

    def entries(self):
        return aidlc_links.entries(self.project, "default", INTENT)


class TestGatePage(Registry, Case):
    def setUp(self):
        super().setUp()
        self.use_registry()

    def test_a_gate_page_is_recorded_under_its_stage(self):
        self.open_gate("user-stories")
        gate_id = self.publish()
        [entry] = self.entries()
        self.assertEqual((entry["kind"], entry["stage"], entry["rhythm"], entry["round"]), ("gate", "user-stories", "per-stage", 1))
        self.assertEqual(entry["url"], f"{URL}#{gate_id}")
        self.assertEqual((entry["artifact"], entry["row"], entry["intent"], entry["session"]), (URL, gate_id, INTENT, "s1"))
        self.assertEqual(entry["title"], "User Stories")
        self.assertTrue(entry["createdAt"].endswith("Z"))

    def test_a_request_changes_round_is_a_new_entry_of_the_same_stage(self):
        self.open_gate("user-stories")
        first = self.publish(f"{INTENT}-user-stories-20260101T0900")
        self.open_gate("user-stories", result="revised")
        second = self.publish(f"{INTENT}-user-stories-20260101T1000")
        found = self.entries()
        self.assertEqual([e["row"] for e in found], [first, second])
        self.assertEqual([e["round"] for e in found], [1, 2])

    def test_the_same_row_written_again_is_not_a_second_entry(self):
        self.open_gate("user-stories")
        gate_id = self.publish()
        self.publish(gate_id)
        self.assertEqual(len(self.entries()), 1)

    def test_a_write_the_artifact_refused_records_nothing(self):
        self.open_gate("user-stories")
        call = self.batch(f"{INTENT}-user-stories-20260101T0900")
        self.post("ArtifactData", call, {"error": "document already exists", "is_error": True})
        self.assertEqual(self.entries(), [])

    def test_a_page_of_no_open_stage_is_not_recorded(self):
        self.open_gate("user-stories")
        call = self.batch(f"{INTENT}-delivery-planning-20260101T0900")
        self.post("ArtifactData", call, {"ok": True})
        self.assertEqual(self.entries(), [])


class TestUnitPages(Registry, UnitCase):
    def setUp(self):
        super().setUp()
        self.use_registry()

    def ask_plan(self):
        with open(os.path.join(self.record, ".aidlc-engine", "active-directive.json"), "w", encoding="utf-8") as f:
            json.dump({"kind": "ask", "ask_type": "plan-approval", "stage": "code-generation", "unit": UNIT}, f)

    def test_the_unit_plan_page_is_recorded_under_code_generation(self):
        self.open_plan()
        self.ask_plan()
        self.write_bundle(self.plan_id)
        [entry] = self.entries()
        self.assertEqual((entry["kind"], entry["stage"], entry["unit"], entry["rhythm"], entry["revision"]),
                         ("unit-plan", "code-generation", UNIT, "unit-end", 1))
        self.assertEqual(entry["url"], f"{URL}#{self.plan_id}")

    def test_the_unit_end_page_and_its_test_plan(self):
        self.open_end()
        self.write_bundle(self.end_id, {"page": "unit-end"})
        plan = f"{INTENT}-{UNIT}-test-v2-{self.now}"
        call = {"action": "batch", "url": URL, "writes": [{"op": "set", "collection": "plans", "doc_id": plan,
                                                           "data": {"title": "Plan", "unit": UNIT, "sections": []}}]}
        self.assertEqual(self.post("ArtifactData", call, {"ok": True})[0], 0)
        found = {e["kind"]: e for e in self.entries()}
        self.assertEqual(sorted(found), ["test-plan", "unit-end"])
        self.assertEqual((found["unit-end"]["stage"], found["unit-end"]["unit"]), ("code-generation", UNIT))
        self.assertEqual((found["test-plan"]["stage"], found["test-plan"]["unit"], found["test-plan"]["revision"], found["test-plan"]["title"]),
                         ("code-generation", UNIT, 2, "Plan"))

    def test_a_bundle_that_does_not_count_for_the_gate_is_not_recorded(self):
        self.open_plan()
        self.ask_plan()
        self.write_bundle(f"{INTENT}-{UNIT}-plan-v1-20200101T0900")
        self.assertEqual(self.entries(), [])


if __name__ == "__main__":
    unittest.main()
