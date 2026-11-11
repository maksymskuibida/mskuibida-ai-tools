"""A revision round's judgment: gate_bundle.py draft hands the agent the developer's last Request Changes and the sections
that changed since the last finalize of the stage; finalize refuses the row until `revision` says what was done for each
piece of the feedback and where it shows on the page.
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_gate_bundle import Case, bundle, fill_judgment, record  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
import judgment  # noqa: E402

STAGE = ["--stage", "user-stories", "--no-brief"]
# The shape the engine writes, copied from a real audit trail (a requirements-analysis round 1 -> 2)
REJECTED = """
## Gate Rejected
**Timestamp**: 2026-02-01T09:00:00Z
**Event**: GATE_REJECTED
**Stage**: user-stories
**Feedback**: [User did not answer this question — they sent a message instead. Treat that message as their response; do not re-ask.]\\nSaturday pickups too\\nand keep the slot at 15 minutes
**Conductor Summary**: Two changes: pickups on Saturdays as well, and the slot stays 15 minutes.
**Message Id**: 3b993454

---
"""
BUTTON_ONLY = REJECTED.replace("2026-02-01T09:00:00Z", "2026-02-02T09:00:00Z").replace(
    "**Feedback**: [User did not answer this question — they sent a message instead. Treat that message as their response; do not re-ask.]\\nSaturday pickups too\\nand keep the slot at 15 minutes",
    "**Feedback**: Request Changes").replace("Two changes: pickups on Saturdays as well, and the slot stays 15 minutes.",
                                             "All three findings sorted Fix on the approval page, no notes.")


class Revision(Case):
    def reject(self, block=REJECTED):
        with open(os.path.join(record(self.project), "audit", "session-a.md"), "a", encoding="utf-8") as f:
            f.write(block)

    def stories(self, change):
        path = os.path.join(record(self.project), "inception", "user-stories", "stories.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(change(text))

    def judgment(self):
        with open(os.path.join(self.out, "judgment.json"), encoding="utf-8") as f:
            return json.load(f)

    def save(self, j):
        with open(os.path.join(self.out, "judgment.json"), "w", encoding="utf-8") as f:
            json.dump(j, f)

    def second_round(self):
        """Round 1 finalized, a Request Changes in the audit trail, stories.md edited, round 2 drafted."""
        self.finalized(*STAGE)
        self.reject()
        self.stories(lambda t: t.replace("## ", "## Saturday pickups\n\nA customer picks a Saturday slot too.\n\n## ", 1))
        return self.summary(*STAGE)


class TestDraft(Revision):
    def test_a_first_round_has_no_revision_slot(self):
        self.summary(*STAGE)
        self.assertNotIn("revision", self.judgment())

    def test_a_revision_round_carries_the_feedback_and_the_changed_sections(self):
        drafted = self.second_round()
        j = self.judgment()
        self.assertEqual(self.gate()["why"], "revision")
        rev = j["revision"]
        self.assertEqual(rev["feedback"], "Two changes: pickups on Saturdays as well, and the slot stays 15 minutes.")
        self.assertEqual(rev["_said"], "Saturday pickups too\nand keep the slot at 15 minutes", "the not-answered preamble is dropped")
        self.assertEqual(rev["changes"], [])
        changed = {(c["where"], c["change"]) for c in rev["_changed"]}
        self.assertIn(("doc:stories#Saturday pickups", "new"), changed)
        self.assertFalse(any(c["document"] == "personas" for c in rev["_changed"]), "an untouched document is not listed")
        self.assertTrue(any(t.startswith("revision: this is a revision round") for t in drafted["todo"]))

    def test_the_button_alone_leaves_the_summary_as_the_feedback(self):
        self.finalized(*STAGE)
        self.reject()
        self.reject(BUTTON_ONLY)
        self.summary(*STAGE)
        rev = self.judgment()["revision"]
        self.assertEqual(rev["feedback"], "All three findings sorted Fix on the approval page, no notes.", "the latest rejection wins")
        self.assertNotIn("_said", rev, "`Request Changes` alone says nothing")

    def test_without_a_record_of_the_last_documents_it_says_so(self):
        self.reject()
        self.summary(*STAGE, "--why", "revision")
        rev = self.judgment()["revision"]
        self.assertEqual(rev["_changed"], [])
        self.assertIn("kept no record of its documents", rev["_note"])


class TestFinalize(Revision):
    def fill(self, revision):
        drafted = self.second_round()
        fill_judgment(drafted["judgment"])
        j = self.judgment()
        if revision is None:
            j.pop("revision")
        else:
            j["revision"].update(revision)
        self.save(j)
        return self.run_finalize()

    def test_a_revision_round_is_refused_without_an_account_of_it(self):
        code, _out, err = self.fill({})
        self.assertEqual(code, 1)
        self.assertIn("revision.changes: at least one {asked, what, where[]}", err)

    def test_a_revision_round_is_refused_without_the_slot(self):
        code, _out, err = self.fill(None)
        self.assertEqual(code, 1)
        self.assertIn("revision: this round follows a Request Changes", err)

    def test_every_place_must_be_on_the_page(self):
        code, _out, err = self.fill({"changes": [
            {"asked": "Saturday pickups", "what": "Added a section for them.", "where": ["doc:stories#Sunday pickups"]},
            {"asked": "Keep 15 minutes", "what": "Left as it was.", "where": ["doc:nowhere", "FR99"]}]})
        self.assertEqual(code, 1)
        self.assertIn("no heading or id 'Sunday pickups' in stories", err)
        self.assertIn("'doc:nowhere' names no document of this gate", err)
        self.assertIn("'FR99' is no place on this page", err)

    def test_a_good_account_goes_on_the_row(self):
        code, out, err = self.fill({"changes": [
            {"asked": "Saturday pickups", "what": "Added a section for them.", "where": "doc:stories#Saturday pickups"},
            {"asked": "Keep 15 minutes", "what": "Left as it was; the evaluation says why.", "where": ["evaluation", "doc:stories"]}]})
        self.assertEqual(code, 0, err)
        with open(os.path.join(self.out, "row.json"), encoding="utf-8") as f:
            row = json.load(f)
        self.assertEqual(row["revision"]["feedback"], "Two changes: pickups on Saturdays as well, and the slot stays 15 minutes.")
        self.assertEqual(row["revision"]["changes"][0]["where"], ["doc:stories#Saturday pickups"], "one place becomes a list")
        self.assertFalse(any(k.startswith("_") for k in row["revision"]), "notes for the agent are dropped")
        self.assertEqual(judgment.row_problems(row), [], "the guard holds the written row to the same rules")

    def test_the_guard_refuses_a_revision_row_without_one(self):
        row = {"why": "revision", "evaluation": {"verdict": "ready", "decides": "d", "lookFirst": [{"text": "t", "why": "w", "sources": ["doc:a"]}],
                                                 "solid": [{"text": "s", "sources": ["doc:a"]}]}, "documents": [{"key": "a"}]}
        self.assertTrue(any(p.startswith("revision:") for p in judgment.row_problems(row)))
        row["revision"] = {"feedback": "Fix it.", "changes": [{"asked": "Fix it", "what": "Fixed.", "where": ["doc:a#Anything"]}]}
        self.assertEqual(judgment.row_problems(row), [], "without the texts a heading is not checked")


class TestSections(unittest.TestCase):
    def test_sections_and_what_changed(self):
        before = {"r": {"sections": judgment.sections("# R\nlead\n## A\nx\n### A1\ny\n## B\nz\n## C\ngone\n")}}
        got = judgment.changed_sections(before, {"r": "# R\nlead\n## A\nx\n### A1\nY changed\n## B\nz\n## D\nnew\n", "n": "# New\n"})
        found = {(c["section"], c["change"]) for c in got}
        self.assertEqual(found, {("A", "changed"), ("A › A1", "changed"), ("D", "new"), ("C", "removed"), ("", "new")})
        self.assertIn({"where": "doc:r#A1", "document": "r", "section": "A › A1", "change": "changed"}, got)

    def test_last_feedback_reads_the_latest_rejection_of_the_stage_only(self):
        import tempfile
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "audit"))
        with open(os.path.join(root, "audit", "a.md"), "w", encoding="utf-8") as f:
            f.write(REJECTED + REJECTED.replace("user-stories", "requirements-analysis").replace("Two changes", "Other stage"))
        got = bundle.last_feedback(root, "user-stories", None)
        self.assertEqual(got["at"], "2026-02-01T09:00:00Z")
        self.assertTrue(got["feedback"].startswith("Two changes"))
        self.assertEqual(bundle.last_feedback(root, "user-stories", "u1-core"), {}, "another Unit's rejection is not this one")


if __name__ == "__main__":
    unittest.main()
