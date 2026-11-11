---
name: check-upstream
description: Use before patching the AI-DLC engine in the person's fork, and before moving the fork to a newer upstream release — check whether upstream (awslabs/aidlc-workflows) already fixes the bug or is about to — upstream main since the fork's base tag, newer stable and preview releases, and open and merged upstream PRs and issues touching the same code — then decide: drop the patch, carry upstream's PR, or write our own. Triggers — "does upstream fix this already", "is there an upstream PR for it", "check upstream before we patch", "can we drop patch 07 now".
---

# Check upstream before patching

`FORKS`, here and in the reference files, is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/forks.py" --data
"${CLAUDE_PLUGIN_DATA}"`, exactly as written on this page (the reference files show only the
name).

0. **Pick the fork.** Read `${CLAUDE_PLUGIN_ROOT}/references/fork.md` and do what it says. You need
   `<base>`, the clone, and from `investigate`: the files and functions at the cause, and the
   failing test.

Below, `<files>` are the engine files at the cause (`core/tools/<file>.ts …`).

## 1. Upstream main since the base

```bash
git -C <clone> fetch upstream --tags
git -C <clone> log --oneline <base>..upstream/main -- <files>
git -C <clone> diff <base> upstream/main -- <files> | head -n 400
```

Read every commit that touches the cause. Then run the failing test on `upstream/main` with only
the test applied:

```bash
git -C <clone> worktree add <tmp> upstream/main
cp <test> <tmp>/tests/unit/ && cd <tmp> && bun install --frozen-lockfile >/dev/null &&
  env -u CLAUDECODE -u CLAUDE_CODE_SESSION_ID bash tests/run-tests.sh --unit --filter '^<name>\.test\.ts$'
```

A pass means upstream's main fixes it. Find the commit (`git log -S '<changed text>'`) and its PR.

## 2. Newer releases

```bash
gh release list --repo <upstream> --limit 40 --json tagName,isPrerelease,publishedAt \
  --jq '.[] | "\(.publishedAt[:10]) \(.tagName) \(if .isPrerelease then "preview" else "stable" end)"'
```

List the stable and preview releases newer than `<base>`. For the newest stable and the newest
preview, ask whether it holds the fix commit: `git -C <clone> merge-base --is-ancestor <commit>
<tag>`. If you found no commit, run the test on that tag as in step 1.

## 3. Upstream PRs and issues on the same code

Search by the refusal text, the function names and the file names. Do several searches:

```bash
gh search prs  --repo <upstream> --state open   "<function or message>" --json number,title,url,updatedAt
gh search prs  --repo <upstream> --merged       "<function or message>" --json number,title,url,closedAt
gh search issues --repo <upstream> "<symptom words>" --json number,title,url,state
```

`gh search` cannot filter by path, so also list the open PRs that touch the files:

```bash
gh pr list --repo <upstream> --state open --limit 200 --json number,title,url,files \
  --jq '.[] | select(any(.files[]; .path == "core/tools/<file>.ts")) | "\(.number) \(.title) \(.url)"'
```

For each hit that looks related, read it: `gh pr view <n> --repo <upstream> --comments`, and its
diff (`gh pr diff <n> --repo <upstream>`). Note what the reviewers asked for and whether it is
draft, approved, or stalled.

## 4. Decide

| What you found | Decision | What happens next |
|---|---|---|
| A stable or preview release newer than `<base>` fixes it | **Drop.** Move the fork to that release (`series`, "Move to a newer upstream release") instead of patching. | Ask the person: move now, or carry a patch until they want to move. |
| Upstream main fixes it, not yet released | **Carry upstream's commit** as a patch, in the upstream group. It drops out at the next move. | `series`, "Add a patch", group upstream. |
| An open upstream PR fixes it | **Carry upstream's PR**: cherry-pick its commits, keep its author, in the upstream group. Note "drops out once #N merges". If reviewers asked for changes, carry the rework too, and say so in the notes. | `series`, "Add a patch". |
| An open PR or issue covers part of it | **Our own, built to fit.** Write the fix so it does not fight that PR. Link it in the notes. | `series`. |
| Nothing upstream | **Our own patch.** Note whether it can go upstream as its own PR (one cause, own test). | `series`, then offer `upstream-pr`. |

Give the decision in one line, with the links (commit, release, PR, issue) behind it. Record it in
the fork's patch notes next to the patch, in the fork's own format.

For the move to a newer release (`series`), run steps 1 and 2 for every fix in the series: its
tests alone, on the new tag. A test that passes there without the fix means the patch can be
dropped or made thinner.

Never comment on, review or react to an upstream PR or issue without the person's yes.
