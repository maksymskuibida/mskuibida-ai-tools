"""Custom per-Unit stages (engine plugins add stages to the project's stage graph): the Unit's last stage, the unit-end
bundle, the map's landed state, the guard's rhythm, and a run-once custom stage as a per-stage gate.
The fixture graph is generic: `demo-assessment-unit` (per Unit, after code-generation) and `demo-assessment-intent`
(run once, after build-and-test). Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from bundle_helpers import SCRIPTS, agent_pass  # noqa: E402
import test_unit_bundle as tub  # noqa: E402
import test_maps as tm  # noqa: E402
from test_gate_bundle import Case as GateCase, bundle as gate_bundle_mod, fill_judgment, record  # noqa: E402
from test_gate_guard import guard  # noqa: E402

sys.path.insert(0, SCRIPTS)
import stage_graph  # noqa: E402

UNIT = tub.UNIT
GRAPH = [
    {"slug": "functional-design", "number": "3.1", "name": "Functional Design", "phase": "construction", "for_each": "unit-of-work"},
    {"slug": "code-generation", "number": "3.5", "name": "Code Generation", "phase": "construction", "for_each": "unit-of-work"},
    {"slug": "demo-assessment-unit", "number": "3.8", "name": "Demo Assessment (Unit)", "phase": "construction",
     "for_each": "unit-of-work", "plugin": "demo-assessment", "requires_stage": "code-generation"},
    {"slug": "build-and-test", "number": "3.7", "name": "Build and Test", "phase": "construction"},
    {"slug": "demo-assessment-intent", "number": "3.9", "name": "Demo Assessment (Intent)", "phase": "construction",
     "plugin": "demo-assessment", "requires_stage": "build-and-test"},
]
STATE = "## Stage Progress\n- [x] code-generation — EXECUTE\n- [ ] demo-assessment-unit — EXECUTE\n- [ ] demo-assessment-intent — EXECUTE\n"


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def add_graph(project, graph=GRAPH):
    put(os.path.join(project, ".claude", "tools", "data", "stage-graph.json"), json.dumps(graph))


class TestStageGraph(unittest.TestCase):
    def setUp(self):
        import tempfile, shutil
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_per_unit_stages_and_last_stage_come_from_the_graph(self):
        add_graph(self.tmp)
        self.assertEqual(stage_graph.unit_stages(self.tmp), ["functional-design", "code-generation", "demo-assessment-unit"])
        self.assertEqual(stage_graph.last_stage(self.tmp), "demo-assessment-unit")
        self.assertEqual(stage_graph.stages_after_code(self.tmp), ["demo-assessment-unit"])

    def test_a_custom_stage_the_intent_state_does_not_list_does_not_apply(self):
        add_graph(self.tmp)
        put(os.path.join(self.tmp, "state", "aidlc-state.md"), "- [x] code-generation — EXECUTE\n- [ ] other-stage — EXECUTE\n")
        self.assertEqual(stage_graph.last_stage(self.tmp, os.path.join(self.tmp, "state")), "code-generation")

    def test_no_graph_or_no_per_unit_flag_falls_back_to_upstream(self):
        self.assertEqual(stage_graph.last_stage(self.tmp), "code-generation")
        add_graph(self.tmp, [{"slug": "code-generation", "number": "3.5", "phase": "construction"}])
        self.assertEqual(stage_graph.unit_stages(self.tmp), list(stage_graph.DEFAULT_UNIT_STAGES))
        self.assertEqual(stage_graph.stages_after_code(self.tmp), [])


class TestUnitEndBundle(tub.Base):
    def setUp(self):
        super().setUp()
        add_graph(self.project)
        intent = os.path.join(self.project, "aidlc", "spaces", "default", "intents", "260101-bakery-preorder")
        with open(os.path.join(intent, "aidlc-state.md"), encoding="utf-8") as f:
            put(os.path.join(intent, "aidlc-state.md"), f.read() + "\n" + STATE)
        put(os.path.join(intent, "construction", UNIT, "demo-assessment-unit", "demo-assessment.md"),
            "# Demo assessment\n\nThe slot rules fit the context budget.\n\n## Detail\nNothing else.\n")
        self.intent = intent

    def _end(self):
        self.finished()
        return self.finished("unit-end")[1]

    def test_the_custom_stages_documents_are_built_rows_and_provenance(self):
        end = self._end()
        built = tub.rows_of(end, "built")
        extra = [r for r in built if r["source"]["key"].startswith("built:demo-assessment-unit:")]
        self.assertEqual(len(extra), 1)
        self.assertEqual(extra[0]["title"], "Demo Assessment (Unit): Demo assessment")
        self.assertIn("slot rules fit", extra[0]["body"])
        self.assertTrue(any(p.endswith("demo-assessment-unit/demo-assessment.md") for p in end["provenance"]["records"]))
        stages = {s["slug"]: s for s in end["header"]["stages"]}
        self.assertTrue(stages["demo-assessment-unit"]["ran"])
        self.assertEqual(stages["demo-assessment-unit"]["name"], "Demo Assessment (Unit)")

    def test_the_plan_page_does_not_list_the_after_stages(self):
        _p, plan, _i = self.finished()
        self.assertNotIn("demo-assessment-unit", [s["slug"] for s in plan["header"]["stages"]])

    def test_without_the_graph_the_unit_end_page_is_what_it_was(self):
        os.remove(os.path.join(self.project, ".claude", "tools", "data", "stage-graph.json"))
        end = self._end()
        self.assertEqual([r["id"] for r in tub.rows_of(end, "built")], ["B-1", "B-2"])


class TestMaps(tm.Sandbox):
    def test_landed_counts_the_units_last_stage(self):
        self.project()
        add_graph(self.proj)
        text = tm.fx.STATE + "- [ ] demo-assessment-unit — EXECUTE\n"
        text = text.replace("| unit | owner | functional-design | code-generation | gate | merged |",
                            "| unit | owner | functional-design | code-generation | demo-assessment-unit | gate | merged |")
        text = text.replace("| u1-core | max | [x] | [x] | [x] | [x] |", "| u1-core | max | [x] | [x] | [x] | [x] | [x] |")
        text = text.replace("| u2-pickup-slots | max | [x] | [ ] | [ ] | [ ] |", "| u2-pickup-slots | max | [x] | [x] | [ ] | [ ] | [ ] |")
        text = text.replace("| u3-order-page | | [ ] | [ ] | [ ] | [ ] |", "| u3-order-page | | [ ] | [ ] | [ ] | [ ] | [ ] |")
        text = text.replace("| u4-baker-list | | [ ] | [ ] | [ ] | [ ] |", "| u4-baker-list | | [ ] | [ ] | [ ] | [ ] | [ ] |")
        put(os.path.join(self.root, "aidlc-state.md"), text)
        status = {b["id"]: b["status"] for b in tm.mb.records(self.root, "units")["blocks"]}
        self.assertEqual(status["u2-pickup-slots"], "building", "code-generation done, the last stage not")
        put(os.path.join(self.root, "aidlc-state.md"), text.replace("| u2-pickup-slots | max | [x] | [x] | [ ]", "| u2-pickup-slots | max | [x] | [x] | [x]"))
        status = {b["id"]: b["status"] for b in tm.mb.records(self.root, "units")["blocks"]}
        self.assertEqual(status["u2-pickup-slots"], "landed")

    def test_a_completed_receipt_lands_a_unit_only_for_its_last_stage(self):
        self.project()
        add_graph(self.proj)
        put(os.path.join(self.root, "aidlc-state.md"), tm.fx.STATE + "- [ ] demo-assessment-unit — EXECUTE\n")
        status = {b["id"]: b["status"] for b in tm.mb.records(self.root, "units")["blocks"]}
        self.assertNotEqual(status["u4-baker-list"], "landed", "its receipt is of code-generation, no longer the last stage")

    def test_the_last_gate_needs_the_unit_map(self):
        self.project()
        add_graph(self.proj)
        self.assertEqual(tm.mb.required_kinds("demo-assessment-unit", project=self.proj), ["units"])
        self.assertEqual(tm.mb.required_kinds("code-generation", project=self.proj), [])
        self.assertEqual(tm.mb.required_kinds("code-generation", "unit-end", project=self.proj), ["units"])


class TestGuard(unittest.TestCase):
    def setUp(self):
        import tempfile, shutil
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.project = os.path.join(self.tmp, "project")
        self.intent = os.path.join(self.project, "aidlc", "spaces", "default", "intents", "260101-bakery-preorder")
        put(os.path.join(self.project, "aidlc", "active-space"), "default\n")
        put(os.path.join(self.project, "aidlc", "spaces", "default", "intents", "active-intent"), "260101-bakery-preorder\n")
        put(os.path.join(self.intent, "aidlc-state.md"), STATE)
        put(os.path.join(self.project, "aidlc", ".aidlc-unit-scope.json"),
            json.dumps({"version": 1, "unit": UNIT, "gate_rhythm": "unit-end", "space": "default"}))
        add_graph(self.project)

    def test_the_unit_end_gate_is_the_last_stage_and_the_plan_stays_at_code_generation(self):
        self.assertEqual(guard.unit_gate_stage(self.project), "demo-assessment-unit")
        self.assertEqual(guard.unit_rhythm(self.project, UNIT, "code-generation"), "unit-end")
        self.assertEqual(guard.unit_rhythm(self.project, UNIT, "demo-assessment-unit"), "unit-end")
        self.assertEqual(guard.unit_rhythm(self.project, UNIT, "functional-design"), "per-stage")
        self.assertEqual(guard.unit_rhythm(self.project, "u9-other", "demo-assessment-unit"), "per-stage")

    def test_a_per_stage_claim_stays_per_stage(self):
        put(os.path.join(self.project, "aidlc", ".aidlc-unit-scope.json"),
            json.dumps({"version": 1, "unit": UNIT, "gate_rhythm": "per-stage", "space": "default"}))
        self.assertEqual(guard.unit_rhythm(self.project, UNIT, "demo-assessment-unit"), "per-stage")

    def test_without_the_graph_the_gate_stage_is_code_generation(self):
        os.remove(os.path.join(self.project, ".claude", "tools", "data", "stage-graph.json"))
        self.assertEqual(guard.unit_gate_stage(self.project), "code-generation")

    def test_a_custom_stage_folder_is_not_a_unit(self):
        os.makedirs(os.path.join(self.intent, "construction", "demo-assessment-intent"))
        self.assertFalse(guard.has_units(self.project))
        os.makedirs(os.path.join(self.intent, "construction", UNIT))
        self.assertTrue(guard.has_units(self.project))


class TestRunOnceStageGate(GateCase):
    def test_a_run_once_custom_stage_is_a_per_stage_gate_with_its_graph_name(self):
        add_graph(self.project)
        put(os.path.join(record(self.project), "construction", "demo-assessment-intent", "assessment.md"),
            "# Assessment\n\nThe whole intent fits the budget.\n")
        code, out, err = self.run_script("--stage", "demo-assessment-intent", "--no-brief")
        self.assertEqual(code, 0, err)
        gate = self.gate()
        self.assertEqual((gate["stage"], gate["stageName"], gate["phase"]), ("demo-assessment-intent", "Demo Assessment (Intent)", "construction"))
        self.assertNotIn("unit", gate)


if __name__ == "__main__":
    unittest.main()
