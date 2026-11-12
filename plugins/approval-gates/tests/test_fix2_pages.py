"""Fix round 2 of the pages (approval-gates 1.35.1): the minor findings of a second on-screen review of the preview pages. One test per
finding (the ids are the review's):

  E-1  a disclosure opens to something it did not show closed (the per-id trace), never to its own header again
  E-2  at a phone width no card is sized by a flex-basis (the "What you asked for" card)
  E-3  F-5  the bar's Rounds control says what is compared: "Round 3 vs 2" (short "r3 vs r2"), in the round's colour; the maps page too
  E-4  F-8  an opened item says its sentence once; the same reference is one chip; a note is listed once in Your answer
  E-5  a diagram wider than its frame says so and has a fade and a scrollbar
  E-6  a criterion's read dot is named "Mark read: <text>, <verdict>"
  E-7  a decision's summary says the decision (the validator names a summary that is only the topic)
  E-8  the acknowledgement sits at the foot of its tile
  F-1  Do it / Leave it mark the row read, as Test now / Later and the per-stage picks do
  F-2  the header's changed / new split is the rows' tags
  F-3  the chain of pieces wraps, is never drawn under three pieces
  F-4  Expand all / Mark all read live in "View and actions", with the keys listed (and ? opens it)
  F-6  the Needs you chip is the rows that wait; a row just settled says Done
  F-7  the test plan page clips nothing; the preview hands it whole sentences
  --   the first filter pill is "All", with no count

jsdom on the preview pages (drive_fix2.js); skipped without Node and the jsdom package. Synthetic data only."""

import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shutil  # noqa: E402
import tempfile  # noqa: E402
from test_fix1_pages import NODE, PLAN_PAGE, SKILL, STAGE_PAGE, UNIT_PAGE, PLUGIN, css_of, has_jsdom, read  # noqa: E402

_BUILT = {}


def built():
    """The preview tool's output, written once for this module (fix round 1's module removes its own folder when it ends)."""
    if "out" not in _BUILT:
        sys.path.insert(0, os.path.join(PLUGIN, "dev"))
        import preview
        _BUILT["out"] = tempfile.mkdtemp(prefix="gates-fix2-test-")
        _BUILT["scenarios"] = preview.build(_BUILT["out"], say=lambda *_: None)
    return _BUILT["out"], _BUILT["scenarios"]


def tearDownModule():
    if "out" in _BUILT:
        shutil.rmtree(_BUILT["out"], ignore_errors=True)

MAPS_PAGE = os.path.join(SKILL, "maps.html")
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))


def drive(scenario, name):
    out, _ = built()
    done = subprocess.run([NODE, os.path.join(HERE, "drive_fix2.js"), scenario, os.path.join(out, name + ".html")], capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise AssertionError(done.stderr)
    result = json.loads(done.stdout)
    assert not result.get("errors"), result["errors"]
    return result


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestFixRound2(unittest.TestCase):
    def test_e1_the_traceability_disclosure_opens_to_the_trace(self):
        for page in ("stage-2-4-user-stories-r1", "stage-2-7-units-generation-r1"):
            r = drive("trace", page)
            self.assertTrue(r["found"], page)
            self.assertGreater(r["entries"], 0, "it opens to the per-id coverage: " + page)
            self.assertFalse(r["again"], "it does not say its own header again: " + r["body"][:80])

    def test_e3_f5_the_rounds_control_says_what_is_compared(self):
        r = drive("bar", "stage-2-4-user-stories-r3")
        self.assertEqual(r["long"], "Round 3 vs 2")
        self.assertEqual(r["short"], "r3 vs r2")
        self.assertIn("rv-t3", r["roundsClass"], "in the round's colour")
        self.assertIn("compared with round 2", r["roundsAria"])
        u = drive("bar", "unit-plan-r3")
        self.assertEqual(u["long"], "Round 3 vs 1")
        self.assertEqual(u["short"], "r3 vs r1")
        self.assertIn("rv-t3", u["roundsClass"])
        css = css_of(STAGE_PAGE)
        self.assertRegex(css, r"\.bmb \.rl-l, \.bmb \.vl-l \{ display: none; \} \.bmb \.rl-s, \.bmb \.vl-s \{ display: inline; \}", "the short form on a phone")

    def test_e3_the_maps_bar_names_the_round(self):
        src = read(MAPS_PAGE)
        self.assertIn('id="map-round"', src)
        self.assertRegex(src, r'"r" \+ esc\(row\.revision\) \+ " vs r" \+ esc\(d\.rev\)')
        self.assertRegex(src, r'"Round " \+ esc\(row\.revision\) \+ " vs " \+ esc\(d\.rev\)')

    def test_f4_view_and_actions_lists_the_actions_and_the_keys(self):
        for page in ("stage-2-4-user-stories-r3", "unit-plan-r3"):
            r = drive("bar", page)
            self.assertEqual(r["viewAria"], "View and actions", page)
            self.assertEqual((r["viewLong"], r["viewShort"]), ("View and actions", "View"))
            self.assertTrue(r["questionOpens"], "? opens the menu: " + page)
            for k in ("n", "u", "?", "Esc"):
                self.assertIn(k, r["keys"], page)
            self.assertIn("Actions", r["actionsLabels"])
            self.assertTrue(any("Expand all" in t for t in r["actions"]) and any("Mark all read" in t for t in r["actions"]), r["actions"])

    def test_the_all_pill_has_no_count(self):
        for page in ("stage-2-4-user-stories-r3", "unit-plan-r3", "build-and-test-r1"):
            r = drive("bar", page)
            self.assertFalse(r["allHasCount"], page)
            self.assertEqual(r["allPill"], "All", page)

    def test_e4_an_opened_item_says_its_sentence_once(self):
        r = drive("item", "stage-2-4-user-stories-r1")
        self.assertFalse(r["sayingTwice"], r)
        self.assertEqual(len(r["rel"]), len(set(r["rel"])))

    def test_e6_a_criterions_read_dot_is_named_with_its_verdict_after_a_comma(self):
        r = drive("dots", "stage-2-4-user-stories-r3")
        self.assertTrue(r["labels"])
        for lab in r["labels"]:
            self.assertRegex(lab, r"^Mark (read|unread): .+, (holds|fails|n/a|not relevant|not judged)$")
            self.assertNotRegex(lab, r"^Mark (read|unread): (Holds|Fails|N/A)", "the verdict is not glued to the text")

    def test_e8_the_acknowledgement_sits_at_the_foot_of_its_tile(self):
        r = drive("ack", "build-and-test-r3")
        self.assertTrue(r["found"])
        self.assertTrue(r["last"] and r["afterLabel"] and not r["nextToDot"], r)

    def test_e2_no_card_is_sized_by_a_flex_basis_on_a_phone(self):
        css = css_of(STAGE_PAGE)
        self.assertRegex(css, r"@media \(max-width: 640px\) \{ \.rvhead \{ flex-direction: column; \} \.rvhead > \* \{ flex: 0 0 auto; \}")

    def test_f1_do_it_and_leave_it_mark_the_row_read(self):
        r = drive("unit-reads", "unit-plan-r3")
        self.assertEqual(int(r["afterDo"]), int(r["before"]) - 1, r)
        self.assertEqual(int(r["afterLeave"]), int(r["before"]) - 2, r)
        self.assertRegex(r["dotAfterDo"], r"unread")

    def test_f2_the_headers_split_is_the_rows_tags(self):
        for page in ("unit-plan-r3", "unit-end-r3", "unit-end-after-test-plan"):
            r = drive("unit-split", page)
            self.assertEqual(r["said"]["changed"], r["tags"]["changed"], (page, r))
            self.assertEqual(r["said"]["new"], r["tags"]["new"], (page, r))

    def test_f3_the_pieces_wrap_and_none_is_drawn_under_three(self):
        r = drive("unit-chain", "unit-end-r1")
        self.assertTrue(r["flow"] and not r["scroll"], "wrapped, not a sideways scroll")
        self.assertGreaterEqual(r["nodes"], 3)
        for t, tip in zip(r["titles"], r["tips"]):
            self.assertTrue(tip.startswith(t), "a label is whole, and its title says it whole")
        self.assertRegex(read(UNIT_PAGE), r"if \(nodes\.length < 3\) return \"\";")
        self.assertTrue(any("Leads to" in t for t in r["tips"]), "an edge is in the title of the piece it leaves")

    def test_f6_the_needs_you_chip_is_the_rows_that_wait(self):
        for page in ("unit-end-r1", "unit-plan-r1"):
            r = drive("unit-needs", page)
            self.assertEqual(r["before"]["chip"], r["before"]["rows"], (page, r))
            a = r["after"]
            self.assertEqual(a["chip"], a["rows"] - a["settled"], (page, r))
            self.assertEqual(a["done"], a["settled"], "a settled row says Done: " + page)
            self.assertGreaterEqual(a["done"], 1)

    def test_f8_a_note_is_listed_once_in_your_answer(self):
        r = drive("unit-answer", "unit-end-r1")
        self.assertEqual(r["times"], 1, r)

    def test_e5_a_wide_diagram_says_so(self):
        r = drive("viz-cue", "stage-3-1-functional-design-r1")
        self.assertTrue(r["found"] and r["on"], r)
        self.assertIn("scroll sideways", r["said"])
        self.assertTrue(r["goneWhenFits"])
        viz = read(os.path.join(os.path.dirname(os.path.dirname(PLUGIN)), "shared", "gate-viz", "gate-viz.css"))
        self.assertIn("::-webkit-scrollbar", viz)
        self.assertRegex(viz, r"no-repeat local")


class TestFixRound2Text(unittest.TestCase):
    def test_e7_a_decision_that_is_only_its_topic_is_named(self):
        import judgment
        self.assertTrue(judgment.says_only_topic({"title": "Refunds", "summary": "Refunds."}))
        self.assertTrue(judgment.says_only_topic({"title": "Opening hours", "summary": "Hours decided."}))
        self.assertFalse(judgment.says_only_topic({"title": "Refunds", "summary": "Refunds go back to the card within three working days."}))

    def test_e7_the_previews_decisions_say_the_decision(self):
        import preview
        s = preview.plain_summary("ADR-001 Refunds\n\n**Status:** accepted\n\n**Context.** Some context here.\n\n**Decision.** Refunds go back to the card within three days.\n")
        self.assertIn("go back to the card", s)

    def test_f7_the_test_plan_page_clips_nothing(self):
        css = css_of(PLAN_PAGE)
        self.assertNotRegex(css, r"line-clamp|text-overflow")
        import preview_units
        _, row = preview_units.test_plan_row()
        for sec in row["plan"]["sections"]:
            for st in sec["steps"]:
                for c in st["criteria"]:
                    self.assertRegex(c, r"[.!?]$", "a criterion is a whole sentence: " + c)


if __name__ == "__main__":
    unittest.main()
