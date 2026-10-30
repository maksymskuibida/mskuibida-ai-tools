# Gate bundle contract (`aidlc-gate-bundle/1`)

A gate bundle is the file the agent writes at a Unit gate when the Unit was claimed with the `unit-end` rhythm.
There are two pages per Unit:

- **`plan`**: shown at the Code Generation plan approval. It is the person's one look at every design stage of the Unit.
- **`unit-end`**: shown at the Unit's single unit-end gate. It covers what was built.

A page renders the bundle. Today the renderer is `skills/approval-gates/unit-gate.html`, an Artifact page. A separate
app may render the same file later. The bundle therefore says **what** to show and how much each piece matters, never
**how** to draw it.

| File | What it is |
|---|---|
| [`gate-bundle.schema.json`](gate-bundle.schema.json) | The shape, as JSON Schema 2020-12. Every object is closed (`additionalProperties: false`). |
| [`../scripts/validate_bundle.py`](../scripts/validate_bundle.py) | The validator: the schema, then the rules below. `python3 validate_bundle.py <bundle.json> [--order]`. |
| [`../scripts/unit_bundle.py`](../scripts/unit_bundle.py) | The builder the agent runs: `draft` from the stage records, `finalize` to mark revisions and validate. |

The schema uses only `type`, `const`, `enum`, `pattern`, `minLength`, `maxLength`, `minimum`, `maximum`, `required`,
`properties`, `additionalProperties` (`false`, or a schema for a map's values), `propertyNames`, `items`, `minItems`,
`maxItems` and local `$ref`. The validator reads the
schema file itself, so the two cannot drift. Keep to that subset when the schema changes.

## The bundle

```
{schema: "aidlc-gate-bundle/1", page: "plan"|"unit-end", id, createdAt, header, sections[], plan?, answers[], design?, ids?, provenance?}
```

| Field | Meaning |
|---|---|
| `id` | `<intent>-<unit>-<page>-v<revision>-<YYYYMMDDTHHMM>`. Every presentation gets a new id. |
| `header` | Header facts. Required: `project`, `intent`, `unit`, `unitName`, `title` (what the page is: `Unit <unit>: Approve plan` / `Unit <unit>: Approve Unit-end`; `unit_bundle.py` writes it and the page derives the same from `unit` + `page`), `lede` (what the Unit does, in plain words), `status` (one line, such as "Plan approval · answer in chat"), `revision`, `revisions[] {n, note, at?}`, and up to six `facts[] {label, value, note?}`. Optional: `intentName`, `unitLabel` (U4), `stages[] {slug, name, ran, note?}`, `links {records?, plan?}`, `footer`. |
| `sections[]` | Each `{key, kind, title, short, hint?, refsLabel?, asApproved?, rows[], map?}`. `short` is the section chip's name in the bar. |
| `plan` | Plan page only: `{title?, hint?, path?, steps[]}`. |
| `answers[]` | The person's answers, one group per questions file: `{key, stage, title, file, questions[] {id: "Q3", anchor, text, answer, proposed?}}`. An answer differs from the proposal when its first letter is not the proposed one. |
| `design` | Unit-end page only: the approved plan page folded to `{bundle, url?, counts?, rows[] {id, title, label}}`. |
| `ids` | What each id the page shows is: `{"FR1.4": {kind, title, text?, doc?, line?}}`, the output of the shared `aidlc_ids.py refs` (its contract: `shared/aidlc-ids/README.md` in the repository) over every text of the bundle, with `--near` the Unit's stage folders, so a BR1.1 is this Unit's and never another's. `unit_bundle.py finalize` writes it after `aidlc_ids.py sync`; the agent never edits it. |
| `provenance` | Where the bundle was built from. Renderers ignore it. |

### Section kinds

| Page | `kind` | Holds |
|---|---|---|
| plan | `narrows` | Places where the design narrows something already approved (an inception record, an earlier Unit, an answer). |
| plan | `assumptions` | Every assumption made without asking. |
| plan | `findings` | Reviewer findings that were waived or left open. Each row says in `coveredBy` what settles it, or that nothing does. |
| plan | `visible` | Changes to what the person sees, stored data, API or MCP shape, security, dependencies. |
| plan | `tests` | The plan's tests, one row per group. |
| unit-end | `changes` | What changed after plan approval. `asApproved: true` with no rows says "the design stays as approved". |
| unit-end | `unverified` | What isn't verified yet. After a test plan: the points still not verified (picked Later, or failed and being fixed). |
| unit-end | `verified` | Only after a test plan: the points the person tested and passed ("Verified by you"). Each row keeps its V id. |
| unit-end | `failed` | Only after a test plan: the points that failed and the person left as known ("Failed, left as known"). |
| unit-end | `built` | What was built, in plain words, labelled core, main or minor. It may carry a `map` of how the pieces connect. |
| both | `other` | Anything else the agent needs to show. |

### Rows

```
{id, title, label, lookFirst?, body, where?, whereIsPath?, refs[], coveredBy?, suggestion?, rev?, revKind?, revNote?, source?}
```

- **`id`** is shown as is (`FD R-06`, `A-2`). Its **anchor** is the id with every run of characters outside
  `[A-Za-z0-9._-]` replaced by one hyphen (`FD-R-06`).
- **`title`** is one line: no line break, and it doesn't end in a space or "…". The renderer cuts it off with "…".
- **`label`** says what the row costs if it is wrong:

  | Label | Meaning |
  |---|---|
  | `critical` | Wrong data, security, or hard to undo. |
  | `high` | Wrong behaviour the person would see. |
  | `medium` | Rework in this Unit. |
  | `low` | Cosmetic or internal. |
  | `core` / `main` / `minor` | `built` rows only: how much of the Unit rests on the piece. |

- **`lookFirst`**: the agent picks it. On the plan page it marks the critical and high rows that are an assumption the
  agent made or a finding left open.
- **`body`**: plain words.
- **`refs[]`**: `{label, tip, target}`. The `tip` is what the reference says, shown on hover and focus. The `target` is
  one of three forms:
  - `#<anchor>`: a row, a step (`step-<n>`), a question, a section key, or `plan`, `answers` or `design`;
  - an `http(s)` URL;
  - `path:<repo-relative path>[#<id>]`: a record outside the bundle. When `header.links.records` is set, the renderer
    links it there; otherwise it offers the path.
- **`coveredBy`**: `{text, settled}`, for a reviewer finding.
- **`suggestion`**: the row proposes something the person may take or leave.
- **`rev`**, **`revKind`**, **`revNote`**: the row changed (`changed`) or appeared (`new`) in revision `rev`, and the
  note says what changed.
- **`source`**: `{path, key, digest}`, the record the row was drawn from. A later draft uses it to keep an unchanged row
  as the agent left it. Renderers ignore it.

### Code-plan steps

```
{n, title, layer, files, subs[] {text, rev?}, implements[] (refs), rev?, revKind?, revNote?, source?}
```

Steps stay in build order: `n` is 1, 2, 3 …. `layer` is one of setup, tests, data, logic, api, UI, infra, checks, docs
or other. `files` is how many files the step touches. `implements` lists the design points the step implements, as
references. A sub-step's own `rev` marks the exact sub-step a revision changed.

## Rules the schema cannot say (checked by the validator)

1. A `plan` page has `plan` and no `design`. A `unit-end` page has `design` and no `plan`.
2. Each page uses only its own section kinds. Section keys are unique and never `plan`, `answers` or `design`.
3. `built` rows are labelled core, main or minor. Every other row is labelled critical, high, medium or low.
4. `lookFirst` goes on critical and high rows only.
5. Every anchor (rows, steps, questions, sections, answer groups) is unique, and every `#` target names one of them.
6. `header.revisions` lists 1 … `revision` in order. No mark is later than `revision`, and every marked row or step
   carries a `revNote`. When a sub-step is marked with the current revision, its step is marked too.
7. `asApproved` belongs only on a `changes` section, and only when that section has no rows. A `map` belongs only on a
   `built` section, and both ends of each of its edges are nodes.
8. The `id` names the page and the revision.

## What a renderer does

These rules are part of the contract. Any page that renders a bundle follows them.

**Order.**
- Sections are sorted by importance: first the top label, then the number of look-first rows, then the number of rows
  at the top label. Rows inside a section are sorted the same way.
- The code plan ranks below any section that has a critical or high row, and above the rest. So it comes first when
  nothing else is critical or high. Its steps stay in build order.
- Tests always come after every other section.
- The person's answers are the very last section. On the unit-end page, the approved design comes after them, folded.

`validate_bundle.py --order` prints the order. The page's `GateView.order` and the Python `order()` implement the same
rule, and the tests hold them to each other.

**Folding.**
- Every section starts open, with its rows folded to a single line: id, title cut off with "…", and label.
- The answers start as one folded group per questions file.
- A section header always shows the count of each label its rows have, so a folded section still shows them.

**The sticky bar** holds:
- the Summary / Full switch (Full opens every row);
- the filters All, Look first, Unread, and High and critical (High and core on the unit-end page);
- Expand all and Collapse all;
- the read progress;
- one chip per section, in page order.

There is no side column. A jump to an anchor lands below the bar, and it opens whatever holds the target.

**References.** Every reference shows its tip on hover and focus, and it is a link.

**Ids.** Every id the page shows, in any text, is a link whose tooltip (on hover and on focus) says what `ids` says of
it: live when the page shows its definition (a row or an answer whose id it is, when no other row or answer has the same
id), so the link opens what holds it and lands there; dotted when it is defined elsewhere in the project; dashed when no
document defines it. A design id among a row's references (a `path:` target) is drawn the same way.

**Revisions.**
- Each revision from v2 on has its own colour, used on the rows, the steps and the exact sub-steps that changed.
- The header has one filter per revision that shows only that revision's changes.
- A row is marked read only with its own read control; opening a row doesn't mark it. A read mark records the
  revision that was read. On a new revision, only the rows marked with that revision turn unread.

**What the person writes.** Read marks are the viewer's own. Notes on a row, and the lean on a suggestion (Do it /
Leave it), are stored with the page's row for the agent to read when the person answers in chat. The decision itself
is always given in chat.

**Test now / Later.** Each row of an `unverified` section carries a Test now / Later pick, stored like the lean on a
suggestion: `picks.<row anchor>` is `"now"` or `"later"` (on these rows only). The agent's test plan covers the rows
picked Test now, or every row when none is. The pick is read by the agent through `ArtifactData`; the bundle itself
does not change.

## Changing the contract

- A field that renderers may ignore is a minor change: add it to the schema, the validator and this file.
- Anything that changes what an existing field means, or that makes an old bundle invalid, is a new `schema` value
  (`aidlc-gate-bundle/2`). Renderers refuse a value they don't know.

## The Build and Test field of a per-stage gate row

Not part of the bundle above: the per-stage `gates/<id>` row for the Build and Test stage may carry `buildTest`, the
stage's tables read into data (commands and their results, line coverage against its floor, the Target Verification
Matrix, the evidence-code legend). `gate_bundle.py` writes it; `approval-gate.html` shows a results strip, a
filterable target matrix and a decision card per Not Met or Unverified target when it is there, and the stage as any
other when it is not. Its shape is [`build-test.schema.json`](build-test.schema.json); check a row with
`python3 validate_bundle.py --build-test <gate.json>`. The developer's picks come back in the row's `targetPicks`
(`{<target id>: {pick: "accept"|"followup"|"fix", note?}}`), written by the page, never by the agent.

## The test plan (unit-end page only)

Not part of the bundle: the developer can test the not-verified points before approving. The plan, its page and the
results have their own files and artifact (**AI-DLC test plans**, `skills/approval-gates/test-plan.html`):

| File | What it is |
|---|---|
| `scripts/test_plan.py` | `validate` a plan against the unit-end bundle, `publish` it as a `plans/<id>` row, `finish` it into `test-plan.md` and `test-plan.json` in the Unit's code-generation stage folder. |

A plan (`aidlc-test-plan/1`):

```
{schema, id, intent, unit, bundle (the unit-end bundle id), title, createdAt, now[] (the V ids covered),
 allByDefault (true when no row was picked Test now), sections[] {key: "A", title, agent, steps[] {id: "A.1", do, expect, verifies[]}}}
```

- Section keys are A, B, C … in order; step ids are `<key>.<n>` from 1. A new section starts wherever the agent must do
  something first (seed data, start a server, deploy, reset state); `agent` says what the agent will do.
- Each step names the V rows it verifies; every row in `now` is verified by at least one step, and no step names a row
  outside `now`.

The `plans/<id>` row holds `{plan, intent, unit, title, createdAt, status, agentDone[]}`; the agent sets `agentDone`
(the keys of sections whose agent step is done). The page writes `results.<step id>` = `{result: "pass"|"fail", note,
at}`; a fail without a note is never saved.

`test-plan.json` (the outcome, written by `finish`) is `{schema: "aidlc-test-outcome/1", plan, results, rows: {<V id>:
{state: "passed"|"failed"|"later", steps[], notes[], decision?: "fix"|"left"}}}`. `unit_bundle.py draft --tested
<test-plan.json>` rebuilds the unit-end page from it: passed rows move to a `verified` section, failed rows decided
`left` to a `failed` section, and every other row stays in `unverified` (retitled "Still not verified").
