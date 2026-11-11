---
name: series
description: Use to keep the person's AI-DLC engine fork in order as a patch series — an upstream release tag plus one commit per patch — when adding a patch, changing one (fixup and autosquash), dropping one, checking every commit typechecks and lints, landing the series on the fork's main with --force-with-lease, or moving the fork to a newer upstream release with rebase --onto. Triggers — "add this fix to the series", "fold this into patch 07", "rebase the fork onto v2.12.0", "check every commit builds", "land it on main".
---

# Keep the series in order

`FORKS`, here and in the reference files, is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/forks.py" --data
"${CLAUDE_PLUGIN_DATA}"`, exactly as written on this page (the reference files show only the
name).

0. **Pick the fork.** Read `${CLAUDE_PLUGIN_ROOT}/references/fork.md` and do what it says. The
   fork's runbook wins where it differs from this page.

## The shape

The fork's `main` is `<base>` (an upstream release tag), then one commit per patch, then the fork's
own commits (its notes folder, its release-workflow change). The patches go in this order:

1. **Upstream's fixes** carried from their open PRs (or from upstream main, not yet released).
2. **Standalone fixes**: ours, standing on the base alone.
3. **Dependent fixes**: ours, needing an earlier patch.
4. **Improvements**: features and behaviour changes, last.

A fix never depends on an improvement. One that would goes after it, and the notes say why.

Every commit must, on its own:

```bash
bun scripts/package.ts && bun run typecheck && bun run lint
```

`bun run lint` is upstream's biome check with `--error-on-warnings`. If the fork's `package.json`
names it differently, use what is there. Upstream's subject style: `fix(scope): what is now true`.

See the series: `git log --reverse --format='%h %s' <base>..origin/main`.

## Add a patch

Write the fix on top of the failing test from `investigate`, then make the fix and its test one
commit (`git commit --amend` or `git rebase -i --autosquash`). Then place it by its group. Rebuild
from the commit it goes after, and replay the rest:

```bash
git switch -c work <the commit it goes after>
git cherry-pick <the patch commit>
git cherry-pick <the commit it goes after>..origin/main
```

Resolve conflicts patch by patch. A conflict in a later patch is that patch's to absorb: keep its
intent, and say which patches you touched.

Then **verify** (below), update the fork's patch notes (one entry per patch: what it fixes, what it
needs, whether it can go upstream), and **land** (below).

## Change a patch

```bash
git switch -c work origin/main
# edit, then:
git commit --fixup=<the patch's commit>
GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash <base>
```

To drop a patch: `git rebase --onto <patch>^ <patch> work`. Then verify, update the notes, land.

## Verify

Every commit typechecks and lints on its own:

```bash
git rebase -x 'bun scripts/package.ts && bun run typecheck && bun run lint && git diff --exit-code --stat' <base>
```

The last check catches a commit whose generated, tracked files are out of date: the build changed
them. The rebase stops at the first commit that fails. Fix it there with `git commit --amend`, then
`git rebase --continue`. A commit made only of the fork's notes may skip the check if the fork's
runbook says so.

Then run the tests of every patch you touched, outside the session's markers:

```bash
env -u CLAUDECODE -u CLAUDE_CODE_SESSION_ID bash tests/run-tests.sh --unit --filter '^(<name>|<name>)\.test\.ts$'
```

Use the fork's own test script and fixtures if it has them (its runbook says which tier a push to
`main` needs). Retry a fixture on a lock message.

Compare with what is published: `git range-diff <base> origin/main work`. Every change shown must
be one you meant.

## Land

Ask the person before this step: it rewrites the fork's public `main`.

```bash
git fetch origin
git push --force-with-lease=main:<the origin/main you built on> origin work:main
```

Never a plain `--force`. A refused lease means someone else landed: fetch, rebuild on the new
`origin/main` (Add a patch), verify, try again.

After the push, check the fork's Actions: `gh run list --repo <fork> --branch main --limit 5`. A
Full Suite run started there always fails in a fork (it needs upstream's credentials): cancel it
with `gh run cancel <id> --repo <fork>`.

## Move to a newer upstream release

```bash
git fetch upstream --tags
git switch -c move origin/main
git rebase --onto <new tag> <old tag>
```

Resolve conflicts patch by patch. Then, for each fix, check whether upstream now fixes it: apply
only its tests to `<new tag>` and run them (`check-upstream`, step 1, on the tag). A test that
passes without the fix means the patch can be dropped or made thinner. Drop the patches upstream
merged. Update the base tag in the fork's docs and notes. Verify, then land.
