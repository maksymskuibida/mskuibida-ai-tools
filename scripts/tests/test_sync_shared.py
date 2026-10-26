"""Tests for scripts/sync-shared.py and shared/aidlc-ids/aidlc_ids.py."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SYNC = os.path.join(ROOT, "scripts", "sync-shared.py")
IDS = os.path.join(ROOT, "shared", "aidlc-ids", "aidlc_ids.py")

spec = importlib.util.spec_from_file_location("aidlc_ids", IDS)
ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai)


def files(root, tree):
    for rel, text in tree.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


class TestIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.intent = os.path.join(self.tmp, "project", "aidlc", "spaces", "default", "intents", "261018-demo")
        os.environ["AIDLC_IDS_DIR"] = os.path.join(self.tmp, "maps")
        self.addCleanup(os.environ.pop, "AIDLC_IDS_DIR", None)
        files(self.intent, {
            "inception/user-stories/stories.md": "# Stories\n\n## US1.1 — Sign in with a token\nAs the Reviewer I paste a token.\n\n"
                                                 "- **AC1.1.2** Given a valid token, when I confirm, then I see my avatar.\n",
            "inception/requirements-analysis/requirements.md": "- **FR1.4** The app shall validate a token. [Q2]\n"
                                                               "- **NFR3 GitHub rate limits:** at most 10 mutations in flight.\n",
            "inception/units-generation/unit-of-work.md": "### U31 — u31-thin-slice\n\n- **What:** the slice.\n",
            "inception/units-generation/unit-of-work-story-map.md": "| US1.1 | U31 | u31-thin-slice |\n",
            "inception/user-stories/user-stories-questions.md": "## Q1: Personas\nWho uses it.\n",
            "inception/domain-design/decisions.md": "| ADR-009 | The token in its own component | Accepted |\n",
            "construction/u1-skeleton/functional-design/rules.md": "```yaml\nrules:\n  # BR1 — Preferences store (C4, E3)\n```\n"
                                                                   "| BR1.1 | Keys are `<feature>.<setting>` and unique | constraint |\n",
            "construction/u1-skeleton/functional-design/functional-spec.md": "| U31 | (thin slice), window shell | seam |\n",
            "construction/u31-thin-slice/functional-design/rules.md": "| BR1.1 | A token is never logged anywhere | constraint |\n",
            "construction/u31-thin-slice/functional-design/functional-design-questions.md": "## Q1: Where the token lives\nKeychain.\n",
            "construction/u31-thin-slice/functional-design/reviews/review-01.md":
                "| R-01 | Major | inception/units-generation/unit-of-work.md > table | The slice misses the sign-out path |\n",
            "ideation/feasibility/raid-log.md": "| R-02 | Every part of the stack is new to the team | High |\n",
        })

    def refs(self, text, near):
        return ai.refs(self.intent, text, near)

    def test_kinds_titles_and_forms(self):
        every = ai.index(self.intent)
        self.assertEqual(every["AC1.1.2"][0]["kind"], "Acceptance criterion")
        self.assertEqual(every["NFR3"][0]["title"], "GitHub rate limits")
        self.assertEqual(every["ADR-009"][0]["title"], "The token in its own component")
        self.assertIn("<feature>.<setting>", every["BR1.1"][0]["title"] + every["BR1.1"][1]["title"])
        self.assertEqual(every["R-02"][0]["kind"], "Risk")

    def test_a_heading_beats_a_table_that_mentions_the_id(self):
        got = self.refs("US1.1 and U31", ["construction/u31-thin-slice/functional-design"])
        self.assertEqual(got["US1.1"]["doc"], "inception/user-stories/stories.md")
        self.assertEqual(got["U31"]["title"], "u31-thin-slice")

    def test_the_pages_own_unit_and_stage(self):
        near = ["construction/u31-thin-slice/functional-design"]
        got = self.refs("BR1.1, Q1 and R-01", near)
        self.assertEqual(got["BR1.1"]["title"], "A token is never logged anywhere")
        self.assertEqual(got["Q1"]["title"], "Where the token lives")
        self.assertEqual(got["R-01"]["title"], "The slice misses the sign-out path")

    def test_another_units_or_stages_definition_is_never_picked(self):
        got = self.refs("BR1.1, Q1, R-01 and FR1.4", ["construction/u2-accounts/functional-design"])
        self.assertEqual(set(got), {"FR1.4"})

    def test_the_map_lives_outside_the_project_and_follows_changes(self):
        _data, first = ai.sync(self.intent)
        self.assertTrue(first["written"])
        self.assertTrue(ai.map_path(self.intent).startswith(os.path.join(self.tmp, "maps")))
        self.assertFalse(any(n.endswith(".json") for _r, _d, fs in os.walk(os.path.join(self.tmp, "project")) for n in fs))
        _data, again = ai.sync(self.intent)
        self.assertEqual((again["written"], again["read"]), (False, 0))
        path = os.path.join(self.intent, "inception", "requirements-analysis", "requirements.md")
        with open(path, "a") as f:
            f.write("- **FR9.9** The app shall do one more thing.\n")
        os.utime(path, (1, 1))
        _data, changed = ai.sync(self.intent)
        self.assertEqual((changed["written"], changed["read"]), (True, 1))
        self.assertIn("FR9.9", ai.index(self.intent))
        os.remove(path)
        _data, gone = ai.sync(self.intent)
        self.assertEqual(gone["dropped"], 1)
        self.assertNotIn("FR1.4", ai.index(self.intent))

    def test_a_group_label_in_a_yaml_comment(self):
        got = self.refs("BR1", ["construction/u1-skeleton/functional-design"])
        self.assertEqual(got["BR1"]["title"], "Preferences store (C4, E3)")

    def test_inception_wins_for_an_intent_wide_id_restated_in_the_shown_file(self):
        got = self.refs("U31", ["construction/u1-skeleton/functional-design/functional-spec.md"])
        self.assertEqual(got["U31"]["doc"], "inception/units-generation/unit-of-work.md")

    def test_not_ids(self):
        self.assertEqual(ai.mentioned("UTF-8, SHA-256, H2 and FR1.4, US1.1a"), ["FR1.4", "US1.1a"])


class TestSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        shutil.copytree(os.path.join(ROOT, "shared"), os.path.join(self.tmp, "shared"))
        os.makedirs(os.path.join(self.tmp, "scripts"))
        shutil.copy(SYNC, os.path.join(self.tmp, "scripts", "sync-shared.py"))
        files(self.tmp, {"plugins/demo/page.html": "<html><head><style>body{}</style></head><body><div id=app></div>"
                                                   "<script>var x = 1;</script></body></html>",
                         "plugins/other/page.html": "<html><style></style><script></script></html>"})
        os.makedirs(os.path.join(self.tmp, "plugins", "demo", "scripts"))

    def run_sync(self, *args):
        return subprocess.run([sys.executable, os.path.join(self.tmp, "scripts", "sync-shared.py"), *args],
                              capture_output=True, text=True)

    def test_add_check_and_drift(self):
        page = os.path.join(self.tmp, "plugins", "demo", "page.html")
        done = self.run_sync("--add-page", page, "--add-python", os.path.join(self.tmp, "plugins", "demo", "scripts"))
        self.assertEqual(done.returncode, 0, done.stderr)
        text = open(page).read()
        self.assertIn("var AidlcIds", text)
        self.assertIn("a.aidlc-id", text)
        self.assertLess(text.index("var AidlcIds"), text.index("var x = 1"))
        check = self.run_sync("--check")
        self.assertEqual(check.returncode, 0, check.stdout)
        self.assertIn("1 aidlc_ids.py, 1 pages", check.stdout)
        with open(page, "w") as f:
            f.write(text.replace("var AidlcIds", "var Changed"))
        check = self.run_sync("--check")
        self.assertEqual(check.returncode, 1)
        self.assertIn("plugins/demo/page.html", check.stdout)
        self.assertEqual(self.run_sync().returncode, 0)
        self.assertEqual(self.run_sync("--check").returncode, 0)

    def test_a_page_without_the_blocks_is_left_alone(self):
        self.assertEqual(self.run_sync("--check").returncode, 0)
        self.assertNotIn("aidlc-ids", open(os.path.join(self.tmp, "plugins", "other", "page.html")).read())


class TestScript(unittest.TestCase):
    def test_js_parses(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        done = subprocess.run([node, "--check", os.path.join(ROOT, "shared", "aidlc-ids", "aidlc-ids.js")],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_js_and_python_agree_on_kinds(self):
        js = open(os.path.join(ROOT, "shared", "aidlc-ids", "aidlc-ids.js")).read()
        for prefix, kind in ai.KINDS.items():
            self.assertIn(f'{prefix}: "{kind}"', js, prefix)


if __name__ == "__main__":
    unittest.main()
