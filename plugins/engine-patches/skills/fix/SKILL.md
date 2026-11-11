---
name: fix
description: Use when the person wants an AI-DLC engine bug fixed in their own fork of awslabs/aidlc-workflows, end to end — "fix this aidlc bug in my fork", "patch the engine so pin stops deadlocking", "the engine refuses report --result skipped, fix it and release". Runs the plugin's steps in order: investigate, check upstream, add the patch to the series, release, roll into projects, and offer an upstream PR. For one step alone, use that step's skill.
---

# Fix an engine bug in the fork

One bug per run, on its own branch. The steps are skills of their own; this one keeps them in
order and says what passes between them.

`FORKS`, here and in the reference files, is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/forks.py" --data
"${CLAUDE_PLUGIN_DATA}"`, exactly as written on this page (the reference files show only the
name).

0. **Pick the fork.** Read `${CLAUDE_PLUGIN_ROOT}/references/fork.md` and do what it says: the
   fork, its clone, its own docs, its base tag. Read `${CLAUDE_PLUGIN_ROOT}/references/lessons.md`
   once.
1. **Investigate** (`investigate` skill). Out: a reproduction, the cause at `file:line`, and a
   test that fails for that reason.
2. **Check upstream** (`check-upstream` skill). Out: one decision — drop, carry upstream's
   PR, or write our own — with the links behind it. If the decision is drop, stop here and tell the
   person which upstream release or PR fixes it.
3. **Write the fix and place it** (`series` skill). The fix and its test are one commit, placed
   by its group. Every commit in the series typechecks and lints. Update the fork's patch notes.
   Ask before the force-push to `main`.
4. **Release** (`release` skill). Ask before starting it. Out: the version string.
5. **Roll into projects** (`release` skill, last part). Only the projects the person names.
6. **Offer an upstream PR** (`upstream-pr` skill), when the fix is our own and stands alone.
   Ask before filing anything upstream.

## Several bugs at once

Each bug gets its own session and branch. Steps 1 and 2 run in parallel safely. Step 3 rewrites
the fork's `main`, so only one session lands at a time:

- Before landing, fetch and rebuild your branch on the newest `origin/main` (`series` skill,
  "Add a patch"). Verify again. Push with `--force-with-lease`.
- A refused lease means another session landed first. Fetch, rebuild, verify, push again. Never
  use a plain `--force`.
- Release once after the batch lands, not once per bug, unless the person asks otherwise.

## When to stop and ask

- The bug does not reproduce, or reproduces only in a live project. Say what you tried.
- The cause is in one of the fork's own patches. The fix is then a fixup to that patch
  (`series` skill, "Change a patch"), not a new patch. Say so before writing it.
- The fix would need an improvement patch underneath it. A fix never depends on an improvement:
  ask whether to split the improvement or move the fix after it.
