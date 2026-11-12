"""The maps (1.32.0): scripts/map_bundle.py builds the rows of the "AI-DLC maps" artifact from an intent's records, and
skills/approval-gates/maps.html draws them.

Synthetic data only: map_fixture.py's bakery (four Units, three components). The script runs as the agent runs it; the page
runs under jsdom (drive_maps.js; the class skips without Node and the jsdom package). Run:
python3 -m unittest discover -s plugins/approval-gates/tests"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
import map_bundle as mb  # noqa: E402
import map_fixture as fx  # noqa: E402
from bundle_helpers import NODE  # noqa: E402

SCRIPT = os.path.join(PLUGIN, "scripts", "map_bundle.py")
PAGE = os.path.join(PLUGIN, "skills", "approval-gates", "maps.html")
DRIVER = os.path.join(HERE, "drive_maps.js")


class Sandbox(unittest.TestCase):
    """A bakery project and a state folder of its own: nothing here touches ~/.claude."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = os.path.join(self.tmp, "state")
        self._env = os.environ.get("APPROVAL_GATES_DIR")
        os.environ["APPROVAL_GATES_DIR"] = self.state
        self.addCleanup(self.restore)

    def restore(self):
        if self._env is None:
            os.environ.pop("APPROVAL_GATES_DIR", None)
        else:
            os.environ["APPROVAL_GATES_DIR"] = self._env
        shutil.rmtree(self.tmp, ignore_errors=True)

    def project(self, **kw):
        self.proj, self.root = fx.make_project(self.tmp, **kw)
        return self.proj

    def run_script(self, *args, ok=True):
        done = subprocess.run([sys.executable, SCRIPT, *args, "--project-dir", self.proj], capture_output=True, text=True,
                              env=dict(os.environ, APPROVAL_GATES_DIR=self.state), timeout=120)
        if ok:
            self.assertEqual(done.returncode, 0, done.stderr)
        return done

    def build(self, kind, tweak=None, out=None):
        """draft, let the agent fill the judgment, finalize: the row."""
        out = out or os.path.join(self.tmp, "out-" + kind)
        self.run_script("draft", "--kind", kind, "--out", out)
        if kind in mb.GRAPH:
            path = os.path.join(out, "judgment.json")
            with open(path, encoding="utf-8") as f:
                j = json.load(f)
            if not j["groups"]:
                j["groups"] = [{"key": "core", "label": "Core"}]
            for k, e in j["blocks"].items():
                e["group"] = e["group"] or j["groups"][0]["key"]
                e["summary"] = e["summary"] or f"{k} is one part of the bakery."
            if tweak:
                tweak(j)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(j, f)
        done = self.run_script("finalize", "--kind", kind, "--out", out)
        with open(os.path.join(out, "row.json"), encoding="utf-8") as f:
            return json.load(f), done


class UnitRecords(Sandbox):
    def test_units_dependencies_waves_points_stories(self):
        self.project()
        rec = mb.records(self.root, "units")
        by = {b["id"]: b for b in rec["blocks"]}
        self.assertEqual(sorted(by), ["u1-core", "u2-pickup-slots", "u3-order-page", "u4-baker-list"])
        self.assertEqual(by["u1-core"]["label"], "U1")
        self.assertEqual([n["id"] for n in by["u3-order-page"]["needs"]], ["u1-core", "u2-pickup-slots"])
        self.assertEqual(by["u3-order-page"]["needs"][1]["why"], "the page offers the slots the service lists")
        self.assertEqual({k: b["layer"] for k, b in by.items()}, {"u1-core": 1, "u2-pickup-slots": 2, "u4-baker-list": 2, "u3-order-page": 3})
        self.assertEqual(by["u3-order-page"]["points"], 8, "unit-points.csv wins over the Units table")
        self.assertEqual(by["u2-pickup-slots"]["pointsSource"], "ai")
        self.assertEqual(by["u1-core"]["stories"], ["US1.1"])
        self.assertEqual(by["u3-order-page"]["stories"], ["US1.1"])
        self.assertEqual([w["points"] for w in rec["waves"]], [5, 6, 8])
        self.assertEqual(rec["warnings"], [])

    def test_a_unit_that_depends_on_nothing_the_documents_define_is_a_warning_not_an_edge(self):
        self.project()
        path = os.path.join(self.root, "inception", "units-generation", "unit-of-work-dependency.md")
        text = open(path, encoding="utf-8").read().replace("depends_on: [u1-core]\n  - name: u3", "depends_on: [u9-ghost]\n  - name: u3")
        open(path, "w", encoding="utf-8").write(text)
        rec = mb.records(self.root, "units")
        self.assertTrue(any("u9-ghost" in w for w in rec["warnings"]), rec["warnings"])
        self.assertEqual([n["id"] for b in rec["blocks"] if b["id"] == "u2-pickup-slots" for n in b["needs"]], [])

    def test_landed_from_the_table_from_a_receipt_with_an_empty_cell_and_not_from_nothing(self):
        self.project()
        status = {b["id"]: b["status"] for b in mb.records(self.root, "units")["blocks"]}
        self.assertEqual(status["u1-core"], "landed", "merged [x] in the Unit Progress table")
        self.assertEqual(status["u4-baker-list"], "landed", "a UNIT_COMPLETED code-generation receipt, every table cell empty")
        self.assertEqual(status["u2-pickup-slots"], "building", "a stage done, nothing landed")
        self.assertEqual(status["u3-order-page"], "planned")

    def test_a_merged_receipt_lands_a_unit_and_a_later_start_means_built_again(self):
        merged = fx.AUDIT.replace("UNIT_COMPLETED", "UNIT_MERGED").replace("**Stage**: code-generation\n", "").replace("u4-baker-list", "u3-order-page")
        self.project(audit=merged)
        status = {b["id"]: b["status"] for b in mb.records(self.root, "units")["blocks"]}
        self.assertEqual(status["u3-order-page"], "landed", "UNIT_MERGED, no stage")
        redo = fx.AUDIT + ("\n## Unit Started\n**Timestamp**: 2026-01-03T09:00:00Z\n**Event**: UNIT_STARTED\n**Stage**: functional-design\n"
                           "**Unit**: u4-baker-list\n\n---\n")
        shutil.rmtree(self.tmp)
        os.makedirs(self.tmp)
        self.project(audit=redo)
        status = {b["id"]: b["status"] for b in mb.records(self.root, "units")["blocks"]}
        self.assertEqual(status["u4-baker-list"], "building", "started again after it landed")

    def test_a_receipt_in_aidlc_state_counts_too(self):
        self.project(audit=None, state=fx.STATE + "\n## Audit\n**Timestamp**: 2026-01-02T09:00:00Z\n**Event**: UNIT_COMPLETED\n**Stage**: code-generation\n**Unit**: u3-order-page\n\n---\n")
        status = {b["id"]: b["status"] for b in mb.records(self.root, "units")["blocks"]}
        self.assertEqual(status["u3-order-page"], "landed")

    def test_no_units_means_nothing_to_map(self):
        self.project(units=False)
        rec = mb.records(self.root, "units")
        self.assertEqual(rec["blocks"], [])
        self.assertFalse(mb.has_subject(rec))
        self.assertEqual(mb.subject_digest(self.root, "units"), (None, 0))
        out = os.path.join(self.tmp, "out")
        done = self.run_script("draft", "--kind", "units", "--out", out)
        report = json.loads(done.stdout)
        self.assertFalse(report["subject"])
        self.assertIn("Nothing to map", report["todo"][0])
        checked = json.loads(self.run_script("check", "--kind", "units").stdout)[0]
        self.assertEqual((checked["subject"], checked["fresh"]), (False, True), "a project with no Units is not held to a map")

    def test_a_redo_changes_the_digest_and_the_row_marks_what_moved(self):
        self.project()
        first, _ = self.build("units")
        self.assertEqual(first["revision"], 1)
        self.assertNotIn("previous", first)
        again, _ = self.build("units", out=os.path.join(self.tmp, "again"))
        self.assertEqual(again["revision"], 1, "nothing changed: the same revision")
        # Units Generation redone: u4 is gone, u5 is new, u3 now also needs u4's replacement, u1 gets a different point count
        base = os.path.join(self.root, "inception", "units-generation")
        work = open(os.path.join(base, "unit-of-work.md"), encoding="utf-8").read()
        work = work.replace("| U4 | u4-baker-list | The baker's morning list | ui | 3 | 2 |", "| U5 | u5-baker-screen | The baker's morning screen | ui | 3 | 2 |")
        open(os.path.join(base, "unit-of-work.md"), "w", encoding="utf-8").write(work)
        dep = open(os.path.join(base, "unit-of-work-dependency.md"), encoding="utf-8").read().replace("u4-baker-list", "u5-baker-screen")
        open(os.path.join(base, "unit-of-work-dependency.md"), "w", encoding="utf-8").write(dep)
        story = open(os.path.join(base, "unit-of-work-story-map.md"), encoding="utf-8").read().replace("U4", "U5").replace("u4-baker-list", "u5-baker-screen")
        open(os.path.join(base, "unit-of-work-story-map.md"), "w", encoding="utf-8").write(story)
        second, done = self.build("units", out=os.path.join(self.tmp, "second"))
        self.assertEqual(second["revision"], 2)
        self.assertNotEqual(second["digest"], first["digest"])
        self.assertEqual(sorted(second["previous"]["blocks"]), sorted(b["id"] for b in first["blocks"]))
        self.assertEqual(second["previous"]["revision"], 1)
        report = json.loads(done.stdout)["maps"][0]
        self.assertEqual(report["changed"]["new"], 1)
        self.assertEqual(report["changed"]["removed"], 1)

    def test_status_alone_makes_a_new_revision(self):
        self.project()
        first, _ = self.build("units")
        row = copy.deepcopy(first)
        state = fx.STATE.replace("| u3-order-page | | [ ] | [ ] | [ ] | [ ] |", "| u3-order-page | | [x] | [x] | [x] | [x] |")
        open(os.path.join(self.root, "aidlc-state.md"), "w", encoding="utf-8").write(state)
        second, _ = self.build("units", out=os.path.join(self.tmp, "second"))
        self.assertEqual(second["revision"], 2)
        self.assertEqual({b["id"]: b["status"] for b in second["blocks"]}["u3-order-page"], "landed")
        self.assertEqual(second["previous"]["blocks"]["u3-order-page"]["status"], "planned")
        del row

    def test_the_judgment_is_kept_for_the_blocks_that_remain(self):
        self.project()
        first, _ = self.build("units", tweak=lambda j: j["blocks"]["u1-core"].update(summary="The heart of the bakery orders."))
        out = os.path.join(self.tmp, "next")
        self.run_script("draft", "--kind", "units", "--out", out)
        with open(os.path.join(out, "judgment.json"), encoding="utf-8") as f:
            j = json.load(f)
        self.assertEqual(j["blocks"]["u1-core"]["summary"], "The heart of the bakery orders.")
        self.assertEqual(j["blocks"]["u1-core"]["_from"], "your last judgment")
        del first


class Finalize(Sandbox):
    def test_refused_in_the_house_shape_until_every_block_has_a_summary_and_a_group(self):
        self.project()
        out = os.path.join(self.tmp, "out")
        self.run_script("draft", "--kind", "components", "--out", out)
        done = self.run_script("finalize", "--kind", "components", "--out", out, ok=False)
        self.assertEqual(done.returncode, 1)
        text = done.stderr
        self.assertTrue(text.startswith("Refused: the components map, because "), text)
        self.assertIn("Do this:\n1. ", text)
        self.assertIn("- OrderService: no group", text)
        self.assertIn("It worked when: ", text)
        self.assertFalse(os.path.exists(os.path.join(out, "writes.json")))

    def test_an_ellipsis_a_long_summary_and_a_stale_block_are_refused(self):
        self.project()
        out = os.path.join(self.tmp, "out")
        self.run_script("draft", "--kind", "units", "--out", out)
        path = os.path.join(out, "judgment.json")
        j = json.load(open(path, encoding="utf-8"))
        j["blocks"]["u1-core"]["summary"] = "It does a lot of things and then…"
        j["blocks"]["u2-pickup-slots"]["summary"] = "x" * 300
        j["blocks"]["u9-ghost"] = {"summary": "gone", "group": "service"}
        j["blocks"]["u3-order-page"]["group"] = "nowhere"
        json.dump(j, open(path, "w", encoding="utf-8"))
        text = self.run_script("finalize", "--kind", "units", "--out", out, ok=False).stderr
        for needle in ("u1-core: the summary ends in an ellipsis", "u2-pickup-slots: the summary is 300 characters", "u9-ghost", "group 'nowhere' is not in groups"):
            self.assertIn(needle, text)

    def test_the_batch_writes_one_row_per_kind_into_the_maps_collection(self):
        self.project()
        row, _ = self.build("components", tweak=lambda j: j["blocks"]["BakerList"].update(group="core"))
        writes = json.load(open(os.path.join(self.tmp, "out-components", "writes.json"), encoding="utf-8"))
        self.assertEqual(writes, [{"op": "set", "collection": "maps", "doc_id": "260101-bakery-preorder-components", "file_path": os.path.join(self.tmp, "out-components", "row.json")}])
        self.assertEqual(row["schema"], "aidlc-map/1")
        self.assertEqual(row["id"], "260101-bakery-preorder-components")
        self.assertEqual(row["view"], "graph")
        by = {b["id"]: b for b in row["blocks"]}
        self.assertEqual([n["id"] for n in by["OrderService"]["needs"]], ["SlotCalendar"])
        self.assertEqual(by["SlotCalendar"]["usedBy"], ["OrderService"])
        self.assertEqual(by["BakerList"]["needs"][0]["why"], "reads the orders of a day")
        self.assertEqual(by["OrderService"]["entities"], ["Loaf", "Order"])

    def test_stories_and_entities_are_matrices_with_their_gaps(self):
        self.project()
        stories, _ = self.build("stories")
        self.assertEqual(stories["view"], "matrix")
        self.assertEqual(stories["cells"]["US1.1"], ["u1-core", "u3-order-page"])
        self.assertEqual(stories["cells"]["US3.1"], [], "a story in stories.md that no Unit builds is a gap")
        self.assertTrue([r for r in stories["rows"] if r["id"] == "US3.1"][0]["uncovered"])
        entities, _ = self.build("entities")
        self.assertEqual(entities["cells"]["Order"], ["BakerList", "OrderService"])

    def test_the_second_finalize_of_an_unchanged_map_keeps_its_revision_and_a_changed_one_adds_one(self):
        self.project()
        one, _ = self.build("stories")
        two, _ = self.build("stories", out=os.path.join(self.tmp, "two"))
        self.assertEqual((one["revision"], two["revision"]), (1, 1))
        story = os.path.join(self.root, "inception", "units-generation", "unit-of-work-story-map.md")
        open(story, "a", encoding="utf-8").write("| US3.1 | U4 | u4-baker-list |\n")
        three, done = self.build("stories", out=os.path.join(self.tmp, "three"))
        self.assertEqual(three["revision"], 2)
        self.assertEqual(json.loads(done.stdout)["maps"][0]["changed"]["new"], 1)

    def test_components_in_prose_form_are_read_too(self):
        self.project(components=False)
        text = ("# Component Inventory\n\n## Components\n\n### App\n- **Type**: Layout\n- **Responsibility**: Root component, renders TodoList\n"
                "- **Dependencies**: TodoList\n\n### TodoList\n- **Type**: Container\n- **Responsibility**: Manages the list\n- **Dependencies**: None\n")
        fx.put(os.path.join(self.root, "inception", "application-design", "components.md"), text)
        rec = mb.records(self.root, "components")
        by = {b["id"]: b for b in rec["blocks"]}
        self.assertEqual([n["id"] for n in by["App"]["needs"]], ["TodoList"])
        self.assertEqual((by["TodoList"]["layer"], by["App"]["layer"]), (1, 2))
        self.assertEqual(by["App"]["kind"], "layout")


class Contract(Sandbox):
    def test_every_row_the_script_writes_holds_to_map_schema_json(self):
        import validate_bundle
        with open(os.path.join(PLUGIN, "contract", "map.schema.json"), encoding="utf-8") as f:
            schema = json.load(f)
        self.project()
        for kind in mb.KINDS:
            row, _ = self.build(kind)
            problems = []
            validate_bundle.check_schema(row, schema, schema, kind, problems)
            self.assertEqual(problems, [], kind)
        # a row with a previous revision
        os.makedirs(os.path.join(self.tmp, "x"), exist_ok=True)
        open(os.path.join(self.root, "aidlc-state.md"), "w", encoding="utf-8").write(fx.STATE.replace("| u3-order-page | | [ ] | [ ] | [ ] | [ ] |", "| u3-order-page | | [x] | [x] | [x] | [x] |"))
        row, _ = self.build("units", out=os.path.join(self.tmp, "second"))
        problems = []
        validate_bundle.check_schema(row, schema, schema, "units", problems)
        self.assertEqual(problems, [])
        self.assertIn("previous", row)
        row["blocks"][0]["surprise"] = 1
        problems = []
        validate_bundle.check_schema(row, schema, schema, "units", problems)
        self.assertTrue(problems)


class MiniYaml(unittest.TestCase):
    def test_the_subset_the_records_use(self):
        v = mb.parse_yaml("components:\n  - name: A\n    summary: x\n    behaviour: >\n      one\n      two\n    depends_on: []\n    dependents:\n      - component: B\n        interaction: reads\n    ext:\n      - name: S3\n    tags: [a, 'b c']\n")
        c = v["components"][0]
        self.assertEqual((c["name"], c["behaviour"], c["depends_on"], c["tags"]), ("A", "one two", [], ["a", "b c"]))
        self.assertEqual(c["dependents"], [{"component": "B", "interaction": "reads"}])
        self.assertEqual(c["ext"], [{"name": "S3"}])


class Freshness(Sandbox):
    def test_a_map_is_fresh_while_the_records_say_what_it_says(self):
        self.project()
        row, _ = self.build("units")
        before = mb.freshness(self.proj, "units")
        self.assertEqual((before["subject"], before["published"], before["fresh"]), (True, False, False))
        mb.record_published(self.proj, "260101-bakery-preorder", "units", row["id"], "https://claude.ai/artifact/abc", row["digest"], row["revision"])
        after = mb.freshness(self.proj, "units")
        self.assertTrue(after["fresh"])
        self.assertEqual(after["url"], "https://claude.ai/artifact/abc#260101-bakery-preorder-units")
        open(os.path.join(self.root, "aidlc-state.md"), "w", encoding="utf-8").write(fx.STATE.replace("| u3-order-page | | [ ] | [ ] | [ ] | [ ] |", "| u3-order-page | | [x] | [ ] | [ ] | [ ] |"))
        self.assertFalse(mb.freshness(self.proj, "units")["fresh"], "a Unit's status moved: the map is stale")
        self.assertEqual(mb.links(self.proj, "260101-bakery-preorder")[0]["url"], "https://claude.ai/artifact/abc#260101-bakery-preorder-units")

    def test_the_stages_that_need_a_map(self):
        self.assertEqual(mb.required_kinds("domain-design"), ["components"])
        self.assertEqual(mb.required_kinds("application-design"), ["components"])
        self.assertEqual(mb.required_kinds("units-generation"), ["units"])
        self.assertEqual(mb.required_kinds("code-generation", "unit-end"), ["units"])
        self.assertEqual(mb.required_kinds("code-generation", "plan"), [])
        self.assertEqual(mb.required_kinds("code-generation"), ["units"], "a per-stage Unit's last gate")
        self.assertEqual(mb.required_kinds("user-stories"), [])


def graph_rows(n=52, groups=5, rev=1):
    """A synthetic Unit map of n blocks over several waves; blocks of a wave need blocks of the wave before."""
    blocks = []
    for i in range(n):
        blocks.append({"id": f"blk-{i:02d}", "label": f"U{i + 1}", "title": f"Block {i}", "group": f"g{i % groups}",
                       "summary": f"Block {i} does one thing (US1.{i % 4 + 1}).", "layer": 1 + i // 9, "needs": [], "usedBy": [],
                       "status": "landed" if i < 6 else ("building" if i < 9 else "planned"), "points": i % 5 + 1})
    for i, b in enumerate(blocks):
        if b["layer"] > 1:
            for j in sorted({(i * 7) % 9 + 9 * (b["layer"] - 2), (i * 3) % 9 + 9 * (b["layer"] - 2)}):
                if j < n:
                    b["needs"].append({"id": blocks[j]["id"], "why": f"uses {blocks[j]['id']}"})
    by = {b["id"]: b for b in blocks}
    for b in blocks:
        for nd in b["needs"]:
            by[nd["id"]]["usedBy"].append(b["id"])
    return {"id": "260101-x-units", "schema": "aidlc-map/1", "intent": "260101-x", "kind": "units", "title": "Unit map", "view": "graph",
            "revision": rev, "builtAt": "2026-01-01T10:00:00Z", "layerName": "Wave", "digest": "d",
            "groups": [{"key": f"g{i}", "label": f"Group {i}"} for i in range(groups)], "blocks": blocks,
            "waves": [{"n": l, "title": f"Wave {l}", "units": [b["id"] for b in blocks if b["layer"] == l],
                       "points": sum(b["points"] for b in blocks if b["layer"] == l),
                       "landed": sum(1 for b in blocks if b["layer"] == l and b["status"] == "landed")} for l in sorted({b["layer"] for b in blocks})],
            "ids": {"US1.1": {"kind": "Story", "title": "Order loaves", "text": "A customer orders loaves.", "doc": "inception/user-stories/stories.md", "line": 3}}}


def ready_rows():
    """Seven Units: what is Ready is c (both needs landed) and g (needs nothing, not started); d waits for c; e is being built; f has landed."""
    def b(i, status, needs, layer):
        return {"id": i, "label": i.upper()[:2], "title": i, "group": "g0", "summary": f"{i} does one thing.", "layer": layer, "status": status, "points": 1,
                "needs": [{"id": n, "why": ""} for n in needs], "usedBy": []}
    blocks = [b("a-landed", "landed", [], 1), b("b-landed", "landed", [], 1), b("c-after-two", "planned", ["a-landed", "b-landed"], 2),
              b("d-half", "planned", ["a-landed", "c-after-two"], 3), b("e-building", "building", ["b-landed"], 2), b("f-done", "landed", [], 1), b("g-no-needs", "planned", [], 1)]
    by = {x["id"]: x for x in blocks}
    for x in blocks:
        for n in x["needs"]:
            by[n["id"]]["usedBy"].append(x["id"])
    return {"id": "260101-x-units", "schema": "aidlc-map/1", "intent": "260101-x", "kind": "units", "title": "Unit map", "view": "graph", "revision": 1,
            "builtAt": "2026-01-01T10:00:00Z", "layerName": "Wave", "digest": "d", "groups": [{"key": "g0", "label": "Group 0"}], "blocks": blocks,
            "waves": [{"n": l, "title": f"Wave {l}", "units": [x["id"] for x in blocks if x["layer"] == l], "points": 1, "landed": sum(1 for x in blocks if x["layer"] == l and x["status"] == "landed")} for l in (1, 2, 3)],
            "ids": {}}


def story_row():
    """Stories by Units, round 2: one gap, and against round 1 a new Unit, one new link and one link that is gone."""
    return {"id": "260101-x-stories", "schema": "aidlc-map/1", "intent": "260101-x", "kind": "stories", "title": "Story map", "view": "matrix",
            "revision": 2, "builtAt": "2026-01-01T10:00:00Z", "rowsTitle": "Story", "colsTitle": "Unit", "digest": "d",
            "rows": [{"id": "US1.1", "label": "US1.1", "title": "Order loaves", "uncovered": False}, {"id": "US1.2", "label": "US1.2", "title": "Slots", "uncovered": False},
                     {"id": "US3.1", "label": "US3.1", "title": "Reminder", "uncovered": True}],
            "cols": [{"id": "u1", "label": "U1", "title": "Core", "layer": 1, "status": "landed"}, {"id": "u2", "label": "U2", "title": "Slots", "layer": 2, "status": "planned"}],
            "cells": {"US1.1": ["u1", "u2"], "US1.2": ["u2"], "US3.1": []},
            "previous": {"revision": 1, "builtAt": "x", "rows": {"US1.1": {"title": "Order loaves", "uncovered": False}, "US1.2": {"title": "Slots", "uncovered": False}, "US3.1": {"title": "Reminder", "uncovered": True}},
                         "cols": {"u1": {"title": "Core", "status": "planned"}, "u0": {"title": "Old", "status": "planned"}}, "cells": ["US1.1|u1", "US1.1|u2", "US1.2|u1"]}}


def has_jsdom():
    return bool(NODE) and subprocess.run([NODE, "-e", "require('jsdom')"], capture_output=True).returncode == 0


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class Page(unittest.TestCase):
    def drive(self, rows, scenario, hash_="", env=None):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "rows.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rows, f)
            done = subprocess.run([NODE, DRIVER, PAGE, path, scenario, hash_], capture_output=True, text=True, timeout=120,
                                  env=dict(os.environ, **(env or {})))
            self.assertEqual(done.returncode, 0, done.stderr)
            out = json.loads(done.stdout)
            self.assertNotIn("error", out, out.get("error"))
            self.assertNotIn("Error", done.stderr, done.stderr)
            return out
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_index_lists_intents_and_their_maps(self):
        a, b = graph_rows(6), graph_rows(6)
        b["id"], b["kind"], b["title"] = "260101-x-components", "components", "Component map"
        out = self.drive([a, b], "index")
        self.assertEqual(out["heads"], ["260101-x"])
        self.assertEqual([r["href"] for r in out["rows"]], ["#260101-x-components", "#260101-x-units"])
        self.assertIn("6 blocks", out["rows"][0]["text"])

    def test_fifty_two_blocks_one_pick_shows_only_its_edges_and_its_neighbours(self):
        out = self.drive([graph_rows(52)], "graph", "260101-x-units", {"PICK_ID": "blk-20", "SEARCH": "blk-3"})
        self.assertEqual(out["blocks"], 52)
        self.assertEqual(out["edgesTotal"], 0, "no edge is drawn until a block is picked")
        self.assertEqual(out["edgesOn0"], [])
        self.assertEqual(len(out["cols"]), 6)
        self.assertTrue(out["cols"][0].startswith("Wave 1 9 · 25 pt · 6"), out["cols"][0])
        self.assertEqual(out["sel"], ["blk-20"])
        self.assertEqual(sorted(out["edgesOn1"]), sorted(["blk-14>blk-20", "blk-15>blk-20", "blk-20>blk-35"]))
        self.assertTrue(out["edgeShapes"] and all(out["edgeShapes"]), "each edge is a rounded orthogonal path")
        self.assertEqual(sorted(out["dep"]), ["blk-14", "blk-15"])
        self.assertEqual(out["user"], ["blk-35"])
        self.assertIn("Needs first (2)", out["panel1"])
        self.assertIn("Waiting for it (1)", out["panel1"])
        self.assertIn("uses blk-14", out["panel1"])
        self.assertEqual(out["hash"], "#260101-x-units/blk-20")
        self.assertFalse(out["bar"]["edgesToggle"], "Show every edge is replaced by the hover preview")
        self.assertGreater(out["previewEdges"], -1)
        self.assertEqual(out["previewGone"], 0)
        self.assertTrue(out["tabindex"] and out["roles"], "every block is reachable by keyboard")
        self.assertEqual(out["went"]["sel"], [out["went"]["to"]], "a neighbour in the panel is a link that picks it")
        self.assertTrue(out["rail0"] and not out["railAfter"], "the panel is a narrow rail until something is picked")

    def test_hovering_a_block_previews_its_edges_when_nothing_is_picked(self):
        out = self.drive([graph_rows(52)], "graph", "260101-x-units", {"PICK": "20", "PICK_ID": "blk-00"})
        self.assertEqual(out["previewEdges"], 3, "blk-20: two needs and one that waits")
        self.assertEqual(out["previewGone"], 0)

    def test_the_fit_view_shows_every_wave_in_compact_cards_without_scrolling_sideways(self):
        for avail in ("1000", "700", "450"):
            out = self.drive([graph_rows(52)], "graph", "260101-x-units", {"AVAIL": avail, "PICK_ID": "blk-20"})
            fit = out["fit"]
            self.assertIn("fit", fit["canvas"])
            self.assertEqual(fit["labels"], 6, "every wave has its column at " + avail)
            self.assertEqual(fit["compact"], 52, "compact cards")
            self.assertEqual(fit["summaryLines"], 0, "no summary line on a compact card")
            self.assertLessEqual(fit["planeWidth"], int(avail), "the drawing fits the width it may use at " + avail)
            self.assertLessEqual(fit["maxRight"], fit["planeWidth"])
            self.assertEqual(fit["overlap"], 0)
        wide = self.drive([graph_rows(52)], "graph", "260101-x-units", {"AVAIL": "1000"})["fit"]
        narrow = self.drive([graph_rows(52)], "graph", "260101-x-units", {"AVAIL": "450"})["fit"]
        self.assertLess(wide["bands"], narrow["bands"], "a narrow width wraps the waves into bands, never into a sideways scroll")

    def test_a_long_wave_wraps_into_columns(self):
        row = graph_rows(30)
        for b in row["blocks"]:
            b["layer"] = 1
        row["waves"] = [{"n": 1, "title": "Wave 1", "units": [b["id"] for b in row["blocks"]], "points": 90, "landed": 6}]
        out = self.drive([row], "graph", "260101-x-units", {"AVAIL": "1000"})
        self.assertEqual(out["fit"]["labels"], 1)
        self.assertGreater(out["fit"]["planeWidth"], 300, "30 blocks in one wave take several columns, not one tall one")

    def test_zoom_fit_and_comfortable(self):
        out = self.drive([graph_rows(52)], "zoom", "260101-x-units", {"AVAIL": "1000"})
        self.assertEqual((out["zoom0"], out["zoom1"], out["zoom2"]), ("fit", "comfy", "fit"))
        self.assertEqual(out["cmp0"], 52)
        self.assertEqual(out["cmp1"], 0, "Comfortable is today's full card")
        self.assertEqual(out["n2"], 52, "with its second line")
        self.assertGreater(out["width1"], out["width0"])

    def test_one_tab_stop_for_the_graph_and_no_link_inside_a_card(self):
        out = self.drive([graph_rows(30)], "graph", "260101-x-units", {"PICK_ID": "blk-05"})
        self.assertEqual(out["tabStops"], 1)
        self.assertEqual(out["tabStopsAfterArrow"], 1, "arrows move the one stop")
        self.assertEqual(out["cardIdLinks"], 0, "the id link is in the panel, not on the card")
        self.assertTrue(any(x.startswith("U") for x in [l.split("|")[0] for l in out["panelLinks"]] + ["U"]))

    def test_search_a_group_chip_and_the_keys(self):
        out = self.drive([graph_rows(52)], "graph", "260101-x-units", {"PICK_ID": "blk-20", "SEARCH": "blk-3"})
        self.assertEqual(out["dimmed"], 52 - 10, "blk-3x: ten blocks match")
        self.assertEqual(out["pickAfterSearch"], 0, "typing in the search lets the pick go: the two do not fight")
        self.assertEqual(out["offAfterChip"], 11, "a hidden group greys its blocks (52 over 5 groups)")
        self.assertEqual(out["chipPressed"], "false")
        self.assertTrue(out["arrowFocus"], "an arrow key moves between blocks")

    def test_ids_in_the_panel_are_links_with_a_tooltip(self):
        out = self.drive([graph_rows(12)], "graph", "260101-x-units", {"PICK_ID": "blk-00"})
        links = [x for x in out["panelLinks"] if x.startswith("US1.1|")]
        self.assertTrue(links, out["panelLinks"])
        self.assertIn("Story US1.1: Order loaves", links[0])

    def test_at_phone_width_the_map_is_a_list_with_the_same_panel(self):
        out = self.drive([graph_rows(52)], "list", "260101-x-units", {"PICK_ID": "blk-20"})
        self.assertEqual(out["listRows"], 52)
        self.assertEqual(out["edgesTotal"], 0, "no drawing")
        self.assertEqual(out["bar"]["views"], [], "no Graph/List switch where the graph cannot be shown")
        self.assertEqual(out["bar"]["zooms"], [])
        self.assertEqual(len(out["lists"]) - sum(1 for x in out["lists"] if not x.startswith("Wave")), 6)
        self.assertIn("Needs first (2)", out["panel1"])
        self.assertIn("blk-35", out["panel1"])

    def test_ready_is_every_need_landed_and_not_landed_itself(self):
        out = self.drive([ready_rows()], "ready", "260101-x-units")
        self.assertEqual(out["readyNodes"], ["c-after-two", "g-no-needs"])
        self.assertIn("2 ready", out["stats"])
        self.assertIn("Ready now 2", out["chip"])
        self.assertEqual(out["readyOnLanded"], 0, "a landed block is never Ready")
        self.assertEqual(out["readyOnBuilding"], 0, "nor one that is being built")
        self.assertEqual(out["pressed"], "true")
        self.assertEqual(sorted(out["litWhenOn"]), ["c-after-two", "g-no-needs"], "the chip lights only what could start now")
        self.assertEqual(out["dimmedWhenOff"], 0)

    def test_the_panel_says_for_each_need_whether_it_has_landed(self):
        d = self.drive([ready_rows()], "graph", "260101-x-units", {"PICK_ID": "d-half"})
        self.assertEqual(d["needMarks"], ["landed", "planned"])
        self.assertIn("1 of 2 landed", d["needsLandedLine"])
        self.assertIn("Not ready yet", d["verdict"])
        self.assertIn("waiting for c-after-two", d["verdict"])
        c = self.drive([ready_rows()], "graph", "260101-x-units", {"PICK_ID": "c-after-two"})
        self.assertEqual(c["needMarks"], ["landed", "landed"])
        self.assertIn("Ready to start", c["verdict"])
        self.assertIn("All 2 needs have landed", c["verdict"])
        self.assertEqual(c["waitMarks"], ["planned"], "what waits for it carries its state too")

    def test_the_sticky_bar_holds_the_tools_and_the_title_and_stats_scroll_away(self):
        out = self.drive([graph_rows(20)], "bar", "260101-x-units")
        self.assertTrue(out["headHasTitle"] and out["headHasStats"])
        self.assertFalse(out["barHasTitle"] or out["barHasStats"], "title and stats are not in the sticky row")
        self.assertEqual(out["barHasTabs"], 1)
        self.assertTrue(out["barHasSearch"])
        self.assertTrue(out["barPrecededByHead"])
        self.assertTrue(out["stickyCss"], "only the tools row is sticky")
        self.assertEqual(out["noTitleButtons"], [], "every control has a tooltip")
        self.assertLessEqual(out["controls"], 16)

    def test_a_revision_marks_new_changed_removed_and_landed(self):
        row = graph_rows(12, rev=3)
        prev = {b["id"]: {"label": b["label"], "title": b["title"], "summary": b["summary"], "group": b["group"], "status": b["status"],
                          "points": b["points"], "layer": b["layer"], "needs": sorted(n["id"] for n in b["needs"])} for b in row["blocks"]}
        del prev["blk-11"]                                       # new now
        prev["blk-03"]["summary"] = "An older sentence."         # changed
        prev["blk-07"]["status"] = "building"                    # blk-07 landed? make it landed now
        row["blocks"][7]["status"] = "landed"
        prev["blk-02"]["needs"] = ["blk-00"]                     # its needs changed
        prev["blk-99"] = {"label": "U99", "title": "Old", "summary": "Gone in this revision.", "group": "g1", "status": "planned", "points": 1, "layer": 2, "needs": []}
        row["previous"] = {"revision": 2, "builtAt": "2026-01-01T09:00:00Z", "blocks": prev}
        out = self.drive([row], "revision", "260101-x-units", {"PICK_ID": "blk-03"})
        self.assertIn("Round 3 since round 2", out["changes"])
        self.assertIn("1 new", out["changes"])
        self.assertIn("1 removed", out["changes"])
        self.assertEqual(out["roundClass"], "rt3", "the colours of round 3, as on the gate pages")
        tags = dict(t.split(":") for t in out["tags"])
        self.assertEqual(tags["blk-11"], "new")
        self.assertEqual(tags["blk-03"], "chg")
        self.assertEqual(tags["blk-07"], "chg")
        self.assertIn("blk-02", tags)
        self.assertEqual(out["ghosts"], ["blk-99"])
        self.assertIn("landed", out["tagTexts"])
        self.assertIn("new", out["tagTexts"])
        self.assertIn("blk-07", out["landedNodes"])
        self.assertTrue(any("An older sentence." in l for l in out["chgLines"]), out["chgLines"])
        self.assertEqual(out["onlyChanges"], 12 - len(out["tags"]), "Only changes greys the rest")  # blk-03 picked and unpicked

    def test_a_first_revision_has_no_marks(self):
        out = self.drive([graph_rows(12, rev=1)], "revision", "260101-x-units")
        self.assertEqual(out["tags"], [])
        self.assertEqual(out["changes"], "")

    def test_the_story_map_opens_as_a_grouped_list_the_matrix_is_the_other_view(self):
        row = story_row()
        out = self.drive([row], "matrix", "260101-x-stories", {"PICK_ID": "US1.2", "PICK_COL": "u1"})
        self.assertEqual(out["defaultView"], "list", "the list is what opens")
        self.assertEqual(out["listHeads"][0].split(" ·")[0], "No Unit builds it", "the gaps come first")
        self.assertEqual(out["listRows"][0], "US3.1")
        self.assertEqual(sorted(out["listRows"]), ["US1.1", "US1.2", "US3.1"])
        self.assertEqual(out["chipsOfFirst"], 0)
        self.assertIn("1 gap", out["stats"])
        self.assertNotIn("1 gaps", out["stats"])
        self.assertIn("Gaps only 1", out["gapsChip"])
        self.assertEqual(out["gapRowsOnly"], ["US3.1"])
        self.assertTrue(out["offered"], "a gap is something the matrix shows")
        self.assertEqual(out["rows"], ["US1.1", "US1.2", "US3.1"])
        self.assertEqual(out["cols"], ["u1", "u2"])
        self.assertEqual(out["dots"], 3)
        self.assertEqual(out["gaps"], ["US3.1"])
        self.assertIn("Units that build it (1)", out["rowPanel"])
        self.assertIn("Stories it covers (1)", out["colPanel"])
        self.assertEqual(out["gapRowsMatrix"], ["US3.1"])
        self.assertEqual(out["fresh"], 1, "one cell is new since round 1")
        self.assertEqual(out["hash"], "#260101-x-stories/c:u1")
        self.assertIn("a row with no dot is a gap", out["matrixLegend"])
        self.assertIn("new link", out["matrixLegend"])
        self.assertEqual(out["backToList"], "list")

    def test_only_changes_on_a_matrix_leaves_out_what_did_not_change(self):
        out = self.drive([story_row()], "matrix", "260101-x-stories", {"PICK_ID": "US1.2", "PICK_COL": "u1"})
        self.assertEqual(out["changedRows"], ["US1.2"], "the rows with a new or dropped link; US1.1 and the gap stayed as they were")
        self.assertEqual(out["changedCols"], ["u1", "u2"], "and the columns of those links, the one a link left and the new one")
        self.assertEqual(out["freshChanged"], 1)
        self.assertEqual(out["droppedCells"], 1, "a link that is no longer there shows as a struck cross")
        self.assertEqual(out["changedListRows"], ["US1.2"])
        self.assertIn("1 new link", out["revisionStrip"])
        self.assertIn("1 link no longer there", out["revisionStrip"])
        self.assertIn("1 new Unit", out["revisionStrip"])

    def test_plurals_are_words_not_a_letter_added(self):
        out = self.drive([story_row()], "matrix", "260101-x-stories", {"PICK_ID": "US1.2", "PICK_COL": "u1"})
        self.assertNotRegex(out["pageText"], r"(?i)storys|entitys")
        self.assertIn("3 stories", out["stats"])
        ent = story_row()
        ent.update({"id": "260101-x-entities", "kind": "entities", "title": "Entity map", "rowsTitle": "Entity", "colsTitle": "Component"})
        out = self.drive([ent], "matrix", "260101-x-entities", {"PICK_ID": "US1.2", "PICK_COL": "u1"})
        self.assertIn("3 entities", out["stats"])
        self.assertNotRegex(out["pageText"], r"(?i)storys|entitys")

    def test_a_matrix_with_no_gaps_and_no_density_is_a_list_only_with_a_line_saying_so(self):
        row = story_row()
        row["rows"] = row["rows"][:2]
        row["cells"] = {"US1.1": ["u1"], "US1.2": ["u2"]}
        row.pop("previous")
        out = self.drive([row], "matrix", "260101-x-stories")
        self.assertFalse(out["offered"], "nothing for a matrix to show: it is not offered")
        self.assertIn("No gaps", out["noGapsLine"])
        self.assertTrue(out["gapsDisabled"])
        self.assertIn("0 gaps", out["stats"])


if __name__ == "__main__":
    unittest.main()
