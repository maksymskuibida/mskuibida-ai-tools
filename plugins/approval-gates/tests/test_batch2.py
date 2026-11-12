"""Batch 2 of the pages' rework: "Needs you" is a view over the items in place (1), a readiness counter with keys (2), a
"Your answer" block (3), every file in one "Records" block (4), one row pattern (5), and read state that stays right (6).

Synthetic data only: batch1_fixture.py's bakery gate with a failed command, an item nothing handles, a criterion not judged
and a file the evaluation does not cover added; the bakery Unit bundles of test_validate_bundle.py. The per-stage page runs
under jsdom (drive_batch2.js, and drive_batch2_unit.js for the Unit page's controller); the Unit page's render functions run
under Node. Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch1_fixture as fx  # noqa: E402
from bundle_helpers import NODE, render  # noqa: E402
from test_validate_bundle import end_bundle, plan_bundle, row  # noqa: E402

SKILL = os.path.join(os.path.dirname(HERE), "skills", "approval-gates")
PAGE = os.path.join(SKILL, "approval-gate.html")
UNIT_PAGE = os.path.join(SKILL, "unit-gate.html")
UNIT_DRIVER = os.path.join(HERE, "drive_batch2_unit.js")
DRIVER = os.path.join(HERE, "drive_batch2.js")


def has_jsdom():
    return bool(NODE) and subprocess.run([NODE, "-e", "require('jsdom')"], capture_output=True).returncode == 0


def gate():
    """Round one of the batch-1 bakery gate, plus: a failed command, an item nothing handles (FR2), a criterion nobody judged,
    and a file the evaluation does not cover (release-notes). Needs you = 3 targets + 2 findings + the failed command + FR2 + 2 criteria."""
    s = copy.deepcopy(fx.sample(False))
    r = s["row"]
    r["buildTest"]["commands"].append({"check": "Slot tests", "command": "pytest slots", "result": "2 failed", "ok": False})
    for it in r["digest"]["items"]:
        if it["key"] == "FR2":
            it["coveredBy"] = {"text": "No stage covers it"}
    r["criteria"].append({"key": "stage-2", "origin": "stage", "title": "Every command has a result", "text": "Every command has a result.", "source": "path:stage.md#L8", "verdict": "unjudged"})
    r["documents"].append({"key": "release-notes", "title": "Release notes", "kind": "markdown", "covered": False, "path": "aidlc/x/release-notes.md"})
    s["documents"]["release-notes"] = {"key": "release-notes", "title": "Release notes", "kind": "markdown", "n": 3, "path": "aidlc/x/release-notes.md",
                                       "text": "# Release notes\n\n## Slots\n\nPick-up slots are 15 minutes.\n\n## Known limits\n\nThe list loads in 1.4 s.\n"}
    return s


NEEDS = ["target:U1/u1:NFR1", "target:U1/u1:NFR6", "target:U1/u1:NFR2", "finding:R-01", "finding:R-02", "cmd:failed", "item:FR2", "crit:review-1", "crit:stage-2"]


def drive(sample, scenario, name="s"):
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, name + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sample, f)
        done = subprocess.run([NODE, DRIVER, PAGE, path, scenario], capture_output=True, text=True, timeout=120)
        assert done.returncode == 0 and done.stdout, done.stderr
        out = json.loads(done.stdout)
        assert "error" not in out, out["error"]
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestNeedsYouIsAView(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.view = drive(gate(), "view")

    def test_the_filter_sits_next_to_all_and_unread_with_the_count_of_things_that_wait(self):
        v = self.view
        self.assertEqual(v["order"][:3], ["All", "Needs you", "Unread"])
        self.assertTrue(v["pillBefore"].startswith("Needs you") and v["pillBefore"].endswith(str(len(NEEDS))), v["pillBefore"])
        self.assertEqual(v["pressed"], "Needs you")

    def test_it_shows_only_what_waits_each_inside_its_own_block(self):
        v = self.view
        self.assertCountEqual(v["items"], NEEDS, "a target without a pick, a finding not sorted, a failed command, an unhandled item, a criterion that fails or is not judged")
        self.assertEqual(v["blocks"], ["b-bt-strip", "b-eval", "b-items", "b-findings", "b-bt-matrix"], "each thing still inside its own block, in page order")
        heads = {b["id"]: b["head"] for b in v["sections"]}
        self.assertEqual(heads["b-eval"], "Claude's evaluation", "the block header stays so the person knows where they are")
        self.assertEqual(heads["b-findings"], "Findings to sort")
        self.assertEqual(heads["b-bt-matrix"], "Target matrix")
        for gone in ("b-summary", "b-brief", "b-records", "b-answer", "b-revision"):
            self.assertNotIn(gone, v["blocks"], "a block with nothing pending hides: " + gone)

    def test_it_is_not_a_second_block_that_copies_them(self):
        v = self.view
        self.assertEqual(v["allBlocks"].count("b-needs"), 0)
        self.assertEqual(len(v["items"]), len(set(v["items"])), "every thing once")
        self.assertEqual(v["rows"], ["u1:NFR1", "u1:NFR6", "u1:NFR2"], "the Met and N/A rows are not waiting")
        self.assertEqual(v["stripTiles"], ["cmd:failed"], "only the failed command's tile stays in the results strip")

    def test_the_folds_with_nothing_pending_leave(self):
        self.assertNotIn("tm-fold", " ".join(self.view["containers"]))
        self.assertFalse(self.view["answerShown"])


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestOneNodeOneKey(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = drive(gate(), "shared")

    def test_a_mark_set_under_needs_you_shows_under_all(self):
        r = self.r
        self.assertTrue(r["underAll"]["sameNode"], "the same DOM node in both views")
        self.assertTrue(r["underAll"]["read"] and r["underAll"]["dot"])

    def test_a_mark_set_under_all_shows_under_needs_you(self):
        self.assertTrue(self.r["itemAfterReadUnderAll"], "an unhandled item has nothing to decide, but reading it does not settle it: it stays until acknowledged")

    def test_a_note_written_under_needs_you_is_the_note_under_all(self):
        self.assertEqual(self.r["noteUnderAll"], "check on a 3G phone")
        self.assertTrue(self.r["sameRow"])


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestResolvedNotRead(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = drive(gate(), "settle")

    def test_reading_a_decision_does_not_resolve_it(self):
        r = self.r
        self.assertTrue(r["afterReadOnly"]["shown"] and not r["afterReadOnly"]["settled"])
        self.assertEqual(r["afterReadOnly"]["count"], r["count0"], "the count did not move")

    def test_a_pick_settles_the_row_in_place_greyed_and_the_count_drops(self):
        r = self.r
        self.assertTrue(r["afterPick"]["shown"], "it does not vanish under the cursor")
        self.assertTrue(r["afterPick"]["settled"] and r["afterPick"]["chosen"])
        self.assertTrue(r["afterPick"]["count"].endswith(str(len(NEEDS) - 1)), r["afterPick"]["count"])

    def test_the_undo_is_the_pick_pressed_again(self):
        r = self.r
        self.assertTrue(r["afterUndo"]["shown"] and not r["afterUndo"]["settled"])
        self.assertEqual(r["afterUndo"]["count"], r["count0"])

    def test_a_sorted_finding_stays_settled_until_the_filter_is_painted_again(self):
        r = self.r
        self.assertTrue(r["findingKept"]["shown"] and r["findingKept"]["settled"])
        self.assertNotIn("finding:R-01", r["afterRepaint"])
        self.assertNotIn("target:U1/u1:NFR1", r["afterRepaint"])
        self.assertTrue(r["writes"], "the pick was saved as before")


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestReadiness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = drive(gate(), "ready")

    def test_it_says_decisions_left_and_unread_and_hides_a_part_at_zero(self):
        r = self.r
        self.assertEqual(r["initial"]["decisions"], 5)
        self.assertRegex(r["initial"]["text"], r"^5 decisions left(?: · \d+ to look at)? · \d+ unread$")
        self.assertRegex(r["afterPicks"]["text"], r"^(?:\d+ to look at · )?\d+ unread$", "no decisions part at zero")

    def test_ready_to_answer_when_both_are_zero_and_it_goes_to_your_answer(self):
        r = self.r
        self.assertNotEqual(r["afterRead"]["text"], "Ready to answer", "reading what is tagged not handled or failing does not settle it")
        self.assertGreater(r["afterRead"]["looks"], 0)
        self.assertEqual(r["afterRead"]["text"], f'{r["afterRead"]["looks"]} to look at')
        self.assertGreater(r["acks"], 0, "each such thing carries its own Seen, will answer in chat")
        self.assertEqual(r["afterAck"]["text"], "Ready to answer")
        self.assertTrue(r["answerOpen"] and r["answerShown"] and r["flashAnswer"])

    def test_the_next_decision_button_walks_the_decisions_in_page_order_and_wraps(self):
        seen = self.r["nextDecisions"]
        self.assertEqual(len(set(seen[:5])), 5, "five different decisions")
        self.assertEqual(seen[5], seen[0], "then it starts over")

    def test_n_and_u_do_what_the_buttons_do_and_stay_silent_inside_a_field(self):
        r = self.r
        self.assertTrue(r["keyN"] and r["keyU"] and r["firstUnread"])
        self.assertFalse(r["firedInField"])


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestYourAnswer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = drive(gate(), "answer")

    def test_it_is_the_last_block_and_says_what_it_is(self):
        r = self.r
        self.assertEqual(r["last"], ["b-records", "b-answer"])
        self.assertIn("The decision itself", r["statement"])
        self.assertIn("given in chat", r["statement"])
        self.assertIn("reach Claude when you answer", r["statement"])
        self.assertIn("You have not picked or written anything yet", r["empty"])

    def test_picks_notes_and_sorts_are_grouped_as_they_reach_claude(self):
        g = {x["id"]: x["rows"] for x in self.r["groups"]}
        self.assertEqual(list(g), ["targets", "findings", "notes"])
        self.assertEqual(g["targets"], ["u1:NFR1 Fix now", "u1:NFR2 Follow-up run it after a restart"])
        self.assertEqual(g["findings"], ["R-02 Accept"])
        self.assertEqual(g["notes"], ["Release notes mention the 3 s page"])
        self.assertEqual(self.r["left"], "2 decisions still without a pick.")

    def test_each_row_links_back_and_nothing_new_is_stored(self):
        r = self.r
        self.assertEqual(r["links"], ["target:U1/u1:NFR1", "target:U1/u1:NFR2", "finding:R-02", "release-notes"])
        self.assertIn("target:U1/u1:NFR1", r["jumped"])
        gate_writes = [w for w in r["writes"] if w != "marks"]
        self.assertTrue(gate_writes and all(w == "findingPicks,notes,targetPicks" for w in gate_writes), "only what the gate stored before: picks and notes")
        self.assertEqual(r["stored"]["local"], [])


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestRecords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = drive(gate(), "records")

    def test_every_file_is_a_row_of_one_closed_block_at_the_bottom(self):
        r = self.r
        self.assertEqual(r["docsOutside"], [], "no file is drawn in full outside Records")
        self.assertEqual(r["oldBlocks"], [False, False], "Reference and As written are gone")
        self.assertEqual(r["blocks"][-2:], ["b-records", "b-answer"])
        self.assertFalse(r["recordsOpen"])
        self.assertEqual(r["count"], "3 files")

    def test_the_files_the_evaluation_does_not_cover_are_listed_first_with_their_tag(self):
        rows = self.r["rows"]
        self.assertEqual([x["id"] for x in rows], ["d-release-notes", "d-build-and-test-summary", "d-test-results"])
        self.assertEqual([x["why"] for x in rows], ["notcovered", "covered", "covered"], "the two covered files come after the one nothing covers")

    def test_a_row_has_its_derived_read_dot_but_a_covered_file_is_read_through_its_items(self):
        rows = {x["id"]: x for x in self.r["rows"]}
        self.assertTrue(rows["d-release-notes"]["dot"])
        self.assertFalse(rows["d-test-results"]["dot"] or rows["d-build-and-test-summary"]["dot"])

    def test_an_uncovered_file_counts_as_unread_until_read_and_gets_a_chip(self):
        r = self.r
        self.assertTrue(any(c.startswith("Records") for c in r["chips"]), r["chips"])
        self.assertGreater(r["readyBefore"]["unread"], 0, "the file nothing covers is one of the unread things in the counter")
        m = drive(gate(), "marks")
        self.assertEqual(m["unreadAfter"], m["unreadBefore"], "reading it in the first page and drawing it again in the second: still read")
        self.assertTrue(m["secondRead"])

    def test_moving_the_files_keeps_every_key(self):
        m = drive(gate(), "marks")
        self.assertIn("release-notes", m["keys"], "the document's own key, as before Records existed")
        self.assertFalse([k for k in m["keys"] if "records" in k])

    def test_a_link_into_a_file_opens_records_then_the_file_then_lands(self):
        d = drive(gate(), "deeplink")
        self.assertFalse(d["before"]["records"])
        self.assertTrue(d["afterGo"]["records"] and d["afterGo"]["doc"] and d["afterGo"]["flashed"])
        self.assertTrue(d["afterChip"]["hasChip"] and d["afterChip"]["records"])


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestNoEvaluationKeepsItsFiles(unittest.TestCase):
    def test_a_gate_with_nothing_else_to_read_opens_records(self):
        s = copy.deepcopy(gate())
        for k in ("evaluation", "criteria", "digest", "findings", "buildTest", "brief", "review", "summary"):
            s["row"].pop(k, None)
        for d in s["row"]["documents"]:
            d["covered"] = False
        got = drive(s, "records")
        self.assertTrue(got["recordsOpen"], "the files are the only reading: Records starts open")
        self.assertEqual(got["docsOutside"], [])


# ---------------------------------------------------------------- the Unit pages

def plan_page():
    b = plan_bundle()
    b["sections"][0]["rows"][1]["suggestion"] = "Show the closest free slot first"
    b["sections"][1]["rows"].append(row("FD R-03", "medium", coveredBy={"text": "Nothing covers it"}))
    b["sections"][1]["rows"].append(row("FD R-04", "low", coveredBy={"text": "Left for later", "acceptanceReason": {"text": "Later Unit.", "by": "agent"}}))
    return b


def rows_of(page):
    """The ids of the rows a rendered Unit page draws, in page order."""
    return re.findall(r'<div class="row[^"]*" id="([^"]+)"', page.split("<main>")[1])


def end_page():
    b = end_bundle()
    b["sections"][1]["rows"].append(row("V-2", "medium"))
    return b


@unittest.skipUnless(NODE, "node is not installed")
class TestUnitNeedsYou(unittest.TestCase):
    def test_the_filter_has_a_count_and_the_rows_that_wait_are_decisions_or_unhandled(self):
        out = render(plan_page(), {"all": {}, "needs": {"filter": "needs"}})
        self.assertRegex(out["all"], r'data-val="needs" aria-pressed="false" title="[^"]*">Needs you<b class="n">2</b>', "A-2 has no Do/Leave, FD R-03 is not handled; FD R-04 has a reason, A-1 has no suggestion")
        page = out["needs"]
        self.assertEqual(rows_of(page), ["A-2", "FD-R-03"], "FD R-02 is linked, FD R-04 has a reason, A-1 and T-1 decide nothing")
        self.assertNotIn('data-sec="plan"', page, "no plan steps wait")
        self.assertNotIn('data-sec="records"', page)
        self.assertNotIn('data-sec="answer"', page, "Your answer shows with the whole page")

    def test_a_pick_settles_in_place_and_reading_does_not(self):
        keep = {"A-2": 1, "FD-R-03": 1}
        page = render(plan_page(), {"s": {"filter": "needs", "picks": {"A-2": "do"}, "needsKeep": keep},
                                    "r": {"filter": "needs", "read": {"A-2": 1}, "needsKeep": keep},
                                    "x": {"filter": "needs", "picks": {"A-2": "do"}}})
        self.assertEqual(rows_of(page["s"]), ["A-2", "FD-R-03"], "picked: kept")
        self.assertIn('class="row nsettled" id="A-2"', page["s"], "...and greyed")
        self.assertNotIn("nsettled", page["r"], "read is not decided: still waiting, not greyed")
        self.assertEqual(rows_of(page["x"]), ["FD-R-03"], "painted again from the bar: the picked one leaves")

    def test_an_unhandled_row_leaves_when_read_and_a_unit_end_test_pick_when_picked(self):
        read = render(plan_page(), {"x": {"filter": "needs", "read": {"FD-R-03": 1}}})["x"]
        self.assertEqual(rows_of(read), ["A-2"])
        out = render(end_page(), {"all": {}, "picked": {"filter": "needs", "picks": {"V-1": "now"}}})
        self.assertIn('Needs you<b class="n">2</b>', out["all"], "V-1 and V-2 are not verified and have no Test now / Later")
        self.assertEqual(rows_of(out["picked"]), ["V-2"])

    def test_the_readiness_counter(self):
        read = {k: 1 for k in ("A-1", "A-2", "FD-R-02", "FD-R-03", "FD-R-04", "T-1", "step:1")}
        out = render(plan_page(), {"all": {}, "done": {"picks": {"A-2": "do"}, "read": read}})
        self.assertIn('data-decisions="1" data-unread="', out["all"])
        self.assertRegex(out["all"], r'data-act="next" data-val="n"[^>]*>1 decision left</button><span class="sep"[^>]*> · </span><button[^>]*data-val="u"[^>]*>\d+ unread</button>')
        self.assertIn(">Ready to answer</button>", out["done"])
        self.assertNotIn("decision left", out["done"], "no decisions part at zero")
        self.assertNotIn(" unread</button>", out["done"], "no unread part at zero")


@unittest.skipUnless(NODE, "node is not installed")
class TestUnitYourAnswerAndRecords(unittest.TestCase):
    def test_your_answer_groups_picks_and_notes_and_links_back(self):
        st = {"picks": {"A-2": "do", "FD-R-03": ""}, "notes": {"A-1": "keep the slot short", "step-1": "split it"}}
        page = render(plan_page(), {"x": st})["x"]
        ans = page.split('id="answer"')[1]
        self.assertIn("The decision itself, approve or request changes, is given in chat", ans)
        self.assertIn("stores nothing", ans)
        self.assertIn('data-ans="suggestions"', ans)
        self.assertRegex(ans, r'data-jump="A-2">A-2</a><b>Do it</b>')
        self.assertRegex(ans, r'data-ans="notes".*data-jump="A-1">A-1</a><span class="ansn">keep the slot short</span>.*data-jump="step-1">Step 1</a><span class="ansn">split it</span>')
        self.assertLess(page.index('id="records"'), page.index('id="answer"'), "the last block")

    def test_test_picks_are_their_own_group_and_the_block_hides_under_a_filter(self):
        page = render(end_page(), {"x": {"picks": {"V-1": "later"}}, "u": {"filter": "unread"}})
        self.assertRegex(page["x"], r'data-ans="tests".*data-jump="V-1">V-1</a><b>Later</b>')
        self.assertNotIn('id="answer"', page["u"])

    def test_records_is_one_closed_block_holding_the_answers_and_the_design(self):
        shut = render(plan_page(), {"x": {}})["x"]
        self.assertEqual(shut.count('data-sec="records"'), 1)
        self.assertNotIn('data-part="answers"', shut, "closed by default")
        self.assertIn('differs from proposal<b>1</b>', shut, "the chip stays on the closed block")
        opened = render(plan_page(), {"x": {"sec": {"records": True}}})["x"]
        self.assertIn('data-part="answers"', opened)
        end = render(end_page(), {"x": {"sec": {"records": True}}})["x"]
        self.assertIn('data-part="design"', end)
        self.assertNotIn('data-sec="answers"', shut + opened + end)
        self.assertNotIn('data-sec="design"', shut + opened + end)

    def test_the_n_and_p_keys_are_free_for_the_readiness_counter(self):
        with open(UNIT_PAGE, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn('e.key === "n" || e.key === "j"', src)
        self.assertIn('Next change (j)', src)


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestUnitController(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        b = plan_page()
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "b.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"id": b["id"], "bundle": b, "createdAt": b["createdAt"], "intent": b["header"]["intent"], "unit": b["header"]["unit"], "page": "plan", "notes": {}, "picks": {}}, f)
            done = subprocess.run([NODE, UNIT_DRIVER, UNIT_PAGE, path], capture_output=True, text=True, timeout=120)
            assert done.returncode == 0 and done.stdout, done.stderr
            cls.r = json.loads(done.stdout)
            assert "error" not in cls.r, cls.r["error"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_needs_you_keeps_a_settled_row_until_the_bar_is_pressed_again(self):
        r = self.r
        self.assertEqual(r["needsRows"], ["A-2", "FD-R-03"])
        self.assertEqual(r["afterPick"]["rows"], ["A-2", "FD-R-03"])
        self.assertTrue(r["afterPick"]["settled"])
        self.assertEqual(r["afterPick"]["pill"], "Needs you1")
        self.assertEqual(r["afterBar"], ["FD-R-03"])

    def test_the_counter_buttons_and_keys_go_to_the_next_row(self):
        r = self.r
        self.assertTrue(r["ready0"].startswith("1 decision left · "), r["ready0"])
        self.assertEqual(r["nextN"], ["A-2", "A-2", "A-2"], "the one decision without a pick")
        self.assertTrue(r["keyN"] and r["keyU"])
        self.assertEqual(r["inField"], 0, "n inside a note field does nothing")

    def test_ready_to_answer_and_your_answer_lists_the_picks_and_notes(self):
        r = self.r
        self.assertEqual(r["afterRead"], "Ready to answer")
        self.assertTrue(any(g.startswith("suggestions:A-2") for g in r["answer"]), r["answer"])
        self.assertTrue(any(g.startswith("notes:A-1") and "keep it short" in g for g in r["answer"]), r["answer"])
        self.assertTrue(all(w == "notes,picks" for w in r["writes"]), "the page stores what it stored before: notes and picks")


class TestStagePageKeysAndNaming(unittest.TestCase):
    def test_the_change_stepper_moved_to_j_and_k(self):
        with open(PAGE, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn('e.key === "n" || e.key === "j"', src)
        self.assertIn('Next change (j)', src)
        self.assertNotIn('id="b-reference"', src)
        self.assertNotIn('id="b-aswritten"', src)

    def test_the_contract_words_the_agent_reads_did_not_change(self):
        with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as f:
            skill = f.read()
        for word in ("targetPicks", "findingPicks"):
            self.assertIn(word, skill)


if __name__ == "__main__":
    unittest.main()
