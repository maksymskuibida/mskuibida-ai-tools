# unit-claim

Before a team AI-DLC Unit is claimed, you choose which design stages it runs and how it is approved. You choose
once, in one dialog, and you can save the choice so you are not asked again.

The agent sends two messages before the claim:

1. **Its reasoning, as plain text.** One line per design stage (Functional Design, NFR Requirements, NFR Design,
   Infrastructure Design). Each line is judged against that stage's own `condition:` from the project's stage graph.
2. **One dialog with three questions:**
   - **Stages**: which design stages run. You can pick several. The question line names the agent's pick, and those
     options are marked "(Recommended)".
   - **Rhythm**: `unit-end` (one plan page before the code and one page at the end, through the approval-gates
     plugin) or `per-stage` (an approval after every stage, as today).
   - **Save**: No, For me, or For this project.

The Unit is then claimed with `--rhythm <your choice>`. Each stage you left out is skipped **for that Unit only**,
through the engine's per-Unit conditional skip:

```
aidlc engine orchestrate report --stage <slug> --unit <unit> --result skipped --reason "skipped at claim by the developer"
```

If you pick NFR Design without NFR Requirements, NFR Requirements is added back, and the agent tells you in one line.
Summary confirmation stays a project setting and isn't asked.

```
skills/unit-claim/SKILL.md   the procedure the agent follows before a claim
scripts/claim_choice.py      the stage conditions, the choice in force, saving, the skip commands
hooks/claim_guard.py         the guard (PreToolUse, PostToolUse, UserPromptSubmit; hooks/hooks.json registers it)
```

## Saving a choice

Once a choice is saved, the dialog isn't shown again.

- **For me**: the choice is saved in the plugin's data folder (`$CLAUDE_PLUGIN_DATA/choice.json`, else
  `~/.claude/plugins/data/unit-claim/`). It applies to every project.
- **For this project**: a bookkeeping pull request adds `.unit-claim.json` at the project root. The agent offers to
  run it in its own session:
  - if it runs there, the Unit carries on here with your choice;
  - if it runs here, the agent creates the pull request first, then follows the project's and your own rules for
    after a PR is opened, then offers to continue the Unit.

  A project choice wins over yours.

A saved choice is either a fixed set of stages (what the dialog saves) or `"agent"`, which means "use the agent's
pick for each Unit without asking". The reasoning message is still sent. To set the second form, ask the agent, which
runs `claim_choice.py save --scope me --stages agent --rhythm unit-end`.

## What the hook refuses

- **The claim**: `aidlc unit claim <unit>`, `aidlc --claim <unit>`, or `aidlc-unit.ts claim <unit>`. It is refused
  until that Unit's dialog is answered or a saved choice exists, and also when the command lacks
  `--rhythm <the chosen rhythm>`.
- **The dialog**:
  - while a choice is saved;
  - until a message of the agent since your last prompt names all four design stages;
  - when it is not the three-question shape above.
- **`aidlc engine state unit start`** of a stage the choice leaves out for that Unit. The refusal names the skip
  report to run instead.
- **Saving a choice the developer didn't ask for**: `claim_choice.py save` passes only after "For this project" in the
  dialog (with the same stages and rhythm), or when the developer's last message asks to save. Writing a choice file
  by hand (`.unit-claim.json`, the plugin's data folder) is refused.
- **A claim whose Unit can't be read**, such as options before the Unit that the hook doesn't know.

The hook does nothing outside an AI-DLC project (no `aidlc/spaces`). It never fails an after-call or prompt hook.
The answer of each Unit is kept in the plugin's data folder (`answers/<project>/<intent>/<unit>.json`).
`UNIT_CLAIM_DIR` changes that folder; the tests use it.

## Install

```bash
claude plugin marketplace add maksymskuibida/mskuibida-ai-tools
claude plugin install unit-claim@mskuibida-tooling
```

## Pairs with

- **approval-gates**: under `unit-end`, it builds the plan page and the unit-end page.
- **story-points**: it checks that a Unit is estimated before it is claimed.

## Tests

```bash
python3 -m unittest discover -s plugins/unit-claim/tests
```

They use the Python 3 standard library only.
