"""Batch 1 of the pages' rework: every thing is said once (A), every separate thing has its own read mark and leaves with it
under Unread (B), and a round's changes are shown and tied to the read marks on every structured block (C).

Synthetic data only: batch1_fixture.py (a bakery's Build and Test gate, two rounds), tables written here, and the bakery
Unit bundles of test_validate_bundle.py. The per-stage page runs under jsdom (drive_batch1.js); the Unit page's render
functions run under Node. Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

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
import batch1_fixture as fx  # noqa: E402
from bundle_helpers import NODE, render  # noqa: E402
from test_gate_bundle import bundle as gate_bundle, load  # noqa: E402
from test_validate_bundle import end_bundle, plan_bundle, row  # noqa: E402

unit_bundle = load("unit_bundle", "scripts", "unit_bundle.py")
validate_bundle = load("validate_bundle", "scripts", "validate_bundle.py")
PAGE = os.path.join(os.path.dirname(HERE), "skills", "approval-gates", "approval-gate.html")
DRIVER = os.path.join(HERE, "drive_batch1.js")


def has_jsdom():
    return bool(NODE) and subprocess.run([NODE, "-e", "require('jsdom')"], capture_output=True).returncode == 0


# ---------------------------------------------------------------- A2: one row per target

TABLE = "| Verdict | Target ID | Expected | Actual | Evidence |\n|---|---|---|---|---|\n"


def write(folder, name, text):
    with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
        f.write(text)


class TestOneRowPerTarget(unittest.TestCase):
    def folder(self, **files):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for name, text in files.items():
            write(tmp, name.replace("_", "-") + ".md", text)
        return tmp

    def parse(self, **files):
        return gate_bundle.parse_build_test(self.folder(**files))

    def test_a_target_in_two_files_is_one_row_and_counts_once(self):
        got = self.parse(summary="### U1 Bakery\n\n" + TABLE + "| Not Met | NFR1 | under 2 s | 3 s | AP load |\n| Met | NFR2 | kept | kept | |\n",
                         results="### U1 Bakery\n\n" + TABLE + "| Met | NFR1 | under 2 s on a phone | 1.5 s | AP load.py, WT slots |\n")
        self.assertEqual([t["id"] for t in got["targets"]], ["NFR1", "NFR2"])
        self.assertEqual(got["counts"], {"met": 1, "notMet": 1, "unverified": 0, "na": 0, "total": 2})
        t = got["targets"][0]
        self.assertEqual(t["verdict"], "Not Met", "the worst verdict wins")
        self.assertEqual(t["expected"], "under 2 s on a phone", "the fullest expected is kept")
        self.assertEqual(t["evidence"], "AP load.py, WT slots", "the fullest evidence is kept")
        self.assertEqual(t["actual"], "1.5 s" if len("1.5 s") > len("3 s") else "3 s")

    def test_sources_that_disagree_are_marked_with_both_verdicts(self):
        got = self.parse(a_summary="### U1 B\n\n" + TABLE + "| Met | NFR1 | x | y | |\n", b_results="### U1 B\n\n" + TABLE + "| Not Met | NFR1 | x | y | |\n")
        t = got["targets"][0]
        self.assertEqual(t["verdict"], "Not Met")
        self.assertEqual(t["disagree"], [{"verdict": "Not Met", "file": "b-results.md"}, {"verdict": "Met", "file": "a-summary.md"}])
        self.assertEqual(validate_bundle.validate_build_test(got), [], "the contract schema allows `disagree`")

    def test_sources_that_agree_carry_no_mark(self):
        got = self.parse(a="### U1 B\n\n" + TABLE + "| Met | NFR1 | x | y | |\n", b="### U1 B\n\n" + TABLE + "| Met | NFR1 | x | y | |\n")
        self.assertEqual(len(got["targets"]), 1)
        self.assertNotIn("disagree", got["targets"][0])

    def test_the_verdict_order_is_not_met_unverified_met_na(self):
        for pair, worst in ((("Unverified", "Met"), "Unverified"), (("N/A", "Met"), "Met"), (("N/A", "Not Met"), "Not Met"), (("Met", "Unverified"), "Unverified")):
            got = self.parse(a="### U1 B\n\n" + TABLE + f"| {pair[0]} | T1 | | | |\n", b="### U1 B\n\n" + TABLE + f"| {pair[1]} | T1 | | | |\n")
            self.assertEqual(got["targets"][0]["verdict"], worst, pair)

    def test_the_same_id_in_two_units_is_two_targets(self):
        got = self.parse(a="### U1 B\n\n" + TABLE + "| Met | T1 | | | |\n\n### U2 C\n\n" + TABLE + "| Not Met | T1 | | | |\n")
        self.assertEqual([(t["unit"], t["verdict"]) for t in got["targets"]], [("U1", "Met"), ("U2", "Not Met")])
        self.assertEqual(got["counts"]["total"], 2)


# ---------------------------------------------------------------- C (Unit pages): the server side of read marks

def unit_rows(*specs):
    return [dict(row(rid, "medium", body=text, title=text), source={"path": "code-summary.md", "key": key, "digest": key}) for rid, key, text in specs]


def unit_page(rows_by_kind, revision=1):
    b = end_bundle()
    b["header"]["revision"] = revision
    b["sections"] = [{"key": k, "kind": k, "title": k, "short": k, "rows": r} for k, r in rows_by_kind.items()]
    b["design"] = None
    del b["design"]
    return b


class TestUnitRowsKeepTheirMarks(unittest.TestCase):
    def test_a_v_point_that_moved_up_a_number_is_not_changed(self):
        before = unit_page({"unverified": unit_rows(("V-1", "unverified:a1", "first"), ("V-2", "unverified:b2", "second"))})
        after = unit_page({"unverified": unit_rows(("V-1", "unverified:b2", "second"))}, revision=2)
        missing = unit_bundle.mark_revisions(after, before)
        moved = after["sections"][0]["rows"][0]
        self.assertNotIn("rev", moved, "the same record under a new number is the same row")
        self.assertEqual(missing, [])

    def test_a_v_point_whose_text_changed_is_changed(self):
        before = unit_page({"unverified": unit_rows(("V-1", "unverified:a1", "first"))})
        after = unit_page({"unverified": unit_rows(("V-1", "unverified:zz", "first, reworded"))}, revision=2)
        unit_bundle.mark_revisions(after, before)
        self.assertEqual(after["sections"][0]["rows"][0]["rev"], 2)
        self.assertEqual(after["sections"][0]["rows"][0]["revKind"], "changed")


# ---------------------------------------------------------------- A5, B, C on the Unit page

SRC = lambda key: {"path": "code-summary.md", "key": key, "digest": key}  # noqa: E731


def verification_bundle():
    b = end_bundle()
    b["sections"] = [
        {"key": "unverified", "kind": "unverified", "title": "Still not verified", "short": "Not verified",
         "rows": [row("V-1", "high", source=SRC("unverified:aa")), row("V-2", "low", source=SRC("unverified:bb"))]},
        {"key": "verified", "kind": "verified", "title": "Verified by you", "short": "Verified", "rows": [row("V-3", "medium", source=SRC("unverified:cc"))]},
        {"key": "failed", "kind": "failed", "title": "Failed, left as known", "short": "Failed", "rows": [row("V-4", "medium", source=SRC("unverified:dd"))]},
        {"key": "built", "kind": "built", "title": "Built", "short": "Built", "rows": [row("B-1", "core", source=SRC("built:rules"))]},
    ]
    return b


def count(html, needle):
    return html.count(needle)


@unittest.skipUnless(NODE, "node is not installed")
class TestUnitEndPage(unittest.TestCase):
    def test_the_v_points_are_one_section_with_state_chips(self):
        b = verification_bundle()
        page = render(b, {"all": {}})["all"]
        self.assertEqual(count(page, 'data-sec="verification"'), 1)
        for gone in ('data-sec="unverified"', 'data-sec="verified"', 'data-sec="failed"'):
            self.assertNotIn(gone, page)
        for v in ("V-1", "V-2", "V-3", "V-4"):
            self.assertEqual(count(page, f'<div class="row" id="{v}"'), 1, f"{v} is drawn once")
        for chip in ("Not verified<b>2</b>", "Verified by you<b>1</b>", "Failed, left as known<b>1</b>"):
            self.assertIn(chip, page)
        self.assertEqual(render(b)["order"], ["verification", "built", "design"])
        self.assertEqual(count(page, 'class="tag vst"'), 4, "each point carries its state")

    def test_a_state_chip_shows_only_those_points_and_test_picks_stay_on_not_verified_rows(self):
        b = verification_bundle()
        page = render(b, {"nv": {"vstate": {"unverified": True}}, "ok": {"vstate": {"verified": True}}, "all": {}})
        self.assertEqual([count(page["nv"], f'<div class="row" id="{v}"') for v in ("V-1", "V-2", "V-3", "V-4")], [1, 1, 0, 0])
        self.assertEqual([count(page["ok"], f'<div class="row" id="{v}"') for v in ("V-1", "V-2", "V-3", "V-4")], [0, 0, 1, 0])
        self.assertEqual(count(page["all"], 'class="testpick"'), 2, "Test now / Later only on the two not-verified points")

    def test_every_row_has_a_read_dot_and_the_section_dot_is_derived(self):
        b = verification_bundle()
        page = render(b, {"none": {}, "all": {"read": {k: 1 for k in ("unverified:aa", "unverified:bb", "unverified:cc", "unverified:dd")}}})
        self.assertEqual(count(page["none"], 'data-act="read"'), 5, "four V points and one built piece")
        self.assertIn('data-act="secread" data-key="verification" aria-label="Mark Verification read"', page["none"])
        self.assertIn('data-act="secread" data-key="verification" aria-label="Mark Verification unread"', page["all"])

    def test_read_points_leave_under_unread_and_their_section_with_them(self):
        b = verification_bundle()
        read_all = {k: 1 for k in ("unverified:aa", "unverified:bb", "unverified:cc", "unverified:dd")}
        page = render(b, {"u": {"filter": "unread", "read": read_all}, "u1": {"filter": "unread", "read": {"unverified:aa": 1}}})
        self.assertNotIn('data-sec="verification"', page["u"], "no empty shell")
        self.assertIn('data-sec="built"', page["u"])
        self.assertNotIn('data-sec="design"', page["u"], "the approved design holds nothing to read")
        self.assertEqual([count(page["u1"], f'<div class="row" id="{v}"') for v in ("V-1", "V-2", "V-3", "V-4")], [0, 1, 1, 1])

    def test_a_point_keeps_its_mark_when_its_number_moves_and_loses_it_when_its_text_changes(self):
        b = verification_bundle()
        b["sections"][0]["rows"][0]["id"] = "V-9"  # the same record, numbered differently
        page = render(b, {"u": {"filter": "unread", "read": {"unverified:aa": 1}}})["u"]
        self.assertNotIn('id="V-9"', page.split('<main>')[1].split("<footer")[0], "the mark follows the record")
        b2 = verification_bundle()
        b2["sections"][0]["rows"][0].update(rev=2, revKind="changed")
        page2 = render(b2, {"u": {"filter": "unread", "read": {"unverified:aa": 1}}})["u"]
        self.assertIn('<div class="row" id="V-1"', page2, "a point changed in revision 2 is unread again")

    def test_the_answers_and_the_design_show_only_with_the_whole_page(self):
        b = end_bundle()
        page = render(b, {"all": {}, "u": {"filter": "unread"}})
        self.assertIn('data-sec="design"', page["all"])
        self.assertNotIn('data-sec="design"', page["u"])

    def test_every_plan_step_and_the_plan_section_have_marks(self):
        b = plan_bundle()
        b["plan"] = {"title": "Code plan", "steps": [{"n": 1, "title": "S1", "layer": "domain", "files": 1, "subs": [{"text": "a"}], "implements": [], "source": SRC("step:s1")},
                                                     {"n": 2, "title": "S2", "layer": "domain", "files": 1, "subs": [{"text": "b"}], "implements": [], "source": SRC("step:s2")}]}
        page = render(b, {"none": {}, "one": {"read": {"step:s1": 1}}, "unread": {"filter": "unread", "read": {"step:s1": 1}}})
        self.assertEqual(count(page["none"], 'class="dot" data-act="read" data-key="step-'), 2)
        self.assertIn('data-act="secread" data-key="plan"', page["none"])
        self.assertNotIn('id="step-1"', page["unread"].split("<main>")[1])
        self.assertIn('id="step-2"', page["unread"].split("<main>")[1])


# ---------------------------------------------------------------- the per-stage page under jsdom

def drive(sample, scenario, pref="show", name="s"):
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, name + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sample, f)
        if scenario == "carry":
            with open(os.path.join(tmp, name + ".r1.json"), "w", encoding="utf-8") as f:
                json.dump(fx.sample(False), f)
        done = subprocess.run([NODE, DRIVER, PAGE, path, scenario], capture_output=True, text=True, timeout=120, env=dict(os.environ, RV_PREF=pref))
        assert done.returncode == 0 and done.stdout, done.stderr
        out = json.loads(done.stdout)
        assert "error" not in out, out["error"]
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def plain_gate(sample):
    """The same gate without an evaluation: the documents are shown, not folded under As written."""
    s = copy.deepcopy(sample)
    for k in ("evaluation", "criteria", "digest"):
        s["row"].pop(k)
    for d in s["row"]["documents"]:
        d["covered"] = False
    return s


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestOneListOfTargets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = drive(fx.sample(False), "layout")

    def test_one_list_with_the_open_targets_first_and_no_decisions_block(self):
        p = self.page
        self.assertNotIn("b-bt-decide", p["blocks"])
        self.assertFalse(p["decideBlock"] or p["decideChip"])
        self.assertEqual(p["cardsOfTargets"], 0)
        self.assertEqual(p["openRows"], ["u1:NFR1", "u1:NFR6", "u1:NFR2"], "Not Met first, then Unverified")
        self.assertEqual(p["foldRows"], ["u1:NFR3", "u2:NFR4"])
        self.assertEqual(sorted(p["rowIds"]), sorted(t["id"] for t in fx.TARGETS), "every target once")

    def test_the_open_rows_carry_the_three_picks_and_met_and_na_fold_under_a_count(self):
        p = self.page
        self.assertEqual(p["picksPerOpenRow"], [3, 3, 3])
        self.assertEqual(p["picksInFold"], 0)
        self.assertEqual(p["foldSummary"], "Met and N/A2")
        self.assertFalse(p["foldOpen"])
        self.assertEqual(p["dcount"], "0 of 3 chosen", "the matrix header keeps the count")

    def test_a_pick_and_a_note_are_saved_as_the_skill_reads_them(self):
        got = drive(fx.sample(False), "picks")
        self.assertEqual(got["writes"][-1], {"u1:NFR1": {"pick": "fix", "note": "slow on a 3G phone"}, "u1:NFR2": {"pick": "followup"}})
        self.assertEqual(got["dcount"], "2 of 3 chosen")
        self.assertTrue(got["chosen"] and got["read"], "choosing proves the row was read")
        self.assertEqual(got["pressed"], "true")

    def test_sources_that_disagree_show_a_small_tag_with_both_verdicts(self):
        p = self.page
        self.assertEqual(p["disagree"], ["sources disagree: Not Met / Met"])
        self.assertEqual(p["disagreeRow"], ["u1:NFR6"])

    def test_a_document_whose_table_became_the_matrix_is_folded_with_a_line_saying_so(self):
        for sample in (fx.sample(False), plain_gate(fx.sample(False))):
            got = drive(sample, "layout")
            self.assertEqual(len(got["matrixDoc"]), 1)
            d = got["matrixDoc"][0]
            self.assertFalse(d["open"])
            self.assertIn("shown above as the target matrix", d["hint"])
            self.assertIn("shown above as the target matrix", d["note"])
            self.assertEqual(got["targetTablesShown"], 0, "the table is not drawn again as a full document")

    def test_an_item_that_is_a_target_links_to_its_row(self):
        item = next(i for i in self.page["itemRows"] if i["id"] == "NFR1")
        self.assertTrue(item["tlink"] and item["link"])
        self.assertEqual(item["vtags"], 0, "no verdict repeated")
        self.assertFalse(item["expected"], "no expected text repeated")
        self.assertEqual(item["dot"], 0, "one read key: the target's")
        self.assertEqual(item["item"], "target:U1/u1:NFR1")
        other = next(i for i in self.page["itemRows"] if i["id"] == "FR1")
        self.assertFalse(other["tlink"])

    def test_a_finding_in_the_brief_and_on_a_card_is_told_once(self):
        rows = self.page["briefRows"]
        self.assertTrue(all(r["sorted"] and not r["detail"] for r in rows), rows)


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestReadMarks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.layout = drive(fx.sample(False), "layout")
        cls.unread = drive(fx.sample(False), "unread")

    def test_every_separate_thing_has_its_own_dot(self):
        keys = self.layout["dots"]
        self.assertEqual(len(keys), len(set(keys)), "one read key per thing")
        for want in ("eval:text", "crit:stage-1", "crit:review-1", "item:FR1", "finding:R-01", "target:U1/u1:NFR1", "target:U2/u2:NFR4",
                     "block:summary", "block:review", "block:evaluation", "block:findings", "block:bt-matrix", "block:items"):
            self.assertIn(want, keys)

    def test_the_item_that_is_a_target_has_no_second_key(self):
        self.assertNotIn("item:NFR1", self.layout["dots"])

    def test_progress_counts_things_not_blocks(self):
        leaves = [k for k in self.unread["keys"] if not k.startswith("block:") or k in ("block:summary", "block:review")]
        self.assertEqual(self.unread["progress0"], f"Read 0/{len(leaves)}")

    def test_under_unread_a_read_thing_is_gone_and_so_is_every_emptied_container(self):
        u = self.unread
        self.assertGreater(u["visibleBefore"], 0)
        self.assertEqual(u["visibleItems"], [])
        self.assertEqual(u["visibleElems"], [])
        self.assertEqual(u["visibleContainers"], [], "no empty shell")
        for gone in ("b-eval", "b-items", "b-findings", "b-bt-matrix"):
            self.assertNotIn(gone, u["blocksShown"], f"{gone} is read through its parts")
        self.assertIn("b-summary", u["blocksShown"], "the summary was never marked")

    def test_a_container_dot_is_derived_and_marks_every_part(self):
        d = drive(fx.sample(False), "derived")
        self.assertEqual(d["oneRead"], [True, False, False, False, False])
        self.assertFalse(d["matrixBlockRead"], "one of five read is not read")
        self.assertEqual(d["afterBlockDot"], [True] * 5)
        self.assertTrue(d["matrixBlockRead2"])
        self.assertEqual(d["afterBlockDot2"], [False] * 5, "pressing again unmarks every part")
        self.assertTrue(all(x.endswith(":true") for x in d["evalDots"]))
        self.assertFalse(d["evalBlockRead"], "one criterion unmarked: the evaluation is unread")
        self.assertFalse(d["itemLinkRead"], "the item row follows the target's key")


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestRoundChanges(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.carry = drive(fx.sample(True), "carry")
        cls.show = drive(fx.sample(True), "rounds", pref="show")
        cls.clean = drive(fx.sample(True), "rounds", pref="none")

    def test_everything_read_in_round_one_and_changed_in_round_two_is_unread_again(self):
        c = self.carry
        self.assertEqual(c["progress1"].split("/")[0].split()[-1], c["progress1"].split("/")[1], "round one was all read")
        self.assertEqual(sorted(c["unreadKeys"]), sorted(["crit:review-1", "item:FR1", "item:FR3", "finding:R-01", "finding:R-03",
                                                           "target:U1/u1:NFR2", "target:U1/u1:NFR5"]))

    def test_what_did_not_change_stays_read_though_it_is_presented_differently(self):
        c = self.carry
        for kept in ("crit:stage-1", "item:FR2", "target:U1/u1:NFR1", "target:U1/u1:NFR6", "target:U2/u2:NFR4"):
            self.assertIn(kept, c["same"])
            self.assertNotIn(kept, c["unreadKeys"])
        self.assertNotIn("eval:text", c["unreadKeys"], "the evaluation's text is the same")
        self.assertNotIn("crit:stage-1", c["unreadKeys"])

    def test_a_criterion_whose_source_line_moved_is_not_changed_but_one_whose_note_changed_is(self):
        self.assertEqual(self.carry["changed"].get("crit:review-1"), "changed")
        self.assertNotIn("crit:stage-1", self.carry["changed"])

    def test_the_changed_filter_and_the_marks_agree(self):
        c = self.carry
        self.assertEqual(sorted(c["changed"]), sorted(c["unreadKeys"]))
        self.assertEqual(sorted(c["shownItems"]), sorted(c["unreadKeys"]), "Unread shows exactly what the round changed")

    def test_containers_above_a_changed_thing_are_unread(self):
        blocks = dict(b.split(":") for b in self.carry["blocks"])
        for key in ("evaluation", "items", "findings", "bt-matrix", "review", "summary"):
            self.assertEqual(blocks[key], "unread", key)

    def test_changes_view_tags_every_structured_block(self):
        s = self.show
        f = {x["id"]: x for x in s["findings"]}
        self.assertEqual((f["R-01"]["cls"], f["R-03"]["cls"]), (["rv-chg"], ["rv-new"]))
        self.assertTrue(f["R-01"]["ins"] and f["R-01"]["del"], "the words are marked")
        self.assertNotIn("Suggested", " ".join(f["R-01"]["ins"] + f["R-01"]["del"]), "a label is not a change")
        t = {x["id"]: x for x in s["targets"]}
        self.assertEqual([t[i]["cls"] for i in ("u1:NFR2", "u1:NFR5", "u1:NFR1", "u2:NFR4")], [["rv-chg"], ["rv-new"], ["rv-same"], ["rv-same"]])
        self.assertTrue(t["u1:NFR2"]["ins"])
        self.assertEqual(self.show["critTags"], ["crit-stage-1:rv-same", "crit-review-1:rv-chg"])
        self.assertTrue(s["brief"]["ins"] and s["brief"]["del"], "the review brief is diffed")

    def test_a_removed_finding_and_a_removed_target_are_listed(self):
        s = self.show
        self.assertEqual(sorted(x[:4] for x in s["removed"]), ["R-02", "u1:N"])
        self.assertTrue(any("removed" in x and "R-02" in x for x in s["list"]))
        self.assertTrue(any("removed" in x and "u1:NFR3" in x for x in s["list"]))

    def test_clean_view_colours_new_findings_and_targets_by_round(self):
        s = self.clean
        edges = [e for e in s["edges"] if e.endswith(":2")]
        for want in ("R-03:2", "u1:NFR5:2", "item:FR3:2"):
            self.assertIn(want, edges)
        text = " ".join(t[1] for t in s["tinted"])
        self.assertIn("ran after a restart", text, "a changed target cell is tinted")
        self.assertIn("is written again", text, "a changed finding is tinted")
        self.assertIn("still", text, "the changed brief is tinted")
        self.assertTrue(all(t[0] == "2" for t in s["tinted"]))


if __name__ == "__main__":
    unittest.main()
