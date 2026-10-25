import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import forks  # noqa: E402


def run(data, *argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = forks.main(["--data", str(data), *argv])
    return code, out.getvalue(), err.getvalue()


class Registry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "data"
        self.clone = Path(self.tmp.name) / "clone"
        subprocess.run(["git", "init", "-q", str(self.clone)], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_none_saved_asks(self):
        code, out, _ = run(self.data, "resolve")
        self.assertEqual(code, 3)
        self.assertIn("No fork saved", out)
        self.assertFalse((self.data / "forks.json").exists())

    def test_one_saved_is_used(self):
        self.assertEqual(run(self.data, "add", "alice/aidlc-workflows", "--clone", str(self.clone))[0], 0)
        code, out, _ = run(self.data, "resolve")
        self.assertEqual(code, 0)
        fork = json.loads(out)
        self.assertEqual(fork["repo"], "alice/aidlc-workflows")
        self.assertEqual(fork["clone"], str(self.clone.resolve()))
        self.assertEqual(fork["upstream"], "awslabs/aidlc-workflows")

    def test_second_fork_makes_it_ask(self):
        run(self.data, "add", "alice/aidlc-workflows")
        code, out, _ = run(self.data, "add", "bob/aidlc-fork")
        self.assertEqual(code, 0)
        self.assertIn("ask which one", out)
        code, out, _ = run(self.data, "resolve")
        self.assertEqual(code, 4)
        self.assertIn("alice/aidlc-workflows", out)
        self.assertIn("bob/aidlc-fork", out)

    def test_add_again_updates_not_duplicates(self):
        run(self.data, "add", "alice/aidlc-workflows")
        code, out, _ = run(self.data, "add", "https://github.com/Alice/aidlc-workflows.git",
                           "--clone", str(self.clone))
        self.assertEqual(code, 0)
        self.assertIn("updated", out)
        saved = json.loads((self.data / "forks.json").read_text())["forks"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["clone"], str(self.clone.resolve()))
        # An empty --clone clears it.
        run(self.data, "add", "alice/aidlc-workflows", "--clone", "")
        self.assertIsNone(json.loads((self.data / "forks.json").read_text())["forks"][0]["clone"])

    def test_bad_input_refused(self):
        self.assertEqual(run(self.data, "add", "not-a-repo")[0], 2)
        code, _, err = run(self.data, "add", "alice/x", "--clone", str(Path(self.tmp.name) / "missing"))
        self.assertEqual(code, 2)
        self.assertIn("not a git clone", err)
        self.assertFalse((self.data / "forks.json").exists())

    def test_broken_file_refused(self):
        self.data.mkdir()
        (self.data / "forks.json").write_text("{not json")
        code, _, err = run(self.data, "resolve")
        self.assertEqual(code, 2)
        self.assertIn("forks.json", err)

    def test_show_and_remove(self):
        run(self.data, "add", "alice/aidlc-workflows")
        self.assertEqual(run(self.data, "show", "bob/other")[0], 5)
        self.assertEqual(run(self.data, "show", "alice/aidlc-workflows")[0], 0)
        self.assertEqual(run(self.data, "remove", "alice/aidlc-workflows")[0], 0)
        self.assertEqual(run(self.data, "resolve")[0], 3)

    def test_data_dir_choice(self):
        with mock.patch.dict(os.environ, {"CLAUDE_PLUGIN_DATA": str(self.data)}):
            self.assertEqual(forks.data_dir(None), self.data)
            # An empty or unexpanded --data falls through to the variable.
            self.assertEqual(forks.data_dir(""), self.data)
            self.assertEqual(forks.data_dir("${CLAUDE_PLUGIN_DATA}"), self.data)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(forks.data_dir(None), forks.FALLBACK)


if __name__ == "__main__":
    unittest.main()
