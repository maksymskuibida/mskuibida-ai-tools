"""Tests for the per-stage gate's judgment: gate_bundle.py draft gathers the criteria and writes judgment.json with a todo
list; finalize refuses the row, in the recipe shape, until the evaluation, every criterion's verdict and every item's
summary and label are there; scripts/criteria.py and the unclipped items of scripts/digest.py.
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_gate_bundle import Case, fill_judgment, record  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import digest  # noqa: E402
import judgment  # noqa: E402


class Judged(Case):
    def draft(self, *args):
        return self.summary("--stage", "user-stories", "--no-brief", *args)

    def load(self, name):
        with open(os.path.join(self.out, name), encoding="utf-8") as f:
            return json.load(f)

    def edit(self, change):
        path = os.path.join(self.out, "judgment.json")
        j = self.load("judgment.json")
        change(j)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(j, f)

    def refused(self):
        code, _out, err = self.run_finalize()
        self.assertEqual(code, 1, "finalize should refuse")
        return err


class TestDraft(Judged):
    def test_the_criteria_come_from_the_stage_the_reviewer_the_rules_and_earlier_stages(self):
        self.draft()
        crit = self.load("criteria.json")
        origins = {c["origin"] for c in crit}
        self.assertEqual(origins, {"stage", "review", "rule", "earlier"})
        by = {c["key"]: c for c in crit}
        self.assertIn("Stories describe what a person does and why", by["stage-1"]["text"])
        self.assertEqual(by["stage-2"]["title"], "stories.md")
        self.assertTrue(by["stage-2"]["source"].startswith("path:.claude/aidlc-common/stages/inception/user-stories.md#L"))
        reviews = [c["title"] for c in crit if c["origin"] == "review"]
        self.assertIn("INVEST criteria met?", reviews)
        self.assertNotIn("Every requirement testable?", reviews, "another stage's checklist is not this one's")
        rules = [c["text"] for c in crit if c["origin"] == "rule"]
        self.assertEqual(len(rules), 2, "NEVER / ALWAYS bullets only, not every bullet of the file")
        self.assertIn("earlier-requirements", by)

    def test_the_draft_writes_a_judgment_to_fill_and_never_a_batch(self):
        os.makedirs(self.out)
        with open(os.path.join(self.out, "writes.json"), "w", encoding="utf-8") as f:
            f.write("[]")
        summary = self.draft()
        self.assertFalse(os.path.exists(os.path.join(self.out, "writes.json")), "an old batch must not outlive a new draft")
        self.assertNotIn("writes", summary)
        j = self.load("judgment.json")
        self.assertEqual(j["schema"], judgment.SCHEMA)
        self.assertIsNone(j["evaluation"]["verdict"])
        self.assertTrue(all(c["verdict"] is None for c in j["criteria"].values()))
        self.assertIn("US1.1", j["items"])
        self.assertIsNone(j["items"]["US1.1"]["summary"])
        self.assertTrue(j["items"]["US1.1"]["_asWritten"])
        self.assertTrue(any("criteria" in t for t in summary["todo"]))
        self.assertTrue(any("one-sentence summary" in t for t in summary["todo"]))
        self.assertIn("finalize --out", summary["next"])

    def test_the_draft_suggests_which_documents_its_items_cover(self):
        self.draft()
        docs = self.load("judgment.json")["documents"]
        self.assertEqual(docs["user-stories-questions"], "shown", "a questions file is always shown")
        self.assertEqual(docs["traceability"], "covered")


class TestFinalizeRefuses(Judged):
    def test_an_empty_judgment_is_refused_as_a_recipe(self):
        self.draft()
        err = self.refused()
        self.assertTrue(err.startswith("Refused: the gate row, because"), err)
        self.assertIn("Do this:\n1. In ", err)
        self.assertIn("evaluation.verdict", err)
        self.assertIn("item US1.1 summary: write it", err)
        self.assertIn("criterion stage-1", err)
        self.assertIn("It worked when:", err)
        self.assertFalse(os.path.exists(os.path.join(self.out, "writes.json")))

    def test_a_clipped_or_overlong_summary_is_refused(self):
        self.draft()
        fill_judgment(os.path.join(self.out, "judgment.json"))
        self.edit(lambda j: j["items"]["US1.1"].update(summary="A customer picks a slot and…"))
        self.assertIn("item US1.1 summary: write it whole, with no ellipsis", self.refused())
        self.edit(lambda j: j["items"]["US1.1"].update(summary="x" * 301))
        self.assertIn("item US1.1 summary: 301 characters", self.refused())

    def test_a_label_and_look_first_are_checked(self):
        self.draft()
        fill_judgment(os.path.join(self.out, "judgment.json"))
        self.edit(lambda j: j["items"]["US1.1"].update(label="important"))
        self.assertIn("item US1.1: label one of critical", self.refused())
        self.edit(lambda j: j["items"]["US1.1"].update(label="low", lookFirst=True))
        self.assertIn("lookFirst is for critical and high items", self.refused())

    def test_every_point_names_a_source_that_exists(self):
        self.draft()
        fill_judgment(os.path.join(self.out, "judgment.json"))
        self.edit(lambda j: j["evaluation"]["solid"].append({"text": "Fine.", "sources": ["FR99"]}))
        self.assertIn("'FR99' is no criterion, item, document or finding", self.refused())
        self.edit(lambda j: j["evaluation"].update(solid=[{"text": "Fine.", "sources": []}]))
        self.assertIn("evaluation.solid[0].sources: name at least one", self.refused())

    def test_a_failed_criterion_needs_a_note_and_a_point_that_names_it(self):
        self.draft()
        fill_judgment(os.path.join(self.out, "judgment.json"))
        self.edit(lambda j: j["criteria"]["rule-1"].update(verdict="fails"))
        err = self.refused()
        self.assertIn("a fails says why in its note", err)
        self.assertIn("name it in the sources of a lookFirst, risks, gaps or conflicts point", err)

        def cite(j):
            j["criteria"]["rule-1"]["note"] = "US1.3 takes a card payment."
            j["evaluation"]["conflicts"] = [{"text": "US1.3 asks for online payment, which the owner ruled out.",
                                             "sources": ["rule-1", "US1.1"]}]
        self.edit(cite)
        code, _out, err = self.run_finalize()
        self.assertEqual(code, 0, err)

    def test_look_first_needs_a_why(self):
        self.draft()
        fill_judgment(os.path.join(self.out, "judgment.json"))
        self.edit(lambda j: j["evaluation"]["lookFirst"][0].pop("why"))
        self.assertIn("evaluation.lookFirst[0].why: write it", self.refused())

    def test_a_judgment_of_another_draft_is_refused(self):
        self.draft()
        fill_judgment(os.path.join(self.out, "judgment.json"))
        self.edit(lambda j: j.update(gate="another-gate-20260101T0000"))
        self.assertIn("belongs to gate another-gate", self.refused())


class TestFinalize(Judged):
    def test_the_row_carries_the_judgment_and_no_notes_for_the_agent(self):
        self.draft()
        fill_judgment(os.path.join(self.out, "judgment.json"))
        self.edit(lambda j: j["items"]["US1.1"].update(label="high", lookFirst=True))
        code, out, err = self.run_finalize()
        self.assertEqual(code, 0, err)
        summary = json.loads(out)
        self.assertEqual((summary["verdict"], summary["lookFirst"]), ("risks", 1))
        row = self.load("row.json")
        self.assertNotIn("gate", row, "the id is the row's doc_id, not a field")
        self.assertEqual(row["evaluation"]["verdict"], "risks")
        self.assertTrue(all(c["verdict"] == "holds" for c in row["criteria"]))
        us = next(i for i in row["digest"]["items"] if i["id"] == "US1.1")
        self.assertEqual((us["summary"], us["label"], us["lookFirst"]), ("A plain one-sentence summary.", "high", True))
        self.assertIn("covered", row["documents"][0])
        self.assertNotIn('"_', json.dumps(row), "keys for the agent never reach the page")
        self.assertEqual(judgment.row_problems(row), [])
        with open(summary["writes"], encoding="utf-8") as f:
            self.assertEqual(json.load(f)[0]["file_path"], os.path.join(self.out, "row.json"))

    def test_the_next_round_carries_what_did_not_change(self):
        self.finalized("--stage", "user-stories", "--no-brief")
        stories = os.path.join(record(self.project), "inception", "user-stories", "stories.md")
        with open(stories, encoding="utf-8") as f:
            text = f.read()
        ids = [i for i in self.load("judgment.json")["items"]]
        changed = ids[0]
        with open(stories, "w", encoding="utf-8") as f:
            f.write(text.replace(changed, changed, 1) + "\n")
        self.draft()
        j = self.load("judgment.json")
        carried = [k for k, v in j["items"].items() if v.get("unchanged")]
        self.assertTrue(carried, "items whose text did not change keep their summary and label")
        for k in carried:
            self.assertEqual(j["items"][k]["summary"], "A plain one-sentence summary.")
        self.assertTrue(any("unchanged since the last round" in t for t in judgment.todo(j, {})))


class TestRowProblems(unittest.TestCase):
    def test_a_row_without_an_evaluation_is_refused(self):
        self.assertIn("no evaluation of the stage", judgment.row_problems({"title": "t"})[0])

    def test_settled_items_need_no_judgment(self):
        row = {"evaluation": {"verdict": "ready", "decides": "d", "lookFirst": [{"text": "t", "why": "w", "sources": ["FR1"]}],
                              "solid": [{"text": "s", "sources": ["FR1"]}]},
               "digest": {"items": [{"id": "FR1", "title": "x", "settled": True}]}}
        self.assertEqual(judgment.row_problems(row), [])


class TestItemsAreWhole(unittest.TestCase):
    def test_a_long_title_is_never_clipped(self):
        title = "A customer " + "who orders bread " * 20 + "gets one pickup slot"
        got = digest.build([{"key": "r", "title": "R", "text": f"| ID | Requirement |\n|---|---|\n| FR1 | {title} |\n"}], {}, "s")
        self.assertEqual(got["items"][0]["title"], title)
        self.assertNotIn("…", json.dumps(got))

    def test_a_rule_in_the_yaml_source_of_truth_keeps_its_logic(self):
        text = ("# Rules\n\n```yaml\nrules:\n  - id: BR1.1\n    statement: A full slot refuses a reservation.\n"
                "    logic: IF the slot holds 12 orders THEN refuse the 13th.\n  - id: BR1.2\n    statement: Slots close at 18:00.\n"
                "```\n\n| ID | Rule |\n|---|---|\n| BR1.1 | Full slot refuses |\n")
        got = {i["id"]: i for i in digest.build([{"key": "rules", "title": "Rules", "text": text}], {}, "s")["items"]}
        self.assertEqual(got["BR1.1"]["format"], "yaml")
        self.assertEqual(got["BR1.1"]["title"], "A full slot refuses a reservation.")
        self.assertIn("logic: IF the slot holds 12 orders THEN refuse the 13th.", got["BR1.1"]["body"])
        self.assertNotIn("BR1.2", got["BR1.1"]["body"])

    def test_a_storys_criteria_are_kept_as_written(self):
        text = "### US1.1 Pick a slot\nAs a customer I pick a slot.\n- AC1.1.1 Given a free slot, when I pick it, then it is mine.\n"
        got = digest.build([{"key": "stories", "title": "Stories", "text": text}], {}, "s")["items"][0]
        self.assertEqual(got["body"], "As a customer I pick a slot.\n- AC1.1.1: Given a free slot, when I pick it, then it is mine.")


if __name__ == "__main__":
    unittest.main()
