# Lessons from patching the engine

General guidance, learned the hard way on real forks. The fork's own runbook wins where it says
something different.

## Keep upstream's files shaped like upstream's

- **Leave the release workflow's jobs alone.** Upstream has a test (t332,
  `tests/unit/t332-preview-release-pipeline.test.ts`) that pins the structure of
  `.github/workflows/preview-release.yml`. Renaming, removing or reordering a job breaks it. A
  fork-specific change goes through an `env:` value the scripts read (for example the build floor)
  or an `if:` condition on `github.repository`, with upstream's behaviour as the default. Update
  t332 in the same commit so it checks both the upstream and the fork conditions.
- **Every commit stands on its own.** It typechecks and passes upstream's lint:
  `bun scripts/package.ts && bun run typecheck`, then `bun run lint` (biome with
  `--error-on-warnings`). A warning is a failure.
- **Write like upstream.** Commit subjects are `fix(scope): what is now true`, as in upstream's
  log. A test file starts with a `covers:` header and a comment that says what broke and why.

## GitHub Actions in a fork

- **Upstream's Full Suite live jobs always fail in a fork.** They need upstream's cloud
  credentials. If a push or a release starts such a run in the fork, cancel it
  (`gh run cancel <id> --repo <fork>`). Do not wait for it, and do not read its failure as a
  real one.
- **A fork can have Actions turned off for tests.** Some forks run tests on the person's machine
  instead (a pre-push hook, a local full run before a release). Follow the fork's runbook.

## Running things on a shared machine

- **Fixtures share one engine lock.** Every `aidlc` command takes the machine-wide transaction lock
  (`~/.local/.aidlc-transaction.lock`). Another session's fixture or project may hold it for a
  moment. On a lock message, wait a few seconds and retry, a few times. Never delete the lock file.
- **Run tests outside the session's own markers.** The engine reacts to the host it runs under. Run
  the suite with `env -u CLAUDECODE -u CLAUDE_CODE_SESSION_ID`, as a fork's test script usually
  does, so a test does not mistake the test run for a live session.
- **Never reproduce in a live project checkout.** Build a scratch workspace (the fork's fixtures
  usually do this) or a throwaway clone.

## People and sessions

- **Never message an AI-DLC Unit session while its gates may be open.** The engine can record a
  message from another session as the person's own answer at a gate. Tell the person what that
  session needs and let them type it. This holds for pin updates too: the person runs
  `aidlc config --pin` in a checkout where a session is live, not you through that session.
- **Ask before anything outward-facing.** Force-pushing the fork's `main`, starting a release,
  filing an upstream issue, opening an upstream PR and commenting upstream each need the
  person's yes, every time.

## A public fork

- **No employer or private project names.** Not in code, tests, fixtures, commit messages, PR
  text or notes. Fixtures and examples use made-up names (`demo-shop`, `example/ws`, `DEMO-2`).
  Before a push, search the diff for the real project and company names the person works with.
  If you do not know them, ask.
- **Nothing private in a reproduction.** Turn a real project's transcript or state into a
  made-up minimal one before it goes into a test or an issue.
