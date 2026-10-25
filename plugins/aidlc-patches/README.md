# aidlc-patches

For people who keep their own fork of the AI-DLC engine
([awslabs/aidlc-workflows](https://github.com/awslabs/aidlc-workflows)) and patch it. The fork's
`main` is an upstream release tag plus one commit per patch. This plugin is the repeatable way to
fix an engine bug there: investigate it, check upstream first, put the patch in its place in the
series, release a preview, roll it into projects, and send the fix upstream.

It is not tied to one fork. It asks for yours the first time and remembers it.

## Install

```bash
/plugin install aidlc-patches --marketplace maksymskuibida/mskuibida-ai-tools
```

Or, with the marketplace already added: `/plugin install aidlc-patches@mskuibida-tooling`.

## Skills

| Skill | What it does |
|---|---|
| `/aidlc-patches:fix` | The whole run for one bug, in order: investigate, check upstream, patch, release, roll out, offer an upstream PR. |
| `/aidlc-patches:investigate` | Reproduce the bug, find the cause in `core/tools/*.ts`, write a test that fails for that cause. |
| `/aidlc-patches:check-upstream` | Upstream main since the fork's base tag, newer stable and preview releases, open and merged upstream PRs and issues on the same code. Decides: drop, carry upstream's PR, or write our own. |
| `/aidlc-patches:series` | Add, change or drop a patch (fixup and autosquash), check every commit typechecks and lints, land on `main` with `--force-with-lease`, move to a newer upstream release with `rebase --onto`. |
| `/aidlc-patches:release` | Run the fork's preview release from `main` (versions are next-patch previews from `.101`), install it, pin projects to it. |
| `/aidlc-patches:upstream-pr` | Issue first, then a branch from `upstream/main`, the patch cherry-picked, the PR against upstream. |
| `/aidlc-patches:forks` | See, add or remove the saved forks. |

Every step that publishes something waits for your yes: the force-push to `main`, a release, an
upstream issue or PR.

## Your forks

The list of forks is one JSON file in the plugin's data folder, `${CLAUDE_PLUGIN_DATA}/forks.json`
(normally `~/.claude/plugins/data/aidlc-patches-mskuibida-tooling/forks.json`). Claude Code keeps
that folder across plugin updates, unlike the install folder. On a Claude Code build without
`${CLAUDE_PLUGIN_DATA}`, the script falls back to `~/.claude/plugins/data/aidlc-patches/`.

- No fork saved: the agent asks which fork (`owner/name`) and where its local clone is, and saves it.
- One saved: it is used without asking.
- You mention another fork: it is saved too, and from then on the agent asks which one, every time.

```json
{
  "version": 1,
  "forks": [
    { "repo": "alice/aidlc-workflows", "clone": "/Users/alice/src/aidlc-workflows", "upstream": "awslabs/aidlc-workflows" }
  ]
}
```

The script is [`scripts/forks.py`](scripts/forks.py) (`resolve`, `list`, `show`, `add`, `remove`,
`path`). You can also edit the file by hand.

## Your fork's own docs win

Forks differ: where the notes live, how tests run, whether there is a release script. Each skill
first looks for the fork's own runbook and patch list (for example `patched/RUNBOOK.md` and
`patched/PATCHES.md`) and follows it where it differs from the plugin. The plugin's defaults
describe the common layout:

- `main` = an upstream release tag, then the patches in four groups (upstream's fixes from their
  open PRs, standalone fixes, dependent fixes, improvements), then the fork's own commits.
- A fix never depends on an improvement.
- Every commit typechecks (`bun scripts/package.ts && bun run typecheck`) and passes upstream's
  lint (biome, `--error-on-warnings`).
- Releases are `<next patch>-preview.<date>.<build>` with builds from `.101`, so they never share a
  version string with upstream's.
- Projects install with `AIDLC_RELEASE_REPOSITORY=<fork> sh install.sh --version <v>`, then
  `aidlc config --pin <v> --yes` once per checkout.

[`references/fork.md`](references/fork.md) is how a skill finds the fork, its clone, its docs and
its base tag. [`references/lessons.md`](references/lessons.md) is what earlier forks learned: leave
the release workflow's jobs alone (t332 pins them), cancel Full Suite runs in a fork, retry on the
machine-wide engine lock, never message an AI-DLC Unit session while its gates may be open, and keep
a public fork free of private names.

## Needs

`git`, `gh` (signed in), `bun`, `python3`, and the `aidlc` launcher for reproducing and rolling out.

## Tests

```bash
python3 -m unittest discover -s plugins/aidlc-patches/tests
```
