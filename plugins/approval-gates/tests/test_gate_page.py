"""Static checks of the per-stage page (skills/approval-gates/approval-gate.html): its scripts parse, and the finding cards
keep their contract (findingPicks written only with the notes; no Accept on a blocking finding; Reject needs a reason).
The page draws with the DOM, so how it looks is checked by eye on the published artifact.
Run: python3 -m unittest discover -s plugins/approval-gates/tests"""

import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(os.path.dirname(HERE), "skills", "approval-gates", "approval-gate.html")
NODE = shutil.which("node")

PARSE = r"""
const h = require("fs").readFileSync(process.argv[1], "utf8");
const scripts = [...h.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
for (const s of scripts) new Function(s);
process.stdout.write(String(scripts.length));
"""


class TestThePage(unittest.TestCase):
    def setUp(self):
        with open(PAGE, encoding="utf-8") as f:
            self.page = f.read()

    @unittest.skipUnless(NODE, "node is not installed")
    def test_every_script_parses(self):
        done = subprocess.run([NODE, "-e", PARSE, PAGE], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_the_finding_cards_keep_their_contract(self):
        self.assertIn('fnd() ? { findingPicks: JSON.parse(JSON.stringify(view.fpicks)) } : {}', self.page)
        self.assertIn('const off = k === "accept" && f.blocking;', self.page)
        self.assertIn("Reject needs a reason", self.page)
        self.assertIn("gates/<id>.findingPicks[<finding id>]", self.page, "the header names the field")

    def test_the_read_dot_is_the_last_element_of_an_item_row_and_a_finding_card(self):
        item = self.page[self.page.index("function itemRow"):]
        item = item[:item.index("function coverageHtml")]
        self.assertLess(item.index('class="ititle"'), item.index("${idot(key, it.id)}"), "item row: dot after the title")
        self.assertLess(item.index("${handledChip(it)}"), item.index("${idot(key, it.id)}"), "item row: dot after the chips")
        card = self.page[self.page.index('<div class="dtop">${sev}'):]
        card = card[:card.index("</div>")]
        self.assertTrue(card.endswith('${idot("finding:" + f.id, f.id)}'), "finding card: dot ends the header")

