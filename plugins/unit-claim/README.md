# unit-claim

Before a team AI-DLC Unit is claimed, you choose which design stages it runs and how it is approved. You choose in
one dialog, with a recommendation for each stage shown above it.

The agent opens the dialog, and the plugin's mod fills it in:

- **Above the dialog**: suggested design stages. A model (Sonnet by default) reads the Unit's entry in
  `unit-of-work.md`, its stories and each stage's own `condition:` from the project's stage graph. It splits the four
  stages (Functional Design, NFR Requirements, NFR Design, Infrastructure Design) into **Recommended stages** and
  **Skip these**, with a reason under each.
- **Stages**: "Suggested stages", "All four stages", or type your own under Other.
- **Rhythm**: the rhythms the project's pinned engine accepts (`aidlc unit claim --help`): today `unit-end` (one plan
  page before the code and one page at the end, through the approval-gates plugin) and `per-stage` (an approval after
  every stage). No default is picked for you.

What you type under Other is read by a second model (Haiku by default), so typos and short forms work ("funtional
desgn, nfr reqs", "infra", "per stag"). An answer that names something that isn't a stage or rhythm, or names a stage
twice, is refused. The refusal and a suggestion of what you probably meant are shown above the same two questions,
asked again.

The Unit is then claimed with `--rhythm <your choice> --skip-stages <the stages you left out>`. The claim itself
skips those stages **for that Unit only**, and the Unit starts at its first stage that runs. This needs AI-DLC engine
2.11.2-preview.20261026.101 or later. The plugin reads the claim's usage line from the project's own harness
(`.claude/tools/aidlc-unit.ts`) to tell. On an older engine the Unit is claimed with `--rhythm` alone, and each
left-out stage is skipped when the engine's directive reaches it:

```
aidlc engine orchestrate report --stage <slug> --unit <unit> --result skipped --reason "skipped at claim by the developer"
```

If you pick NFR Design without NFR Requirements, NFR Requirements is added back, and the agent tells you in one line.
Nothing is saved across Units or claims: every claim asks. Your answer is used by the claim it was given for; once that
claim goes through, the answer is marked used, and claiming the same Unit again later (after a release, or from another
session) shows the dialog again.

```
hooks/register.tsx           the mod: the dialog's questions, the recommendation above it, reading typed answers, recording
hooks/claim_guard.py         the guard (PreToolUse, PostToolUse, UserPromptSubmit)
hooks/hooks.json             registers both
scripts/claim_choice.py      the stage conditions, the Unit's brief, the recorded answer, what the engine takes at a claim, the claim's flags
skills/unit-claim/SKILL.md   the procedure the agent follows before a claim
```

## How the dialog is opened

A mod can ask only one question at a time on its own (`$.ui.ask`); `AskUserQuestion` is the model's. So the agent
calls `AskUserQuestion` with `metadata.source` set to `unit-claim:<unit>` and a placeholder question. The mod catches
that call, puts its two questions in, and draws the recommendation (or a refusal) above the dialog. Once you have
answered, it records the answer with `claim_choice.py record` and adds one line for the agent: either recorded and
claim with `--rhythm`, or refused and ask again. Nothing reads the session transcript.

## What the hook refuses

- **The claim**: `aidlc unit claim <unit>`, `aidlc --claim <unit>`, or `aidlc-unit.ts claim <unit>`. It is refused
  until that Unit has a recorded answer, and also when its `--rhythm` or `--skip-stages` differs from the answer (an
  engine without `--skip-stages` takes `--rhythm` alone). The refusal
  tells the agent how to open the dialog.
- **Recording an answer by the agent**: `claim_choice.py record` from Bash, and writing an answer file by hand. An
  answer is recorded only by the mod, after you answer.
- **`aidlc engine state unit start`** of a stage the choice leaves out for that Unit. The refusal names the skip
  report to run instead.
- **A claim whose Unit can't be read**, such as options before the Unit that the hook doesn't know.

The hook does nothing outside an AI-DLC project (no `aidlc/spaces`). It never fails an after-call or prompt hook.
The answer of each Unit is kept in `~/.claude/plugins/data/unit-claim/answers/<project>/<intent>/<unit>.json`, the
project being the main checkout, so a git worktree and its main checkout share one answer. `UNIT_CLAIM_DIR` changes
that folder; the tests use it.

## Settings

| Setting | Default | What it does |
|---|---|---|
| Recommendation model (`recommendModel`) | `claude-sonnet-5-5` | Writes the run or skip recommendation and a reason per stage |
| Answer resolver model (`resolveModel`) | `claude-haiku-5-5` | Reads stage names or a rhythm you typed under Other |

## Install

```bash
claude plugin marketplace add maksymskuibida/mskuibida-ai-tools
claude plugin install unit-claim@mskuibida-tooling
```

The dialog needs a Claude Code build that loads plugin mods (`"modules"` in `hooks/hooks.json`). Without the mod, the
hook still refuses the claim, but nothing fills in the dialog.

## Pairs with

- **approval-gates**: under `unit-end`, it builds the plan page and the unit-end page.
- **story-points**: it checks that a Unit is estimated before it is claimed.

## Tests

```bash
python3 -m unittest discover -s plugins/unit-claim/tests
claude plugin test plugins/unit-claim
```

The first covers the hook and the script, with the Python 3 standard library only. The second runs the mod's tests
(`tests/dialog.test.ts`) against the engine, with the dialog, the processes and the two models stood in for.

The engine ignores `--help`/`-h` on `unit claim <unit>` and claims for real, so the hook checks such a command like any claim; read the help with `aidlc unit claim --help` (no Unit). A claim that went through with a rhythm or skipped stages other than the chosen ones is flagged after the fact.
