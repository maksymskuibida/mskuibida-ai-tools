"""The per-stage page rendering a judged gate: gate_bundle.py draft, a written judgment (fixtures/judgment/user-stories.json),
finalize, then approval-gate.html under jsdom (render_gate_page.js) with a stand-in for the artifact's db.
Needs Node and the jsdom package (NODE_PATH); without them the class skips. CI installs jsdom for it.
Set APPROVAL_GATES_SAMPLE_OUT to a path to keep the rendered page for a person to open.
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
PAGE = os.path.join(PLUGIN, "skills", "approval-gates", "approval-gate.html")
HARNESS = os.path.join(HERE, "render_gate_page.js")
FIXTURE = os.path.join(HERE, "fixtures", "project")
JUDGMENT = os.path.join(HERE, "fixtures", "judgment", "user-stories.json")
NODE = shutil.which("node")


def has_jsdom():
    if not NODE:
        return False
    return subprocess.run([NODE, "-e", "require('jsdom')"], capture_output=True).returncode == 0


def build_sample(tmp):
    """sample.json for the harness: the finalized row and its documents."""
    project, out = os.path.join(tmp, "project"), os.path.join(tmp, "gate")
    shutil.copytree(FIXTURE, project)
    env = dict(os.environ, APPROVAL_GATES_DIR=os.path.join(tmp, "state"), AIDLC_IDS_DIR=os.path.join(tmp, "ids"))
    script = os.path.join(PLUGIN, "scripts", "gate_bundle.py")
    done = subprocess.run([sys.executable, script, "draft", "--stage", "user-stories", "--no-brief", "--project-dir", project,
                           "--out", out], capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr
    with open(os.path.join(out, "judgment.json"), encoding="utf-8") as f:
        j = json.load(f)
    with open(JUDGMENT, encoding="utf-8") as f:
        written = json.load(f)
    for key in ("evaluation", "documents"):
        j[key] = written[key]
    for key in ("criteria", "items"):
        for k, v in written[key].items():
            j[key][k].update(v)
    with open(os.path.join(out, "judgment.json"), "w", encoding="utf-8") as f:
        json.dump(j, f)
    done = subprocess.run([sys.executable, script, "finalize", "--out", out], capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr
    gate_id = json.loads(done.stdout)["id"]
    with open(os.path.join(out, "row.json"), encoding="utf-8") as f:
        row = json.load(f)
    documents = {}
    for name in sorted(os.listdir(os.path.join(out, "documents"))):
        with open(os.path.join(out, "documents", name), encoding="utf-8") as f:
            documents[name[:-5]] = json.load(f)
    path = os.path.join(tmp, "sample.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"id": gate_id, "row": row, "documents": documents}, f)
    return path


@unittest.skipUnless(has_jsdom(), "node and the jsdom package are not installed")
class TestTheJudgedPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        sample = build_sample(cls.tmp)
        args = [NODE, HARNESS, PAGE, sample]
        if os.environ.get("APPROVAL_GATES_SAMPLE_OUT"):
            args.append(os.environ["APPROVAL_GATES_SAMPLE_OUT"])
        done = subprocess.run(args, capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr
        cls.r = json.loads(done.stdout)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_evaluation_leads(self):
        self.assertEqual(self.r["blocks"][0], "b-eval")
        self.assertEqual(self.r["blocks"][1], "b-items")
        self.assertEqual(self.r["verdict"], "Ready, with risks")
        self.assertIn("reserve a loaf for the next morning", self.r["decides"])
        self.assertEqual(len(self.r["lookFirst"]), 2)
        self.assertIn("Why first", self.r["lookFirst"][0])
        self.assertEqual(self.r["columns"][:2], ["Risks1", "Gaps1"])
        self.assertIn("Solid2", self.r["columns"])
        self.assertTrue(self.r["chips"][0].startswith("Evaluation2 to look at first"), self.r["chips"][0])

    def test_every_criterion_shows_its_verdict_and_a_source_opens_it(self):
        verdicts = {c["id"]: c["verdict"] for c in self.r["criteria"]}
        self.assertEqual(verdicts["crit-stage-2"], "Fails")
        self.assertEqual(verdicts["crit-rule-2"], "Not relevant")
        self.assertEqual(len(verdicts), 10)
        self.assertTrue(self.r["sourceOpened"], "a criterion chip opens the criterion it names")

    def test_items_carry_the_agents_summary_grouped_by_what_matters(self):
        self.assertEqual(self.r["tiers"], ["Look at first", "Main"])
        by = {i["id"]: i for i in self.r["items"]}
        self.assertTrue(by["US1.1"]["summary"].startswith("A customer reserves a loaf for tomorrow until 18:00"))
        self.assertIn("high", by["US1.1"]["chips"])
        for item in self.r["items"]:
            self.assertNotIn("…", item["summary"])
        self.assertTrue(any(f.startswith("Traceability") for f in self.r["folds"]))

    def test_opening_an_item_shows_it_as_written(self):
        self.assertIn("As written", self.r["opened"])
        self.assertIn("AC1.1.2", self.r["opened"])
        self.assertIn("orders for tomorrow are closed", self.r["opened"])

    def test_covered_files_fold_under_as_written_and_no_raw_table_leads(self):
        self.assertEqual(self.r["asWritten"], ["d-stories", "d-traceability"])
        self.assertNotIn("d-stories", self.r["shownDocs"])
        self.assertIn("d-personas", self.r["shownDocs"])
        self.assertEqual(self.r["tablesOutsideAsWritten"], ["d-review-02"], "only the reviewer's findings table")

    def test_rendering_writes_nothing(self):
        self.assertEqual(self.r["writes"], 0, "opening the page never writes to the gate")


if __name__ == "__main__":
    unittest.main()
