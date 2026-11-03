"""Tests for shared/aidlc-links/aidlc_links.py: the registry's writer and reader, the places a hook derives a stage from,
and the backfill from transcripts."""

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
spec = importlib.util.spec_from_file_location("aidlc_links", os.path.join(ROOT, "shared", "aidlc-links", "aidlc_links.py"))
al = importlib.util.module_from_spec(spec)
spec.loader.exec_module(al)

REAL = os.path.join(os.path.expanduser("~"), ".claude", "plugins", "data", "aidlc-artifacts")


def real_listing():
    found = []
    for folder, dirs, files in os.walk(REAL):
        found += [os.path.join(folder, name) for name in dirs + files]
    return sorted(found)


BEFORE = real_listing()  # taken when the suite is loaded, before any test runs
ART = "https://claude.ai/artifact/abc123"
INTENT = "261027-demo"
STATE = """# State
## Stage Progress
### INCEPTION PHASE
- [x] user-stories — EXECUTE
- [x] units-generation — EXECUTE
### CONSTRUCTION PHASE
- [-] functional-design — EXECUTE
- [ ] code-generation — EXECUTE
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        patch = mock.patch.dict(os.environ, {"AIDLC_ARTIFACTS_DIR": os.path.join(self.tmp, "data")})
        patch.start()
        self.addCleanup(patch.stop)
        self.project = os.path.join(self.tmp, "proj")
        self.intent_dir = os.path.join(self.project, "aidlc", "spaces", "default", "intents", INTENT)
        os.makedirs(os.path.join(self.intent_dir, "construction", "u3-day-page"))
        with open(os.path.join(self.intent_dir, "aidlc-state.md"), "w") as f:
            f.write(STATE)

    def rec(self, kind="gate", row="r1", stage="user-stories", **kw):
        return al.record(self.project, "default", INTENT, kind, kw.pop("artifact", ART), row, stage, **kw)


class TestRegistry(Base):
    def test_the_file_is_one_per_checkout_and_intent_under_the_data_folder(self):
        self.rec()
        path = al.registry_path(self.project, "default", INTENT)
        self.assertTrue(path.startswith(os.path.join(self.tmp, "data", "links")))
        self.assertTrue(path.endswith("default--" + INTENT + ".json"))
        doc = json.load(open(path))
        self.assertEqual((doc["schema"], doc["intent"], doc["space"], doc["checkout"]), (al.SCHEMA, INTENT, "default", self.project))

    def test_an_entry_has_every_field_and_the_link_is_artifact_hash_row(self):
        made = self.rec("unit-end", "u3-unit-end-v6-20261027T1000", "code-generation", phase="construction", unit="u3-day-page",
                        rhythm="unit-end", revision=6, title="Unit end", session="s9")
        self.assertEqual(made["url"], ART + "#u3-unit-end-v6-20261027T1000")
        self.assertEqual({k: made[k] for k in ("artifact", "kind", "intent", "phase", "stage", "unit", "rhythm", "round", "revision", "title", "session")},
                         {"artifact": ART, "kind": "unit-end", "intent": INTENT, "phase": "construction", "stage": "code-generation",
                          "unit": "u3-day-page", "rhythm": "unit-end", "round": 1, "revision": 6, "title": "Unit end", "session": "s9"})
        self.assertRegex(made["createdAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_a_trailing_slash_or_hash_on_the_artifact_url_is_dropped(self):
        self.assertEqual(self.rec(artifact=ART + "/#old")["url"], ART + "#r1")

    def test_rounds_count_per_kind_stage_and_unit(self):
        self.rec(row="a")
        self.rec(row="b")
        self.rec(row="c", stage="requirements-analysis")
        self.rec("questions-form", row="d")
        rounds = {e["row"]: e["round"] for e in al.entries(self.project, "default", INTENT)}
        self.assertEqual(rounds, {"a": 1, "b": 2, "c": 1, "d": 1})

    def test_the_same_row_again_keeps_its_entry_and_takes_a_new_title(self):
        first = self.rec(title="")
        again = self.rec(title="Stories")
        self.assertEqual(again["createdAt"], first["createdAt"])
        found = al.entries(self.project, "default", INTENT)
        self.assertEqual([e["title"] for e in found], ["Stories"])

    def test_what_cannot_be_an_entry_is_refused_not_raised(self):
        self.assertIsNone(self.rec(kind="essay"))
        self.assertIsNone(self.rec(row=""))
        self.assertIsNone(self.rec(artifact=""))
        self.assertIsNone(self.rec(stage=""))
        self.assertEqual(al.entries(self.project, "default", INTENT), [])

    def test_a_damaged_file_reads_as_empty_and_is_replaced_by_the_next_write(self):
        self.rec()
        with open(al.registry_path(self.project, "default", INTENT), "w") as f:
            f.write("{not json")
        self.assertEqual(al.entries(self.project, "default", INTENT), [])
        self.assertIsNotNone(self.rec(row="again"))
        self.assertEqual(len(al.entries(self.project, "default", INTENT)), 1)

    def test_an_unwritable_registry_never_raises(self):
        blocked = os.path.join(self.tmp, "proj", "aidlc-state-is-a-file")
        open(blocked, "w").close()
        patch = mock.patch.dict(os.environ, {"AIDLC_ARTIFACTS_DIR": blocked})
        patch.start()
        self.addCleanup(patch.stop)
        self.assertIsNone(self.rec())

    def test_another_checkout_has_its_own_file(self):
        self.rec()
        self.assertEqual(al.entries(os.path.join(self.tmp, "other"), "default", INTENT), [])


class TestDerivation(Base):
    def test_a_questions_file_names_its_phase_stage_and_unit(self):
        inception = os.path.join(self.intent_dir, "inception", "user-stories", "user-stories-questions.md")
        unit = os.path.join(self.intent_dir, "construction", "u3-day-page", "functional-design", "functional-design-questions.md")
        self.assertEqual(al.questions_location(inception), (self.project, "default", INTENT, "inception", "user-stories", None))
        self.assertEqual(al.questions_location(unit), (self.project, "default", INTENT, "construction", "functional-design", "u3-day-page"))
        self.assertIsNone(al.questions_location(os.path.join(self.project, "aidlc", "spaces", "default", "x-questions.md")))
        self.assertIsNone(al.questions_location("/tmp/elsewhere-questions.md"))

    def test_the_phase_comes_from_the_state_file(self):
        self.assertEqual(al.phase_of(self.intent_dir, "user-stories"), "inception")
        self.assertEqual(al.phase_of(self.intent_dir, "functional-design"), "construction")
        self.assertEqual(al.phase_of(self.intent_dir, "nfr-design"), "construction")
        self.assertEqual(al.phase_of(self.intent_dir, "mystery"), "")

    def test_page_ids(self):
        self.assertEqual(al.bundle_page("demo-u3-unit-end-v6-20261027T1000"), ("unit-end", 6, "demo-u3"))
        self.assertEqual(al.bundle_page("demo-u3-plan-v1-20261027T1000"), ("unit-plan", 1, "demo-u3"))
        self.assertIsNone(al.bundle_page("demo-u3-20261027T1000"))
        self.assertEqual(al.test_plan_revision("demo-u3-test-v2-20261027T1000"), (2, "demo-u3"))

    def test_a_gate_id_splits_into_stage_and_unit_only_when_both_are_known(self):
        stages = ["user-stories", "functional-design", "code-generation"]
        units = {"u3-day-page"}
        self.assertEqual(al.split_gate_id(f"{INTENT}-user-stories-20261027T1000", INTENT, stages, units), ("user-stories", None))
        self.assertEqual(al.split_gate_id(f"{INTENT}-functional-design-u3-day-page-20261027T1000", INTENT, stages, units), ("functional-design", "u3-day-page"))
        self.assertIsNone(al.split_gate_id(f"{INTENT}-functional-design-u9-gone-20261027T1000", INTENT, stages, units))
        self.assertIsNone(al.split_gate_id(f"{INTENT}-mystery-20261027T1000", INTENT, stages, units))


class TestBackfill(Base):
    def transcript(self, calls):
        path = os.path.join(self.tmp, "t.jsonl")
        with open(path, "w") as f:
            for n, ti in enumerate(calls):
                f.write(json.dumps({"sessionId": "s1", "timestamp": f"t{n}", "message": {"content": [
                    {"type": "tool_use", "name": "ArtifactData", "input": ti}]}}) + "\n")
        return path

    def test_certain_rows_are_recorded_and_the_rest_listed_not_guessed(self):
        path = self.transcript([
            {"action": "batch", "url": ART, "writes": [
                {"op": "set", "collection": "gates", "doc_id": f"{INTENT}-user-stories-20261020T0900", "data": {"title": "Stories"}},
                {"op": "set", "collection": "gates", "doc_id": f"{INTENT}-mystery-20261020T0900", "data": {}},
                {"op": "set", "collection": "bundles", "doc_id": f"{INTENT}-u3-day-page-unit-end-v2-20261021T0900", "data": {}}]},
            {"action": "set", "url": ART, "collection": "plans", "doc_id": f"{INTENT}-u3-day-page-test-v1-20261022T0900", "data": {"unit": "u3-day-page"}},
            {"action": "set", "url": "https://claude.ai/artifact/other", "collection": "gates", "doc_id": f"{INTENT}-user-stories-20261020T1000", "data": {}},
            {"action": "get", "url": ART, "collection": "gates", "doc_id": "x"},
        ])
        recorded, undecided = al.backfill(self.project, "default", INTENT, [path], [ART])
        self.assertEqual([r["kind"] for r in recorded], ["gate", "unit-end", "test-plan"])
        self.assertEqual([u[0] for u in undecided], [f"{INTENT}-mystery-20261020T0900"])
        found = {e["kind"]: e for e in al.entries(self.project, "default", INTENT)}
        self.assertEqual((found["gate"]["stage"], found["gate"]["phase"], found["gate"]["title"], found["gate"]["session"]), ("user-stories", "inception", "Stories", "s1"))
        self.assertEqual((found["unit-end"]["unit"], found["unit-end"]["revision"], found["unit-end"]["stage"]), ("u3-day-page", 2, "code-generation"))
        self.assertTrue(all("judged" not in e for e in found.values()))

    def test_a_dry_run_records_nothing(self):
        path = self.transcript([{"action": "set", "url": ART, "collection": "gates", "doc_id": f"{INTENT}-user-stories-20261020T0900", "data": {}}])
        recorded, _ = al.backfill(self.project, "default", INTENT, [path], [], dry_run=True)
        self.assertEqual(len(recorded), 1)
        self.assertEqual(al.entries(self.project, "default", INTENT), [])

    def test_a_form_is_tied_to_its_stage_by_the_questions_file_it_names(self):
        rel = "aidlc/spaces/default/intents/%s/inception/user-stories/user-stories-questions.md" % INTENT
        path = self.transcript([{"action": "set", "url": ART, "collection": "forms", "doc_id": "f1", "data": {"file": rel}}])
        recorded, _ = al.backfill(self.project, "default", INTENT, [path])
        self.assertEqual([(r["kind"], r["stage"]) for r in recorded], [("questions-form", "user-stories")])


class TestZRealRegistryUntouched(unittest.TestCase):
    """Runs last (the name): a full run of this folder's tests leaves the real registry folder as it was."""

    def test_the_real_registry_folder_is_as_it_was_before_the_run(self):
        self.assertEqual(real_listing(), BEFORE)


if __name__ == "__main__":
    unittest.main()
