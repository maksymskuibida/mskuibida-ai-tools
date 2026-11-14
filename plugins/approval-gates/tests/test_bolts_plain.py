"""The bolt plan view takes short bolt headings, and a document with no view of its own is read section by section (approval-gates 1.35.3).

  1  `## B1 name (U1)` is a bolt, as `## Bolt 1: name` and `### Bolt 1` under milestone H2s still are; "Background" is not; a Sequence table
     feeds the strip; B1 and Bolt 1 both resolve as references
  2  a document with no view of its own: one read dot per H2 section (per H3 when there is no H2); no headings, one block;
     a section unchanged in the next round stays read, the changed one goes unread and is marked changed

Synthetic data only: the preview's delivery-planning gate with the bolt-plan document's text replaced; driven under jsdom by drive_bolts.js.
Skips without Node and jsdom. Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import json
import os
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
from test_fix1_pages import has_jsdom  # noqa: E402

_BUILT = {}


def scenario():
    if "s" not in _BUILT:
        import preview
        out = tempfile.mkdtemp(prefix="gates-bolts-test-")
        _BUILT["out"] = out
        _BUILT["s"] = next(s for s in preview.build(out, only="stage-2-9-delivery-planning-r3", say=lambda *_: None) if s.name.endswith("delivery-planning-r3"))
    return _BUILT["s"]


def tearDownModule():
    if "out" in _BUILT:
        shutil.rmtree(_BUILT["out"], ignore_errors=True)


def page_with(name, texts):
    """A page of the delivery-planning gate whose bolt-plan reads texts[round - 1] in each round; texts of one or two rounds drop the later ones."""
    import preview
    rows = {}
    for path, row in scenario().rows.items():
        stamp = [r for r in (1, 2, 3) if f"2026010{r}T0900" in path]
        if stamp and stamp[0] > len(texts):
            continue
        if path.endswith("/documents/bolt-plan"):
            row = dict(row, text=texts[stamp[0] - 1])
        rows[path] = row
    hash_id = [p.split("/")[1] for p in rows if p.count("/") == 1][-1] if len(texts) < 3 else scenario().hash_id
    hash_id = max((p.split("/")[1] for p in rows if p.count("/") == 1), key=lambda i: i.rsplit("-", 1)[-1])
    path = os.path.join(_BUILT["out"], name + ".html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(preview.page("gate", rows, hash_id, {"name": name, "desc": ""}))
    return path


def drive(*args):
    done = subprocess.run([NODE, os.path.join(HERE, "drive_bolts.js"), *args], capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


SEQUENCE = ("## Sequence\n\n| Bolt | Unit | Line | Starts when | Can run beside |\n|---|---|---|---|---|\n" +
            "".join(f"| B{i} | U{i} part {i} | {'both' if i == 1 else 'api'} | {'now' if i == 1 else f'B{i - 1} is done'} | {'nothing' if i != 3 else 'B2'} |\n" for i in range(1, 12)))
SHORT = ("# Bolt plan\n\nEleven bolts.\n\n" + SEQUENCE +
         "".join(f"\n## B{i} part {i} (U{i})\n\n- **Done when**: part {i} works.\n- **Confidence hypothesis**: it is small.\n- **Expected demo**: part {i} on screen" +
                 (". Needs B1 first, and Bolt 1 too.\n" if i == 2 else ".\n") for i in range(1, 12)) +
         "\n## Not a Bolt\n\nNothing here.\n\n## Sources\n\n- FR1\n")
LONG_H2 = "# Bolt plan\n\nThree bolts.\n\n" + "".join(f"## Bolt {i}: part {i}\n\n**Units:** U{i}\n\n**Done when**: part {i} works." + (" Needs Bolt 1 and B1 first." if i == 2 else "") + "\n\n" for i in range(1, 4)) + "## Background\n\nWhy.\n"
H3_UNDER_MILESTONES = ("# Bolt plan\n\n## Milestone 1\n\nFirst.\n\n### Bolt 1: part one\n\n**Units:** U1\n\ntext\n\n### Bolt 2 — part two\n\n**Units:** U2\n\ntext\n\n"
                       "## Milestone 2\n\n### Bolt 3. part three\n\n**Units:** U3\n\ntext\n")
NOT_BOLTS = "# Plan\n\n## Background\n\nWhy.\n\n## Bonus 2 things\n\nMore.\n\n## B-side\n\nNone.\n"
PLAIN_V1 = "# Plan\n\n## Background\n\nWhy we plan.\n\n## Scope\n\nWhat is in.\n\n## Approach\n\nHow it goes.\n\n## Notes\n\nOther.\n"
PLAIN_V2 = PLAIN_V1.replace("What is in.", "What is in, and what is out.")


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestBoltHeadings(unittest.TestCase):
    def view(self, name, text):
        out = drive("view", page_with(name, [text] * 3))
        self.assertEqual(out["errors"], [])
        return out

    def test_short_bolts_get_the_bolt_view(self):
        out = self.view("short", SHORT)
        self.assertEqual(len(out["strip"]), 11)
        self.assertEqual(out["strip"][0]["title"], "B1 part 1 (U1)")
        self.assertIn("1 unit", out["strip"][0]["hint"])  # the Unit is read from the title
        self.assertEqual(out["facts"], 33)  # three "- **Done when**" style facts per bolt are read as facts
        titles = [s["title"] for s in out["sections"]]
        self.assertEqual(titles[0], "Sequence")
        self.assertEqual(titles[-2:], ["Not a Bolt", "Sources"])

    def test_sequence_table_feeds_the_strip(self):
        out = self.view("sequence", SHORT)
        self.assertIn("api", out["strip"][1]["hint"])
        self.assertIn("beside B2", out["strip"][2]["hint"])
        self.assertNotIn("beside", out["strip"][0]["hint"])  # "nothing" says nothing

    def test_both_forms_resolve_as_references(self):
        out = self.view("refs", SHORT)
        self.assertTrue(out["refs"]["B1"].startswith("B1 part 1"))
        self.assertTrue(out["refs"]["B3"].startswith("B3 part 3"))
        live = [l for l in out["links"] if l["in"].startswith("B2") and l["ref"] in ("B1", "BOLT 1")]
        self.assertTrue(live and not any(l["dead"] for l in live), out["links"])

    def test_every_section_has_a_dot_but_a_table_has_row_dots(self):
        out = self.view("dots", SHORT)
        by = {s["title"]: s["dot"] for s in out["sections"]}
        self.assertTrue(all(v for t, v in by.items() if t != "Sequence"), by)  # B1..B11, Not a Bolt, Sources
        self.assertFalse(by["Sequence"])  # its rows have the dots
        self.assertEqual(out["dots"], 13 + 11)

    def test_bolt_n_forms_are_unchanged(self):
        out = self.view("long", LONG_H2)
        self.assertEqual([b["title"] for b in out["strip"]], ["Bolt 1: part 1", "Bolt 2: part 2", "Bolt 3: part 3"])
        self.assertIn("1 unit", out["strip"][0]["hint"])
        self.assertTrue(out["refs"]["B1"].startswith("Bolt 1"))
        live = [l for l in out["links"] if l["in"].startswith("Bolt 2") and l["ref"] in ("B1", "BOLT 1")]
        self.assertTrue(live and not any(l["dead"] for l in live), out["links"])
        out = self.view("h3", H3_UNDER_MILESTONES)
        self.assertEqual([b["title"] for b in out["strip"]], ["Bolt 1: part one", "Bolt 2 — part two", "Bolt 3. part three"])

    def test_a_word_starting_with_b_is_not_a_bolt(self):
        out = self.view("notbolts", NOT_BOLTS)
        self.assertEqual(out["strip"], [] if "strip" in out else None)  # no view: the plain document, its sections
        self.assertEqual([s["title"] for s in out["sections"]], ["Background", "Bonus 2 things", "B-side"])


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestPlainDocumentReadPoints(unittest.TestCase):
    def test_four_h2_sections_four_dots_and_one_changed(self):
        out = drive("plain", page_with("plain-r2", [PLAIN_V1, PLAIN_V1]), page_with("plain-r3", [PLAIN_V1, PLAIN_V1, PLAIN_V2]))
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["before"]["bolts"], 0)
        self.assertEqual(out["before"]["dots"], 4)
        self.assertEqual([s["title"] for s in out["before"]["sections"]], ["Background", "Scope", "Approach", "Notes"])
        self.assertEqual(out["readInA"], 4)
        self.assertEqual(out["unread"], ["Scope"])  # the changed section only
        self.assertEqual(out["changed"], ["Scope"])

    def test_h3_only_document_is_split_into_h3_sections(self):
        v1 = "# Plan\n\nLead.\n\n### One\n\nA.\n\n### Two\n\nB.\n\n### Three\n\nC.\n"
        out = drive("plain", page_with("h3-r2", [v1, v1]), page_with("h3-r3", [v1, v1, v1.replace("B.", "B, changed.")]))
        self.assertEqual(out["before"]["dots"], 3)
        self.assertEqual(out["unread"], ["Two"])
        self.assertEqual(out["changed"], ["Two"])

    def test_document_without_headings_stays_one_block(self):
        v = "# Plan\n\nJust a paragraph.\n\nAnd another.\n"
        out = drive("plain", page_with("flat-r2", [v, v]), page_with("flat-r3", [v, v, v]))
        self.assertEqual(out["before"]["sections"], [])
        self.assertEqual(out["flatDots"], 0)


if __name__ == "__main__":
    unittest.main()
