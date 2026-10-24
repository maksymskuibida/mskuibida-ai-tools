"""Tests for hooks/claim_guard.py and scripts/claim_choice.py.
Run: python3 -m unittest discover -s plugins/unit-claim/tests

The hook runs as a subprocess, as the harness runs it, with UNIT_CLAIM_DIR and CLAUDE_PROJECT_DIR pointing into a
temporary folder that holds a small AI-DLC project."""

import contextlib
import datetime
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
HOOK = os.path.join(PLUGIN, "hooks", "claim_guard.py")
SCRIPT = os.path.join(PLUGIN, "scripts", "claim_choice.py")
sys.path.insert(0, os.path.join(PLUGIN, "scripts"))
import claim_choice as cc  # noqa: E402

UNIT = "u4-day-navigation"
REASONING = ("- Functional Design: run, the calendar has rules.\n- NFR Requirements: skip, nothing new.\n"
             "- NFR Design: skip, it needs NFR Requirements.\n- Infrastructure Design: skip, nothing changes.")
os.environ.pop("CLAUDE_PROJECT_DIR", None)
os.environ.pop("CLAUDE_PLUGIN_DATA", None)


def dialog(unit=UNIT, picked=("Functional Design",), question=None, multi=True, rhythm=("unit-end", "per-stage"),
           save=("No", "For me", "For this project"), stages=("Functional Design", "NFR Requirements", "NFR Design", "Infrastructure Design")):
    question = question or f"Which design stages should `{unit}` run? I'd run {' and '.join(picked) or 'none of them'}."
    return {"questions": [
        {"question": question, "header": "Stages", "multiSelect": multi,
         "options": [{"label": s + (" (Recommended)" if s in picked else ""), "description": "why"} for s in stages]},
        {"question": "How should this Unit be approved?", "header": "Rhythm", "multiSelect": False,
         "options": [{"label": r, "description": "x"} for r in rhythm]},
        {"question": "Save this choice?", "header": "Save", "multiSelect": False,
         "options": [{"label": s, "description": "x"} for s in save]},
    ]}


def answered(ti, stages, rhythm, save):
    qs = ti["questions"]
    return {"answers": {qs[0]["question"]: stages, qs[1]["question"]: rhythm, qs[2]["question"]: save}}


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.project = os.path.join(self.tmp, "project")
        intents = os.path.join(self.project, "aidlc", "spaces", "default", "intents")
        os.makedirs(os.path.join(intents, "261016-daily-page-mvp"))
        with open(os.path.join(self.project, "aidlc", "active-space"), "w") as f:
            f.write("default\n")
        with open(os.path.join(intents, "active-intent"), "w") as f:
            f.write("261016-daily-page-mvp\n")
        self.data = os.path.join(self.tmp, "data")
        self.transcript = os.path.join(self.tmp, "t.jsonl")
        open(self.transcript, "w").close()
        os.environ["UNIT_CLAIM_DIR"] = self.data
        self.addCleanup(os.environ.pop, "UNIT_CLAIM_DIR", None)

    def run_hook(self, event):
        env = dict(os.environ, UNIT_CLAIM_DIR=self.data, CLAUDE_PROJECT_DIR=self.project)
        event = dict({"transcript_path": self.transcript, "session_id": "s1", "cwd": self.project}, **event)
        done = subprocess.run([sys.executable, HOOK], input=json.dumps(event), capture_output=True, text=True, env=env, timeout=30)
        return done.returncode, done.stdout, done.stderr

    def pre(self, tool, ti):
        return self.run_hook({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": ti})

    def post(self, tool, ti, response):
        return self.run_hook({"hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": ti, "tool_response": response})

    def said(self, text, kind="assistant"):
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        content = [{"type": "text", "text": text}]
        with open(self.transcript, "a") as f:
            f.write(json.dumps({"type": kind, "timestamp": stamp, "message": {"role": kind, "content": content}}) + "\n")

    def context(self, out):
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]

    def answer(self, stages="Functional Design (Recommended)", rhythm="unit-end", save="No", ti=None):
        ti = ti or dialog()
        self.said(REASONING)
        code, _out, err = self.pre("AskUserQuestion", ti)
        self.assertEqual(code, 0, err)
        code, out, err = self.post("AskUserQuestion", ti, answered(ti, stages, rhythm, save))
        self.assertEqual(code, 0, err)
        return self.context(out)

    def claim(self, extra=" --rhythm unit-end", unit=UNIT):
        return self.pre("Bash", {"command": f"aidlc unit claim {unit} --team A{extra}"})


class TestClaimIsGated(Case):
    def test_claim_refused_until_the_dialog_is_answered(self):
        code, _out, err = self.claim()
        self.assertEqual(code, 2)
        self.assertIn("unit-claim skill", err)
        self.answer()
        code, _out, err = self.claim()
        self.assertEqual(code, 0, err)

    def test_options_before_the_unit_and_the_equals_form(self):
        for cmd in (f"aidlc --claim={UNIT} --team A", f"aidlc unit claim --force {UNIT}", f"aidlc unit claim --team A --rhythm unit-end {UNIT}"):
            code, _out, err = self.pre("Bash", {"command": cmd})
            self.assertEqual(code, 2, cmd)
            self.assertIn(f"Before {UNIT} is claimed", err, cmd)
        code, _out, err = self.pre("Bash", {"command": "aidlc unit claim --team A"})
        self.assertEqual(code, 2)
        self.assertIn("names no Unit", err)

    def test_every_spelling_of_the_claim(self):
        for cmd in (f"aidlc unit claim {UNIT}", f"cd x && aidlc --claim {UNIT} --team A", f"bun .claude/tools/aidlc-unit.ts claim {UNIT}",
                    f"/usr/local/bin/aidlc unit claim --team A {UNIT}"):
            code, _out, err = self.pre("Bash", {"command": cmd})
            self.assertEqual(code, 2, cmd)
            self.assertIn(f"Before {UNIT} is claimed", err, cmd)
        for cmd in ("aidlc unit claim --help", "aidlc unit status", "git log --grep claim", "aidlc engine orchestrate next"):
            code, _out, err = self.pre("Bash", {"command": cmd})
            self.assertEqual(code, 0, cmd + err)

    def test_the_claim_carries_the_chosen_rhythm(self):
        self.answer(rhythm="per-stage")
        code, _out, err = self.claim("")
        self.assertEqual(code, 2)
        self.assertIn("--rhythm per-stage", err)
        code, _out, err = self.claim(" --rhythm unit-end")
        self.assertEqual(code, 2)
        self.assertIn("not unit-end", err)
        self.assertEqual(self.claim(" --rhythm per-stage")[0], 0)
        self.assertEqual(self.claim(" --rhythm=per-stage")[0], 0)

    def test_another_unit_is_still_gated(self):
        self.answer()
        self.assertEqual(self.claim(unit="u5-live-updates")[0], 2)

    def test_outside_an_aidlc_project_nothing_is_checked(self):
        shutil.rmtree(os.path.join(self.project, "aidlc"))
        os.makedirs(os.path.join(self.project, "x"))
        self.assertEqual(self.claim()[0], 0)


class TestDialog(Case):
    def test_reasoning_comes_first(self):
        code, _out, err = self.pre("AskUserQuestion", dialog())
        self.assertEqual(code, 2)
        self.assertIn("reasoning first", err)
        self.said("- Functional Design: run.\n- NFR Requirements: skip.")  # two of four
        self.assertEqual(self.pre("AskUserQuestion", dialog())[0], 2)
        self.said(REASONING)
        self.assertEqual(self.pre("AskUserQuestion", dialog())[0], 0)

    def test_reasoning_from_before_the_last_prompt_does_not_count(self):
        self.said(REASONING)
        self.said("claim u4", kind="user")
        self.assertEqual(self.pre("AskUserQuestion", dialog())[0], 2)

    def test_the_dialog_shape(self):
        self.said(REASONING)
        bad = [
            dialog(multi=False),
            dialog(question="Which design stages should this Unit run? I'd run Functional Design."),
            dialog(question="Which design stages should `u4` run?"),  # the pick is not named
            dialog(rhythm=("one", "two")),
            dialog(save=("No", "Yes")),
            dialog(stages=("Functional Design", "NFR Requirements", "NFR Design")),
            {"questions": dialog()["questions"][:2]},
        ]
        for ti in bad:
            code, _out, err = self.pre("AskUserQuestion", ti)
            self.assertEqual(code, 2, json.dumps(ti)[:200])
        self.assertEqual(self.pre("AskUserQuestion", dialog(picked=()))[0], 0, "no pick is a pick")

    def test_a_saved_choice_is_not_asked_again(self):
        self.answer(save="For me")
        self.said(REASONING)
        code, _out, err = self.pre("AskUserQuestion", dialog(unit="u5-live-updates"))
        self.assertEqual(code, 2)
        self.assertIn("not shown again", err)
        code, _out, err = self.claim(unit="u5-live-updates")
        self.assertEqual(code, 0, err)

    def test_other_questions_pass(self):
        ti = {"questions": [{"question": "Approve?", "header": "Approval", "options": [{"label": "Approve", "description": "x"}, {"label": "No", "description": "y"}]}]}
        self.assertEqual(self.pre("AskUserQuestion", ti)[0], 0)
        self.assertEqual(self.post("AskUserQuestion", ti, {"answers": {"Approve?": "Approve"}})[1], "")


class TestAnswer(Case):
    def test_answer_is_recorded(self):
        said = self.answer("Functional Design (Recommended), Infrastructure Design", "unit-end (Recommended)", "No")
        self.assertIn("Functional Design, Infrastructure Design", said)
        self.assertIn("--rhythm unit-end", said)
        choice = cc.choice_for(self.project, UNIT)
        self.assertEqual((choice["stages"], choice["rhythm"], choice["source"]), (["functional-design", "infrastructure-design"], "unit-end", "answer"))
        self.assertIsNone(cc.saved_choice(self.project)[0])

    def test_nfr_design_brings_nfr_requirements_back(self):
        said = self.answer("Functional Design, NFR Design")
        self.assertIn("NFR Requirements was added back: NFR Design needs it.", said)
        self.assertEqual(cc.choice_for(self.project, UNIT)["stages"], ["functional-design", "nfr-requirements", "nfr-design"])

    def test_save_for_me(self):
        said = self.answer(save="For me")
        self.assertIn("not shown again", said)
        with open(os.path.join(self.data, "choice.json")) as f:
            self.assertEqual(json.load(f)["stages"], ["functional-design"])
        self.assertEqual(cc.choice_for(self.project, "u9-other")["source"], "me")

    def test_save_for_the_project_points_to_the_bookkeeping_pull_request(self):
        said = self.answer(save="For this project")
        self.assertIn("bookkeeping pull request", said)
        self.assertIn("save --scope project --stages functional-design --rhythm unit-end", said)
        self.assertFalse(os.path.exists(os.path.join(self.project, ".unit-claim.json")), "the file lands through the pull request")
        self.assertEqual(self.claim()[0], 0, "the Unit carries on with the choice")

    def test_a_typed_answer(self):
        self.answer("none", "per-stage", "No")
        self.assertEqual(cc.choice_for(self.project, UNIT)["stages"], [])

    def test_an_answer_that_cannot_be_read(self):
        ti = dialog()
        self.said(REASONING)
        _code, out, _err = self.post("AskUserQuestion", ti, answered(ti, "only the important ones", "unit-end", "No"))
        self.assertIn("could not be read", self.context(out))
        self.assertIsNone(cc.choice_for(self.project, UNIT))

    def test_the_text_form_of_the_answer(self):
        ti = dialog()
        q = ti["questions"]
        text = f'User has answered your questions: "{q[0]["question"]}"="Functional Design", "{q[1]["question"]}"="unit-end", "{q[2]["question"]}"="No". You can now continue.'
        self.post("AskUserQuestion", ti, text)
        self.assertEqual(cc.choice_for(self.project, UNIT)["rhythm"], "unit-end")


class TestSaving(Case):
    def save_cmd(self, scope="me", stages="none", rhythm="per-stage"):
        return {"command": f'python3 "{SCRIPT}" save --scope {scope} --stages {stages} --rhythm {rhythm}'}

    def test_the_agent_cannot_save_on_its_own(self):
        self.said("claim u4", kind="user")
        for scope in ("me", "project"):
            code, _out, err = self.pre("Bash", self.save_cmd(scope))
            self.assertEqual(code, 2, scope)
        for path in (os.path.join(self.project, ".unit-claim.json"), os.path.join(self.data, "choice.json"),
                     os.path.join(self.data, "answers", "x", "y", f"{UNIT}.json")):
            self.assertEqual(self.pre("Write", {"file_path": path, "content": "{}"})[0], 2, path)
        self.assertEqual(self.pre("Write", {"file_path": os.path.join(self.project, "notes.md"), "content": "x"})[0], 0)

    def test_the_developer_asking_allows_it(self):
        self.said("please save my claim choice: no design stages, per-stage", kind="user")
        self.assertEqual(self.pre("Bash", self.save_cmd())[0], 0)

    def test_for_this_project_allows_exactly_that_answer(self):
        self.answer("Functional Design", "unit-end", "For this project")
        self.said("go on", kind="user")
        self.assertEqual(self.pre("Bash", self.save_cmd("project", "functional-design", "unit-end"))[0], 0)
        self.assertEqual(self.pre("Bash", self.save_cmd("project", "none", "unit-end"))[0], 2)


class TestAfterTheClaim(Case):
    def test_skips_are_named_after_the_claim(self):
        self.answer()
        _code, out, _err = self.post("Bash", {"command": f"aidlc unit claim {UNIT} --team A --rhythm unit-end"}, {"stdout": "claimed"})
        said = self.context(out)
        for slug in ("nfr-requirements", "nfr-design", "infrastructure-design"):
            self.assertIn(f'--stage {slug} --unit {UNIT} --result skipped --reason "skipped at claim by the developer"', said)
        self.assertNotIn("--stage functional-design", said)

    def test_a_left_out_stage_cannot_start(self):
        self.answer()
        code, _out, err = self.pre("Bash", {"command": f"aidlc engine state unit start --stage nfr-design --unit {UNIT}"})
        self.assertEqual(code, 2)
        self.assertIn("--result skipped", err)
        code, _out, err = self.pre("Bash", {"command": f"aidlc engine state unit start --stage functional-design --unit {UNIT}"})
        self.assertEqual(code, 0, err)
        code, _out, err = self.pre("Bash", {"command": f"aidlc engine state unit start --stage nfr-design --unit u5-other"})
        self.assertEqual(code, 0, err)


class TestPrompt(Case):
    def test_claim_prompt_points_to_the_skill(self):
        _code, out, _err = self.run_hook({"hook_event_name": "UserPromptSubmit", "prompt": f"/aidlc --claim {UNIT} --team A"})
        self.assertIn("unit-claim skill", self.context(out))

    def test_claim_prompt_with_a_saved_choice(self):
        with contextlib.redirect_stdout(io.StringIO()):
            cc.main(["save", "--scope", "project", "--stages", "functional-design,nfr-design", "--rhythm", "unit-end", "--project-dir", self.project])
        _code, out, _err = self.run_hook({"hook_event_name": "UserPromptSubmit", "prompt": f"/aidlc --claim {UNIT}"})
        said = self.context(out)
        self.assertIn("(project)", said)
        self.assertIn("Functional Design, NFR Requirements, NFR Design", said)

    def test_other_prompts(self):
        _code, out, _err = self.run_hook({"hook_event_name": "UserPromptSubmit", "prompt": "what is a claim?"})
        self.assertEqual(out, "")


class TestScript(Case):
    def run_script(self, *args):
        env = dict(os.environ, UNIT_CLAIM_DIR=self.data)
        return subprocess.run([sys.executable, SCRIPT, *args, "--project-dir", self.project], capture_output=True, text=True, env=env)

    def test_stages_reads_the_conditions_from_the_graph(self):
        done = self.run_script("stages")
        self.assertEqual([s["slug"] for s in json.loads(done.stdout)], list(cc.DESIGN_STAGES))
        self.assertIn("Skip if NFR Requirements was skipped", done.stdout)
        os.makedirs(os.path.join(self.project, ".claude", "tools", "data"))
        with open(os.path.join(self.project, ".claude", "tools", "data", "stage-graph.json"), "w") as f:
            json.dump([{"slug": "nfr-design", "name": "NFR Design", "condition": "From the graph."}], f)
        self.assertIn("From the graph.", self.run_script("stages").stdout)

    def test_project_choice_wins_over_mine(self):
        self.run_script("save", "--scope", "me", "--stages", "none", "--rhythm", "per-stage")
        self.assertEqual(json.loads(self.run_script("status", "--unit", UNIT).stdout)["choice"]["source"], "me")
        self.run_script("save", "--scope", "project", "--stages", "nfr-design", "--rhythm", "unit-end")
        status = json.loads(self.run_script("status", "--unit", UNIT).stdout)
        self.assertEqual((status["choice"]["source"], status["choice"]["stages"]), ("project", ["nfr-requirements", "nfr-design"]))

    def test_agent_pick_only_with_a_saved_agent_choice(self):
        done = self.run_script("pick", "--unit", UNIT, "--stages", "functional-design")
        self.assertEqual(done.returncode, 1)
        self.assertIn("ask the claim dialog", done.stderr)
        self.run_script("save", "--scope", "me", "--stages", "agent", "--rhythm", "unit-end")
        status = json.loads(self.run_script("status", "--unit", UNIT).stdout)
        self.assertEqual((status["agentPick"], status["ask"]), (True, False))
        self.assertEqual(self.claim()[0], 2)
        done = self.run_script("pick", "--unit", UNIT, "--stages", "functional-design")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.claim()[0], 0)

    def test_skips_and_forget(self):
        self.answer("Functional Design, NFR Requirements")
        lines = self.run_script("skips", "--unit", UNIT).stdout.splitlines()
        self.assertEqual(len(lines), 2)
        self.run_script("forget", "--unit", UNIT)
        self.assertIsNone(cc.choice_for(self.project, UNIT))

    def test_parsing(self):
        self.assertEqual(cc.parse_stages("NFR Design (Recommended), functional design"), ["functional-design", "nfr-design"])
        self.assertEqual(cc.parse_stages(["Infrastructure Design"]), ["infrastructure-design"])
        self.assertIsNone(cc.parse_stages("Functional Design, Security"))
        self.assertEqual(cc.parse_rhythm("unit-end (Recommended)"), "unit-end")
        self.assertEqual(cc.parse_save("For this project"), "project")
        self.assertEqual(cc.with_needs(["nfr-design"])[0], ["nfr-requirements", "nfr-design"])


class TestHooksJson(unittest.TestCase):
    def test_events_and_matchers(self):
        with open(os.path.join(PLUGIN, "hooks", "hooks.json")) as f:
            hooks = json.load(f)["hooks"]
        self.assertEqual(set(hooks), {"PreToolUse", "PostToolUse", "UserPromptSubmit"})
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "Bash|AskUserQuestion|Write|Edit|MultiEdit")
        self.assertEqual(hooks["PostToolUse"][0]["matcher"], "Bash|AskUserQuestion")
        for entries in hooks.values():
            self.assertIn("claim_guard.py", entries[0]["hooks"][0]["command"])


if __name__ == "__main__":
    unittest.main()
