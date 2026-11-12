"""Batch 4 of the pages' rework: better presentation of the records, with visuals (the diagram view of a record, the target heat
grid, the verification funnel, the round timeline, plan steps as lanes, criteria at a glance, a file's outline) and the preview
tool (dev/preview.py) that writes every page and scenario as a self-contained file.

The pages run under jsdom (drive_batch4.js, drive_preview.js) on the files the preview tool writes: the real templates with rows
built by the plugin's own scripts from a made-up bakery. Needs node and the jsdom package; the tests skip without them.
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(PLUGIN, "dev"))
from bundle_helpers import NODE  # noqa: E402

VIZ = os.path.join(os.path.dirname(os.path.dirname(PLUGIN)), "shared", "gate-viz", "gate-viz.js")


def has_jsdom():
    return bool(NODE) and subprocess.run([NODE, "-e", "require('jsdom')"], capture_output=True).returncode == 0


_BUILT = {}


def built():
    """The preview tool's output, written once for the whole module: (folder, [Scenario])."""
    if "out" not in _BUILT:
        import preview
        out = tempfile.mkdtemp(prefix="gates-preview-test-")
        _BUILT["out"] = out
        _BUILT["scenarios"] = preview.build(out, say=lambda *_: None)
    return _BUILT["out"], _BUILT["scenarios"]


def tearDownModule():
    if "out" in _BUILT:
        shutil.rmtree(_BUILT["out"], ignore_errors=True)


def drive(scenario, page, storage=None):
    done = subprocess.run([NODE, os.path.join(HERE, "drive_batch4.js"), scenario, page] + ([json.dumps(storage)] if storage else []), capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


def node_eval(code):
    done = subprocess.run([NODE, "-e", "const V = require(process.argv[1]); process.stdout.write(JSON.stringify((" + code + ")(V)))", VIZ], capture_output=True, text=True, timeout=60)
    if done.returncode:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


class TestPreviewTool(unittest.TestCase):
    def test_it_writes_a_page_for_every_stage_in_round_1_and_in_round_3_and_every_scenario(self):
        out, scenarios = built()
        names = {s.name for s in scenarios}
        graph = json.load(open(os.path.join(PLUGIN, "dev", "stage-graph.json"), encoding="utf-8"))
        self.assertGreaterEqual(len(graph), 33, "the engine's stage list: initialization, ideation, inception, construction, operation")
        self.assertEqual({s["phase"] for s in graph}, {"initialization", "ideation", "inception", "construction", "operation"})
        for st in graph:
            if st["slug"] == "build-and-test":
                self.assertIn("build-and-test-r1", names)
                self.assertIn("build-and-test-r3", names)
                continue
            for r in (1, 3):
                self.assertIn(f"stage-{st['number'].replace('.', '-')}-{st['slug']}-r{r}", names)
        for n in ("gate-findings-to-sort", "gate-unhandled-items", "gate-nothing-pending", "unit-plan-r1", "unit-plan-r3", "unit-end-r1", "unit-end-r3", "unit-end-after-test-plan",
                  "test-plan", "maps-components", "maps-units", "maps-stories", "maps-entities", "list-gates", "list-unit-pages", "list-test-plans", "list-maps"):
            self.assertIn(n, names)
        index = open(os.path.join(out, "index.html"), encoding="utf-8").read()
        for s in scenarios:
            self.assertTrue(os.path.isfile(os.path.join(out, s.file)), s.file)
            self.assertIn(f'href="{s.file}"', index)
            self.assertTrue(s.desc.strip(), "a line on what to look at")

    def test_a_page_is_the_real_template_with_a_stub_in_front_and_its_rows_embedded(self):
        out, scenarios = built()
        s = next(x for x in scenarios if x.name == "stage-2-4-user-stories-r3")
        html = open(os.path.join(out, s.file), encoding="utf-8").read()
        template = open(os.path.join(PLUGIN, "skills", "approval-gates", "approval-gate.html"), encoding="utf-8").read()
        self.assertIn(template, html)
        self.assertLess(html.index("window.claude = "), html.index("<title>"), "the stub is in front of the page")
        self.assertIn('location.hash = "' + s.hash_id + '"', html)
        rows = [k for k in s.rows if k.count("/") == 1]
        self.assertEqual(len(rows), 3, "round 3 and the two rounds before it")

    def test_the_rows_are_long_and_full_enough_to_look_real(self):
        _out, scenarios = built()
        bt = next(x for x in scenarios if x.name == "build-and-test-r1")
        row = next(v for k, v in bt.rows.items() if k.count("/") == 1 and "r1" not in k)
        self.assertEqual(len(row["buildTest"]["targets"]), 48)
        self.assertTrue(any(t.get("disagree") for t in row["buildTest"]["targets"]), "a target two files disagree on")
        long = [d for k, d in bt.rows.items() if "/documents/" in k]
        self.assertTrue(any(len(d["text"]) > 5000 for d in long))
        stories = next(x for x in scenarios if x.name == "stage-2-4-user-stories-r1")
        g = next(v for k, v in stories.rows.items() if k.count("/") == 1)
        self.assertGreaterEqual(len(g["digest"]["items"]), 10)
        for n in ("gate-findings-to-sort", "gate-unhandled-items", "gate-nothing-pending"):
            self.assertIn(n, {s.name for s in scenarios})
        f = next(x for x in scenarios if x.name == "gate-findings-to-sort")
        self.assertEqual(len(next(v for k, v in f.rows.items() if k.count("/") == 1)["findings"]["items"]), 6)

    def test_the_maps_hold_fifty_units_some_landed_new_and_changed_and_each_matrix_kind(self):
        _out, scenarios = built()
        rows = next(x for x in scenarios if x.name == "maps-units").rows
        units = rows["maps/260101-bakery-preorder-units"]
        self.assertEqual(units["revision"], 2)
        self.assertGreaterEqual(len(units["blocks"]), 50)
        self.assertGreaterEqual(sum(1 for b in units["blocks"] if b["status"] == "landed"), 10)
        old = units["previous"]["blocks"]
        self.assertGreaterEqual(len({b["id"] for b in units["blocks"]} - set(old)), 1, "new since the last revision")
        self.assertGreaterEqual(len(set(old) - {b["id"] for b in units["blocks"]}), 1, "removed since the last revision")
        self.assertEqual({r["view"] for r in rows.values()}, {"graph", "matrix"})
        self.assertEqual(sorted(k.rsplit("-", 1)[1] for k in rows), ["components", "entities", "stories", "units"])

    @unittest.skipUnless(has_jsdom(), "needs node and the jsdom package")
    def test_every_output_parses_and_boots_under_jsdom_without_console_errors(self):
        out, scenarios = built()
        files = [os.path.join(out, s.file) for s in scenarios]
        done = subprocess.run([NODE, os.path.join(HERE, "drive_preview.js")] + files, capture_output=True, text=True, timeout=600)
        self.assertEqual(done.returncode, 0, done.stderr)
        reports = json.loads(done.stdout)
        self.assertEqual(len(reports), len(files))
        bad = {r["file"]: r["errors"] for r in reports if r["errors"]}
        self.assertEqual(bad, {}, "console errors")
        thin = [r["file"] for r in reports if r["text"] < 800]
        self.assertEqual(thin, [], "a page that booted to almost nothing")


class TestVizFunctions(unittest.TestCase):
    """GateViz returns strings and needs no DOM: absent when the data does not support it, labelled when present."""

    @unittest.skipUnless(NODE, "needs node")
    def test_each_visual_is_absent_without_data_and_labelled_with_it(self):
        got = node_eval("""(V) => ({
          funnelNone: V.funnel({ total: 0 }), lanesOne: V.lanes({ lanes: [{ name: "logic", steps: [{ key: "step-1", n: 1, title: "a", implements: [] }] }] }), dotsNone: V.dots([]),
          outlineFew: V.outline([{ id: "a", title: "A" }]), timelineNone: V.timeline([]), diagramUnknown: V.diagram({ kind: "nothing", id: "x" }),
          heat: V.heat({ cols: ["U1", "U2"], rows: ["NFR"], cells: { "NFR\\u0001U1": { n: 3, worst: "Not Met" }, "NFR\\u0001U2": { n: 2, worst: "Met" } } }),
          funnel: V.funnel({ total: 10, auto: 4, verified: 3, unverified: 2, failed: 1 }),
          lanes: V.lanes({ lanes: [{ name: "logic", steps: [{ key: "step-1", n: 1, title: "Rules", implements: ["FR1"] }] }, { name: "UI", steps: [{ key: "step-2", n: 2, title: "Page", implements: [] }] }] }),
          dots: V.dots([{ name: "Stage", items: [{ key: "stage-1", v: "holds", title: "T", label: "Holds" }, { key: "stage-2", v: "fails", title: "U", label: "Fails" }] }]),
          timeline: V.timeline([{ k: 1, tone: 2, base: true, changed: 0, added: 0, removed: 0 }, { k: 2, tone: 2, changed: 3, added: 1, removed: 2, words: 40 }], 2),
          layers: V.diagram({ id: "c", kind: "layers", title: "L", alt: "Layers", map: "components", layers: [{ name: "domain", items: [{ id: "A", label: "A" }] }], edges: [] }, { maps: [{ kind: "components", url: "https://x.test/m", title: "Component map" }] }),
        })""")
        for k in ("funnelNone", "lanesOne", "dotsNone", "outlineFew", "timelineNone", "diagramUnknown"):
            self.assertEqual(got[k], "", k)
        for k in ("heat", "funnel", "lanes", "dots", "layers"):
            self.assertRegex(got[k], r'role="group" aria-label="[^"]+"', k + " has a label")
            self.assertIn('data-aidlc-noids', got[k], k + " keeps the id links out of the drawing")
        self.assertIn('data-vz-set="heat:cell:NFR\x01U1"', got["heat"])
        self.assertIn("Target heat grid: 5 targets, 2 Units, 1 groups", got["heat"])
        self.assertRegex(got["heat"], r"<caption class=\"sr\">")
        self.assertIn('class="vz-seg auto"', got["funnel"])
        self.assertNotIn('data-vz-set="verif:auto"', got["funnel"], "the points the tests cover are not rows, so that part filters nothing")
        for k in ("verified", "unverified", "failed"):
            self.assertIn(f'data-vz-set="verif:{k}"', got["funnel"])
        self.assertIn('data-vz-go="step-2"', got["lanes"])
        self.assertIn('data-vz-go="stage-2"', got["dots"])
        self.assertEqual(got["timeline"].count("data-rvonly"), 1, "the first round is not a filter; each later round is one chip")
        self.assertIn('aria-pressed="true"', got["timeline"])
        self.assertIn("Open the full Component map", got["layers"])

    @unittest.skipUnless(NODE, "needs node")
    def test_a_diagram_marks_what_is_new_and_lists_what_is_gone_since_the_round_before(self):
        got = node_eval("""(V) => {
          const was = { id: "t", kind: "trace", title: "T", alt: "t", cols: [{ key: "requirement", label: "R" }, { key: "story", label: "S" }], nodes: [{ id: "FR1", col: "requirement" }, { id: "FR2", col: "requirement" }, { id: "US1", col: "story" }], edges: [["FR1", "US1"], ["FR2", "US1"]] };
          const now = JSON.parse(JSON.stringify(was)); now.nodes = now.nodes.filter((n) => n.id !== "FR2").concat([{ id: "FR3", col: "requirement" }]); now.edges = [["FR1", "US1"], ["FR3", "US1"]];
          return { plain: V.diagram(now, {}), marked: V.diagram(now, { prev: was }) };
        }""")
        self.assertNotIn("vz-new", got["plain"])
        self.assertEqual(got["marked"].count("vz-node vz-new"), 1)
        self.assertIn("FR3, new in this round", got["marked"])
        self.assertIn("removed", got["marked"])
        self.assertRegex(got["marked"], r"vz-gone.*FR2")

    @unittest.skipUnless(NODE, "needs node")
    def test_every_diagram_kind_has_a_text_alternative(self):
        got = node_eval("""(V) => [
          { kind: "sequence", actors: ["A", "B"], messages: [{ from: "A", to: "B", text: "hi" }, { from: "B", to: "B", text: "think" }] },
          { kind: "states", states: ["x", "y", "z"], transitions: [{ from: "x", to: "y", text: "go" }, { from: "y", to: "z", text: "" }, { from: "z", to: "x", text: "back" }] },
          { kind: "steps", steps: [{ n: 1, text: "one" }, { n: 2, text: "two" }] },
          { kind: "flow", dir: "LR", nodes: [{ id: "A", label: "A", shape: "box" }, { id: "B", label: "B", shape: "diamond" }], edges: [{ from: "A", to: "B", text: "yes" }] },
          { kind: "list", heading: "Shares", items: [{ text: "Dogs" }] },
        ].map((d, i) => V.diagram(Object.assign({ id: "d" + i, title: "T", alt: "Alt " + i }, d), {}))""")
        for html in got:
            self.assertRegex(html, r'aria-label="Alt \d"')
            self.assertIn('<ul class="vz-sr">', html)
            self.assertNotIn("mermaid", html.lower())


@unittest.skipUnless(has_jsdom(), "needs node and the jsdom package")
class TestStagePage(unittest.TestCase):
    def page(self, name):
        out, scenarios = built()
        return os.path.join(out, next(s.file for s in scenarios if s.name == name))

    def test_criteria_at_a_glance_one_dot_each_and_a_dot_opens_its_criterion(self):
        o = drive("gate", self.page("stage-2-4-user-stories-r1"))
        self.assertEqual(o["errors"], [])
        self.assertEqual(len(o["dots"]), o["criteria"])
        self.assertTrue(all(d["label"] for d in o["dots"]), "a label on every dot")
        self.assertEqual({d["cls"].split()[1] for d in o["dots"]}, {"holds", "fails", "na"})
        self.assertIn("Criteria at a glance", o["dotsLabel"])
        self.assertTrue(o["dotOpened"])

    def test_the_diagram_switch_is_offered_where_a_record_has_structure_and_nowhere_else(self):
        o = drive("gate", self.page("stage-2-4-user-stories-r1"))
        self.assertEqual(o["diagramDocs"], ["traceability"])
        self.assertGreaterEqual(o["hiddenDiagramButtons"], 2, "personas, the assessment and the questions have no structure to draw")
        o = drive("gate", self.page("stage-0-1-workspace-scaffold-r1"))
        self.assertEqual(o["diagramDocs"], [])
        o = drive("gate", self.page("stage-3-1-functional-design-r1"))
        self.assertIn("functional-spec", o["diagramDocs"])

    def test_a_diagram_is_a_second_view_with_no_read_key_of_its_own_and_its_choice_is_remembered(self):
        o = drive("gate", self.page("stage-2-4-user-stories-r1"))
        self.assertTrue(o["figure"])
        self.assertIn("Trace ribbon", o["figureLabel"])
        self.assertGreater(o["altItems"], 5, "the links, as a list for a screen reader")
        self.assertTrue(o["noReadKeysInside"])
        self.assertEqual(o["readsBefore"], o["readsAfter"], "no second read key, and none gone")
        self.assertEqual(o["saved"], "diagram")
        # the next visit opens on the diagram
        again = drive("gate", self.page("stage-2-4-user-stories-r1"), {"approval-gates:viz:traceability": "diagram"})
        self.assertTrue(again["figure"] is True)

    def test_pressing_a_mark_jumps_to_the_real_row_or_says_it_is_not_in_this_gate(self):
        o = drive("gate", self.page("stage-2-4-user-stories-r1"))
        after = o["afterNode"]
        self.assertTrue(after["flash"] or "not shown in this gate" in (after["toast"] or ""), after)
        self.assertEqual(after["mode"], "false", "the text or view is back when a mark is pressed")

    def test_a_mermaid_block_is_drawn_where_it_stands_never_as_source(self):
        o = drive("gate", self.page("stage-2-4-user-stories-r1"))
        self.assertEqual(o["mermaidSourceShown"], 0)
        self.assertGreaterEqual(o["inlineFlows"], 1)

    def test_a_long_file_has_an_outline_on_wide_screens_and_a_strip_on_narrow_ones(self):
        o = drive("gate", self.page("stage-2-4-user-stories-r1"))
        self.assertGreaterEqual(o["outlines"], 1)
        self.assertEqual(o["outlines"], o["outlineStrip"])
        self.assertTrue(o["outlineTarget"])

    def test_the_round_timeline_replaces_the_legend_chips_and_keeps_their_behaviour(self):
        o = drive("gate", self.page("stage-2-4-user-stories-r3"))
        self.assertEqual([t["only"] for t in o["timeline"]], [None, "2", "3"])
        self.assertIn("first round", o["timeline"][0]["text"])
        self.assertRegex(o["timeline"][1]["text"], r"~\d+\+\d+−\d+", "changed, added, removed")
        self.assertEqual(o["pressedAfter"], ["true", "false"], "one round only")
        self.assertEqual(o["pressedAgain"], ["false", "false"], "the same chip again: all")
        self.assertEqual(o["pressedOther"], ["false", "true"])
        self.assertEqual(o["legendChips"], 2, "the chips are the timeline's: no second legend")
        r1 = drive("gate", self.page("stage-2-4-user-stories-r1"))
        self.assertNotIn("timeline", r1, "a first round has nothing to compare")

    def test_round_changes_show_in_the_diagram_too(self):
        o = drive("gate", self.page("stage-2-4-user-stories-r3"), {"approval-gates:viz:traceability": "diagram", "aidlc-rev:view": "show"})
        self.assertIn("removed", o["goneNote"])
        self.assertEqual(o["readsBefore"], o["readsAfter"])

    def test_a_diagram_new_in_this_round_is_marked_new(self):
        import preview
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        graph = json.load(open(os.path.join(PLUGIN, "dev", "stage-graph.json"), encoding="utf-8"))
        bakery = preview.Bakery(tmp, graph)
        st = next(s for s in graph if s["slug"] == "user-stories")
        sample = preview.sample_of(bakery, st, None, 2, tmp)
        path = os.path.join(tmp, "two-rounds.html")
        open(path, "w", encoding="utf-8").write(preview.page("gate", preview.gate_rows(sample), sample["id"], {}))
        o = drive("gate", path, {"approval-gates:viz:traceability": "diagram", "aidlc-rev:view": "show"})
        self.assertGreaterEqual(o["newNodes"], 2, "FR13 and US13.1 came in round 2")
        self.assertEqual(o["readsBefore"], o["readsAfter"])


@unittest.skipUnless(has_jsdom(), "needs node and the jsdom package")
class TestHeatGrid(unittest.TestCase):
    def page(self, name):
        out, scenarios = built()
        return os.path.join(out, next(s.file for s in scenarios if s.name == name))

    def test_units_across_groups_down_a_cell_filters_the_one_list_of_targets(self):
        o = drive("heat", self.page("build-and-test-r1"))
        self.assertTrue(o["heat"])
        self.assertIn("48 targets", o["label"])
        self.assertEqual(o["rowsAll"], 48)
        self.assertEqual(o["cell"]["rows"], o["cell"]["n"], "the list shows exactly the cell's targets")
        self.assertTrue(o["cell"]["clear"])
        self.assertEqual(o["rowsCleared"], 48)
        self.assertLess(o["col"]["rows"], 48)
        self.assertTrue(o["noReadKeysInside"])

    def test_below_twelve_targets_the_list_is_enough(self):
        import batch1_fixture as fx
        import preview
        sample = fx.sample(False)
        rows = {"gates/" + sample["id"]: sample["row"]}
        for did, d in sample["documents"].items():
            rows[f"gates/{sample['id']}/documents/{did}"] = d
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "small.html")
        open(path, "w", encoding="utf-8").write(preview.page("gate", rows, sample["id"], {}))
        o = drive("heat", path)
        self.assertFalse(o["heat"])
        self.assertLess(len(sample["row"]["buildTest"]["targets"]), 12)
        self.assertEqual(o["errors"], [])


@unittest.skipUnless(has_jsdom(), "needs node and the jsdom package")
class TestUnitPages(unittest.TestCase):
    def page(self, name):
        out, scenarios = built()
        return os.path.join(out, next(s.file for s in scenarios if s.name == name))

    def test_the_verification_funnel_and_its_parts_set_the_state_chip(self):
        o = drive("unit", self.page("unit-end-after-test-plan"))
        self.assertEqual(o["errors"], [])
        self.assertEqual([s["cls"] for s in o["funnel"]["segs"]], ["auto", "verified", "unverified", "failed"])
        self.assertEqual([s["tag"] for s in o["funnel"]["segs"]], ["SPAN", "BUTTON", "BUTTON", "BUTTON"])
        self.assertIn("Verification funnel: 27 points", o["funnel"]["label"])
        self.assertEqual((o["rowsAll"], o["failed"]["rows"], o["failed"]["chip"], o["failed"]["seg"]), (13, 3, "true", "true"))
        self.assertEqual(o["cleared"]["rows"], 13, "the same part again: all points")
        self.assertEqual(o["verified"]["chips"], ["verified"])
        self.assertEqual(o["verified"]["rows"], 6)

    def test_the_funnel_starts_from_the_tests_and_is_absent_when_there_is_only_one_part(self):
        o = drive("unit", self.page("unit-end-r1"))
        self.assertEqual([s["cls"] for s in o["funnel"]["segs"]], ["auto", "unverified"], "before a test plan: the tests' points and the not-verified ones")
        import preview
        import preview_units
        b = preview_units.end_bundle(1)
        del b["verification"]
        row = {"bundle": b, "page": "unit-end", "title": "t", "createdAt": b["createdAt"], "status": "open", "intent": b["header"]["intent"], "unit": b["header"]["unit"]}
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "one-part.html")
        open(path, "w", encoding="utf-8").write(preview.page("unit", {"bundles/" + b["id"]: row}, b["id"], {}))
        o = drive("unit", path)
        self.assertIsNone(o["funnel"], "all the points not verified: the list says it already")
        self.assertEqual(o["errors"], [])

    def test_plan_steps_as_lanes_in_build_order_each_step_linking_to_its_row(self):
        o = drive("unit", self.page("unit-plan-r1"))
        lanes = o["lanes"]
        self.assertGreaterEqual(len(lanes["names"]), 2)
        self.assertEqual(lanes["names"][0], "setup", "the lane of the first step comes first")
        self.assertEqual(lanes["steps"], lanes["rowSteps"], "every step once")
        self.assertTrue(o["laneJump"]["open"])
        self.assertIn("Plan steps by layer", lanes["label"])

    def test_a_plan_with_one_layer_keeps_the_list(self):
        import preview_units
        import preview
        b = preview_units.plan_bundle(1)
        for st in b["plan"]["steps"]:
            st["layer"] = "logic"
        row = {"bundle": b, "page": "plan", "title": "t", "createdAt": b["createdAt"], "status": "open", "intent": b["header"]["intent"], "unit": b["header"]["unit"]}
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "one-layer.html")
        open(path, "w", encoding="utf-8").write(preview.page("unit", {"bundles/" + b["id"]: row}, b["id"], {}))
        o = drive("unit", path)
        self.assertIsNone(o["lanes"])
        self.assertEqual(o["errors"], [])

    def test_the_version_timeline_replaces_the_legend_and_one_round_shows_alone(self):
        o = drive("unit", self.page("unit-plan-r3"))
        self.assertEqual(len(o["timeline"]), 3)
        self.assertIn("first round", o["timeline"][0])
        self.assertRegex(o["timeline"][1], r"~\d+\+\d+−\d+")
        self.assertEqual(o["pressed"][0], "true")
        self.assertEqual(o["pressedAgain"], ["false", "false"])


class TestContract(unittest.TestCase):
    def test_the_unit_end_bundle_may_carry_how_many_points_the_tests_cover(self):
        sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
        import unit_bundle
        import validate_bundle
        from test_validate_bundle import end_bundle
        b = end_bundle()
        b["verification"] = {"auto": 14}
        self.assertEqual(validate_bundle.validate(b), [])
        b["verification"] = {"auto": -1}
        self.assertTrue(validate_bundle.validate(b))
        b["verification"] = {"auto": 3, "extra": 1}
        self.assertTrue(any("extra" in p for p in validate_bundle.validate(b)))
        f = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
        f.write("# S\n\n## Verified Here\n\n- the slot rules, by tests\n- the list page, by tests\n\n## Not Verified Here\n\n- the phone\n")
        f.close()
        self.addCleanup(os.remove, f.name)
        self.assertEqual(unit_bundle.auto_verified(f.name), 2)

    def test_the_gate_row_carries_the_diagrams_the_records_give(self):
        _out, scenarios = built()
        s = next(x for x in scenarios if x.name == "stage-3-1-functional-design-r1")
        g = next(v for k, v in s.rows.items() if k.count("/") == 1)
        kinds = {(d["doc"], d["kind"]) for d in g["diagrams"]}
        self.assertIn(("traceability", "trace"), kinds)
        self.assertIn(("functional-spec", "states"), kinds)
        self.assertIn(("functional-spec", "sequence"), kinds)
        self.assertTrue(any(d.get("fence") == 0 and d.get("h") for d in g["diagrams"]), "a mermaid block is found by the hash of its source")
        quiet = next(x for x in scenarios if x.name == "stage-0-1-workspace-scaffold-r1")
        self.assertNotIn("diagrams", next(v for k, v in quiet.rows.items() if k.count("/") == 1))


if __name__ == "__main__":
    unittest.main()
