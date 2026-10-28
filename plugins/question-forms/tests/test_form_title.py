"""question-form.html's formTitle: rows written with the older titles read as what the form is."""
import json
import os
import re
import shutil
import subprocess
import unittest

PAGE = os.path.join(os.path.dirname(__file__), "..", "skills", "question-forms", "question-form.html")
NODE = shutil.which("node")


def titles(rows):
    with open(PAGE, encoding="utf-8") as f:
        src = re.search(r"  const formTitle = .*?\n  \};\n", f.read(), re.S).group(0)
    done = subprocess.run([NODE, "-e", src + "\nprocess.stdout.write(JSON.stringify(JSON.parse(require('fs').readFileSync(0,'utf8')).map(formTitle)))"],
                          input=json.dumps(rows), capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@unittest.skipUnless(NODE, "node is not installed")
class TestFormTitle(unittest.TestCase):
    def test_titles(self):
        got = titles([
            {"title": "Unit u2-accounts: Functional Design questions", "unit": "u2-accounts"},
            {"title": "Requirements Analysis questions"},
            {"title": "Unit u2-accounts: Domain Design review findings", "view": "board"},
            {"title": "Code review findings", "view": "board"},
            {"title": "Code review findings · #12", "view": "board"},
            {"title": "Functional Design — u2-accounts"},
            {"title": "Requirements Analysis"},
            {"title": "Review findings · Domain Design", "view": "board", "unit": "u1-core"},
            {"title": "Review findings · Domain Design", "view": "board"},
            {"title": "Review findings · code review", "view": "board"},
        ])
        self.assertEqual(got, [
            "Unit u2-accounts: Functional Design questions", "Requirements Analysis questions",
            "Unit u2-accounts: Domain Design review findings", "Code review findings", "Code review findings · #12",
            "Unit u2-accounts: Functional Design questions", "Requirements Analysis questions",
            "Unit u1-core: Domain Design review findings", "Domain Design review findings", "Code review findings"])


if __name__ == "__main__":
    unittest.main()
