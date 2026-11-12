"""What changed between two rounds, on the pages: approval-gate.html and unit-gate.html under jsdom (drive_revision.js)
with the shared RevDiff (shared/rev-diff/rev-diff.js) marking words, sections and elements.

  - a requirements-analysis gate in two rounds with the shape of a real one and made-up text (revision_gate.py);
  - synthetic rounds: a section added, removed and reworded, a rule removed and reworded, and a document of 100+ KB;
  - a Unit page in two versions, built by unit_bundle.py.
Needs Node and the jsdom package (NODE_PATH); without them the classes skip. CI installs jsdom for them.
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(PLUGIN))
PAGE = os.path.join(PLUGIN, "skills", "approval-gates", "approval-gate.html")
UNIT_PAGE = os.path.join(PLUGIN, "skills", "approval-gates", "unit-gate.html")
DRIVER = os.path.join(HERE, "drive_revision.js")
ENGINE = os.path.join(ROOT, "shared", "rev-diff", "rev-diff.js")
NODE = shutil.which("node")
sys.path.insert(0, HERE)
import revision_gate  # noqa: E402


def has_jsdom():
    return bool(NODE) and subprocess.run([NODE, "-e", "require('jsdom')"], capture_output=True).returncode == 0


def drive(kind, page, sample, scenario=""):
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "sample.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sample, f)
        done = subprocess.run([NODE, DRIVER, kind, page, path, scenario], capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, done.stderr
        out = json.loads(done.stdout)
        assert "error" not in out, out.get("error")
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def real_gate(with_revision=True):
    s = revision_gate.sample()
    if with_revision:
        s["row"]["revision"] = {
            "feedback": "Both review findings sorted Fix on the approval page, and a note: add opening hours.",
            "changes": [
                {"asked": "R-01: the sold-out mark against a whole-list write", "what": "A list write never clears a sold-out mark.",
                 "where": ["doc:requirements#FR2.2", "FR2.2"]},
                {"asked": "Your note: opening hours", "what": "A new section with the shop's opening hours.",
                 "where": ["doc:requirements#Opening hours"]}]}
    return s


@unittest.skipUnless(has_jsdom(), "node and the jsdom package are not installed")
class TestTwoRounds(unittest.TestCase):
    """Round 2 of a requirements analysis against round 1 (revision_gate.py: the shape of a real gate, made-up text)."""

    @classmethod
    def setUpClass(cls):
        cls.r = drive("gate", PAGE, real_gate(), "page")

    def test_what_changed_leads_the_page(self):
        self.assertEqual(self.r["blocks"][:2], ["b-revision", "b-eval"])
        self.assertTrue(self.r["chips"][0].startswith("What changed"))
        self.assertEqual(self.r["feedback"], "What you asked forBoth review findings sorted Fix on the approval page, and a note: add opening hours.")
        self.assertEqual([d["where"] for d in self.r["done"]], [["Requirements › FR2.2", "FR2.2"], ["Requirements › Opening hours"]])
        self.assertEqual(len(self.r["picker"]), 1)
        self.assertTrue(self.r["picker"][0].startswith("Round 1 · "))

    def test_every_change_is_listed_with_its_counts(self):
        groups = " | ".join(self.r["groups"])
        for name in ("Claude's evaluation", "What the stage says", "Completion summary", "Requirements: Bakery pre-order", "Review 02"):
            self.assertIn(name, groups)
        self.assertNotIn("Review 01", groups, "a review copy replaced by the next one is not a removal")
        self.assertRegex(self.r["total"], r"^\d+ changes since round 1 \(\d+ changed, \d+ new, \d+ removed\) · \+\d+ −\d+$")
        entries = " | ".join(self.r["entries"])
        self.assertIn("FR2.2 · Sold out is set per product and no list write clears it.", entries)
        self.assertIn("FR3.1", entries)
        self.assertIn("FR2.3", entries, "a removed item is listed")
        self.assertIn("Opening hours", entries)

    def test_words_are_marked_where_they_changed(self):
        self.assertIn("nine", self.r["ins"], "the evaluation's count of requirements moved from eight to nine")
        self.assertIn("eight", self.r["del"])
        self.assertTrue(any("at most 12 orders" in t for t in self.r["ins"]), "FR1.2's new wording is highlighted")
        self.assertEqual(sorted(self.r["changedSecs"]), ["Assumptions", "Functional requirements"])
        self.assertEqual(self.r["newSecs"], ["Opening hours"])
        self.assertTrue(any("FR2.3" in g for g in self.r["gone"]), "the removed requirement row stays as a struck ghost")
        self.assertTrue(all(not s["open"] for s in self.r["sameSecs"]), "unchanged sections are folded")
        self.assertIn("Intent analysis", [s["title"] for s in self.r["sameSecs"]])

    def test_items_changed_since_round_1_are_tagged(self):
        self.assertEqual(sorted(self.r["items"]), ["FR1.2:changed", "FR2.2:changed", "FR3.1:new", "FR3.2:new"])
        self.assertTrue(any("FR2.3" in g for g in self.r["itemsGone"]))
        self.assertTrue(self.r["evalTags"], "a criterion whose verdict and note changed carries a tag")

    def test_count_badges_are_not_read_as_words(self):
        self.assertFalse(any(re.fullmatch(r"(Risks|Gaps|Solid|Conflicts)\d+", g) for g in self.r["gone"]), self.r["gone"])
        self.assertIn("Gaps", self.r["gone"], "the gaps column round 2 no longer has is a ghost")

    def test_an_extended_sentence_is_one_insertion_not_a_ghost(self):
        self.assertNotIn("Wrote the requirements from your answers.", self.r["gone"])
        self.assertTrue(any(t.strip().startswith("In this round: slot capacity") for t in self.r["ins"]))
        self.assertNotIn("The baker can mark a product sold out.", self.r["gone"], "an item's summary is marked inline, never as a block")
        self.assertIn("The baker can mark a", self.r["del"])

    def test_words_from_neighbouring_elements_do_not_run_together(self):
        self.assertFalse(any(re.search(r"[a-z](Is|Project|Stage)\b", t) for t in self.r["del"] + self.r["ins"]), self.r["del"] + self.r["ins"])


@unittest.skipUnless(has_jsdom(), "node and the jsdom package are not installed")
class TestReviewing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = drive("gate", PAGE, real_gate(), "interact")

    def test_next_and_previous_walk_the_changes(self):
        total = self.r["before"]["pos"].split(" / ")[1]
        self.assertGreater(int(total), 10)
        self.assertEqual(self.r["next"], "2 / " + total)
        self.assertEqual(self.r["prev"], "1 / " + total)
        self.assertEqual(self.r["key"], "2 / " + total, "the j key goes to the next change")

    def test_the_changed_filter_keeps_only_what_changed(self):
        self.assertEqual((self.r["changed"]["items"], self.r["changed"]["of"]), (4, 9))
        self.assertNotIn("b-findings", self.r["changed"]["blocks"])
        self.assertIn("b-revision", self.r["changed"]["blocks"])

    def test_clean_shows_the_page_as_it_is_and_is_remembered(self):
        self.assertEqual(self.r["clean"]["rv"], "clean")
        self.assertEqual(self.r["clean"]["pref"], "clean")
        self.assertFalse(self.r["clean"]["pos"], "no change navigation in Clean")
        self.assertEqual(self.r["clean"]["sameFolded"], 0, "nothing is folded for being unchanged")
        self.assertEqual(self.r["show"], {"rv": "show", "pref": "show"})

    def test_a_place_the_agent_named_opens_and_an_item_opens_with_its_marks(self):
        self.assertEqual(self.r["went"], "doc:requirements#FR2.2")
        self.assertTrue(self.r["landedOpen"])
        self.assertNotEqual(self.r["landed"], "d-requirements", "it lands on FR2.2's line, not the whole document")
        self.assertTrue(self.r["itemOpened"])
        self.assertGreater(self.r["itemMarks"], 0, "the item's text as written carries its changes")


@unittest.skipUnless(has_jsdom(), "node and the jsdom package are not installed")
class TestReadMarksStay(unittest.TestCase):
    def test_a_read_mark_is_the_hash_of_the_text_not_of_its_marks(self):
        s = sample_of([("rules", "Business rules", RULES_1)], [("rules", "Business rules", RULES_2)])
        s["dotSelector"] = "#d-rules [data-eread]"  # BR1.1, reworded: its words carry marks
        with_base = drive("gate", PAGE, s, "reads")
        alone = dict(s, others=[])
        without = drive("gate", PAGE, alone, "reads")
        self.assertEqual(with_base["key"], without["key"])
        self.assertTrue(with_base["mark"])
        self.assertEqual(with_base["mark"], without["mark"])


def gate_row(n, created, docs, why="first"):
    return {"title": "Approve Notes", "stage": "notes", "stageName": "Notes", "phase": "inception", "intent": "i1", "round": n, "why": why,
            "status": "open", "createdAt": created, "documents": [{"key": k, "title": t, "kind": "md", "path": f"inception/notes/{k}.md"} for k, t, _ in docs]}


def sample_of(old_docs, new_docs, revision=None):
    new_row = gate_row(2, "2026-02-01T10:00:00Z", new_docs, "revision")
    if revision:
        new_row["revision"] = revision
    return {"id": "i1-notes-20260201T1000", "row": new_row,
            "documents": {k: {"key": k, "title": t, "kind": "md", "n": i, "text": x} for i, (k, t, x) in enumerate(new_docs)},
            "others": [{"id": "i1-notes-20260101T1000", "row": gate_row(1, "2026-01-01T10:00:00Z", old_docs),
                        "documents": {k: {"key": k, "title": t, "kind": "md", "n": i, "text": x} for i, (k, t, x) in enumerate(old_docs)}}]}


NOTES_1 = """# Notes

## Kept the same
Nothing here moves between rounds.

## Reworded
A customer reserves a loaf before six in the evening and collects it in the morning.

## Old section
This whole section goes away in round 2.
"""
NOTES_2 = """# Notes

## Kept the same
Nothing here moves between rounds.

## Reworded
A customer reserves a loaf before 18:00 and collects it at the shop in the morning.

## New section
This section arrives in round 2.
"""
RULES_1 = """# Business rules

```yaml
rules:
  - id: BR1.1
    statement: A full slot refuses a reservation.
    category: capacity
    logic: IF the slot holds 12 orders THEN refuse the 13th
  - id: BR1.2
    statement: Slots close at 18:00.
    category: time
  - id: BR1.3
    statement: A cancelled order frees its place.
    category: capacity
```
"""
RULES_2 = RULES_1.replace("A full slot refuses a reservation.", "A full slot refuses a new reservation and says so.") \
    .replace("  - id: BR1.2\n    statement: Slots close at 18:00.\n    category: time\n", "") \
    .replace("IF the slot holds 12 orders THEN refuse the 13th", "IF the slot holds 15 orders THEN refuse the 16th")


@unittest.skipUnless(has_jsdom(), "node and the jsdom package are not installed")
class TestSyntheticRounds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = drive("gate", PAGE, sample_of([("notes", "Notes", NOTES_1), ("rules", "Business rules", RULES_1), ("gone", "Gone file", "# Gone\n\nOnly in round 1.\n")],
                                              [("notes", "Notes", NOTES_2), ("rules", "Business rules", RULES_2)]), "page")

    def test_a_section_added_removed_and_reworded(self):
        self.assertEqual(self.r["newSecs"], ["New section"])
        self.assertEqual(self.r["goneSecs"], ["Old section"])
        self.assertEqual(self.r["changedSecs"], ["Reworded", "BR1"], "BR1: the rules view's group that holds BR1.1")
        self.assertIn("Kept the same", [s["title"] for s in self.r["sameSecs"]])
        self.assertIn("18:00", "".join(self.r["ins"]))
        self.assertIn("six in the evening", "".join(self.r["del"]))
        self.assertTrue(any("v2 removed" in t for t in self.r["removed"]), "a removed thing is tagged with the round that removed it")

    def test_an_element_removed_and_one_reworded(self):
        # the "Reworded" section of the notes document is an element of its own too (each section of a file shown as written is)
        self.assertEqual(self.r["changedElems"], ["el:notes:Reworded", "el:rules:BR1.1"])
        self.assertTrue(any(t.startswith("BR1.2") and "v2 removed" in t for t in self.r["removed"]), self.r["removed"])
        self.assertIn("new", [t.strip() for t in self.r["ins"]])
        self.assertIn("and says so", [t.strip() for t in self.r["ins"]])
        self.assertIn("15", self.r["ins"], "a change in the rule's folded logic shows too")

    def test_a_document_gone_is_listed(self):
        self.assertTrue(any(g.startswith("removedGone file") for g in self.r["groups"]), self.r["groups"])


def big_doc(n, edit=False):
    parts = ["# Big register\n"]
    for i in range(n):
        body = " ".join(f"Entry {i}.{k}: the register keeps line {k} of section {i} with enough words to weigh." for k in range(22))
        if edit and i in (7, 70, 133):
            body = body.replace(f"line 3 of section {i}", f"line three of section {i}, now reworded")
        if edit and i == 90:
            continue
        parts.append(f"## Section {i}\n\n{body}\n")
        if edit and i == 40:
            parts.append("## Section inserted\n\nA new section in round 2.\n")
    return "\n".join(parts)


@unittest.skipUnless(has_jsdom(), "node and the jsdom package are not installed")
class TestBigDocument(unittest.TestCase):
    def test_a_document_of_over_100_kb_is_compared_section_by_section(self):
        old, new = big_doc(150), big_doc(150, edit=True)
        self.assertGreater(len(new.encode("utf-8")), 100_000)
        start = time.time()
        r = drive("gate", PAGE, sample_of([("register", "Register", old)], [("register", "Register", new)]), "page")
        took = time.time() - start
        self.assertEqual(sorted(r["changedSecs"]), ["Section 133", "Section 7", "Section 70"])
        self.assertEqual(r["newSecs"], ["Section inserted"])
        self.assertEqual(r["goneSecs"], ["Section 90"])
        self.assertLess(took, 30, "the page and its diff stay quick on a large document")


@unittest.skipUnless(bool(NODE), "node is not installed")
class TestEngine(unittest.TestCase):
    def run_js(self, code):
        done = subprocess.run([NODE, "-e", f"const R = require({json.dumps(ENGINE)});\n{code}"], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_words_read_as_one_removal_and_one_insertion(self):
        got = self.run_js('process.stdout.write(JSON.stringify(R.words("The quick brown fox jumps", "The slow brown fox leaps high")))')
        self.assertEqual(got, [{"t": "=", "s": "The "}, {"t": "-", "s": "quick"}, {"t": "+", "s": "slow"}, {"t": "=", "s": " brown fox "},
                               {"t": "-", "s": "jumps"}, {"t": "+", "s": "leaps high"}])

    def test_a_large_diff_is_fast_and_a_hopeless_one_gives_up(self):
        got = self.run_js("""
          const a = [...Array(20000)].map((_, i) => "line " + i), b = a.slice(); b.splice(9000, 3, "x", "y"); b[10] = "z";
          let t = Date.now(); const runs = R.diff(a, b); const fast = Date.now() - t;
          const r1 = [...Array(4000)].map((_, i) => "a" + i), r2 = [...Array(4000)].map((_, i) => "b" + i);
          t = Date.now(); const none = R.diff(r1, r2, 300); const quit = Date.now() - t;
          process.stdout.write(JSON.stringify({ runs: runs.filter((r) => r.t !== "=").length, fast, none, quit }));""")
        self.assertEqual(got["runs"], 4)
        self.assertLess(got["fast"], 500)
        self.assertIsNone(got["none"])
        self.assertLess(got["quit"], 2000)


@unittest.skipUnless(has_jsdom(), "node and the jsdom package are not installed")
class TestUnitPage(unittest.TestCase):
    def test_a_unit_page_marks_what_changed_since_its_last_version(self):
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
        removed = copy.deepcopy(v1)
        rows_of(removed, "assumptions").append({"id": "A-9", "title": "A row only v1 had", "label": "low", "body": "Gone in v2.", "refs": []})
        row = lambda bundle, at: {"intent": bundle["header"]["intent"], "unit": bundle["header"]["unit"], "page": bundle["page"],
                                  "createdAt": at, "status": "open", "bundle": bundle}
        r = drive("unit", UNIT_PAGE, {"id": v2["id"], "row": row(v2, "2026-02-02T10:00:00Z"),
                                      "others": [{"id": v1["id"], "row": row(removed, "2026-02-01T10:00:00Z")}]})
        self.assertIn("Round 2 compared with round 1", r["strip"])
        self.assertEqual(r["rows"], ["A-2:changed"])
        self.assertIn("Changed to cover Saturdays too", " ".join(r["ins"]), "the row's new words are highlighted (when it is open)")
        self.assertTrue(any("A-9" in x and "removed" in x for x in r["list"]), r["list"])
        self.assertTrue(any(f.startswith("Changed") for f in r["filters"]), r["filters"])
        self.assertIn("A-2", r["changedOnly"])
        self.assertNotIn("A-1", r["changedOnly"], "an unchanged row leaves under Changed")
        self.assertTrue(r["pos"].startswith("1 / "))
        self.assertEqual(r["clean"], {"rv": "clean", "nav": False})
        self.assertEqual(len(r["picker"]), 1)


if __name__ == "__main__":
    unittest.main()
