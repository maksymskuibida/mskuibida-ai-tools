"""The Clean view colours each round's changes (RevDiff.attributeText / attributeTree, shared/rev-diff/rev-diff.js) on
both pages, under jsdom (drive_revision.js with RV_PREF=none: a reader who never chose a view, which is Clean).

All text is made up (revision_gate.py's bakery, a Unit built by unit_bundle.py). Needs Node and, for the page classes, jsdom."""

import copy
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import revision_gate as rg  # noqa: E402
import test_revision_page as trp  # noqa: E402
from test_revision_page import ENGINE, NODE, PAGE, UNIT_PAGE, has_jsdom  # noqa: E402


def drive_none(kind, page, sample, scenario="", pref="none"):
    """drive() with the viewer's stored view set to pref ("none": never chose)."""
    old = os.environ.get("RV_PREF")
    os.environ["RV_PREF"] = pref
    try:
        return trp.drive(kind, page, sample, scenario)
    finally:
        if old is None:
            os.environ.pop("RV_PREF", None)
        else:
            os.environ["RV_PREF"] = old


def three_rounds():
    """Round 1 and 2 as revision_gate has them; round 3 changes FR2.2's wording again (the words round 2 wrote, so round 3
    wins there) and a row round 2 added (FR3.2), and extends the summary."""
    s = rg.sample()
    r1 = s["others"][0]
    r2 = {"id": s["id"], "row": s["row"], "documents": s["documents"]}
    r3 = copy.deepcopy(r2)
    r3["id"] = rg.INTENT + "-" + rg.STAGE + "-20260103T1000"
    r3["row"]["round"] = 3
    r3["row"]["createdAt"] = "2026-01-03T10:00:00Z"
    r3["row"]["summary"] += " Round three: the wording of FR2.2 and FR3.2."
    text = r3["documents"]["requirements"]["text"]
    text = text.replace("never clears that mark.", "never clears that flag.")
    text = text.replace("Two opening windows that overlap count as one.", "Two opening windows that overlap count as a single window.")
    assert "flag" in text and "single window" in text
    r3["documents"]["requirements"]["text"] = text
    return {"id": r3["id"], "row": r3["row"], "documents": r3["documents"], "others": [r1, r2]}


@unittest.skipUnless(NODE, "node is not installed")
class TestAttribution(unittest.TestCase):
    """Per-round attribution over text: the engine alone."""

    def js(self, code):
        done = subprocess.run([NODE, "-e", f"const R = require({json.dumps(ENGINE)});\n{code}"], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def att(self, texts, rounds):
        return self.js(f"process.stdout.write(JSON.stringify(R.attributeText({json.dumps(texts)}, {json.dumps(rounds)})))")

    def test_each_round_keeps_the_words_it_wrote_over_three_rounds(self):
        got = self.att(["The cat sat on the mat.", "The dog sat on the mat.", "The dog sat on the rug today."], [1, 2, 3])
        self.assertEqual(got, [{"r": 0, "s": "The "}, {"r": 2, "s": "dog"}, {"r": 0, "s": " sat on the "}, {"r": 3, "s": "rug today"}, {"r": 0, "s": "."}])

    def test_where_a_later_round_changes_the_same_words_the_latest_wins(self):
        got = self.att(["alpha beta gamma", "alpha BETA gamma", "alpha BETA2 gamma"], [1, 2, 3])
        self.assertEqual(got, [{"r": 0, "s": "alpha "}, {"r": 3, "s": "BETA2"}, {"r": 0, "s": " gamma"}])
        self.assertFalse([g for g in got if g["r"] == 2], "round 2's colour is gone where round 3 rewrote it")

    def test_a_later_round_leaves_an_earlier_rounds_words_alone(self):
        got = self.att(["one two three", "one TWO three", "one TWO three four"], [1, 2, 3])
        self.assertEqual(got, [{"r": 0, "s": "one "}, {"r": 2, "s": "TWO"}, {"r": 0, "s": " three"}, {"r": 3, "s": " four"}])

    def test_a_part_a_round_did_not_have_is_written_by_the_round_that_added_it(self):
        self.assertEqual(self.att([None, "hello world", "hello world"], [1, 2, 3]), [{"r": 2, "s": "hello world"}])
        self.assertEqual(self.att(["gone", None, "back again"], [1, 2, 3]), [{"r": 3, "s": "back again"}])

    def test_a_single_round_text_is_not_coloured(self):
        self.assertEqual(self.att(["Nothing changed here."], [1]), [{"r": 0, "s": "Nothing changed here."}])
        self.assertEqual(self.att(["Same.", "Same.", "Same."], [1, 2, 3]), [{"r": 0, "s": "Same."}])

    def test_clean_is_the_default_and_an_explicit_choice_is_kept(self):
        got = self.js("""
          const mem = {}; global.localStorage = { getItem: (k) => (k in mem ? mem[k] : null), setItem: (k, v) => { mem[k] = String(v); } };
          const out = { fresh: R.pref() }; R.setPref("show"); out.chose = R.pref(); R.setPref("clean"); out.back = R.pref();
          process.stdout.write(JSON.stringify(out));""")
        self.assertEqual(got, {"fresh": "clean", "chose": "show", "back": "clean"})


@unittest.skipUnless(has_jsdom(), "node and the jsdom package are not installed")
class TestGateColours(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = drive_none("gate", PAGE, three_rounds(), "colours")

    def test_clean_is_the_default_and_draws_no_changes_marks(self):
        self.assertEqual(self.r["colours"]["changesMarks"], 0, "no strikethrough and no insertion marks in Clean")
        self.assertEqual(self.r["show"]["rv"], "show")
        self.assertEqual(self.r["show"]["pref"], "show", "the reader's explicit choice is kept")
        self.assertEqual(self.r["show"]["tinted"], 0, "the Changes view carries no round colours")
        self.assertGreater(self.r["show"]["marks"], 0)

    def test_the_legend_has_a_chip_for_each_round_after_the_first(self):
        self.assertEqual(self.r["colours"]["legend"], ["2:false", "3:false"])

    def test_each_round_is_in_its_own_colour(self):
        ins = self.r["colours"]["ins"]
        r2 = " | ".join(t for k, t in ins if k == 2)
        r3 = " | ".join(t for k, t in ins if k == 3)
        self.assertIn("short name", r2, "words round 2 wrote and nobody touched since")
        self.assertIn("flag", r3)
        self.assertIn("single window", r3)

    def test_the_latest_round_wins_where_rounds_clash(self):
        ins = self.r["colours"]["ins"]
        self.assertFalse([t for k, t in ins if k == 2 and "flag" in t], "round 3 rewrote 'mark' to 'flag': round 2's tint is gone")
        self.assertFalse([t for k, t in ins if k == 2 and "single window" in t])
        self.assertTrue([t for k, t in ins if k == 3 and "single window" in t])

    def test_a_row_that_round_2_added_carries_its_edge_and_round_3_edits_it_in_its_own_colour(self):
        blocks = self.r["colours"]["blocks"]
        self.assertTrue(any(k == 2 for k, _ in blocks), blocks)

    def test_a_legend_chip_shows_one_round_alone(self):
        self.assertEqual(self.r["pressed"], ["true", "false"])
        self.assertTrue(self.r["dimmed"] and all(k != 2 for k in self.r["dimmed"]), self.r["dimmed"])
        self.assertEqual(self.r["undimmed"], 0, "a second click shows every round again")


@unittest.skipUnless(has_jsdom(), "node and the jsdom package are not installed")
class TestGateTwoRoundsAndOne(unittest.TestCase):
    def test_two_rounds_colour_round_2(self):
        r = drive_none("gate", PAGE, trp.real_gate(), "colours")
        self.assertEqual(r["colours"]["legend"], ["2:false"])
        self.assertTrue(r["colours"]["ins"] and all(k == 2 for k, _ in r["colours"]["ins"]))
        self.assertIn("nine", [t for _, t in r["colours"]["ins"]], "the evaluation's count moved from eight to nine in round 2")
        self.assertEqual(r["colours"]["changesMarks"], 0)

    def test_a_page_with_one_round_renders_as_before(self):
        one = rg.sample()
        one["others"] = []
        clean = drive_none("gate", PAGE, one, "html")
        show = drive_none("gate", PAGE, one, "html", pref="show")
        self.assertEqual(clean["ins"], 0)
        self.assertEqual((clean["legend"], clean["edges"]), (0, 0))
        self.assertEqual(clean["html"], show["html"], "with one round the two views draw the same page")

    def test_a_page_with_one_round_and_no_stored_view_is_clean(self):
        one = rg.sample()
        one["others"] = []
        self.assertEqual(drive_none("gate", PAGE, one, "html")["rv"], "clean")


@unittest.skipUnless(has_jsdom(), "node and the jsdom package are not installed")
class TestUnitColours(unittest.TestCase):
    def versions(self):
        from test_unit_bundle import Base, rows_of  # noqa: E402

        class Builder(Base):
            def runTest(self):
                pass
        b = Builder()
        b.setUp()
        try:
            path1, v1, _ = b.finished()
            path, d2, _ = b.draft()
            rows = rows_of(d2, "assumptions")
            rows[1].update(body="Changed to cover Saturdays too.", revNote="Changed in v2: Saturdays too.")
            d2["header"]["revisions"][-1]["note"] = "after your note"
            b.save(path, d2)
            info = b.finalize(path)
            with open(info["bundle"], encoding="utf-8") as f:
                v2 = json.load(f)
        finally:
            b.doCleanups()
        v3 = copy.deepcopy(v2)
        v3["id"] = v2["id"].replace("-v2-", "-v3-")
        v3["header"]["revision"] = 3
        r3 = rows_of(v3, "assumptions")
        r3[1]["body"] = "Changed to cover Saturdays and Sundays too."   # round 3 rewrites round 2's words
        r3[0]["title"] = r3[0]["title"] + " (clarified)"                  # and a row round 2 left alone
        row = lambda bundle, at: {"intent": bundle["header"]["intent"], "unit": bundle["header"]["unit"], "page": bundle["page"],
                                  "createdAt": at, "status": "open", "bundle": bundle}
        return v1, v2, v3, row

    def test_three_versions_each_in_its_own_colour_and_the_latest_wins(self):
        v1, v2, v3, row = self.versions()
        r = drive_none("unit", UNIT_PAGE, {"id": v3["id"], "row": row(v3, "2026-02-03T10:00:00Z"),
                                           "others": [{"id": v1["id"], "row": row(v1, "2026-02-01T10:00:00Z")},
                                                      {"id": v2["id"], "row": row(v2, "2026-02-02T10:00:00Z")}]})
        c = r["colours"]
        self.assertEqual(c["rv"], "clean")
        self.assertEqual(c["marks"], 0, "no strikethrough and no insertion marks")
        self.assertEqual([x.split(":")[0] for x in c["legend"]], ["2", "3"])
        ins = c["ins"]
        self.assertTrue([t for k, t in ins if k == 3 and "Sundays" in t], ins)
        self.assertTrue([t for k, t in ins if k == 3 and "clarified" in t], ins)
        self.assertFalse([t for k, t in ins if k == 2 and "Sundays" in t], "round 3 wrote 'and Sundays': not round 2's colour")
        self.assertTrue([t for k, t in ins if k == 2 and "Saturdays" in t] or [t for k, t in ins if k == 2], "words only round 2 wrote keep its colour")
        self.assertEqual(r["pressed"], ["true", "false"], "a legend chip shows one round alone")
        self.assertTrue(r["dim"])

    def test_one_version_draws_no_colour(self):
        v1, _v2, _v3, row = self.versions()
        r = drive_none("unit", UNIT_PAGE, {"id": v1["id"], "row": row(v1, "2026-02-01T10:00:00Z"), "others": []})
        self.assertEqual(r["colours"]["ins"], [])
        self.assertEqual(r["colours"]["legend"], [])
        self.assertEqual(r["colours"]["blocks"], [])


if __name__ == "__main__":
    unittest.main()
