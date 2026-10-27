# Build and Test Summary — Dayboard, first version

## Target Verification Matrix

Sources are named by Unit and ID (`u1:NFR2.1`); an ID without a source number was derived from the source's file and section. Evidence codes:

- **A**: `uv run pytest --cov --cov-fail-under=80` in `dayboard-api`: 779 passed, 98.85%.
- **AP**: `uv run pytest -m perf tests/perf --no-cov`: 16 passed.
- **W**: `vitest run --project unit --coverage` with a build present: 71 files, 719 passed, 98.17%.
- **WT**: `vitest run --project timing`: 7 passed.
- **E**: `scripts/e2e_check.py`: every step passed. **SZ**: `pnpm size`: 203.1 of 300 KB.
- **L**: Ruff, mypy (API), Biome, `tsc` (web): clean. **H**: by hand in the browser, this run. **I**: read in the code, no test.


### U1 API core and HTTP

| Target ID | Source | Expected | Actual | Evidence | Owning Stage | Verdict |
|---|---|---|---|---|---|---|
| u1:NFR2.1 | u1 performance-requirements, Targets | read 200-item day, p95 ≤ 300 ms | 3.2 ms | AP `test_speed.py` | build-and-test | Met |
| u1:NFR2.2 | same | store one change, p95 ≤ 300 ms | 8.3 ms | AP `test_speed.py` | build-and-test | Met |
| u1:NFR5.6 | same | five tabs read one day while one writes, NFR2.1 holds | no test | none | build-and-test | Unverified |
| u1:NFR5.4 | same | a write and a read \| at once, one `stale` | no separate-process test | in-process stand-ins `test_changes.py` | build-and-test | Unverified |

### U2 Assistant access

| Target ID | Source | Expected | Actual | Evidence | Owning Stage | Verdict |
|---|---|---|---|---|---|---|
| u2:NFR2.8 | u2 performance-requirements | `read_day`, p95 ≤ 300 ms | 21.1 ms | AP `test_mcp_speed.py` | build-and-test | Met |
| u2:NFR2.9 | same | `change_day`, p95 ≤ 300 ms | 36.4 ms | AP | build-and-test | Met |

### U3 The day page

| Target ID | Source | Expected | Actual | Evidence | Owning Stage | Verdict |
|---|---|---|---|---|---|---|
| u3:NFR2.1 | u3 performance-requirements | render 200-item day, p95 ≤ 1 s | passes | WT `day.timing.test.tsx` | build-and-test | Met |
| u3:NFR2.2 | same | control shows new value ≤ 100 ms, p95 of 50 | passes | WT | build-and-test | Met |
| u3:NFR7.4 | same | at 360 px every control ≥ 44 × 44 px | switches, menus, buttons ≥ 44 px; **Markdown task checkboxes 22 × 22 px** | W `contrast.test.ts` (size tokens only); H | build-and-test | Not Met |

### U4 Moving between days

| Target ID | Source | Expected | Actual | Evidence | Owning Stage | Verdict |
|---|---|---|---|---|---|---|
| u4:NFR2.1 | u4 performance-requirements | arrow press shows the day ≤ 50 ms, p95 of 50 | passes | WT `navigation.timing.test.tsx` | build-and-test | Met |
| u4:NFR2.2 | same | calendar grid ≤ 100 ms, p95 of 20 | passes | WT | build-and-test | Met |

### U5 Live updates and end-to-end check

| Target ID | Source | Expected | Actual | Evidence | Owning Stage | Verdict |
|---|---|---|---|---|---|---|
| u5:NFR2.1 | u5 performance-requirements | watcher reads every 500 ms ± 50 | 510.8 ms | AP `test_events_speed.py` | build-and-test | Met |
| u5:NFR2.2 | same | `day` notices within 1 s of the store, p95 | 506.0 ms | AP | build-and-test | Met |

### U6 Installation

| Target ID | Source | Expected | Actual | Evidence | Owning Stage | Verdict |
|---|---|---|---|---|---|---|
| u6:checks | u6 unit-test-instructions, Checks 1 to 7 | per repository: launchd and systemd examples valid; no non-loopback host; real `DAYBOARD_` names; made-up paths; start command and address named; `e2e_check.py` named only while it exists | 14 checks pass | A `tests/docs`; W `src/docs` | build-and-test | Met |
| u6:lint | same | Ruff, mypy strict, Biome, `tsc` pass | clean | L | build-and-test | Met |

### Cross-repository

| Target ID | Source | Expected | Actual | Evidence | Owning Stage | Verdict |
|---|---|---|---|---|---|---|
| x:e2e | team practices, Testing Posture | one scripted end-to-end check talks to the MCP server and the web server directly | all steps pass | E | build-and-test | Met |
| x:privacy-tests | team practices, Testing Posture | the privacy guard has its own tests from the first Unit | present and passing (see `security-test-instructions.md`) | A | build-and-test | Met |
| x:traceability | stage Step 10 | every requirement and criterion built or marked N/A | 179 of 182 covered; `NFR1`, `NFR4`, `NFR8` not | see `cross-unit-traceability.md` | build-and-test | Not Met |
