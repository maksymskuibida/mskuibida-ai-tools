"""Tests for hooks/claim_guard.py and scripts/claim_choice.py.
Run: python3 -m unittest discover -s plugins/unit-claim/tests

The hook runs as a subprocess, as the harness runs it, with UNIT_CLAIM_DIR and CLAUDE_PROJECT_DIR pointing into a
temporary folder that holds a small AI-DLC project. The claim dialog itself is the mod's (hooks/register.tsx); here an
answer is recorded the way the mod records it, with `claim_choice.py record`."""

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
INTENT = "261016-daily-page-mvp"
os.environ.pop("CLAUDE_PROJECT_DIR", None)
os.environ.pop("CLAUDE_PLUGIN_DATA", None)

UNIT_OF_WORK = f"""# Units of Work

## Unit details

### U4 — {UNIT}

- **What it delivers:** Day navigation: previous and next day, a month picker.
- **Stories:** US2.1, US2.3

### U5 — u5-live-updates

- **What it delivers:** Live updates.
"""

STORIES = """# Stories

## US2.1 — Go to the next day
As a user I move one day forward.

## US2.2 — Not this one
Unrelated.

## US2.3 — Pick a month
As a user I jump to a month.
"""


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.project = os.path.join(self.tmp, "project")
        intents = os.path.join(self.project, "aidlc", "spaces", "default", "intents")
        inception = os.path.join(intents, INTENT, "inception")
        os.makedirs(os.path.join(inception, "units-generation"))
        os.makedirs(os.path.join(inception, "user-stories"))
        with open(os.path.join(self.project, "aidlc", "active-space"), "w") as f:
            f.write("default\n")
        with open(os.path.join(intents, "active-intent"), "w") as f:
            f.write(INTENT + "\n")
        with open(os.path.join(inception, "units-generation", "unit-of-work.md"), "w") as f:
            f.write(UNIT_OF_WORK)
        with open(os.path.join(inception, "user-stories", "stories.md"), "w") as f:
            f.write(STORIES)
        self.data = os.path.join(self.tmp, "data")
        os.environ["UNIT_CLAIM_DIR"] = self.data
        self.addCleanup(os.environ.pop, "UNIT_CLAIM_DIR", None)

    def run_hook(self, event):
        env = dict(os.environ, UNIT_CLAIM_DIR=self.data, CLAUDE_PROJECT_DIR=self.project)
        event = dict({"session_id": "s1", "cwd": self.project}, **event)
        done = subprocess.run([sys.executable, HOOK], input=json.dumps(event), capture_output=True, text=True, env=env, timeout=30)
        return done.returncode, done.stdout, done.stderr

    def run_script(self, *args):
        env = dict(os.environ, UNIT_CLAIM_DIR=self.data)
        return subprocess.run([sys.executable, SCRIPT, *args, "--project-dir", self.project], capture_output=True, text=True, env=env)

    def pre(self, tool, ti):
        return self.run_hook({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": ti})

    def post(self, tool, ti, response):
        return self.run_hook({"hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": ti, "tool_response": response})

    def context(self, out):
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]

    def answer(self, stages="functional-design", rhythm="unit-end", unit=UNIT):
        """Record an answer as the mod does after the claim dialog."""
        done = self.run_script("record", "--unit", unit, "--stages", stages, "--rhythm", rhythm)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def claim(self, extra=" --rhythm unit-end", unit=UNIT):
        return self.pre("Bash", {"command": f"aidlc unit claim {unit} --team A{extra}"})


class TestClaimIsGated(Case):
    def test_claim_refused_until_the_dialog_is_answered(self):
        code, _out, err = self.claim()
        self.assertEqual(code, 2)
        self.assertIn(f'"source": "unit-claim:{UNIT}"', err)
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


class TestTheAnswerIsTheDevelopers(Case):
    def test_the_agent_cannot_record_an_answer(self):
        for cmd in (f"python3 {SCRIPT} record --unit {UNIT} --stages none --rhythm unit-end",
                    f"cd x && python3 scripts/claim_choice.py record --unit {UNIT} --stages none --rhythm per-stage"):
            code, _out, err = self.pre("Bash", {"command": cmd})
            self.assertEqual(code, 2, cmd)
            self.assertIn("unit-claim mod", err)
        code, _out, err = self.pre("Bash", {"command": f"python3 {SCRIPT} status --unit {UNIT}"})
        self.assertEqual(code, 0, err)

    def test_an_answer_file_is_not_written_by_hand(self):
        code, _out, err = self.pre("Write", {"file_path": os.path.join(self.data, "answers", "x", f"{UNIT}.json"), "content": "{}"})
        self.assertEqual(code, 2)
        self.assertIn("never written by hand", err)
        code, _out, err = self.pre("Write", {"file_path": os.path.join(self.project, "notes.md"), "content": "x"})
        self.assertEqual(code, 0, err)

    def test_the_dialog_is_not_checked_by_the_hook(self):
        code, _out, err = self.pre("AskUserQuestion", {"questions": [{"question": "Anything?", "header": "Stages", "options": []}]})
        self.assertEqual(code, 0, err)


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


class TestWorktrees(Case):
    """A session in a git worktree may have its hooks run from the main checkout and its mod's processes from the
    worktree; both must find the same answer. A worktree also lacks the gitignored cursors (active-space,
    active-intent)."""

    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.project, ".git", "worktrees", "wt"))
        self.worktree = os.path.join(self.project, ".claude", "worktrees", "wt")
        os.makedirs(os.path.join(self.worktree, "aidlc", "spaces", "default", "intents", INTENT))
        with open(os.path.join(self.worktree, ".git"), "w") as f:
            f.write(f"gitdir: {os.path.join(self.project, '.git', 'worktrees', 'wt')}\n")
        with open(os.path.join(self.project, ".git", "worktrees", "wt", "commondir"), "w") as f:
            f.write("../..\n")

    def record_in_worktree(self):
        env = dict(os.environ)  # as the mod starts it: no CLAUDE_PLUGIN_DATA
        env.pop("CLAUDE_PLUGIN_DATA", None)
        done = subprocess.run([sys.executable, SCRIPT, "record", "--unit", UNIT, "--stages", "functional-design",
                               "--rhythm", "unit-end"], capture_output=True, text=True, env=env, cwd=self.worktree)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_an_answer_recorded_in_the_worktree_lets_the_main_checkout_claim(self):
        self.record_in_worktree()
        self.assertEqual(cc.intent_of(self.worktree), INTENT)
        self.assertEqual(cc.answer_path(self.worktree, UNIT), cc.answer_path(self.project, UNIT))
        code, _out, err = self.claim()
        self.assertEqual(code, 0, err)
        code, _out, err = self.run_hook({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.worktree,
                                         "tool_input": {"command": f"aidlc unit claim {UNIT} --team A --rhythm unit-end"}})
        self.assertEqual(code, 0, err)

    def test_the_plugin_data_folder_the_hook_is_given_does_not_split_the_answers(self):
        os.environ.pop("UNIT_CLAIM_DIR")
        os.environ["HOME"], home = self.tmp, os.environ.get("HOME", "")
        self.addCleanup(os.environ.__setitem__, "HOME", home)
        self.record_in_worktree()
        env = dict(os.environ, CLAUDE_PLUGIN_DATA=os.path.join(self.tmp, "elsewhere"), CLAUDE_PROJECT_DIR=self.project)
        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": self.project,
                 "tool_input": {"command": f"aidlc unit claim {UNIT} --team A --rhythm unit-end"}}
        done = subprocess.run([sys.executable, HOOK], input=json.dumps(event), capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)


class TestSkipStagesAtClaim(Case):
    """An engine whose claim takes --skip-stages (2.11.2-preview.20261026.101 on): the claim carries exactly the stages
    the developer left out, and they are skipped by the claim itself."""

    USAGE = ("Usage: aidlc-unit claim <unit> [--team <label>] [--rhythm per-stage|unit-end] "
             "[--skip-stages <stage[,stage...]>]")

    def setUp(self):
        super().setUp()
        tools = os.path.join(self.project, ".claude", "tools")
        os.makedirs(tools)
        with open(os.path.join(tools, "aidlc-unit.ts"), "w") as f:
            f.write(f'  if (!unit) fail("{self.USAGE}");\n')

    def test_the_engine_is_read_from_the_harness(self):
        eng = json.loads(self.run_script("engine").stdout)
        self.assertEqual((eng["rhythms"], eng["skipStages"]), (["per-stage", "unit-end"], True))

    def test_the_claim_carries_exactly_the_left_out_stages(self):
        got = self.answer("functional-design")
        self.assertEqual(got["claimFlags"], "--rhythm unit-end --skip-stages nfr-requirements,nfr-design,infrastructure-design")
        self.assertEqual(got["skips"], [])
        code, _out, err = self.claim()
        self.assertEqual(code, 2)
        self.assertIn("--skip-stages nfr-requirements,nfr-design,infrastructure-design", err)
        code, _out, err = self.claim(" --rhythm unit-end --skip-stages nfr-requirements,infrastructure-design")
        self.assertEqual(code, 2)
        self.assertIn("not --skip-stages nfr-requirements,infrastructure-design", err)
        self.assertEqual(self.claim(" --rhythm unit-end --skip-stages infrastructure-design,nfr-design,nfr-requirements")[0], 0)
        self.assertEqual(self.claim(" --rhythm=unit-end --skip-stages=nfr-requirements,nfr-design,infrastructure-design")[0], 0)

    def test_every_stage_runs_so_no_flag(self):
        self.answer("functional-design,nfr-requirements,nfr-design,infrastructure-design")
        self.assertEqual(self.claim()[0], 0)
        code, _out, err = self.claim(" --rhythm unit-end --skip-stages nfr-design")
        self.assertEqual(code, 2)
        self.assertIn("its flags are `--rhythm unit-end`", err)

    def test_after_the_claim_and_a_skipped_stages_start(self):
        self.answer("functional-design")
        cmd = f"aidlc unit claim {UNIT} --team A --rhythm unit-end --skip-stages nfr-requirements,nfr-design,infrastructure-design"
        _code, out, _err = self.post("Bash", {"command": cmd}, {"stdout": "claimed"})
        said = self.context(out)
        self.assertIn("NFR Requirements, NFR Design, Infrastructure Design are skipped for this Unit only", said)
        self.assertIn("aidlc engine orchestrate next", said)
        self.assertNotIn("--result skipped", said)
        code, _out, err = self.pre("Bash", {"command": f"aidlc engine state unit start --stage nfr-design --unit {UNIT}"})
        self.assertEqual(code, 2)
        self.assertIn("skipped at the claim", err)

    def test_status_and_the_prompt_name_the_flags(self):
        self.answer("functional-design,nfr-requirements")
        status = json.loads(self.run_script("status", "--unit", UNIT).stdout)
        self.assertEqual(status["claimFlags"], "--rhythm unit-end --skip-stages nfr-design,infrastructure-design")
        _code, out, _err = self.run_hook({"hook_event_name": "UserPromptSubmit", "prompt": f"/aidlc --claim {UNIT}"})
        self.assertIn("`--rhythm unit-end --skip-stages nfr-design,infrastructure-design`", self.context(out))


class TestOlderEngine(Case):
    def test_an_engine_without_the_flag_refuses_it_and_keeps_the_per_stage_reports(self):
        got = self.answer("functional-design")
        self.assertEqual(got["claimFlags"], "--rhythm unit-end")
        self.assertEqual(len(got["skips"]), 3)
        code, _out, err = self.claim(" --rhythm unit-end --skip-stages nfr-requirements,nfr-design,infrastructure-design")
        self.assertEqual(code, 2)
        self.assertIn("has no `--skip-stages`", err)
        self.assertEqual(self.claim()[0], 0)


class TestPrompt(Case):
    def test_claim_prompt_says_how_to_open_the_dialog(self):
        _code, out, _err = self.run_hook({"hook_event_name": "UserPromptSubmit", "prompt": f"/aidlc --claim {UNIT} --team A"})
        self.assertIn(f'"source": "unit-claim:{UNIT}"', self.context(out))

    def test_claim_prompt_with_a_recorded_answer(self):
        self.answer("functional-design,nfr-design")
        _code, out, _err = self.run_hook({"hook_event_name": "UserPromptSubmit", "prompt": f"/aidlc --claim {UNIT}"})
        said = self.context(out)
        self.assertIn("Functional Design, NFR Requirements, NFR Design", said)
        self.assertIn("--rhythm unit-end", said)

    def test_other_prompts(self):
        _code, out, _err = self.run_hook({"hook_event_name": "UserPromptSubmit", "prompt": "what is a claim?"})
        self.assertEqual(out, "")


class TestScript(Case):
    def test_stages_reads_the_conditions_from_the_graph(self):
        done = self.run_script("stages")
        self.assertEqual([s["slug"] for s in json.loads(done.stdout)], list(cc.DESIGN_STAGES))
        self.assertIn("Skip if NFR Requirements was skipped", done.stdout)
        os.makedirs(os.path.join(self.project, ".claude", "tools", "data"))
        with open(os.path.join(self.project, ".claude", "tools", "data", "stage-graph.json"), "w") as f:
            json.dump([{"slug": "nfr-design", "name": "NFR Design", "condition": "From the graph."}], f)
        self.assertIn("From the graph.", self.run_script("stages").stdout)

    def test_brief_holds_the_unit_and_its_stories(self):
        brief = json.loads(self.run_script("brief", "--unit", UNIT).stdout)
        self.assertTrue(brief["entry"].startswith(f"### U4 — {UNIT}"))
        self.assertNotIn("u5-live-updates", brief["entry"])
        self.assertEqual([s.splitlines()[0] for s in brief["stories"]], ["## US2.1 — Go to the next day", "## US2.3 — Pick a month"])
        self.assertEqual(len(brief["stages"]), 4)

    def test_record_status_and_needs(self):
        self.assertIsNone(json.loads(self.run_script("status", "--unit", UNIT).stdout)["choice"])
        got = self.answer("nfr-design", "per-stage")
        self.assertEqual(got["choice"]["stages"], ["nfr-requirements", "nfr-design"])
        self.assertIn("NFR Requirements was added back", got["notes"][0])
        status = json.loads(self.run_script("status", "--unit", UNIT).stdout)["choice"]
        self.assertEqual((status["stages"], status["rhythm"]), (["nfr-requirements", "nfr-design"], "per-stage"))
        done = self.run_script("record", "--unit", UNIT, "--stages", "security", "--rhythm", "unit-end")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.run_script("record", "--unit", UNIT, "--stages", "none", "--rhythm", "weekly").returncode, 2)

    def test_skips_and_forget(self):
        self.answer("functional-design,nfr-requirements")
        lines = self.run_script("skips", "--unit", UNIT).stdout.splitlines()
        self.assertEqual(len(lines), 2)
        self.run_script("forget", "--unit", UNIT)
        self.assertIsNone(cc.choice_for(self.project, UNIT))

    def test_parsing(self):
        self.assertEqual(cc.parse_stages("nfr-design, functional design"), ["functional-design", "nfr-design"])
        self.assertEqual(cc.parse_stages("none"), [])
        self.assertIsNone(cc.parse_stages("functional-design, security"))
        self.assertEqual(cc.with_needs(["nfr-design"])[0], ["nfr-requirements", "nfr-design"])


class TestHooksJson(unittest.TestCase):
    def test_events_matchers_and_the_mod(self):
        with open(os.path.join(PLUGIN, "hooks", "hooks.json")) as f:
            config = json.load(f)
        self.assertEqual(config["modules"], ["./register.tsx"])
        hooks = config["hooks"]
        self.assertEqual(set(hooks), {"PreToolUse", "PostToolUse", "UserPromptSubmit"})
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "Bash|Write|Edit|MultiEdit")
        self.assertEqual(hooks["PostToolUse"][0]["matcher"], "Bash")
        for entries in hooks.values():
            self.assertIn("claim_guard.py", entries[0]["hooks"][0]["command"])


if __name__ == "__main__":
    unittest.main()
