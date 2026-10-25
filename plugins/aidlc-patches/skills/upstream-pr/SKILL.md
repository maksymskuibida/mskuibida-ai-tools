---
name: upstream-pr
description: Use to send one of the fork's AI-DLC engine patches upstream to awslabs/aidlc-workflows — file the issue first, cut a branch from upstream/main, cherry-pick the patch, check it, and open the PR from the fork. Triggers — "send this fix upstream", "open an upstream PR for patch 09", "file the upstream issue", "upstream this". Every issue and PR waits for the person's yes.
---

# Open an upstream PR

`FORKS`, here and in the reference files, is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/forks.py" --data
"${CLAUDE_PLUGIN_DATA}"`, exactly as written on this page (the reference files show only the
name).

0. **Pick the fork.** Read `${CLAUDE_PLUGIN_ROOT}/references/fork.md` and do what it says. Read
   upstream's `CONTRIBUTING.md` on `upstream/main`: its rules for issues, PRs and commit style win.

## 1. Is it ready

A patch goes upstream on its own when it has one cause and its own test, and depends on no other
patch of the fork. The fork's patch notes often say "upstream candidate". Check `check-upstream`
step 3 again: no open upstream PR or issue covers it already. If one does, link to it instead.

## 2. The issue first

Upstream asks for an issue before a PR. Draft it from the fork's notes (a fork may keep a draft):

- **Title:** what goes wrong, in upstream's words.
- **What happens:** the steps, the command, the actual output, the expected output.
- **Where:** the version (`<base>`, and that it is still on `upstream/main` at `<sha>`), and the
  cause at `core/tools/<file>.ts:<line>`.
- **Proposed fix:** one paragraph. Say a PR is ready.

No employer or private project names, nothing from a real project's state (lessons, "A public
fork"). Show the person the draft. On their yes:

```bash
gh issue create --repo <upstream> --title "<title>" --body-file <draft>
```

## 3. The branch

From upstream's `main`, not the fork's:

```bash
git -C <clone> fetch upstream
git -C <clone> switch -c fix/<name> upstream/main
git -C <clone> cherry-pick <the patch's commit>
```

Resolve conflicts against upstream main. Nothing from the fork's own folders (its notes, fixtures,
release changes) goes upstream. Then check the branch:

```bash
bun install --frozen-lockfile && bun scripts/package.ts && bun run typecheck && bun run lint
env -u CLAUDECODE -u CLAUDE_CODE_SESSION_ID bash tests/run-tests.sh --unit --filter '^<name>\.test\.ts$'
```

The patch's test must fail on `upstream/main` without the fix and pass with it.

## 4. The PR

Ask the person before pushing and opening it. Then:

```bash
git -C <clone> push -u origin fix/<name>
gh pr create --repo <upstream> --base main --head <owner>:fix/<name> \
  --title "<the patch's subject>" --body-file <body>
```

The body: what was wrong, why, what the fix changes, the test, and `Fixes #<issue>`. Follow
upstream's PR template if `.github` has one.

## 5. After

Record the issue and PR links in the fork's patch notes next to the patch. When upstream merges
it, the next move to a newer upstream release drops the patch (`series`, "Move to a newer upstream
release"). Reviewer comments come back to the person; answer upstream only on their yes.
