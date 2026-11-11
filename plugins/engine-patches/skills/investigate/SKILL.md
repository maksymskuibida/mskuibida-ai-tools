---
name: investigate
description: Use to investigate a bug in the AI-DLC engine (awslabs/aidlc-workflows) in the person's fork — reproduce it, find the cause in the engine source (core/tools/*.ts), and write a test that fails for that cause. Triggers — "why does aidlc refuse this", "find the cause of this engine bug", "reproduce the pin deadlock", "write a failing test for it", an `aidlc engine …` refusal or wrong next_stage pasted from a project. Read-only toward the fork's main; it writes only a test on a branch of its own.
---

# Investigate an engine bug

`FORKS`, here and in the reference files, is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/forks.py" --data
"${CLAUDE_PLUGIN_DATA}"`, exactly as written on this page (the reference files show only the
name).

0. **Pick the fork.** Read `${CLAUDE_PLUGIN_ROOT}/references/fork.md` and do what it says. Read
   `${CLAUDE_PLUGIN_ROOT}/references/lessons.md` once. Work in a worktree of the clone on a new
   branch from `origin/main`: `git -C <clone> worktree add <path> -b investigate/<slug> origin/main`.

## 1. Pin the bug down

Write down, before touching code:

- the exact command and its exact output (the refusal text, the wrong `next_stage`, the hang);
- the engine version: `aidlc --version` on the machine, and the project's `.aidlc-version`;
- the state that leads there: team or solo, which phase and stage, which Unit, which gates are
  open, what ran just before.

Missing pieces: ask the person. Do not open or message the project's live sessions to find out
(lessons, "People and sessions"). Read the project's files, its audit shards and state, read-only.

Check the fork's patch notes (its "known bugs" list, its open patch branches) and the fork's open
issues and PRs: `gh issue list --repo <fork>`, `gh pr list --repo <fork>`. The bug may already be
known or half-done.

## 2. Reproduce

Smallest first:

1. **A test against the engine.** Find the test that owns the code path. Grep the `covers:`
   headers: `grep -rl 'covers:.*<function or subcommand>' tests/`. Extend its scenario or copy its
   setup.
2. **A fixture.** If the bug needs real git remotes, two clones or a host, use the fork's fixture
   drivers if it has some (its runbook names them). Else write a short shell driver that builds a
   throwaway workspace in a temp directory, with made-up names.

Run the engine as the fork builds it. If the fork has a script that installs the checkout as a
local test build, use that, with a test version string that cannot be mistaken for a release.
Retry on a lock message (lessons, "Running things on a shared machine").

Show the reproduction failing the same way the person saw it. If it does not, say what differs and
stop.

## 3. Find the cause

- Grep `core/tools/*.ts` for the refusal text or the field that is wrong. Follow the call chain to
  the decision that goes wrong. Note it as `core/tools/<file>.ts:<line>`.
- Ask who wrote that line: `git log -L <start>,<end>:core/tools/<file>.ts --oneline` or
  `git blame`. Then, is it upstream's code or one of the fork's patches?
  `git log --oneline <base>..origin/main -- core/tools/<file>.ts`.
  - **A fork patch caused it:** the fix is a fixup to that patch, not a new one. Name the patch.
  - **Upstream's code:** it is an upstream bug. `check-upstream` looks for an upstream fix next.
- Check the cause against the reproduction: change the line by hand, rerun, see the symptom go.
  Then undo it. The fix is written in the `series` step.

## 4. A test that fails for that cause

- Put it where the owning tests live, usually `tests/unit/`. Name it like its neighbours
  (`t-<what>.test.ts`). Start it with a `covers:` header and a comment: what broke, why, and what
  is now true.
- Assert the specific wrong behaviour (the refusal text, the stage name), not just a non-zero exit.
- Run only that file, outside the session's markers:

  ```bash
  env -u CLAUDECODE -u CLAUDE_CODE_SESSION_ID bash tests/run-tests.sh --unit --filter '^<name>\.test\.ts$'
  ```

- It must fail on the fork's `main`. If the cause is upstream's code, it must also fail on the
  base tag with only the test applied: `git worktree add <tmp> <base>`, copy the test in, run it.
- Commit the test alone on the branch: `test(<scope>): <what must be true>`. Typecheck and lint it
  (`bun scripts/package.ts && bun run typecheck && bun run lint`).

## 5. Hand over

Tell the person, in a few lines:

- the symptom and the reproduction (test path, or fixture path and command);
- the cause at `core/tools/<file>.ts:<line>`, and whose code it is (upstream, or patch NN);
- the test, and that it fails on `main` (and on `<base>` for an upstream bug);
- the fix you would write, in one sentence.

Then run `check-upstream`. Skip it only when the cause is one of the fork's own patches, not one
carried from an upstream PR: that goes straight to `series`, "Change a patch".
