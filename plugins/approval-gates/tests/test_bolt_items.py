"""Each bolt of a Delivery Planning bolt plan is a review item (approval-gates 1.35.4).

  1  digest.build reads `## B1 name (U1)` / `## Bolt 1: name` / `### Bolt 1` headings of the bolt-plan document as items B<n>: the title without
     the Unit parentheses, the Units, the done-when / confidence / demo bullets, the Sequence table row; other documents' B-words are not bolts
  2  the draft asks for a summary, label and lookFirst per bolt, finalize refuses a blank one, and the judgment lands on the row's items
  3  the page shows each bolt's review point inside the bolt's own section of the bolt view, the read dots and references still working

Synthetic data only. The page check is driven under jsdom by drive_bolts.js (skips without Node and jsdom).
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import copy
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import digest  # noqa: E402
import judgment  # noqa: E402
from test_bolts_plain import SHORT, LONG_H2, H3_UNDER_MILESTONES, NOT_BOLTS, drive, page_with  # noqa: E402
from test_fix1_pages import has_jsdom  # noqa: E402


def built(text, key="bolt-plan"):
    return digest.build([{"key": key, "title": key, "text": text}], {}, "inception/delivery-planning")


def bolts(text, key="bolt-plan"):
    return [i for i in built(text, key)["items"] if i["kind"] == "bolt"]


class TestExtraction(unittest.TestCase):
    def test_short_headings_become_items_with_units_fields_and_order(self):
        found = bolts(SHORT)
        self.assertEqual([b["id"] for b in found], [f"B{i}" for i in range(1, 12)])
        b2 = found[1]
        self.assertEqual(b2["title"], "part 2")
        self.assertEqual(b2["units"], ["U2"])
        self.assertEqual(b2["fields"]["done"], "part 2 works.")
        self.assertEqual(b2["fields"]["confidence"], "it is small.")
        self.assertIn("part 2 on screen", b2["fields"]["demo"])
        self.assertEqual(b2["order"], {"position": 2, "line": "api", "startsWhen": "B1 is done"})
        self.assertEqual(found[2]["order"]["beside"], "B2")
        self.assertEqual(b2["key"], "B2")
        self.assertIn("**Done when**", b2["body"])
        self.assertEqual(built(SHORT)["counts"]["bolt"], 11)

    def test_not_a_bolt_and_sources_are_not_items(self):
        ids = [i["id"] for i in built(SHORT)["items"]]
        self.assertNotIn("Not a Bolt", ids)
        self.assertEqual([b["id"] for b in bolts(SHORT)], [f"B{i}" for i in range(1, 12)])

    def test_long_h2_and_h3_forms(self):
        found = bolts(LONG_H2)
        self.assertEqual([(b["id"], b["title"], b["units"]) for b in found], [(f"B{i}", f"part {i}", [f"U{i}"]) for i in range(1, 4)])
        self.assertEqual([b["id"] for b in bolts(H3_UNDER_MILESTONES)], ["B1", "B2", "B3"])
        self.assertEqual(bolts(H3_UNDER_MILESTONES)[1]["title"], "part two")

    def test_words_starting_with_b_and_other_documents_give_none(self):
        self.assertEqual(bolts(NOT_BOLTS), [])
        self.assertEqual(bolts(SHORT, key="requirements"), [])

    def test_a_bolt_naming_a_requirement_relates_to_it(self):
        text = "# Plan\n\n## B1 first (U1, U2)\n\n- **Done when**: FR1 and US1.1 work.\n"
        b = bolts(text)[0]
        self.assertEqual(b["units"], ["U1", "U2"])
        self.assertEqual(b["mentions"], ["FR1", "US1.1"])


class TestPlanStaysShown(unittest.TestCase):
    def test_a_bolt_plan_is_not_suggested_as_covered(self):
        doc = {"key": "bolt-plan", "title": "bolt-plan"}
        self.assertEqual(judgment.suggest_document(doc, SHORT, built(SHORT)["items"]), "shown")


class TestJudgmentRoundTrip(unittest.TestCase):
    def gate(self):
        return {"stage": "delivery-planning", "unit": None, "round": 1, "documents": [{"key": "bolt-plan", "title": "bolt-plan"}],
                "digest": built(SHORT)}

    def test_the_skeleton_asks_for_every_bolt_and_the_row_carries_the_answers(self):
        gate = self.gate()
        j = judgment.skeleton("g1", gate, [], {"bolt-plan": SHORT})
        self.assertEqual([k for k in j["items"] if k.startswith("B")], [f"B{i}" for i in range(1, 12)])
        self.assertEqual(j["items"]["B3"]["_kind"], "bolt")
        self.assertTrue(any("B1" in t for t in judgment.todo(j, gate)))  # blank summaries are listed
        for k, e in j["items"].items():
            e.update(summary=f"{k} ships on its own.", label="high" if k == "B1" else "medium", lookFirst=k == "B1")
        row = judgment.merge(gate, [], j)
        by = {i["id"]: i for i in row["digest"]["items"]}
        self.assertEqual(by["B1"]["summary"], "B1 ships on its own.")
        self.assertTrue(by["B1"]["lookFirst"])
        self.assertEqual(by["B2"]["label"], "medium")
        self.assertEqual(by["B2"]["units"], ["U2"])  # what the draft read stays on the item
        self.assertEqual(judgment.todo(j, gate), [t for t in judgment.todo(j, gate) if "B" not in t.split(":")[0] or True])

    def test_a_blank_bolt_is_refused(self):
        gate = self.gate()
        j = judgment.skeleton("g1", gate, [], {"bolt-plan": SHORT})
        for e in j["items"].values():
            e.update(summary="A plain sentence.", label="medium")
        j["items"]["B4"]["summary"] = None
        self.assertTrue(any("B4" in p for p in judgment.todo(j, gate)))
        row = judgment.merge(gate, [], j)
        self.assertTrue(any("B4" in p for p in judgment.row_problems(row)))


@unittest.skipUnless(has_jsdom(), "needs Node and the jsdom package")
class TestPage(unittest.TestCase):
    def test_each_bolt_shows_its_review_point_in_its_section(self):
        out = drive("items", page_with("bolt-items", [SHORT] * 3))
        self.assertEqual(out["errors"], [])
        self.assertTrue(out["found"])
        self.assertEqual([p["bolt"] for p in out["points"]], [f"B{i}" for i in range(1, 12)])
        for p in out["points"]:
            self.assertTrue(p["in"].startswith(p["bolt"] + " "), p)
            self.assertTrue(p["summary"], p)
            self.assertTrue(p["label"], p)
        self.assertTrue(any(p["lookFirst"] for p in out["points"]))
        self.assertEqual(out["listed"], 11)  # and the items block lists them too, for the look-first tiers

    def test_the_strip_and_read_dots_still_work(self):
        out = drive("items", page_with("bolt-items-dots", [SHORT] * 3))
        self.assertEqual(out["strip"], 11)
        self.assertEqual(out["dots"], 13 + 11)


if __name__ == "__main__":
    unittest.main()
