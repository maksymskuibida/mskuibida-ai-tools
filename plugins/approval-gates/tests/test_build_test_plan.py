"""Tests for the Build and Test test plan (approval-gates 1.38.0): the third deferral pick at a unit-end gate, the
deferral record, `test_plan.py collect/validate/publish/finish` for kind "build-and-test", old plans still holding, and
the copy blocks of the plan page under Node.
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import json
import os
import subprocess
import sys
import unittest

from bundle_helpers import NODE, PAGE, SCRIPTS
from test_test_plan import PLAN_PAGE, end_bundle, good_plan
from test_unit_bundle import Base, UNIT

sys.path.insert(0, SCRIPTS)
import test_plan  # noqa: E402
import unit_bundle  # noqa: E402
import validate_bundle  # noqa: E402

BT_ID = "bakery-build-and-test-test-v1-20260102T1000"


def src(unit, point, title):
    return {"id": f"{unit}:{point}", "unit": unit, "point": point, "title": title}


def bt_plan(now=("u1-core:V-1", "u2-pickup-slots:V-2", "build-and-test:M-1")):
    sources = [src("u1-core", "V-1", "Orders keep their slot"), src("u2-pickup-slots", "V-2", "Full slots are greyed out"),
               src("build-and-test", "M-1", "The release notes read well")]
    return {"schema": "aidlc-test-plan/1", "kind": "build-and-test", "id": BT_ID, "intent": "bakery", "unit": "build-and-test",
            "title": "Build and Test: bakery", "now": list(now), "allByDefault": False, "sources": sources,
            "sections": [
                {"key": "A", "title": "Install from a throwaway tag", "agent": "I cut tag `0.0.0-test` and install it.",
                 "steps": [{"id": "A.1", "do": "Open the slot list.\n\n```Terminal\nnpm run start\n```", "criteria": ["Full slots are greyed out."], "verifies": ["u2-pickup-slots:V-2"]},
                           {"id": "A.2", "do": "Move an order.", "criteria": ["It keeps its slot."], "verifies": ["u1-core:V-1"]}]},
                {"key": "B", "title": "Cut the real release", "agent": "I cut the real release tag.",
                 "steps": [{"id": "B.1", "do": "Read the notes.", "criteria": ["They read well."], "verifies": ["build-and-test:M-1"]}]}]}


class TestPlanContract(unittest.TestCase):
    def problems(self, plan, deferred=None):
        return test_plan.problems_of(plan, None, deferred)

    def test_a_good_build_and_test_plan_holds_with_no_bundle(self):
        self.assertEqual(self.problems(bt_plan()), [])

    def test_the_kind_unit_bundle_and_sources_are_checked(self):
        plan = bt_plan()
        plan["unit"] = "u1-core"
        plan["bundle"] = "x-unit-end-v1-20260101T0900"
        plan["sources"][0]["id"] = "u1-core:V-9"
        plan["sources"][2]["point"] = "V-4"
        plan["sources"][2]["id"] = "build-and-test:V-4"
        found = "\n".join(self.problems(plan))
        for want in ("unit must be build-and-test", "has no bundle", "id must be u1-core:V-1", "M points belong to build-and-test"):
            self.assertIn(want, found)
        plan = bt_plan()
        del plan["sources"]
        self.assertTrue(any("sources must list" in p for p in self.problems(plan)))
        plan = bt_plan()
        plan["kind"] = "other"
        self.assertTrue(any("kind is absent" in p for p in self.problems(plan)))

    def test_every_point_in_now_is_a_source_and_is_verified_by_a_step(self):
        plan = bt_plan(now=("u1-core:V-1", "u2-pickup-slots:V-2", "build-and-test:M-1", "u3:V-1"))
        self.assertIn("now names u3:V-1, which is not in the plan's sources", self.problems(plan))
        plan = bt_plan()
        plan["sections"][1]["steps"][0]["verifies"] = ["u1-core:V-1"]
        self.assertIn("build-and-test:M-1 is to be tested now but no step verifies it", self.problems(plan))
        plan = bt_plan()
        plan["sections"][0]["steps"][0]["verifies"] = ["u9:V-1"]
        self.assertTrue(any("verifies u9:V-1, which is not one of the rows" in p for p in self.problems(plan)))

    def test_a_point_a_unit_deferred_must_be_in_the_plan(self):
        self.assertEqual(self.problems(bt_plan(), ["u1-core:V-1"]), [])
        self.assertEqual(self.problems(bt_plan(), ["u3-x:V-5"]), ["u3-x:V-5 was deferred to Build and Test but is not in the plan's sources"])

    def test_an_old_unit_plan_still_validates_and_has_no_kind(self):
        plan = good_plan()
        self.assertNotIn("kind", plan)
        self.assertEqual(test_plan.problems_of(plan, end_bundle()), [])

    def test_a_point_picked_at_build_and_test_is_not_tested_in_the_unit(self):
        bundle = end_bundle()
        self.assertEqual(test_plan.now_rows(bundle, {"V-2": "now", "V-3": "buildtest"}), (["V-2"], False))
        self.assertEqual(test_plan.now_rows(bundle, {"V-1": "buildtest"}), (["V-2", "V-3"], True))
        self.assertEqual(test_plan.now_rows(bundle, {"V-1": "buildtest", "V-2": "buildtest", "V-3": "buildtest"}), ([], True))


class TestBuildAndTestFlow(Base):
    def script(self, *args):
        env = dict(os.environ, AIDLC_IDS_DIR=os.path.join(self.tmp, "ids"))
        env.pop("CLAUDE_PROJECT_DIR", None)
        return subprocess.run([sys.executable, os.path.join(SCRIPTS, "test_plan.py"), *args], capture_output=True, text=True, env=env, timeout=60)

    def file(self, name, value):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(value, f)
        return path

    def bundle(self, unit):
        b = end_bundle(("V-1", "V-2", "V-3"))
        b["header"] = {"intent": "bakery", "unit": unit}
        return self.file(f"{unit}.json", b)

    def defer(self, unit, picks, *extra):
        return self.script("defer", "--bundle", self.bundle(unit), "--picks-file", self.file(f"picks-{unit}.json", {"picks": picks}),
                           "--unit", unit, "--project-dir", self.project, *extra)

    def test_defer_records_the_picked_points_and_lists_the_rest(self):
        done = self.defer("u1-core", {"V-1": "buildtest", "V-2": "later"})
        self.assertEqual(done.returncode, 0, done.stderr)
        info = json.loads(done.stdout)
        self.assertEqual((info["deferred"], info["stillNotVerified"]), (["V-1"], ["V-2", "V-3"]))
        self.assertTrue(info["file"].endswith(os.path.join("construction", "u1-core", "code-generation", "deferred-to-build-and-test.json")))
        with open(info["file"], encoding="utf-8") as f:
            rec = json.load(f)
        self.assertEqual((rec["schema"], rec["unit"], rec["bundle"]), ("aidlc-deferred-points/1", "u1-core", "bakery-u2-unit-end-v1-20260101T0900"))
        self.assertEqual([p["choice"] for p in rec["points"]], ["buildtest", "later", "later"])
        done = self.defer("u1-core", {}, "--all")
        self.assertEqual(json.loads(done.stdout)["deferred"], ["V-1", "V-2", "V-3"])

    def test_collect_reads_every_units_record_and_says_when_there_is_none(self):
        self.assertEqual(self.script("collect", "--project-dir", self.project).returncode, 1)
        self.defer("u1-core", {"V-1": "buildtest"})
        self.defer(UNIT, {"V-3": "buildtest"})
        found = json.loads(self.script("collect", "--project-dir", self.project).stdout)
        self.assertEqual([u["unit"] for u in found["units"]], ["u1-core", UNIT])
        self.assertTrue(found["stageDir"].endswith(os.path.join("construction", "build-and-test")))
        self.assertEqual(found["intent"], "260101-bakery-preorder")

    def test_validate_with_the_project_names_a_deferred_point_the_plan_left_out(self):
        self.defer("u1-core", {"V-1": "buildtest", "V-2": "buildtest"})
        plan = self.file("plan.json", bt_plan())
        done = self.script("validate", "--plan", plan, "--project-dir", self.project)
        self.assertEqual(done.returncode, 1)
        self.assertIn("u1-core:V-2 was deferred to Build and Test but is not in the plan's sources", done.stdout)
        self.assertEqual(self.script("validate", "--plan", plan).returncode, 0)

    def test_publish_writes_the_row_with_the_source_titles(self):
        out = os.path.join(self.tmp, "out")
        done = self.script("publish", "--plan", self.file("plan.json", bt_plan()), "--out", out)
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(os.path.join(out, "row.json"), encoding="utf-8") as f:
            row = json.load(f)
        self.assertEqual((row["unit"], row["status"]), ("build-and-test", "open"))
        self.assertEqual(row["plan"]["rows"]["u1-core:V-1"], "Orders keep their slot")
        self.assertNotIn("results", row)

    def test_finish_writes_the_stage_outcome_and_marks_each_unit_points_back(self):
        self.defer("u1-core", {"V-1": "buildtest"})
        self.defer(UNIT, {"V-2": "buildtest"})
        results = {"A.1": {"result": "fail", "note": "Not greyed."}, "A.2": {"result": "pass"}, "B.1": {"result": "pass", "note": "Fine."}}
        args = ["finish", "--plan", self.file("plan.json", bt_plan()), "--results", self.file("results.json", results), "--project-dir", self.project]
        done = self.script(*args)
        self.assertEqual(done.returncode, 0, done.stderr)
        info = json.loads(done.stdout)
        self.assertEqual((info["passedRows"], info["failedRows"]), (["build-and-test:M-1", "u1-core:V-1"], ["u2-pickup-slots:V-2"]))
        stage = os.path.dirname(info["markdown"])
        self.assertTrue(stage.endswith(os.path.join("construction", "build-and-test")))
        with open(info["markdown"], encoding="utf-8") as f:
            text = f.read()
        for want in ("# Build and Test plan: Build and Test: bakery", "u1-core V-1 Orders keep their slot: Verified by you", "Failed", "Agent step: I cut the real release tag."):
            self.assertIn(want, text)
        with open(info["outcome"], encoding="utf-8") as f:
            self.assertEqual(json.load(f)["kind"], "build-and-test")
        done = self.script(*args, "--fix", "none")
        self.assertEqual(done.returncode, 0, done.stderr)
        mine = os.path.join(self.project, "aidlc", "spaces", "default", "intents")
        with open(os.path.join(mine, "active-intent"), encoding="utf-8") as f:
            intent = f.read().strip()
        folder = os.path.join(mine, intent, "construction", "u1-core", "code-generation")
        with open(os.path.join(folder, "build-and-test-outcome.json"), encoding="utf-8") as f:
            outcome = json.load(f)
        self.assertEqual(outcome["rows"]["V-1"]["state"], "passed")
        self.assertNotIn("M-1", outcome["rows"])
        with open(os.path.join(folder, "deferred-to-build-and-test.json"), encoding="utf-8") as f:
            self.assertEqual([p.get("state") for p in json.load(f)["points"]], ["passed", None, None])
        # the Unit page reads that file exactly as it reads a Unit test plan's outcome
        bundle = {"sections": [{"key": "unverified", "kind": "unverified", "title": "x", "short": "x", "hint": "", "rows":
                                [{"id": "V-1", "title": "a", "body": "Body."}, {"id": "V-2", "title": "b", "body": "Body."}]}]}
        got = unit_bundle.apply_tested(bundle, outcome)
        self.assertEqual((got["passed"], got["stillNotVerified"]), (1, 1))

    def test_finish_refuses_a_plan_with_a_step_not_run(self):
        done = self.script("finish", "--plan", self.file("plan.json", bt_plan()), "--results", self.file("r.json", {"A.1": {"result": "pass"}}), "--project-dir", self.project)
        self.assertEqual(done.returncode, 1)
        self.assertIn("step A.2 has no Pass or Fail yet", done.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class TestCopyAndSourcesOnThePage(unittest.TestCase):
    RENDER = r"""
const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync(process.argv[1], "utf8");
const src = html.split("/* RENDER-START")[1].split("/* RENDER-END */")[0];
const ctx = { module: {} }; vm.createContext(ctx); vm.runInContext("/*" + src, ctx);
const G = ctx.module.exports, input = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify({ page: input.row ? G.render(input.row, {}) : "", parsed: G.parseDo(input.text || ""), doHtml: G.doHtml(input.text || "") }));
"""

    def run_page(self, **input):
        done = subprocess.run([NODE, "-e", self.RENDER, PLAN_PAGE], input=json.dumps(input), capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_a_fenced_block_keeps_its_label_and_its_exact_text(self):
        text = "Run it:\n```Terminal\nnpm run start -- --port=3000\n  indented <tag> & more\n```\nthen ask:\n```Ask Claude\nWhat does `foo` do?\n```"
        got = self.run_page(text=text)
        self.assertEqual([(s["type"], s.get("label"), s["text"]) for s in got["parsed"]],
                         [("text", None, "Run it:"), ("block", "Terminal", "npm run start -- --port=3000\n  indented <tag> & more"),
                          ("text", None, "then ask:"), ("block", "Ask Claude", "What does `foo` do?")])
        html = got["doHtml"]
        self.assertEqual(html.count('data-copy="block"'), 2)
        self.assertIn('<span class="where">Terminal</span>', html)
        self.assertIn('<span class="where">Ask Claude</span>', html)
        self.assertIn("indented &lt;tag&gt; &amp; more", html)
        self.assertIn('aria-label="Copy Terminal block"', html)
        self.assertIn("What does `foo` do?", html, "backticks inside a block stay text, not an inline button")
        self.assertNotIn('data-copy="inline"', html)

    def test_inline_code_is_a_copy_button_and_a_block_without_a_label_still_copies(self):
        got = self.run_page(text="Open `src/app.ts` and set `PORT=3000`.\n\n```\nls -la\n```")
        html = got["doHtml"]
        self.assertEqual(html.count('data-copy="inline"'), 2)
        self.assertIn('aria-label="Copy src/app.ts"', html)
        self.assertIn(">PORT=3000</button>", html)
        self.assertIn('<span class="where"></span>', html)
        self.assertIn('aria-label="Copy block"', html)

    def test_an_unclosed_fence_runs_to_the_end_and_script_text_is_escaped(self):
        got = self.run_page(text="```Terminal\n<script>alert(1)</script>")
        self.assertEqual(got["parsed"], [{"type": "block", "label": "Terminal", "text": "<script>alert(1)</script>"}])
        self.assertNotIn("<script>", got["doHtml"])

    def test_a_build_and_test_point_shows_the_unit_it_came_from(self):
        plan = dict(bt_plan(), rows={s["id"]: s["title"] for s in bt_plan()["sources"]})
        row = {"plan": plan, "id": plan["id"], "unit": "build-and-test", "intent": "bakery", "title": plan["title"],
               "createdAt": "2026-01-02T10:00:00Z", "status": "open", "agentDone": []}
        page = self.run_page(row=row)["page"]
        for want in ("u1-core · V-1", "u2-pickup-slots · V-2", "build-and-test · M-1", 'title="Orders keep their slot"', 'data-copy="block"'):
            self.assertIn(want, page)

    def test_an_old_plan_without_sources_or_fences_renders_as_before(self):
        plan = dict(good_plan(), rows={"V-1": "Point V-1"})
        row = {"plan": plan, "id": plan["id"], "unit": "u2", "intent": "bakery", "title": plan["title"], "createdAt": "2026-01-01T10:00:00Z",
               "status": "open", "agentDone": []}
        page = self.run_page(row=row)["page"]
        self.assertIn(">V-1</span>", page)
        self.assertIn("Open the slot list.", page)
        self.assertNotIn('data-copy=', page)

    def test_the_page_script_copies_through_the_clipboard_with_a_fallback_and_is_keyboard_reachable(self):
        with open(PLAN_PAGE, encoding="utf-8") as f:
            html = f.read()
        for want in ("navigator.clipboard.writeText", 'document.execCommand("copy")', "selectContents(src)", 'aria-live="polite"'):
            self.assertIn(want, html)
        self.assertRegex(html, r'<pre tabindex="0">')
        self.assertNotRegex(html, r"\.cp[^{]*\{[^}]*outline: ?none")

    def test_the_unit_page_has_the_third_pick(self):
        with open(PAGE, encoding="utf-8") as f:
            html = f.read()
        self.assertIn('data-val="buildtest"', html)
        self.assertIn("At Build and Test", html)


if __name__ == "__main__":
    unittest.main()
