---
name: mac-cleanup
description: Find what fills a Mac's disk and reclaim it safely — the whole disk, not one folder. Walks the Data volume once, has six read-only investigators explain each area (developer builds, simulators, Docker and models, caches, projects, personal files, system), says how much it could not verify and which folders need Full Disk Access, and publishes one page in the developer's "Mac cleanup" artifact where they pick Remove or Keep per item; picked items are re-checked at the moment of removal. Includes the worktree gates (unpushed work, live sessions, recent activity) for orphaned git worktrees. Use whenever the disk is full or filling ("where did my space go", "I had 100 GB free last month", "clean up my Mac", "what can I delete"), whenever worktrees pile up or someone asks which worktrees are safe to delete, and before any bulk `git worktree remove` or `rm -rf` over checkouts or caches. A question about one known folder ("how big is node_modules here") is a plain du, not this skill.
---

# Mac cleanup

A full disk is rarely one thing. On a developer's Mac it is usually a dozen: simulator runtimes, Docker's disk
image, Xcode's compilation cache, worktrees each with their own build output, a second copy of an app's VM,
swap, a prepared macOS update. The value of this skill is an account of **the whole disk**, from the
volume down, that says what every big thing is and whether removing it costs anything, and then removes only
what the owner picked, re-checked at the moment of removal.

Two ways this goes wrong, and the rule against each:

- **Removing something that was in use or irreplaceable.** Nothing is removed that the owner did not pick on the
  page, and everything picked is re-checked against the disk as it is at removal (exists, no running session
  inside, no open file, nothing written in the last 30 minutes). Worktrees go through their own three gates.
- **A confident account that is not true.** Every size comes from `du`; a size the walk contradicts (a mounted
  image's contents, a sparse file's apparent size) is left out, and what the walk could not read is reported as
  a number, never folded in silently.

## Workflow

Scripts live in `${CLAUDE_PLUGIN_ROOT}/skills/mac-cleanup/scripts/` (below: `$SC`). Use a scratch folder for
everything (below: `$OUT`); nothing is written into projects.

### 1. Walk the disk and start the investigators — at the same time

```bash
python3 "$SC/mac_scan.py" walk --out "$OUT"          # run_in_background: 3–5 minutes
```

It records the APFS container (`volumes.json`), every folder's size to depth 9 (`walk.tsv`), every folder
du could not read (`walk.err`) and every file over 1 MB written in the last 30 days (`recent.tsv`).

While it runs, spawn the **six investigators** of [`references/investigators.md`](references/investigators.md)
in one message, each on Haiku, each brief its shared part plus its area. They write `$OUT/agents/<area>.json`.
Do not duplicate their work while they run.

### 2. Worktrees, with liveness

Collect liveness and scan worktrees exactly as [`references/worktrees.md`](references/worktrees.md) § 1 says
(session cwds and agent names into two files, then `scan_worktrees.py --json $OUT/worktrees.json`). Keep the
live-paths file: `build` marks items a session works in.

### 3. Build the page's rows

When the walk and all six investigators are done, write a short Markdown summary for the top of the page (where
the space went, what grew in the last 30 days, the biggest safe wins, two to five lines) to `$OUT/summary.md`, then:

```bash
python3 "$SC/mac_scan.py" build --dir "$OUT" --out "$OUT/page" --worktree-plan "$OUT/worktrees.json" \
  --live-paths "$OUT/live-paths.txt" --summary-file "$OUT/summary.md"
```

It prints `{"id", "writes", "batches", "items", "suggestedBytes", "unverifiedBytes"}`. Read its stderr: each
`left out` line is an investigator's size the walk contradicts. Large folders no investigator explained become
rows of their own ("Not yet explained"), so nothing big goes missing.

### 4. Publish the page

`Artifact` → `action: "list"` → the artifact titled **Mac cleanup**. If there is none, publish
[`cleanup.html`](cleanup.html) from this folder once: `capabilities: {db: {}, user: {}}`, `icon: "chart"`,
description "Where the disk went, and what to remove: pick per item, Claude re-checks before removing."
Reuse its URL from then on; after a plugin update republish this file to the same URL (rows stay). Then send
the rows with one `ArtifactData` `batch`: the `writes` array of `writes.json` as it is (or each file named in
`batches`, in order).

Send the link `<artifact url>#<id>` in a message with, in plain words: the three biggest things, the safe total,
and **how much could not be verified** — `unverifiedBytes` (the Data volume's consumed bytes minus what the walk
measured) with the folders behind it. The owner grants access themselves (it is a security setting): System
Settings › Privacy & Security › Full Disk Access › turn on Claude (or the terminal running Claude Code), reopen
it, and scan again. Then ask them to pick on the page and say when they are done.

### 5. Remove what was picked

On "done": `ArtifactData` `get` of `scans/<id>`, save its `picks` to `$OUT/picks.json`, collect liveness again
(fresh files, as for worktrees), then:

```bash
python3 "$SC/mac_scan.py" remove --scan "$OUT/page/scan.json" --picks "$OUT/picks.json" \
  --live-paths "$OUT/live-paths-fresh.txt"                    # dry run
```

Show the owner what it would remove, what it held back and why, and confirm. Then:

- **Plain folders and files** (`kind: path`): the same command with `--execute`. It re-checks each one first.
- **Worktrees**: `remove_worktrees.py --only <paths>` with fresh liveness, per `references/worktrees.md` § 3.
- **Tool commands** (`kind: command`: `xcrun simctl runtime delete`, `docker volume rm`, `brew cleanup`, …):
  one at a time, each shown before it runs. Never one that needs sudo: give it to the owner to run.
- **Manual steps** (`kind: manual`: an app's setting, installing a prepared macOS update): list them for the owner.

### 6. Report what was freed

From what was removed and measured, never from what was planned. `df` before and after is not proof: other
sessions write to the disk meanwhile. Say what was held back and why, and repeat the unverified amount and the
access steps if they still apply.

## Never

- Never remove what the owner did not pick, never widen a pick to its parent folder, never run a cleanup command
  "while we are at it".
- Never use sudo, change a security setting, delete a local snapshot or touch a system volume yourself; those are
  steps for the owner.
- Never stop, start or recreate containers to measure or clean them; shared test infrastructure lives there.
- Never write picks or notes into the page's rows: they are the owner's.
