# The investigators

Six read-only subagents, one per area, started in parallel while `mac_scan.py walk` runs. Spawn each on
Haiku (`model: "haiku"`, `subagent_type: "general-purpose"`): locating and measuring is search work. Each brief
is the **shared part** below followed by its **area**. Replace `<OUT>` with the walk's `--out` folder.

## Shared part (every brief starts with this)

> You are one of six read-only disk investigators on a Mac (home: `$HOME`). The disk is nearly full. Find what
> in YOUR AREA takes space, say what each thing is, whether removing it loses anything, and how it could be
> reclaimed.
>
> Hard rules:
> - Read-only. Never delete, move, prune, clean, thin, purge or modify anything; no cleanup commands of any kind
>   (dry runs such as `brew cleanup -n` are fine). Never use sudo.
> - Do not start, boot or open any app, daemon, simulator, emulator or VM. A CLI that needs something running
>   that is not running is skipped; measure the files instead. Never create containers.
> - In git checkouts use only `du`, `find`, `stat` and read-only `git -C <repo> log -1 --format=%cs`: no
>   `git status` (it rewrites indexes live sessions use).
> - Measure with `du -sk` or `du -k -d 2` (bytes = KB × 1024), on your area only. Never run du over `/` or
>   the whole home folder: another process already walks the whole disk. Never report a size you did not
>   measure; an estimate (a mounted image's contents, a sparse file's apparent size) is left out, with a line
>   in `summary` saying so.
> - Record every path where a command says "Operation not permitted" or "Permission denied" in `denied`. They
>   need Full Disk Access; never work around it.
> - Budget about 10 minutes of commands.
>
> Report items of 200 MB or more. When a big directory is a mix (one folder per app, device, version, project,
> model), report its children instead of only the parent.
>
> Write your result as JSON to `<OUT>/agents/<area>.json` (`mkdir -p` the folder; write with a python3
> heredoc; working files go elsewhere or under another name), shape:
> `{"area": "<area>", "items": [{"path", "bytes", "what", "category", "risk", "regenerates", "action",
> "modified", "recent", "notes"}], "denied": ["/path"], "summary": "2-4 sentences"}`
> - `path`: absolute. Things that are not files take a prefixed name instead: `docker-image:<name> (<id>)`,
>   `docker-volume:<name>`, `docker-build-cache`.
> - `what`: one plain line saying what it is ("Xcode build cache for the Reviewdesk project").
> - `category`: one of `dev-build`, `dev-tools`, `simulators`, `containers-vms`, `ai-models`, `package-caches`,
>   `app-caches`, `app-data`, `repos`, `personal-files`, `system`, `logs`, `backups`, `other`.
> - `risk`: `safe` = a cache or build output that comes back on its own, nothing the owner made is lost;
>   `review` = probably reclaimable, but the owner should look; `keep` = in use or irreplaceable, listed so
>   the owner can see where the space goes.
> - `regenerates`: how it comes back, or what is lost.
> - `action`: the exact command that would reclaim it, preferring the owning tool's own (`xcrun simctl
>   runtime delete <id>`, `docker volume rm <name>`, `npm cache clean --force`, `rm -rf <path>`), or the step
>   in an app ("Telegram › Settings › Data and Storage › Clear cache"). You do NOT run it.
> - `modified`: newest date you can see (YYYY-MM-DD); `recent`: true if something in it changed in the last
>   30 days.
>
> Then reply with only: the file you wrote, the total bytes of your items, and your summary.

## The six areas

**apple-dev** — Apple and mobile development. `~/Library/Developer` (Xcode DerivedData per project, Archives,
DeviceSupport, Previews, CoreSimulator Devices per device with its name, runtime and state from
`xcrun simctl list devices -j`, CoreSimulator Caches), `/Library/Developer` (simulator runtimes:
`xcrun simctl runtime list`; dyld caches), `/System/Library/AssetsV2/com_apple_MobileAsset_iOSSimulatorRuntime`,
Xcode apps, Android (`~/Library/Android/sdk`, `~/.android/avd` per AVD), `~/.gradle`, `~/.expo`, CocoaPods,
SwiftPM caches. Identify any extra mounted APFS container (`diskutil list`, `hdiutil info`): usually a
simulator runtime image.

**containers-ai** — Containers, VMs and AI models. Docker Desktop (`~/Library/Containers/com.docker.docker`;
`docker system df -v` only if `docker info` answers within 5 s), OrbStack, colima/lima, Podman, VM bundles
(`*.utm`, `*.pvm`, `*.vmwarevm`), ollama (`~/.ollama/models`, per model from its manifests), LM Studio,
Hugging Face and other model caches, any `*.gguf`/`*.safetensors` over 500 MB, the Claude desktop app's data
(`~/Library/Application Support/Claude`, `~/.claude-instances/*`), Claude Code's `~/.claude` (projects
transcripts: the 10 biggest), other AI tools' folders.

**caches-toolchains** — `~/Library/Caches` (per app), `~/.cache`, npm, pnpm, yarn, bun, deno, pip, uv, poetry
(including its virtualenvs), pyenv/nvm/fnm/volta versions, rustup/cargo, Go, Maven, Homebrew (`brew --cache`,
Cellar per formula, `/usr/local/Cellar` left from an Intel install, `brew cleanup -n --prune=all`), Playwright
and Puppeteer browsers, JetBrains caches and old IDE versions, VS Code/Cursor/Windsurf storage, browser caches
and on-device model folders.

**repos** — Code projects and their build output: every git checkout at depth ≤ 2 under `$HOME`. Per project
≥ 200 MB: the project (`keep`, or `review` when untouched for 60+ days), its `.git` when ≥ 500 MB, and per kind
the sum of `node_modules`, `.build`, `.venv`/`venv`, `dist`/`build`/`.next`/`target`/`.turbo`/`.expo`/`Pods`
(`safe`). A project's `.claude/worktrees` folder as one `review` item (the worktree gates decide about each
worktree). Temp clones in `/private/tmp` and `/private/var/folders/*/*/T`, summed per kind (`review`).

**personal-apps** — Personal files and applications: Downloads, Documents, Desktop, Movies, Music, Pictures
(the Photos library's size only), media-heavy folders at the top of home (biggest files with dates), the Trash,
iCloud Drive, Mail, Messages attachments, iPhone/iPad backups (one item per backup), Group Containers and
Containers per app, Application Support per app (others cover Claude, editors and Docker), `/Applications` apps
≥ 500 MB with their last-used date. Names, sizes and dates only: never read personal documents.

**system** — `/Library` (except what apple-dev covers), `/private/var` (`folders`, `vm`, `db`, `log`),
`/opt`, `/usr/local`, `/Users/Shared`, `/private/tmp`, the logs. The volumes: `diskutil apfs list`,
`diskutil info /System/Volumes/Data` (purgeable space), local snapshots (`tmutil listlocalsnapshots /`,
`diskutil apfs listSnapshots`), why Preboot is large (a prepared macOS update?), swap (`sysctl vm.swapusage`).
This one also fills `"volumes"`, `"snapshots"` and `"purgeable_bytes"` in its JSON. System items are `keep`
unless an owner-run step frees them (install the prepared update, restart to shrink swap).
