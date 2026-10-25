# Pick the fork and get to its clone

Every skill in this plugin starts here. `FORKS` is the command the skill that sent you here
defines. Use it exactly as that skill writes it.

## 1. Which fork

The saved forks live in `forks.json` in the plugin's data directory (`FORKS path` prints it). That
directory survives plugin updates. Never write the list anywhere else.

```bash
FORKS resolve
```

- **Exit 0** — exactly one fork is saved. Its JSON is printed. Use it without asking.
- **Exit 3** — none is saved. Ask the person for the fork (`owner/name`) and the path of its local
  clone, if they have one. Then save it: `FORKS add <owner/name> [--clone <path>]`.
- **Exit 4** — several are saved. They are printed. Ask which one to use, through the question
  dialog, one option per fork. Ask every time, even if you used one earlier in this session.

When the person mentions or asks about a fork that `FORKS list` does not show, save it as well
(`FORKS add`). From then on there are several, so `resolve` asks.

The upstream is `awslabs/aidlc-workflows` unless the fork's entry says otherwise
(`--upstream`). Below, `<fork>` is the fork's `owner/name`, `<owner>` its owner, `<upstream>` the
upstream's `owner/name`, and `<clone>` the clone path.

## 2. The clone

If the entry has no clone, ask where to put one, then:

```bash
gh repo clone <fork> <path> && FORKS add <fork> --clone <path>
```

In the clone, check the remotes. `origin` must be the fork. `upstream` must be the upstream:

```bash
git -C <clone> remote -v
git -C <clone> remote add upstream https://github.com/<upstream>.git   # only if missing
git -C <clone> fetch origin && git -C <clone> fetch upstream --tags
```

If the remotes have other names, use those names in every command and say so once.

Work on a branch or a worktree of your own, cut from `origin/main`. Never edit the clone's
checked-out branch if it has uncommitted changes you did not make. Never switch or reset a branch
another session may be using: `git -C <clone> worktree list` shows them.

## 3. The fork's own docs come first

A fork usually keeps its own notes: a runbook, a list of patches, its release script. Look for them:

```bash
git -C <clone> ls-files | grep -iE '(^|/)(runbook|patches|patched|fork)[^/]*\.md$|(^|/)(patched|fork)/'
git -C <clone> log --format='%h %s' -5 origin/main
```

The fork's own commits usually sit at the top of `main`, after the patches (for example a
`patched:` or `fork:` commit). Read what they add: `git -C <clone> show --stat <commit>`.

Read the runbook and the patch list before you change anything. **Where the fork's docs and this
plugin disagree, the fork's docs win.** Say which point differs, in one line. If the fork has
scripts for a step (install a local build, run the tests, release), use them.

## 4. The base tag

The fork's `main` is an upstream release tag plus the patch series. The fork's docs usually name the
tag. If they do not, find the upstream tag nearest to `origin/main`:

```bash
git -C <clone> ls-remote --tags --refs upstream 'v*' | sed 's#.*refs/tags/##' | while read -r t; do
  git -C <clone> merge-base --is-ancestor "$t" origin/main 2>/dev/null &&
    echo "$(git -C <clone> rev-list --count "$t..origin/main") $t"
done | sort -k1,1n -k2,2 | head -n 1
```

The fork's own release tags (for example `v2.11.2-preview.20261020.101`) are not upstream tags, so
they never come out of this. Then check that the series is what you expect:

```bash
git -C <clone> log --reverse --format='%h %s' <base>..origin/main
```

Every line is one patch, then the fork's own commits. A merge commit or a run of upstream commits
means the fork is not kept this way. Stop and ask the person how it is kept.

Below, `<base>` is that tag.
