---
name: release
description: Use to release the person's patched AI-DLC engine fork and roll the release into their projects — run the fork's preview release workflow from main, find the version it published (next-patch previews numbered from .101), install it on the machine, and pin projects to it (aidlc config --pin). Triggers — "release the fork", "cut a preview", "publish .103", "roll the new engine into my projects", "pin the project to the new release", "install the patched aidlc here".
---

# Release the fork and roll it into projects

`FORKS`, here and in the reference files, is `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/forks.py" --data
"${CLAUDE_PLUGIN_DATA}"`, exactly as written on this page (the reference files show only the
name).

0. **Pick the fork.** Read `${CLAUDE_PLUGIN_ROOT}/references/fork.md` and do what it says. If the
   fork has a release script or a release section in its runbook, use that; it wins over this page.

## 1. Before the release

- `main` holds what you mean to release: `git log --reverse --format='%h %s' <base>..origin/main`.
- The fork's checks for a release are met (its runbook may need a full local test run first).
- **Ask the person** before starting the release. It publishes a public GitHub release.

## 2. Versions

A fork release is a **preview of the next patch** after `<base>`, numbered from **.101**:
`<base + 1 patch>-preview.<yyyymmdd>.<build>`, build 101, 102, … For a base `v2.11.1`:
`2.11.2-preview.20261020.101`. Upstream's own previews count from .1, so the two never share a
version string.

Upstream's Preview Release workflow allocates the build number itself. A fork sets the floor with
an `env:` value in `.github/workflows/preview-release.yml` (for example
`AIDLC_PREVIEW_BUILD_FLOOR: "100"`). If the fork does not have it yet, adding it is a fork commit,
made the way lessons ("Keep upstream's files shaped like upstream's") says: env values and `if:`
conditions only, jobs untouched, t332 updated.

## 3. Run it

With the fork's own script if it has one. Otherwise, run upstream's workflow on the fork's `main`:

```bash
gh api --method POST -H 'X-GitHub-Api-Version: 2026-03-10' \
  repos/<fork>/actions/workflows/preview-release.yml/dispatches -f ref=main --jq '.workflow_run_id'
```

That prints the run id. If the API answers without one, use `gh workflow run preview-release.yml
--repo <fork> --ref main`, then find the run with
`gh run list --repo <fork> --workflow preview-release.yml --limit 1`.

Watch it until it ends, in the background. At the first failed job, read its log
(`gh run view <id> --repo <fork> --log-failed | tail -n 80`), cancel the run, and stop: nothing
was published. A job that needs upstream's cloud credentials (Full Suite's live jobs) always fails
in a fork: if the fork's workflow does not already skip it, cancel that run and say so. Do not
read it as a real failure.

When it succeeds:

```bash
gh release list --repo <fork> --limit 3
gh release view v<version> --repo <fork> --json tagName,isPrerelease,assets --jq '.tagName, (.assets[].name)'
```

The release must carry `install.sh` and the platform builds. Report the version and the release URL.

## 4. Install on this machine

```bash
curl -fsSL "https://github.com/<fork>/releases/download/v<version>/install.sh" -o "$TMPDIR/aidlc-install.sh"
AIDLC_RELEASE_REPOSITORY=<fork> sh "$TMPDIR/aidlc-install.sh" --version <version>
```

`AIDLC_RELEASE_REPOSITORY` makes the installer fetch from the fork instead of upstream. If a local
test build of the same version is installed, move it aside first (the fork's runbook says where).

## 5. Roll into projects

Only the projects the person names. For each one:

1. In a scratch clone or a fresh worktree of the project, never in a checkout that holds live Unit
   work:

   ```bash
   v=<version> && aidlc config --pin "$v" --yes
   ```

   If the fork's runbook says to regenerate the harness shell after a pin (for example
   `aidlc config --harness claude --yes`), do that too.
2. Commit (`Engine shell: pin release <version>`), push a branch, open the project's PR. Ask before
   pushing. The person merges it.
3. After it merges, **every checkout** of the project runs this once, the main checkout after it
   pulls, each Unit worktree, each fresh clone:

   ```bash
   aidlc config --pin <version> --yes
   ```

   Until a checkout does, its engine commands refuse with "this project's <version> pin is not
   registered on this machine". Run it yourself only in checkouts with no live session. For a
   checkout where an AI-DLC Unit session runs, tell the person the command and let them run it.
   Never send it to that session as a message: the engine can record another session's message as
   the person's answer at an open gate.

`aidlc --version` prints the machine's active version, not a project's pin. A project's pin is its
`.aidlc-version` file.
