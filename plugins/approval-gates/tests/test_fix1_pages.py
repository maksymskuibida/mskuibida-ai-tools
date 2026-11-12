"""Fix round 1 of the pages' rework (approval-gates 1.34.0): what a first on-screen review of every stage's page found, fixed for the
per-stage page, the Unit pages and the test plan page. One test class per decision:

  1  round changes are always visible (Clean too): a round tag, the removed things struck where they were; one count everywhere
  2  nothing twice: a record whose table became the matrix draws its other sections only; an opened item says its detail once
  3  no empty shells: no items block without items; Units are items of Units Generation; the right plural
  4  Text / View / Diagram never closes anything and never changes the read totals
  5  the sticky bar: one row, the same on every page; filters and the counter; the rest in menus; a tooltip on everything
  6  phone: no sideways scroll, a row keeps the width of its sentence (the rules are in the templates' CSS)
  7  Unit pages open in Summary; Your answer follows a note the moment it is written
  8  readiness is honest: what is tagged not handled or failing stays until acknowledged
  9  each evaluation card has its own read mark
 10  ids never collide (a design row's id is not a link to a verification row)
 11  one vocabulary (round) and English dates
 12  a trace too big to draw at once is offered per requirement
 13  the test plan page: the others' width, header and tokens; no scroll jump on load; a sticky progress strip
 14  the preview covers what the reviewers could not reach

Synthetic data only: the pages dev/preview.py writes (a made-up bakery), driven under jsdom by drive_fix1.js; needs node and the jsdom,
marked, dompurify and js-yaml packages (the tests skip without jsdom). Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

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
SKILL = os.path.join(PLUGIN, "skills", "approval-gates")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(PLUGIN, "dev"))
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
from bundle_helpers import NODE  # noqa: E402

VIZ = os.path.join(os.path.dirname(os.path.dirname(PLUGIN)), "shared", "gate-viz", "gate-viz.js")
STAGE_PAGE = os.path.join(SKILL, "approval-gate.html")
UNIT_PAGE = os.path.join(SKILL, "unit-gate.html")
PLAN_PAGE = os.path.join(SKILL, "test-plan.html")


def has_jsdom():
    return bool(NODE) and subprocess.run([NODE, "-e", "require('jsdom')"], capture_output=True).returncode == 0


_BUILT = {}


def built():
    """The preview tool's output, written once for the whole module: (folder, [Scenario])."""
    if "out" not in _BUILT:
        import preview
        out = tempfile.mkdtemp(prefix="gates-fix1-test-")
        _BUILT["out"] = out
        _BUILT["scenarios"] = preview.build(out, say=lambda *_: None)
    return _BUILT["out"], _BUILT["scenarios"]


def tearDownModule():
    if "out" in _BUILT:
        shutil.rmtree(_BUILT["out"], ignore_errors=True)


def drive(scenario, name, storage=None):
    out, _ = built()
    cmd = [NODE, os.path.join(HERE, "drive_fix1.js"), scenario, os.path.join(out, name + ".html")] + ([json.dumps(storage)] if storage else [])
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise AssertionError(done.stderr)
    result = json.loads(done.stdout)
    assert not result.get("errors"), result["errors"]
    return result


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def css_of(path):
    return "\n".join(re.findall(r"<style>(.*?)</style>", read(path), re.S))


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestRoundChangesAreAlwaysVisible(unittest.TestCase):
    """Decision 1."""

    def test_clean_view_keeps_a_round_tag_and_the_removed_things(self):
        r = drive("clean", "stage-2-4-user-stories-r3")
        self.assertEqual(r["rv"], "clean")
        self.assertTrue(any(t.startswith("v3 ") for t in r["tags"]), r["tags"])
        self.assertTrue(any(t == "v3 removed" for t in r["tags"]), "a removed thing is tagged in Clean as in Changes")
        self.assertGreater(r["removed"], 0, "removed things are in the page in Clean, struck where they were")
        self.assertEqual(r["roundClass"], ["rv-t3"], "the page carries the colour of the round on show")
        self.assertNotIn("hidden", r["banner"].lower(), "the banner never says the changes are hidden")

    def test_the_css_shows_them_in_clean(self):
        css = css_of(STAGE_PAGE)
        self.assertRegex(css, r'#col\[data-rv="clean"\] \.rv-tag \{[^}]*display: inline-flex !important')
        self.assertRegex(css, r'#col\[data-rv="clean"\] :is\(div, li, p, details, section\)\.rv-gone[^{]*\{ display: block !important')
        unit = css_of(UNIT_PAGE)
        self.assertRegex(unit, r'#app\[data-rv="clean"\] \.rv-tag \{ display: inline-flex !important')
        self.assertRegex(unit, r'#app\[data-rv="clean"\] \.row\.rv-removed \{ display: block !important')

    def test_the_changed_filter_shows_the_removed_things_and_drops_no_block(self):
        r = drive("clean", "stage-2-4-user-stories-r3")
        self.assertFalse(r["itemsBlockHidden"], "the items block has a removed item: it stays under Changed")
        self.assertGreaterEqual(r["removedUnderChanged"], 1)
        self.assertEqual(r["hiddenBlocksWithChanges"], 0)

    def test_the_pill_the_banner_and_the_timeline_are_one_count(self):
        r = drive("clean", "stage-2-4-user-stories-r3")
        banner = [int(n) for n in re.findall(r"(\d+) (?:changed|new|removed)", r["banner"])]
        self.assertEqual(sum(banner), int(re.search(r"\d+", r["pill"]).group()), "the Changed pill is the banner's changed + new + removed")
        self.assertTrue(r["timelineInBar"], "the round timeline is in the bar's Rounds menu")

    def test_the_unit_page_counts_once_and_lists_what_it_counts(self):
        r = drive("unit", "unit-plan-r3")
        banner = [int(n) for n in re.findall(r"(\d+) (?:changed|new|removed)", r["banner"])]
        self.assertEqual(sum(banner), int(re.search(r"\d+", r["pillChanged"]).group()))
        steps = r["changed"]["steps"]
        self.assertGreaterEqual(steps, 4, "Changed keeps the code plan: the steps that changed in any round are rows like the others")
        self.assertTrue(any(s[0] == "plan" and s[1] == steps for s in r["changed"]["secs"]))
        self.assertTrue(any(s[2] for s in r["changed"]["secs"]), "a removed row is listed where it was, struck")
        self.assertNotIn("Revisions", r["banner"])


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestNothingTwice(unittest.TestCase):
    """Decision 2."""

    @classmethod
    def setUpClass(cls):
        cls.t = drive("tips", "build-and-test-r3")

    def test_a_record_whose_table_became_the_matrix_draws_no_table_of_targets(self):
        from_page = drive("shell", "build-and-test-r3")
        self.assertEqual(from_page["rows"], 0)
        out, _ = built()
        html = read(os.path.join(out, "build-and-test-r3.html"))
        self.assertIn("function stripMatrixTable", html)
        self.assertIn("above, drawn once; the rest of the file is here as written", html)

    def test_the_ledger_names_a_target_by_its_id_only(self):
        for line in self.t["ledger"]:
            self.assertRegex(line, r"^u\d:NFR\d+$", line)

    def test_an_opened_item_does_not_list_the_ids_its_own_text_shows(self):
        html = read(STAGE_PAGE)
        self.assertIn("const relIds = [...new Set(it.relates || it.mentions || [])].filter((m) => !shown(m));", html)
        self.assertIn("sameAsSum ? \"\" : inline(it.title)", html)

    def test_a_criterion_does_not_say_its_title_again(self):
        self.assertIn("function critText(c)", read(STAGE_PAGE))
        self.assertNotIn('class="cov2 ctally"', read(STAGE_PAGE).split("function criteriaHtml")[1].split("function criteriaDots")[0].replace("${bars}", "").replace('const bars', ''), "the bars repeat the lists")


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestNoEmptyShells(unittest.TestCase):
    """Decision 3."""

    def test_units_are_the_items_of_units_generation(self):
        r = drive("shell", "stage-2-7-units-generation-r1")
        self.assertTrue(r["hasItems"])
        self.assertEqual(sorted(r["ids"]), [f"U{n}" for n in range(1, 9)])
        self.assertIn("8 Units", r["head"])

    def test_a_stage_with_only_a_trace_has_no_items_block_and_keeps_the_trace_in_the_evaluation(self):
        r = drive("shell", "stage-3-5-code-generation-r1")
        self.assertFalse(r["hasItems"])
        self.assertTrue(r["trace"], "the traceability line moved to the foot of the evaluation")
        self.assertEqual(r["emptyDots"], 0)

    def test_the_subtitle_has_no_dangling_punctuation_and_stories_is_spelt(self):
        r = drive("shell", "stage-2-4-user-stories-r1")
        self.assertNotRegex(r["head"], r"^What the stage says\s*[;,]")
        self.assertIn("12 stories", r["head"])
        self.assertFalse(r["storys"])

    def test_the_digest_reads_units_from_the_units_record_only(self):
        import digest
        doc = {"key": "unit-of-work", "title": "Units", "text": "# Units\n\n## Units\n\n### U1 Core ordering\n\nTakes the orders.\n\n### U2: Pick-up slots\n\nOwns the calendar.\n\n- **U3** Reminders\n"}
        other = {"key": "build-and-test-summary", "title": "Summary", "text": "| Unit | Targets |\n|---|---|\n| U1 | 12 |\n"}
        got = digest.build([doc, other], {}, "inception/units-generation", {})
        self.assertEqual([(i["id"], i["kind"]) for i in got["items"]], [("U1", "unit"), ("U2", "unit"), ("U3", "unit")])
        self.assertEqual(got["counts"], {"unit": 3})
        story = {"key": "stories", "title": "Stories", "text": "### US1.1 Order\n\nAs a customer, I want to order.\n"}
        self.assertEqual([i["kind"] for i in digest.build([story], {}, "inception/user-stories", {})["items"]], ["story"], "US1.1 is a story, not a Unit")


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestSwitchingNeverClosesAnything(unittest.TestCase):
    """Decision 4 (and the totals of A-9)."""

    def test_diagram_text_and_view_keep_the_record_open_and_the_totals(self):
        r = drive("switch", "stage-2-6-domain-design-r1")
        self.assertFalse(r.get("skipped"), "this page offers a diagram")
        for step in ("before", "after", "back"):
            self.assertTrue(r[step]["recOpen"] and r[step]["docOpen"], step)
            self.assertEqual(r[step]["unread"], r["before"]["unread"], f"the read total after {step}")
        self.assertEqual(r["after"]["dots"], r["before"]["dots"], "the section marks stay while the diagram shows")
        self.assertGreaterEqual(r["after"]["diagram"], 1)
        self.assertEqual(r["after"]["underHidden"], 1, "the record's own view is still built, hidden, under the diagram")


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestTheBar(unittest.TestCase):
    """Decision 5: one row; the same spec on the per-stage page and the Unit pages."""

    PAGES = ("stage-2-4-user-stories-r3", "build-and-test-r3", "unit-plan-r3", "unit-end-r3", "unit-end-r1", "stage-1-1-intent-capture-r1")

    def test_one_row_with_the_filters_the_counter_and_menus(self):
        for name in self.PAGES:
            with self.subTest(name):
                r = drive("bar", name)
                self.assertEqual(r["rows"], 1)
                self.assertEqual(r["children"][:2], ["filters", "ready"])
                self.assertEqual(r["children"][-1], "bmenus")
                self.assertLessEqual(r["controls"], 10, r["controlTexts"])
                self.assertEqual(r["pills"][:3], ["All", "Needs you", "Unread"])
                self.assertIn(r["pills"][3:], ([], ["Changed"]))
                self.assertEqual(r["chipsOutsidePopovers"], 0, "no row of jump chips in the bar")
                self.assertFalse(r["readCounter"], "the unread count is in the counter, not again as Read x/y")
                self.assertTrue(r["hasReady"])
                self.assertEqual(r["titles"], 0, "every control has a tooltip or a label")

    def test_the_menus_hold_the_rest_on_every_page(self):
        for name in ("stage-2-4-user-stories-r3", "unit-plan-r3"):
            with self.subTest(name):
                r = drive("bar", name)
                buttons = " ".join(" ".join(p["buttons"]) for p in r["popMenus"])
                for want in ("Changes", "Clean", "Expand all", "Collapse all", "Mark all read"):
                    self.assertIn(want, buttons)
                self.assertTrue(all(p["hidden"] for p in r["popMenus"]), "closed until pressed")

    def test_the_bar_css_is_one_spec_in_both_pages(self):
        for path, bar in ((STAGE_PAGE, ".gbar"), (UNIT_PAGE, ".bar")):
            css = css_of(path)
            for rule in (".bmenus {", ".bm {", ".bmb {", ".bpop {", ".bmrow {"):
                self.assertIn(rule, css, f"{os.path.basename(path)} {rule}")
            self.assertRegex(css, re.escape(bar) + r" \{ flex-direction: row;", "the bar is one row")
            self.assertRegex(css, r"@media \(max-width: 767px\) \{\s*\n?\s*" + re.escape(bar) + r" \{ padding: 5px 8px;", "phone: two short rows at most")
        a, b = css_of(STAGE_PAGE), css_of(UNIT_PAGE)
        grab = lambda css, sel: re.search(re.escape(sel) + r" \{([^}]*)\}", css).group(1).strip()  # noqa: E731
        for sel in (".bmenus", ".bm", ".bpop", ".bmrow", ".bml", ".bmh"):
            self.assertEqual(re.sub(r"\s+", " ", grab(a, sel)), re.sub(r"\s+", " ", grab(b, sel)), f"{sel} is the same on both pages")


class TestPhone(unittest.TestCase):
    """Decision 6: the rules that keep a phone from scrolling sideways, and a row's sentence from being squeezed."""

    def test_the_why_first_paragraph_is_not_the_nowrap_chip(self):
        css = css_of(STAGE_PAGE)
        self.assertNotRegex(css, r"(?m)^\.why \{[^}]*nowrap", "the document chip's nowrap leaked onto the Why first paragraph")
        self.assertRegex(css, r"span\.why \{[^}]*nowrap")
        self.assertRegex(css, r"p\.why, \.pt1, \.decides \{ white-space: normal;")

    def test_a_row_title_wraps_and_the_tags_wrap_under_it(self):
        css = css_of(UNIT_PAGE)
        self.assertRegex(css, r"\.rowhead \{ flex-wrap: wrap;")
        self.assertRegex(css, r"\.rowhead \.rtitle \{[^}]*white-space: normal;")
        self.assertRegex(css, r"\.rowhead > \.rtitle \+ :is\(")


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestUnitPages(unittest.TestCase):
    """Decision 7, 10 and the Unit page's own findings."""

    def test_the_page_opens_in_summary_one_line_per_row(self):
        r = drive("unit", "unit-plan-r1")
        self.assertEqual(r["openRows"], 0)
        self.assertEqual(r["textareas"], 0, "note fields only on demand")
        self.assertEqual(r["modeSummary"], "true")

    def test_do_it_and_leave_it_sit_on_the_rows_line(self):
        r = drive("unit", "unit-plan-r1")
        self.assertGreaterEqual(r["picksInHead"], 4, "two suggestions, a Do it and a Leave it each, answered without opening the row")

    def test_your_answer_lists_a_note_the_moment_it_is_written(self):
        r = drive("unit", "unit-end-r1")
        self.assertIn("Notes", r["answerAfterNote"])
        self.assertIn("baker's own words", r["answerAfterNote"])

    def test_the_tiles_are_numbers_the_page_can_show(self):
        r = drive("unit", "unit-plan-r3")
        self.assertIn("Steps18", r["facts"], "the tile is the rows of the plan block")
        self.assertIn("Look first2 rows", r["facts"], "the tile is what the Look first filter shows")
        r = drive("unit", "unit-end-r1")
        self.assertFalse([f for f in r["facts"] if f.startswith("Steps")], "no Steps tile on a page without a plan")

    def test_a_design_row_id_is_not_a_link_to_a_verification_row(self):
        out, _ = built()
        html = read(os.path.join(out, "unit-end-r1.html"))
        self.assertIn('class="rid" data-aidlc-noids title="The design row', html)

    def test_the_list_marks_the_current_page_and_mutes_the_replaced_ones(self):
        r = drive("list", "list-unit-pages")
        olds = [x for x in r["rows"] if x["old"]]
        news = [x for x in r["rows"] if not x["old"]]
        self.assertEqual(len(news), 2, "one current plan page and one current unit-end page")
        self.assertTrue(all("current" in x["text"] for x in news))
        self.assertTrue(all("replaced by round" in x["text"] for x in olds))
        self.assertTrue(any("Unit end" in x["text"] for x in r["rows"]), "unit-end pages are in the list")
        self.assertTrue(all(re.search(r"\d+ rows", x["text"]) for x in r["rows"]), "each row says how many rows it holds")


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestReadinessIsHonest(unittest.TestCase):
    """Decision 8."""

    def test_four_stories_tagged_not_handled_keep_needing_the_person_until_acknowledged(self):
        r = drive("ack", "gate-unhandled-items")
        self.assertGreaterEqual(r["ackButtons"], 4)
        self.assertEqual(r["afterRead"]["unread"], 0)
        self.assertGreater(r["afterRead"]["looks"], 0, "marking them read did not settle them")
        self.assertNotEqual(r["afterRead"]["text"], "Ready to answer")
        self.assertEqual(r["needsAfterRead"], r["needsStart"], "Needs you still holds them")
        self.assertEqual(r["afterOneAck"]["looks"], r["afterRead"]["looks"] - 1)
        self.assertEqual(r["afterAllAck"]["text"], "Ready to answer")


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestEachEvaluationCardIsItsOwnElement(unittest.TestCase):
    """Decision 9."""

    def test_every_card_has_its_own_mark_and_look_first_clears_when_it_is_read(self):
        r = drive("cards", "stage-2-4-user-stories-r1")
        self.assertGreaterEqual(r["cards"], 4)
        self.assertEqual(r["withDot"], r["cards"])
        self.assertEqual(r["keys"], r["cards"], "one key per card")
        self.assertEqual(r["lf"], "1 to look at first")
        self.assertTrue(r["lfHidden"] and r["lfAfter"].startswith("0"), "the count clears when the card is read")
        self.assertEqual(r["unreadDelta"], 1, "one card read is one thing read")
        self.assertTrue(all(not re.match(r"Mark (?:un)?read: (?:crit|item|eval|evc):", s) for s in r["labels"]))

    def test_a_dot_is_named_by_the_thing_it_marks_never_by_a_key(self):
        r = drive("tips", "stage-2-4-user-stories-r1")
        self.assertEqual(r["ariaRaw"], 0)


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestSmallerFindings(unittest.TestCase):
    """B-12, B-15, B-16, B-17, A-13."""

    def test_a_tooltip_never_shows_markdown_table_source(self):
        r = drive("tips", "build-and-test-r3")
        self.assertGreater(r["links"], 0)
        self.assertEqual(r["rawTables"], 0)
        self.assertEqual(r["rawKeys"], 0, "no anchor hash in the list of changes")

    def test_a_cell_pressed_twice_clears_and_a_filtered_list_says_so(self):
        r = drive("heat", "build-and-test-r3")
        self.assertEqual((r["rows0"], r["rows2"], r["rows3"]), (48, 48, 48))
        self.assertLess(r["rows1"], 48)
        self.assertRegex(r["showing1"], r"Showing \d+ of 48 targets")
        self.assertEqual(r["showing2"], "")
        self.assertTrue(r["clearButton"])

    def test_a_reject_without_a_reason_says_so_in_your_answer(self):
        r = drive("reject", "gate-findings-to-sort")
        self.assertIn("Reject, reason missing", r["answer"])
        self.assertIn("0 of 6 sorted", r["sorted"])


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestOneVocabularyEnglishDates(unittest.TestCase):
    """Decision 11."""

    def test_dates_are_english_whatever_the_browser_locale(self):
        r = drive("clean", "stage-2-4-user-stories-r3")
        self.assertRegex(r["dates"], r"\(2 Jan 2026, \d\d:\d\d\)")
        out, _ = built()
        for name in ("stage-2-4-user-stories-r3", "unit-plan-r3", "list-unit-pages", "test-plan"):
            self.assertNotRegex(read(os.path.join(out, name + ".html")).split("</style>")[-1], r"toLocale(?:Date|Time)?String\(\[\]")

    def test_the_unit_page_says_round_not_revision(self):
        r = drive("unit", "unit-plan-r3")
        self.assertIn("Round 3 compared with round", r["banner"])
        self.assertNotIn("Revisions:", read(UNIT_PAGE))


class TestTraceDiagram(unittest.TestCase):
    """Decision 12 and A-21: the order untangles; above a size the trace is offered per requirement."""

    def run_viz(self, code):
        done = subprocess.run([NODE, "-e", "const V = require(process.argv[1]); process.stdout.write(JSON.stringify((" + code + ")(V)))", VIZ], capture_output=True, text=True, timeout=60)
        if done.returncode:
            raise AssertionError(done.stderr)
        return json.loads(done.stdout)

    @unittest.skipUnless(NODE, "needs Node")
    def test_a_small_trace_is_in_natural_order(self):
        out = self.run_viz("""(V) => {
          const ids = ["US10.1", "US2.1", "US1.1", "US11.1"];
          const d = { kind: "trace", id: "t", cols: [{ key: "a", label: "Requirements" }, { key: "b", label: "Stories" }],
            nodes: [{ id: "FR1", col: "a" }].concat(ids.map((i) => ({ id: i, col: "b" }))), edges: ids.map((i) => ["FR1", i]), alt: "x" };
          const svg = V.diagram(d, {});
          return { order: [...svg.matchAll(/class="vz-id" x="\\d+" y="(\\d+)">(US[\\d.]+)</g)].sort((a, b) => a[1] - b[1]).map((m) => m[2]), pick: /vz-pick/.test(svg) };
        }""")
        self.assertEqual(out["order"], ["US1.1", "US2.1", "US10.1", "US11.1"])
        self.assertFalse(out["pick"])

    @unittest.skipUnless(NODE, "needs Node")
    def test_a_big_trace_is_offered_per_requirement(self):
        out = self.run_viz("""(V) => {
          const reqs = Array.from({ length: 16 }, (_, i) => "FR" + (i + 1)), stories = reqs.map((r, i) => "US" + (i + 1) + ".1");
          const d = { kind: "trace", id: "t", cols: [{ key: "a", label: "Requirements" }, { key: "b", label: "Stories" }],
            nodes: reqs.map((i) => ({ id: i, col: "a" })).concat(stories.map((i) => ({ id: i, col: "b" }))), edges: reqs.map((r, i) => [r, stories[i]]), alt: "x" };
          const svg = V.diagram(d, {});
          return { pick: /<select class="vz-pick"/.test(svg), chains: (svg.match(/class="vz-chain"/g) || []).length, hidden: (svg.match(/class="vz-chain" data-for="[^"]+" hidden/g) || []).length,
                   first: (svg.match(/class="vz-chain" data-for="([^"]+)"/) || [])[1], nodesInFirst: (svg.split('class="vz-chain"')[1].split("</svg>")[0].match(/class="vz-node/g) || []).length };
        }""")
        self.assertTrue(out["pick"])
        self.assertEqual((out["chains"], out["hidden"], out["first"], out["nodesInFirst"]), (16, 15, "FR1", 2), "one chain shows: the requirement and its story")


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestTestPlanPage(unittest.TestCase):
    """Decision 13."""

    def test_it_opens_at_its_top_with_the_progress_in_view(self):
        r = drive("plan", "test-plan")
        self.assertEqual(r["scrolls"], 0, "no scroll jump on load")
        self.assertTrue(r["pbar"] and r["next"])
        self.assertEqual(r["progress"], "2/7")
        self.assertTrue(r["crumbsLink"] and r["band"])
        self.assertTrue(r["status"].startswith("Open"))

    def test_it_has_the_others_width_and_visible_focus(self):
        css = css_of(PLAN_PAGE)
        self.assertRegex(css, r"#app \{ max-width: 1180px;")
        self.assertIn(".pbar { position: sticky;", css)
        self.assertIn(".rb button:focus-visible { outline-offset: -3px; }", css, "the segmented buttons clip their outline")
        self.assertIn(".vchip:focus-visible", css)
        self.assertEqual(re.search(r"max-width: (\d+)px; margin: 0 auto", css_of(UNIT_PAGE)).group(1), "1180", "the Unit pages' column")


class TestPreviewCoversWhatReviewersCouldNotReach(unittest.TestCase):
    """Decision 14."""

    def test_the_new_scenarios_exist(self):
        _, scenarios = built()
        names = {s.name: s for s in scenarios}
        self.assertIn("gate-ideation-open-decisions", names, "a phase 0-2 gate with open decisions")
        rows = names["gate-ideation-open-decisions"].rows
        self.assertTrue(any(v.get("findings") and v["findings"].get("items") for k, v in rows.items() if "/documents/" not in k), "it has findings to sort")
        for n in ("stage-2-6-domain-design-r1", "stage-2-7-units-generation-r3", "stage-3-5-code-generation-r1"):
            gate = [v for k, v in names[n].rows.items() if "/documents/" not in k][0]
            self.assertTrue(gate.get("maps"), f"{n}: gate rows that carry links to the maps")
            self.assertTrue(all(m["url"].startswith("https://") for m in gate["maps"]))
        plan = [v["bundle"] for v in names["unit-plan-r1"].rows.values()][0]
        self.assertTrue(any(r.get("suggestion") for s in plan["sections"] for r in s["rows"]), "suggestion rows with Do it / Leave")
        listed = {v["page"] for v in names["list-unit-pages"].rows.values()}
        self.assertEqual(listed, {"plan", "unit-end"}, "unit-end pages in the list view")

    def test_the_rows_say_what_a_real_agent_would(self):
        import preview
        s = preview.plain_summary("Refunds\nStatus: accepted\nContext\nA refund is issued within 3 days. Staff see it at once.")
        self.assertEqual(s, "Refunds: a refund is issued within 3 days.")
        self.assertNotRegex(preview.plain_summary("Reminders\nAs a counter clerk, I want to see stock."), r"^Reminders As")

    def test_a_scenario_that_starts_at_round_one_is_round_one(self):
        _, scenarios = built()
        for n in ("gate-findings-to-sort", "gate-nothing-pending", "gate-unhandled-items"):
            sc = next(s for s in scenarios if s.name == n)
            gate = [v for k, v in sc.rows.items() if "/documents/" not in k][0]
            self.assertEqual((gate["round"], gate["why"]), (1, "first"), n)


if __name__ == "__main__":
    unittest.main()
