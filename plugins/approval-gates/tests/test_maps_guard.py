"""The guard holds the gates that settle the components and the Units to a current project map (approval-gates 1.32.0).

The hook runs as a subprocess, as test_gate_guard.py runs it, in a copy of map_fixture.py's bakery (four Units, three
components). The Approval question is refused without a map, and with a map built from older records; it passes with a
current one and in a project whose records hold nothing to map. Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import json
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import map_fixture as fx  # noqa: E402
from test_gate_guard import INTENT, PLUGIN, URL, Case  # noqa: E402

sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
import map_bundle as mb  # noqa: E402

MAPS_URL = "https://claude.ai/artifact/maps999"


class MapCase(Case):
    units = True
    components = True

    def setUp(self):
        super().setUp()
        shutil.rmtree(self.project)
        self.project, self.root = fx.make_project(self.tmp, units=self.units, components=self.components)
        self._env = os.environ.get("APPROVAL_GATES_DIR")
        os.environ["APPROVAL_GATES_DIR"] = self.state
        self.addCleanup(self.restore_env)

    def restore_env(self):
        if self._env is None:
            os.environ.pop("APPROVAL_GATES_DIR", None)
        else:
            os.environ["APPROVAL_GATES_DIR"] = self._env

    def map_row(self, kind, revision=1):
        """A `maps` row as map_bundle.py finalize leaves it, reduced to what the hook reads."""
        digest, _n = mb.subject_digest(self.root, kind)
        path = os.path.join(self.tmp, f"map-{kind}-{self.counter}.json")
        self.counter += 1
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"schema": mb.SCHEMA, "id": f"{INTENT}-{kind}", "intent": INTENT, "kind": kind, "digest": digest, "revision": revision}, f)
        return {"action": "batch", "url": MAPS_URL, "writes": [{"op": "set", "collection": "maps", "doc_id": f"{INTENT}-{kind}", "file_path": path}]}

    def publish_map(self, kind, revision=1):
        call = self.map_row(kind, revision)
        code, _out, err = self.pre("ArtifactData", call)
        self.assertEqual(code, 0, err)
        code, out, err = self.post("ArtifactData", call, {"ok": True})
        self.assertEqual(code, 0, err)
        return out

    def gate(self, stage, unit=None):
        """Open the gate, publish its page and send its link: what is left is the question."""
        self.open_gate(stage, unit)
        return self.publish(gate_id=f"{INTENT}-{stage}" + (f"-{unit}" if unit else "") + "-20260101T0900")

    def ask_gate(self):
        return self.ask("Domain Design complete. How would you like to proceed?")


class TestComponentMap(MapCase):
    def test_refused_without_a_map_with_the_recipe(self):
        self.gate("domain-design")
        code, _out, err = self.ask_gate()
        self.assertEqual(code, 2)
        self.assertIn("because the developer reads the component map at this gate and no component map was published", err)
        self.assertIn(os.path.join(PLUGIN, "scripts", "map_bundle.py"), err)
        self.assertIn("draft --kind components", err)
        self.assertIn("finalize --kind components", err)
        self.assertIn('"AI-DLC maps" artifact', err)
        self.assertIn("maps.html", err)

    def test_passes_with_a_current_map_and_the_hook_records_where_it_lives(self):
        self.gate("domain-design")
        out = self.publish_map("components")
        self.assertIn(f"maps/{INTENT}-components is published", self.context(out))
        code, _out, err = self.ask_gate()
        self.assertEqual(code, 0, err)
        published = mb.published(self.project, INTENT)
        self.assertEqual(published["components"]["url"], MAPS_URL)
        self.assertEqual(mb.links(self.project, INTENT)[0]["url"], f"{MAPS_URL}#{INTENT}-components")

    def test_a_map_built_before_the_components_changed_is_stale(self):
        self.gate("domain-design")
        self.publish_map("components")
        path = os.path.join(self.root, "inception", "domain-design", "components.md")
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n```yaml\ncomponents:\n  - name: Reminders\n    summary: Sends a reminder.\n    depends_on: []\n```\n")
        code, _out, err = self.ask_gate()
        self.assertEqual(code, 2)
        self.assertIn("was built from records that have changed since", err)

    def test_the_old_stage_name_is_held_too(self):
        self.gate("application-design")
        code, _out, err = self.ask("Application Design complete. How would you like to proceed?")
        self.assertEqual(code, 2)
        self.assertIn("component map", err)

    def test_the_gate_row_itself_is_not_written_before_the_map(self):
        self.open_gate("domain-design")
        call = self.batch(f"{INTENT}-domain-design-20260101T0900")
        with open(call["writes"][0]["file_path"], encoding="utf-8") as f:
            row = json.load(f)
        row["stage"] = "domain-design"
        with open(call["writes"][0]["file_path"], "w", encoding="utf-8") as f:
            json.dump(row, f)
        code, _out, err = self.pre("ArtifactData", call)
        self.assertEqual(code, 2)
        self.assertIn(f"the write of gates/{INTENT}-domain-design-20260101T0900", err)
        self.publish_map("components")
        self.assertEqual(self.pre("ArtifactData", call)[0], 0)

    def test_other_stages_are_not_held_to_a_component_map(self):
        self.gate("user-stories")
        self.assertEqual(self.ask("User Stories complete. How would you like to proceed?")[0], 0)


class TestUnitMap(MapCase):
    def ask_units(self):
        return self.ask("Units Generation complete. How would you like to proceed?")

    def test_units_generation_is_refused_without_the_unit_map(self):
        self.gate("units-generation")
        code, _out, err = self.ask_units()
        self.assertEqual(code, 2)
        self.assertIn("no unit map was published", err)
        self.assertIn("draft --kind units", err)

    def test_units_generation_passes_with_it_and_again_stale_after_a_redo(self):
        self.gate("units-generation")
        self.publish_map("units")
        self.assertEqual(self.ask_units()[0], 0)
        # Units Generation redone: a Unit leaves
        path = os.path.join(self.root, "inception", "units-generation", "unit-of-work-dependency.md")
        with open(path, encoding="utf-8") as f:
            text = f.read().replace("  - name: u4-baker-list\n    kind: ui\n    depends_on: [u1-core]\n", "")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        work = os.path.join(self.root, "inception", "units-generation", "unit-of-work.md")
        with open(work, encoding="utf-8") as f:
            table = f.read().replace("| U4 | u4-baker-list | The baker's morning list | ui | 3 | 2 |\n", "")
        with open(work, "w", encoding="utf-8") as f:
            f.write(table)
        self.open_gate("units-generation", result="revised")
        self.publish(gate_id=f"{INTENT}-units-generation-20260101T0910")
        code, _out, err = self.ask_units()
        self.assertEqual(code, 2)
        self.assertIn("was built from records that have changed since", err)
        self.publish_map("units", revision=2)
        self.assertEqual(self.ask_units()[0], 0)

    def test_a_unit_end_gate_wants_the_status_refreshed(self):
        self.gate("code-generation", "u2-pickup-slots")
        code, _out, err = self.ask("Code Generation complete. How would you like to proceed?")
        self.assertEqual(code, 2, "a per-stage Unit's last gate is where the Unit ends")
        self.assertIn("no unit map was published", err)
        self.publish_map("units")
        self.assertEqual(self.ask("Code Generation complete. How would you like to proceed?")[0], 0)
        # the Unit lands: the next unit-end gate needs the map again
        state = fx.STATE.replace("| u2-pickup-slots | max | [x] | [ ] | [ ] | [ ] |", "| u2-pickup-slots | max | [x] | [x] | [x] | [x] |")
        open(os.path.join(self.root, "aidlc-state.md"), "w", encoding="utf-8").write(state)
        self.open_gate("code-generation", "u3-order-page")
        self.publish(gate_id=f"{INTENT}-code-generation-u3-order-page-20260101T0930")
        code, _out, err = self.ask("Code Generation complete. How would you like to proceed?")
        self.assertEqual(code, 2)
        self.assertIn("was built from records that have changed since", err)

    def test_the_unit_end_page_of_the_unit_end_rhythm_needs_it_and_the_plan_page_does_not(self):
        self.assertEqual(mb.required_kinds("code-generation", "unit-end"), ["units"])
        self.assertEqual(mb.required_kinds("code-generation", "plan"), [])

    def test_a_unit_end_bundle_is_not_written_before_the_map(self):
        bundle_id = f"{INTENT}-u2-pickup-slots-unit-end-v1-20260101T0900"
        path = os.path.join(self.tmp, "bundle-row.json")
        json.dump({"bundle": {}, "page": "unit-end", "unit": "u2-pickup-slots"}, open(path, "w", encoding="utf-8"))
        call = {"action": "batch", "url": URL, "writes": [{"op": "set", "collection": "bundles", "doc_id": bundle_id, "file_path": path}]}
        code, _out, err = self.pre("ArtifactData", call)
        self.assertEqual(code, 2)
        self.assertIn(f"the write of bundles/{bundle_id}", err)
        plan = {"action": "batch", "url": URL, "writes": [{"op": "set", "collection": "bundles", "doc_id": bundle_id.replace("unit-end", "plan"), "file_path": path}]}
        self.assertEqual(self.pre("ArtifactData", plan)[0], 0, "the plan page is not held to the map")
        self.publish_map("units")
        self.assertEqual(self.pre("ArtifactData", call)[0], 0)


class TestNothingToMap(MapCase):
    units = False
    components = False

    def test_a_project_with_no_components_and_no_units_is_not_held_to_a_map(self):
        for stage, text in (("domain-design", "Domain Design complete."), ("units-generation", "Units Generation complete."),
                            ("code-generation", "Code Generation complete.")):
            self.gate(stage, "u1-core" if stage == "code-generation" else None)
            code, _out, err = self.ask(text + " How would you like to proceed?")
            self.assertEqual(code, 0, f"{stage}: {err}")


class TestOnlyUnits(MapCase):
    components = False

    def test_no_components_means_no_component_map_but_the_unit_map_still_holds(self):
        self.gate("domain-design")
        self.assertEqual(self.ask_gate()[0], 0)
        self.gate("units-generation")
        self.assertEqual(self.ask("Units Generation complete. How would you like to proceed?")[0], 2)


if __name__ == "__main__":
    unittest.main()
