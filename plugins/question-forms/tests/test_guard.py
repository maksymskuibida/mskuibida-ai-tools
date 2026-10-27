"""Tests for hooks/question_guard.py and scripts/preference.py.
Run: python3 -m unittest discover -s plugins/question-forms/tests

The hook runs as a subprocess, as the harness runs it, with QUESTION_FORMS_DIR and CLAUDE_PROJECT_DIR pointing into a
temporary folder that holds a small AI-DLC project. The dialogs are the mod's (hooks/register.tsx); here a choice is
recorded the way the mod records it, with `preference.py`."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
HOOK = os.path.join(PLUGIN, "hooks", "question_guard.py")
SCRIPT = os.path.join(PLUGIN, "scripts", "preference.py")
os.environ.pop("CLAUDE_PROJECT_DIR", None)

REL = "aidlc/spaces/default/intents/261027-x/construction/u12/functional-design/functional-design-questions.md"
URL = "https://claude.ai/artifact/abc123"
FORM = "261027-x-functional-design-u12"
OPEN = "## Q1\n[Answer]:\n\n## Q2\n[Answer]: B\n"
FILLED = "## Q1\n[Answer]: A\n"


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.project = os.path.join(self.tmp, "project")
        self.file = os.path.join(self.project, REL)
        os.makedirs(os.path.dirname(self.file))
        self.write_file(OPEN)
        self.data = os.path.join(self.tmp, "data")
        self.transcript = os.path.join(self.tmp, "t.jsonl")
        open(self.transcript, "w").close()

    def write_file(self, text, path=None):
        with open(path or self.file, "w") as f:
            f.write(text)

    def env(self):
        return dict(os.environ, QUESTION_FORMS_DIR=self.data, CLAUDE_PROJECT_DIR=self.project)

    def run_hook(self, event, project=None):
        event = dict({"session_id": "s1", "cwd": project or self.project, "transcript_path": self.transcript}, **event)
        env = self.env()
        if project:
            env["CLAUDE_PROJECT_DIR"] = project
        done = subprocess.run([sys.executable, HOOK], input=json.dumps(event), capture_output=True, text=True, env=env, timeout=30)
        return done.returncode, done.stdout, done.stderr

    def script(self, *args, project=None):
        done = subprocess.run([sys.executable, SCRIPT, *args, "--project-dir", project or self.project], capture_output=True, text=True, env=self.env())
        self.assertEqual(done.returncode, 0, done.stderr)
        return done

    def pre(self, tool, ti, **kw):
        return self.run_hook({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": ti}, **kw)

    def post(self, tool, ti, response=None, **kw):
        return self.run_hook({"hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": ti, "tool_response": response or {}}, **kw)

    def stop(self, active=False):
        code, out, err = self.run_hook({"hook_event_name": "Stop", "stop_hook_active": active})
        self.assertEqual(code, 0, err)
        return json.loads(out) if out.strip() else {}

    def context(self, out):
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]

    def written(self, project=None):
        return self.post("Write", {"file_path": self.file if project is None else os.path.join(project, REL)}, project=project)

    def form_row(self):
        return self.post("ArtifactData", {"action": "batch", "writes": [{"op": "set", "path": f"forms/{FORM}", "data": {"file": REL}},
                                                                         {"op": "set", "path": f"forms/{FORM}/questions/q1", "data": {}}]})

    def say(self, text):
        with open(self.transcript, "a") as f:
            f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}) + "\n")


class TestPendingAndNextStep(Case):
    def test_no_preference_owes_the_preference_dialog(self):
        code, out, _ = self.written()
        self.assertEqual(code, 0)
        self.assertIn('"source": "question-forms:preference"', self.context(out))

    def test_always_says_to_publish_the_form(self):
        self.script("set", "--value", "always")
        _, out, _ = self.written()
        self.assertIn("becomes a form", self.context(out))

    def test_ask_owes_the_per_file_ask(self):
        self.script("set", "--value", "ask")
        _, out, _ = self.written()
        self.assertIn(f'question-forms:ask:{REL}', self.context(out))

    def test_ask_answer_edit_means_no_form(self):
        self.script("set", "--value", "ask")
        self.written()
        self.script("answer", "--file", REL, "--choice", "edit")
        self.assertEqual(self.stop(), {})

    def test_never_does_nothing(self):
        self.script("set", "--value", "never")
        code, out, _ = self.written()
        self.assertEqual((code, out.strip()), (0, ""))
        self.assertEqual(self.stop(), {})
        code, _, _ = self.pre("Bash", {"command": "aidlc engine orchestrate next"})
        self.assertEqual(code, 0)

    def test_other_files_and_outside_a_project_are_ignored(self):
        other = os.path.join(self.project, "aidlc", "spaces", "notes.md")
        self.write_file("[Answer]:\n", other)
        self.assertEqual(self.post("Write", {"file_path": other})[1].strip(), "")
        bare = os.path.join(self.tmp, "bare")
        os.makedirs(bare)
        self.assertEqual(self.run_hook({"hook_event_name": "Stop"}, project=bare)[:2], (0, ""))
        self.assertEqual(self.pre("Bash", {"command": "aidlc engine orchestrate next"}, project=bare)[0], 0)

    def test_the_file_needs_answer_tags(self):
        self.write_file("# no tags\n")
        self.assertEqual(self.written()[1].strip(), "")


class TestStop(Case):
    def test_held_until_the_preference_is_recorded(self):
        self.written()
        self.assertEqual(self.stop()["decision"], "block")
        self.script("set", "--value", "never")
        self.assertEqual(self.stop(), {})

    def test_held_while_the_ask_is_owed(self):
        self.script("set", "--value", "ask")
        self.written()
        self.assertIn("ask", self.stop()["reason"])

    def test_form_needs_a_row_and_the_link(self):
        self.script("set", "--value", "always")
        self.written()
        self.assertIn("forms/<id>", self.stop()["reason"])
        self.form_row()
        self.assertIn(f"#{FORM}", self.stop()["reason"])
        self.say(f"The form: {URL}#{FORM}-other")  # another form's link does not count
        self.assertEqual(self.stop()["decision"], "block")
        self.say(f"The form for {REL}: {URL}#{FORM}")
        self.assertEqual(self.stop(), {})

    def test_a_link_in_a_tool_result_or_the_developer_does_not_count(self):
        self.script("set", "--value", "always")
        self.written()
        self.form_row()
        with open(self.transcript, "a") as f:
            f.write(json.dumps({"type": "user", "message": {"content": f"{URL}#{FORM}"}}) + "\n")
        self.assertEqual(self.stop()["decision"], "block")

    def test_a_link_sent_before_the_form_row_does_not_count(self):
        self.script("set", "--value", "always")
        self.written()
        self.say(f"{URL}#{FORM}")
        self.form_row()
        self.assertEqual(self.stop()["decision"], "block")

    def test_the_stop_block_is_bounded(self):
        self.written()
        self.assertEqual(self.stop()["decision"], "block")
        self.assertEqual(self.stop(active=True)["decision"], "block")
        self.assertEqual(self.stop(active=True)["decision"], "block")
        let_through = self.stop(active=True)
        self.assertNotIn("decision", let_through)
        self.assertIn("let through", let_through["systemMessage"])
        # a fresh attempt is held again
        self.assertEqual(self.stop()["decision"], "block")

    def test_release_clears_the_session(self):
        self.written()
        code, out, _ = self.run_hook({"hook_event_name": "UserPromptSubmit", "prompt": "/question-forms:release"})
        self.assertIn("cleared", self.context(out))
        self.assertEqual(self.stop(), {})


class TestAskUserQuestion(Case):
    def test_the_form_link_inside_a_question_is_refused(self):
        self.script("set", "--value", "always")
        self.written()
        self.form_row()
        ask = {"questions": [{"question": f"Look at {URL}#{FORM} and say done?", "options": [{"label": "Done"}]}]}
        code, _, err = self.pre("AskUserQuestion", ask)
        self.assertEqual(code, 2)
        self.assertIn("message of its own", err)
        code, _, _ = self.pre("AskUserQuestion", {"questions": [{"question": "Is the form done?", "options": [{"label": "Done"}]}]})
        self.assertEqual(code, 0)

    def test_the_dialogs_are_not_refused(self):
        code, _, _ = self.pre("AskUserQuestion", {"metadata": {"source": "question-forms:preference"}, "questions": [{"question": "Show?"}]})
        self.assertEqual(code, 0)


class TestEngineGate(Case):
    def opened(self):
        self.script("set", "--value", "always")
        self.written()
        self.form_row()

    def test_next_is_refused_while_tags_are_empty_and_passes_once_copied(self):
        self.opened()
        for cmd in ("aidlc engine orchestrate next", "aidlc engine orchestrate continue", "aidlc engine orchestrate report --result completed"):
            code, _, err = self.pre("Bash", {"command": cmd})
            self.assertEqual(code, 2, cmd)
            self.assertIn("empty [Answer]: tags", err)
        self.write_file(FILLED)
        self.assertEqual(self.pre("Bash", {"command": "aidlc engine orchestrate next"})[0], 0)

    def test_a_stage_flag_scopes_the_refusal(self):
        self.opened()
        self.assertEqual(self.pre("Bash", {"command": "aidlc engine orchestrate report --stage nfr-design --result completed"})[0], 0)
        self.assertEqual(self.pre("Bash", {"command": "aidlc engine orchestrate report --stage functional-design --result completed"})[0], 2)

    def test_edit_choice_and_unopened_forms_are_not_refused(self):
        self.script("set", "--value", "ask")
        self.written()
        self.script("answer", "--file", REL, "--choice", "edit")
        self.assertEqual(self.pre("Bash", {"command": "aidlc engine orchestrate next"})[0], 0)


class TestRecordingIsTheModsAlone(Case):
    def test_bash_and_hand_written_files_are_refused(self):
        for cmd in (f"python3 {SCRIPT} set --value always", f"python3 '{SCRIPT}' answer --file x --choice edit",
                    f"echo '{{}}' > {self.data}/preferences/x.json", f"rm -r {self.data}"):
            self.assertEqual(self.pre("Bash", {"command": cmd})[0], 2, cmd)
        self.assertEqual(self.pre("Bash", {"command": f"python3 {SCRIPT} get"})[0], 0)
        code, _, err = self.pre("Write", {"file_path": os.path.join(self.data, "preferences", "x.json")})
        self.assertEqual(code, 2)
        self.assertIn("never written by hand", err)


class TestWorktree(Case):
    def test_a_worktree_shares_the_main_checkouts_preference(self):
        # the main checkout holds the repository; the worktree's .git file points into it
        gitdir = os.path.join(self.project, ".git", "worktrees", "wt")
        os.makedirs(gitdir)
        with open(os.path.join(gitdir, "commondir"), "w") as f:
            f.write("../..\n")
        tree = os.path.join(self.tmp, "wt")
        os.makedirs(os.path.join(tree, "aidlc", "spaces"))
        with open(os.path.join(tree, ".git"), "w") as f:
            f.write(f"gitdir: {gitdir}\n")
        self.script("set", "--value", "never")  # recorded from the main checkout
        out = self.script("get", project=tree)
        self.assertEqual(json.loads(out.stdout), {"preference": "never"})
        sibling = os.path.join(self.tmp, "other")
        os.makedirs(os.path.join(sibling, "aidlc", "spaces"))
        self.assertEqual(json.loads(self.script("get", project=sibling).stdout), {"preference": None})
        # and the hook in the worktree sees it: nothing pending, nothing held
        os.makedirs(os.path.dirname(os.path.join(tree, REL)))
        self.write_file(OPEN, os.path.join(tree, REL))
        self.assertEqual(self.written(project=tree)[1].strip(), "")


if __name__ == "__main__":
    unittest.main()
