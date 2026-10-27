# Test Results — Build and Test, first run

## Result
| Result | Count |
|---|---|
| Commands run, all exit 0 | 12 |
| Targets `Met` | 156 |
| Targets `Not Met` | 2 |
| Targets `Unverified` | 21 |
| Targets `N/A` (owned by CI Pipeline, later in this plan) | 12 |
| Targets in the matrix | 191 |

## Build

| Step | Command | Result |
|---|---|---|
| Web build | `pnpm build` in `dayboard-web` | success, 1 page prerendered |
| API install | `uv run …` (environment already synced) | success |

## Checks and tests

| Check | Command | Result |
|---|---|---|
| API lint | `uv run ruff check .` | all checks passed |
| API tests | `uv run pytest --cov --cov-fail-under=80` | 779 passed, 0 failed, 16 deselected (the `perf` ones, run below); lines 98.85% (floor 80%) |
| Web unit tests | `DAYBOARD_REQUIRE_BUILD=1 pnpm exec vitest run --project unit --coverage` | 71 files, 719 passed, 0 failed, 0 skipped; lines 98.17%, statements 96.81%, branches 90.34% (floor 80%) |
| Web size | `pnpm size` (Node.js 24) | 203.1 KB gzip of 300 KB |
