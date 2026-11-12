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
DRIVER = os.path.join(HERE, "drive_gate_page.js")
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
        self.assertTrue(self.r["chips"][0].startswith("Claude's evaluation") and "2 to look at first" in self.r["chips"][0], self.r["chips"][0])

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

    def test_every_file_is_a_row_of_records_and_no_raw_table_leads(self):
        r = self.r
        self.assertEqual(r["docsOutsideRecords"], [], "no file is drawn in full outside Records")
        self.assertEqual(r["recordsWhy"]["d-stories"], "covered")
        self.assertEqual(r["recordsWhy"]["d-traceability"], "covered")
        self.assertEqual(r["recordsWhy"]["d-personas"], "notcovered")
        self.assertEqual(r["records"][-2:], ["d-stories", "d-traceability"], "covered files come last")
        self.assertLess(r["records"].index("d-personas"), r["records"].index("d-stories"), "files the evaluation does not cover come first")
        self.assertFalse(r["recordsOpen"], "closed by default while there is anything else to read")
        self.assertEqual(r["tablesOutsideRecords"], [], "no raw table is drawn outside Records")

    def test_rendering_writes_nothing(self):
        self.assertEqual(self.r["writes"], 0, "opening the page never writes to the gate")


COMPONENTS = """# Components

```yaml
components:
  - name: OrderService
    summary: Takes and closes the preorders.
    responsibilities: [accept an order, close orders at 18:00]
  - name: LoafStock
    summary: Counts the loaves left for tomorrow.
    responsibilities: [reserve a loaf]
```
"""
ENTITIES = """# Entities

```yaml
entities:
  - name: Order
    owner: orders
    description: One customer's reservation.
    attributes:
      - {name: id, type: uuid, required: true}
  - name: Loaf
    owner: stock
    description: A loaf type.
    attributes:
      - {name: sku, type: string, required: true}
```
"""
RULES = """# Rules

```yaml
rules:
  - id: BR1.1
    statement: Orders for tomorrow close at 18:00.
    category: timing
    logic: IF now > 18:00 THEN reject
  - id: BR1.2
    statement: One loaf type per order line.
    category: ordering
```
"""
FINDINGS = {"blocking": 0, "carried": [], "items": [
    {"id": "F%d" % i, "title": "Finding %d" % i, "severity": "medium", "blocking": False, "action": "Do something %d" % i,
     "actionBy": "reviewer", "why": "because"} for i in (1, 2, 3)]}


def drive(tmp, scenario, edit):
    """Run a scenario of drive_gate_page.js on the sample with edit(sample) applied to it."""
    with open(os.path.join(tmp, "sample.json"), encoding="utf-8") as f:
        sample = json.load(f)
    edit(sample)
    path = os.path.join(tmp, scenario + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sample, f)
    done = subprocess.run([NODE, DRIVER, PAGE, path, scenario], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert "error" not in out, out["error"]
    return out


def add_docs(sample):
    for n, (key, title, text) in enumerate((("components", "Components", COMPONENTS), ("entities", "Entities", ENTITIES), ("rules", "Rules", RULES)), 10):
        sample["row"]["documents"].append({"key": key, "title": title, "path": "x/%s.md" % key, "kind": "markdown", "bytes": len(text), "covered": False})
        sample["documents"][key] = {"n": n, "key": key, "title": title, "path": "x/%s.md" % key, "kind": "markdown", "text": text, "part": 1, "parts": 1}


@unittest.skipUnless(has_jsdom(), "node and the jsdom package are not installed")
class TestReadMarks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        build_sample(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_a_block_whose_items_are_all_read_leaves_under_unread(self):
        r = drive(self.tmp, "items", lambda s: None)
        self.assertTrue(r["unreadAllShown"]["block"])
        self.assertTrue(all(t["shown"] for t in r["unreadAllShown"]["tiers"]))
        first, other = r["firstTierRead"]["tiers"][0], r["firstTierRead"]["tiers"][1:]
        self.assertEqual(first["name"], "Look at first")
        self.assertFalse(first["shown"], "a tier whose items are all read hides")
        self.assertTrue(all(t["shown"] for t in other))
        self.assertTrue(r["firstTierRead"]["block"])
        done = r["allRead"]
        self.assertFalse(done["block"], "the whole block hides: header, tiers and folded groups")
        self.assertFalse(any(t["shown"] for t in done["tiers"]))
        self.assertFalse(any(done["folds"]))
        self.assertFalse(any(c.startswith("What the stage says") for c in done["chips"]), "the block leaves the page with its parts")
        self.assertTrue(r["back"]["block"] and all(t["shown"] for t in r["back"]["tiers"]), "All brings everything back")
        self.assertTrue(any(c.startswith("What the stage says") for c in r["back"]["chips"]))

    def test_answering_a_finding_card_marks_it_read(self):
        r = drive(self.tmp, "finding", lambda s: s["row"].update(findings=FINDINGS))
        self.assertFalse(r["before"]["read"])
        self.assertTrue(r["picked"]["read"] and r["picked"]["pick"])
        self.assertFalse(r["picked"]["other"], "only the answered card")
        self.assertFalse(r["unpicked"]["pick"])
        self.assertTrue(r["unpicked"]["read"], "un-picking leaves the read mark alone")
        self.assertEqual(r["unread"], {"f1": False, "f2": True, "f3": True})
        self.assertFalse(r["afterF2"]["f2"], "an answered card disappears under Unread")
        self.assertEqual(r["afterF2"]["focus"], "card:F3", "focus moves to the next card")
        self.assertFalse(r["afterAll"]["block"], "the findings block leaves when every card is read")
        self.assertFalse(r["afterAll"]["chip"])
        self.assertEqual(r["afterAll"]["focus"], "bar", "no card and no header left: focus stays in the bar")
        self.assertTrue(r["back"]["block"] and r["back"]["f1"] and r["back"]["f1Read"])

    def test_every_element_of_a_structured_view_has_its_own_mark(self):
        r = drive(self.tmp, "elements", add_docs)
        self.assertEqual(r["counts"], {"components": 2, "entities": 2, "rules": 2})
        self.assertIn("el:components:OrderService", r["keys"])
        self.assertIn("el:rules:BR1.1", r["keys"])
        self.assertIn("el:entities:Order", r["keys"])
        self.assertTrue(all("edotc" in c for c in r["dotRows"]), "a rule row ends in its dot cell")
        one = r["afterOne"]
        self.assertTrue(one["card"] and not one["blockRead"])
        self.assertTrue(any(k.startswith("el:components:") for k in one["stored"]), "stored as el:<doc>:<element>")
        self.assertNotEqual(r["progress0"], one["progress"], "elements count in the bar's progress")
        self.assertEqual(r["unreadOne"], {"hiddenCards": 1, "total": 2, "blockShown": True})
        self.assertFalse(r["unreadAll"]["blockShown"], "all elements read: the block rolls up to read and leaves")
        self.assertTrue(r["unreadAll"]["blockRead"])
        self.assertEqual(r["unreadAll"]["chip"], [])
        self.assertTrue(r["unreadAll"]["entities"])
        self.assertTrue(r["entityMark"]["read"] and r["entityMark"]["key"].startswith("el:entities:Order"))
        self.assertTrue(r["rule"]["read"] and r["rule"]["det"])
        self.assertEqual(r["rulesUnread"], {"shownRows": 1, "rows": 2, "detEh": 1}, "the read rule and its detail row hide")
        self.assertTrue(r["blockDot"]["elements"] and r["blockDot"]["blockRead"], "the block dot marks every element")
        self.assertFalse(r["blockDotOff"]["elements"] or r["blockDotOff"]["blockRead"])


if __name__ == "__main__":
    unittest.main()
