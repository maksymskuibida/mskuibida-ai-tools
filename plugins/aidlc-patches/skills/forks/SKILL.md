---
name: forks
description: Use to see, add, change or remove the forks of the AI-DLC engine (awslabs/aidlc-workflows) this person patches — "which forks do I have", "add my fork alice/aidlc-workflows", "my clone of it is at ~/src/aidlc", "forget that fork", "use the other fork" — and whenever the person names a fork of the engine this plugin has not saved yet. The list is kept in the plugin's data folder, so it survives plugin updates.
---

# The saved forks

The plugin keeps one list of the engine forks the person works with. Every other skill here picks
its fork from it (`${CLAUDE_PLUGIN_ROOT}/references/fork.md`, step 1). Below, `FORKS` stands for
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/forks.py" --data "${CLAUDE_PLUGIN_DATA}"`.

| Ask | Command |
|---|---|
| What is saved | `FORKS list` (one line per fork: repo, clone, upstream) |
| Save a fork, or set its clone | `FORKS add <owner/name> [--clone <path>]` |
| Clear a fork's clone | `FORKS add <owner/name> --clone ""` |
| A fork of another upstream | `FORKS add <owner/name> --upstream <owner/name>` |
| Forget a fork | `FORKS remove <owner/name>` (ask first) |
| Where the list lives | `FORKS path` |

`add` accepts `owner/name` or a GitHub URL. Adding a fork that is already saved updates it. A
`--clone` path must already be a git clone: clone first (`gh repo clone <fork> <path>`), then save.

## The rules

- **No fork saved:** ask which fork (`owner/name`) and its local clone path, if any. Save the answer.
- **Exactly one saved:** use it without asking.
- **The person names another fork:** save it too. From then on, ask which saved fork to use, every
  time, through the question dialog with one option per fork.

Before you save a fork, check it is one: `gh repo view <fork> --json isFork,parent --jq
'.isFork, .parent.nameWithOwner'`. If its parent is not the upstream, say so and ask whether to
save it with `--upstream <its parent>`.

Show the line the command prints. Exit 2 is an error (a bad name, a missing clone, a broken file):
show it and stop.
