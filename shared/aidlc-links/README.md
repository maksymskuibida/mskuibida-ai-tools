# aidlc-links: the registry of the pages and forms published for each stage

The project panel shows, under each AI-DLC stage, the links to the pages made for it: gate pages, unit plan and
unit-end pages, test plans, questions forms. Which page belongs to which stage is written **once, by the plugin that
publishes it**, at the moment it publishes, in a hook. It is never left to the agent's memory.

| Who writes | When | Entry |
|---|---|---|
| approval-gates `hooks/gate_guard.py` | an ArtifactData write of a `gates/` row (per-stage page), a `bundles/` row (a Unit's plan or unit-end page), a `plans/` row (a test plan) | `gate` (stage, per-stage), `unit-plan` / `unit-end` (code-generation, the Unit, rhythm `unit-end`), `test-plan` (code-generation, the Unit) |
| question-forms `hooks/question_guard.py` | a `forms/` row whose `file` is a questions file under a stage's folder | `questions-form` (the stage, and the Unit, from the file's path) |

A board form with no questions file (the review-findings board) names no stage, so it is not registered
(`findings-form` is in the schema for a writer that can tie one to a stage).

## File

`~/.claude/plugins/data/aidlc-artifacts/links/<checkout path, non-word characters as _>/<space>--<intent>.json`
(`$AIDLC_ARTIFACTS_DIR` moves the folder). One file per checkout and intent; every plugin's copy of `aidlc_links.py`
and the panel read the same one. See the module's docstring for the entry's fields.

## Backfill

`aidlc_links.py backfill [--project-dir <dir>] [--transcripts <glob> ...] [--artifact <url> ...] [--dry-run]` reads
session transcripts (default `~/.claude/projects/<project>*/*.jsonl`) for ArtifactData writes and records the ones a
script can tie to a stage with certainty: a gate row id `<intent>-<stage>[-<unit>]-<stamp>` whose stage and Unit are
both known in the intent's state; a unit plan, unit-end or test-plan row id naming a known Unit; a form row naming a
questions file. What it cannot tie, it lists as undecided and records nothing. There is no model judge: an entry with
a `judged` field would be one a model, not a script, placed.

## Edit

Edit `shared/aidlc-links/aidlc_links.py`, then run `scripts/sync-shared.py`: it writes the copy into each plugin that
carries one (`plugins/*/scripts/aidlc_links.py`); `--check` is what CI runs.
