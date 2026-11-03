"""The registry entry hooks/question_guard.py writes when a questions form is published (scripts/aidlc_links.py).
Run: python3 -m unittest discover -s plugins/question-forms/tests"""

import os
import sys
import unittest

from test_guard import FORM, REL, URL, Case

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import aidlc_links  # noqa: E402


class TestFormRegistry(Case):
    def setUp(self):
        super().setUp()
        os.environ["AIDLC_ARTIFACTS_DIR"] = os.path.join(self.tmp, "links-data")
        self.addCleanup(os.environ.pop, "AIDLC_ARTIFACTS_DIR", None)

    def entries(self):
        return aidlc_links.entries(self.project, "default", "261027-x")

    def write_form(self, form_id=FORM, file=REL, url=URL, **extra):
        data = dict({"file": file, "title": "Functional design questions"}, **extra)
        call = {"action": "batch", "url": url, "writes": [{"op": "set", "collection": "forms", "doc_id": form_id, "data": data}]}
        code, _out, err = self.post("ArtifactData", call)
        self.assertEqual(code, 0, err)

    def test_a_form_of_a_units_stage_is_recorded_under_that_stage_and_unit(self):
        self.written()
        self.write_form()
        [entry] = self.entries()
        self.assertEqual((entry["kind"], entry["phase"], entry["stage"], entry["unit"]), ("questions-form", "construction", "functional-design", "u12"))
        self.assertEqual((entry["url"], entry["artifact"], entry["row"], entry["title"]), (f"{URL}#{FORM}", URL, FORM, "Functional design questions"))
        self.assertEqual(entry["session"], "s1")

    def test_an_inception_form_has_a_stage_and_no_unit(self):
        rel = "aidlc/spaces/default/intents/261027-x/inception/user-stories/user-stories-questions.md"
        os.makedirs(os.path.dirname(os.path.join(self.project, rel)))
        self.write_file("## Q1\n[Answer]:\n", os.path.join(self.project, rel))
        self.write_form("261027-x-user-stories", rel)
        [entry] = self.entries()
        self.assertEqual((entry["phase"], entry["stage"], entry.get("unit")), ("inception", "user-stories", None))

    def test_the_form_row_written_again_stays_one_entry(self):
        self.written()
        self.write_form()
        self.write_form()
        self.assertEqual(len(self.entries()), 1)

    def test_a_form_with_no_questions_file_of_a_stage_is_not_recorded(self):
        self.write_form("board", "aidlc/spaces/default/other-questions.md")
        self.assertEqual(self.entries(), [])


if __name__ == "__main__":
    unittest.main()
