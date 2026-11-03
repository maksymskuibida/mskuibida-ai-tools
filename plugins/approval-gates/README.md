# approval-gates

At every AI-DLC approval gate, the stage's documents become one readable page in a private
artifact, **AI-DLC approval gates**, published once per developer from the template in this plugin.
The agent writes the documents as rows, sends the page's link in a message before the gate question, and the developer
reads them there: the summary, the review brief, then every document of the stage in a view made for
its kind. A note per document goes back to the agent, which quotes it when the developer chooses
Request Changes. The decision itself is given in chat; the engine's gate question is unchanged and the
page holds no decision.

```
skills/approval-gates/SKILL.md            the procedure the agent follows at every gate
skills/approval-gates/approval-gate.html  the per-stage template — the data contract is in its header
skills/approval-gates/unit-gate.html      the unit-end template: a Unit's plan page and unit-end page
skills/approval-gates/test-plan.html      the test-plan template (artifact "AI-DLC test plans")
skills/test-plan/SKILL.md                 /approval-gates:test-plan
scripts/test_plan.py                      validates, publishes and finishes a test plan
skills/release/SKILL.md                   /approval-gates:release
scripts/gate_bundle.py                    builds the rows for one per-stage gate from the intent's files
scripts/unit_bundle.py                    drafts and finalizes a Unit's gate bundle (unit-end rhythm)
scripts/validate_bundle.py                checks a gate bundle against its contract
contract/                                 the gate-bundle contract: README.md and gate-bundle.schema.json
hooks/gate_guard.py                       the guard (hooks/hooks.json registers it)
```

## A Unit with the unit-end rhythm

A team Unit claimed with `--rhythm unit-end` (the `unit-claim` plugin asks for the rhythm before the claim) runs its
design stages with their reviewer rounds and no approval between them. You stop twice:

- **The plan page**, at the Code Generation plan approval. This is your one look at every design stage. It shows:
  - where the design narrows something already approved;
  - every assumption the agent made;
  - reviewer findings that were waived or left open, each with what in the plan settles it;
  - changes to what people see, stored data, API or MCP shape, security and dependencies;
  - the code plan, in build order;
  - the tests, grouped;
  - your answers, one group per questions file.
- **The unit-end page**, at the Unit's one gate. It shows:
  - what changed after the plan was approved, or "the design stays as approved";
  - what isn't verified yet;
  - what was built, in plain words, with a small map of how the pieces connect;
  - the approved design.

Each page is one **gate bundle**: a JSON file whose contract is [`contract/README.md`](contract/README.md) and
[`contract/gate-bundle.schema.json`](contract/gate-bundle.schema.json). `unit_bundle.py draft` fills every row it can
take from the records. The agent then labels each row by what it costs if wrong: critical, high, medium or low, or
core, main or minor for built pieces. It also picks "look first", rewrites titles in plain words, and writes the
sections the records can't give. `unit_bundle.py finalize` marks what changed since the last presentation and
validates the bundle.

The page lives in a second private artifact, **AI-DLC unit approvals** (`unit-gate.html`, with the `db` and `user`
capabilities):

- Everything starts open: every section and every row (the Summary view folds rows to one line). Pressing a
  row's read dot marks it read and folds it; marking it unread opens it again. Mark all read folds every row.
- A sticky bar holds Summary/Full, the filters (All, Look first, Unread, High and critical), Expand all and Collapse
  all, your read progress, and a chip per section.
- Revisions v2, v3 and so on each have their own colour, down to the sub-step, with one filter per revision.
- Read marks are yours. On a new revision, only the changed rows turn unread.
- Every reviewer finding, requirement and NFR row says where it is handled (a plan step, a document section, a code or
  test file, a later Unit: a green chip that opens it) or why it is not (the reason in a line under the row, with your
  words quoted when it is your reason). `finalize` refuses a bundle with a row that does neither (1.21.0).
- Notes on rows, and Do it / Leave it on suggestion rows, reach the agent with your chat answer. The decision itself
  is given in chat.

Per-stage pages open on Claude's evaluation of the stage (below); the Build and Test stage adds its own views.

### Build and Test

At the `build-and-test` gate `gate_bundle.py` also reads the stage's tables into `buildTest` on the gate row
(`contract/build-test.schema.json`), and the page shows, above the usual documents:

- a **results strip**: commands passed out of run, line coverage per repository as a bar against its floor, and the
  Met / Not Met / Unverified / N/A counts (press a count to filter the matrix);
- a **target matrix**: Not Met and Unverified first, filter chips by verdict and by Unit, a search by ID or text, and
  evidence codes whose legend shows on hover;
- a **decision card** per Not Met or Unverified target: Accept as known, Follow-up or Fix now, with an optional note.
  The picks are saved in the row (`targetPicks`) and the agent reads them with your chat answer: Fix now becomes a
  Request Changes naming those targets, Follow-up is recorded as follow-up work, Accept as a known limit;
- the build, integration, performance and security instruction files folded in a closed **Reference** section.

If the tables are not found, the stage looks like any other.

## What you see

On both pages every id (US1.1, AC1.1.2, FR1.4, NFR3, BR1.2, Q4, U31, C2, E7, ADR-009, R-01 and every other kind the
project's documents define) is a link with a tooltip, on hover and on keyboard focus, saying what it is and where it is
written: live when the page shows its definition (a click opens what holds it, lands there and flashes it), dotted when
it is defined elsewhere in the project (a click says so), dashed when no document defines it. The pages find ids the one
shared way (`shared/aidlc-ids`, the `aidlc-ids` plugin): the writer syncs the project's id map and stores what each id
the page shows is, nearest the stage's documents, so a Q1 or R-01 is this stage's and a BR1.1 this Unit's.

A page per gate, newest first in a list grouped by intent. A gate looks and works like the unit approvals page:

- A header card with the stage, the intent and phase, and its facts: the round (and why), the documents, the open
  findings and your notes.
- A sticky bar: filters (All, Unread, Changed, With notes, each with its count), your read progress, Expand all,
  Collapse all, Mark all read, whether your notes are saved, and a chip per block (summary, review, every document)
  that jumps to it. On wide screens an outline of every document's sections sits beside the blocks; on a phone it
  opens from the bar.
- Read marks are yours: a block is marked read with its dot. On a new round only the blocks whose text changed turn
  unread.
- From the second presentation of a stage on, the page compares itself with the previous one: changed and new
  documents, and the changed sections inside them, carry the round's colour, and the Changed filter shows only those.
- Then the blocks: the agent's summary, the review (verdict, open-finding count, a findings table whose rows open to
  the finding, where and required action), then every document, each with its sections collapsible and an Add a
  note button for a note to Claude. A note says whether it is saving, saved or not saved; a failed save is sent again
  when you type, or with Retry in the bar. Everything starts open; pressing a block's read dot marks
  it read and folds it (unread opens it again), and a block already read starts folded. A document longer than a
  database row is split at its headings and joined back on the page.

Each document kind has its own view, with a Text switch back to the document as written:

- **entities.md**: an entity diagram from the `entities:` block's relations, then a section per entity
  with its attributes (type, required, unique, default, limits, allowed values), constraints and
  relations.
- **rules.md**: the `rules:` block as a table per group (BR1, BR2, …), filterable by category and
  searchable; a row opens to the rule's logic, trigger, violation and source.
- **components.md**, **logical-components.md**: a dependency graph (calls solid, events dashed) and a
  card per component with what it does, what it depends on, who uses it and its entities.
- **unit-of-work-dependency.md**: the `units:` block as build layers, first the Units with no
  dependencies. **unit-of-work.md**: a section per Unit with its facts. **unit-of-work-story-map.md**:
  the map grouped by Unit.
- **stories.md**: cards by epic with priority, traces and every acceptance criterion split into
  Given, When and Then. **requirements.md** and the NFR files: a table per group, searchable.
- **decisions.md**: a card per ADR with its status, the Decision open and Context, Consequences and
  Alternatives folded. **bolt-plan.md**: a strip of Bolts with their points, then each Bolt.
- **contract-summary.md**: a section per contract; an OpenAPI block becomes an operations table, a type
  sheet a table per type. **traceability.json**: coverage by status.

- **Ideation and Inception documents**: **requirements.md** reads the table, the `- **FR1.1**` bullet
  and the titled `- **NFR1 Title:**` bullet (sub-bullets and source tags kept) as one table per group;
  **feasibility-assessment.md** shows the verdict as a banner and each area's rating as a chip;
  **raid-log.md**, **constraint-register.md**, **stakeholder-map.md** and the risk register of
  **risk-and-sequencing-rationale.md** are grids with the id linked, likelihood, impact and severity as
  chips, and a tally strip over the sections; **team-practices.md** and **team-allocation.md** fold each
  labelled practice under its label; **discovered-rules.md** marks ALWAYS and NEVER lines;
  **user-stories-assessment.md** shows the decision as a banner; **wireframes.md**, **mockups.md** and
  the other screen documents frame every ASCII screen with its heading as caption and add an "All
  screens" section that shows them side by side. **intent-statement.md**, **scope-document.md**,
  **intent-backlog.md**, **evidence.md**, **user-flow.md** (Mermaid flows drawn),
  **interaction-spec.md**, **design-system-mapping.md** and **accessibility-checklist.md** get a facts
  row from their bold-label lines, tables as grids (a filter bar over 8 rows), numbered lists as
  steppers and every H2 as a collapsible section. Source tags such as `[Q3]` or `[assumption]` are
  quiet tags, and a `Q` id links to its question.

Every id that names something in the gate (FR1.2, BR3.5, US1.1, AC1.1.2, ADR-003, U3, C4, R-02, Step 2), every
entity, component or type name, and every file name of a document in the gate is a link: hover or focus it for the
text, press it to jump there and see it highlighted. An id of a known kind (FR, NFR, BR, US, AC, ADR, U, Q, Step,
Bolt, RAID, R-) whose target is not in the gate is still shown as a link: its tooltip says what kind of thing it is,
and pressing it says it is not in this page. Badges explain themselves the same way: severity, likelihood and impact,
priority, verdicts, statuses, source tags such as `[Q3]` or `[assumption]`, and the change marks. A document whose
shape is not recognised is Markdown with every H2 a collapsible section.

## Claude's evaluation (1.24.0)

A per-stage page no longer opens on the stage's documents split into lines. It opens on the agent's **judgment of the
stage against its rules**:

- `gate_bundle.py draft` gathers what the stage is judged against (`scripts/criteria.py`): the engine's definition of the
  stage (its Constraints and what each file it writes must hold), the reviewer's checklist (its Core Review Questions and
  the stage's "What to Check"), the project's settled rules (every NEVER / ALWAYS bullet of the memory files that apply)
  and what earlier stages settled (one per document the stage consumes). It writes them to `criteria.json`, an empty
  `judgment.json` and a `todo` list, and no batch.
- The agent judges in `judgment.json`: a verdict per criterion (holds, fails, not relevant), what approving decides, what
  to look at first and why, what is solid, the risks, gaps and conflicts with earlier stages or rules (each point with the
  criteria, items or files it rests on), one sentence and an importance label per item, and which files the items cover.
- `gate_bundle.py finalize` refuses the row, one line per problem, until all of it is there (no ellipsis, no source that
  names nothing, every failed criterion named in a point); the guard refuses a `gates/` row without it the same way.
- The page leads with **Claude's evaluation**, then **What the stage says**: each item as the agent's sentence with its
  label, grouped Look at first / Matters most / Main / Minor; opening one shows it whole, as written (a rule's logic, a
  story's criteria). Items an earlier stage settled, items unchanged since the last round and the traceability fold away
  with a count. Files the items cover fold under **As written**; the rest still render in their views.
- After Request Changes, the next draft carries the summary and label of every item whose text did not change.

Rows written before 1.24.0 still open on At a glance:

## At a glance (1.23.0)

Every per-stage page opens on **At a glance**, the stage item by item, before the documents as written (those follow,
folded):

- **Tiles**: how many items you have read (each requirement, rule, decision, story and finding card has its own read
  dot), how many finding cards you sorted, how many traced items are not handled, how many are settled from earlier.
- **What the stage holds**: one bar per kind (requirements, NFRs, rules, decisions, stories), split into covered and
  linked, accepted with a reason, new in this stage, and settled earlier; hover a segment for its count.
- **Traceability**: when the stage has a traceability.json, a matrix of what is traced (rows) against what covers it
  (columns), a dot for covered and a cross for not.
- **Read dots** sit at the right end of every row and card, in the same column as the block summaries' dots.
- **One lane per kind**: one line per item (its id, its title in plain words, a chip saying where it is handled or that
  it was accepted, and the reason under the line when it is one); pressing the title opens what it says, what it relates
  to (the ids it names, so you see how decisions connect) and a jump to its document. Items an earlier stage settled are
  folded under a count: quoted here, approved before.

The read progress in the bar counts items, not sections, and the Unread filter hides the items you read. `gate_bundle.py`
builds it (`scripts/digest.py`) and refuses a stage whose traceability leaves something uncovered without a link or a
reason (`--handling`), the same rule as the unit pages.

## Review findings at the gate (1.22.0)

There is no separate Findings question (the `review-findings` plugin is deprecated for AI-DLC). When the review brief
lists open findings, the agent fixes the ones it can fix for certain and asks the reviewer again; a READY review settles
them. Every finding left goes on the gate page as a card in a **Findings to sort** block, above the review:

- the title, what it means, the suggested action in bold (the reviewer's, or one sentence a cheap model wrote: a Haiku
  subagent, recorded with `scripts/findings.py suggest`), where it is, and its severity;
- **Fix** (goes back with Request Changes), **Accept** (carried as a known risk; not offered on a blocking finding) or
  **Reject** (not applicable; a reason is required), with a note; saved as you click, as `findingPicks` on the row;
- findings you sorted Accept or Reject in an earlier round of the same stage are listed once, not asked again.

You answer the gate in chat as before. The agent then reads your sort: Fix cards go into Request Changes by id with
their action, Reject cards go on the rejected report as `--reject-finding`, Accept cards are carried. A message that is
just one choice for every card ("fix all", "accept all") counts as your sort.

The hook refuses: a piped or redirected review brief; the gate while a brief was cut off; a gate row that leaves an open
finding off the page; the Approval question until such a page went out; every closing report until your sort was read;
Approve while a card is Fix or a blocking card is not Rejected; a rejected report whose `--reason` misses a Fix card or
that leaves a Reject card out of `--reject-finding`. The page's `findingPicks` are never written by the agent.

## What the agent does

After `aidlc engine orchestrate report --result awaiting-approval` (or `revised`), it runs
`gate_bundle.py`, writes the rows with one `ArtifactData` batch, sends you `<artifact url>#<gate id>` in a
message of its own, and then asks the Approval question. After Request Changes it reads `gates/<id>` and quotes your notes in
the `--reason` of the rejected report. It never writes your notes, and never updates a row.

## What the hook refuses

- The Approval question (header `Approval`, an option such as Approve, Approve Plan or Accept as-is, no
  pull request named) until a `gates` row for the stage was written after the gate opened. While a gate is open, any
  question offering one of those options counts, whatever its header. The plan approval is open from the moment the
  engine asks for it (the active directive is an `ask` with `ask_type: "plan-approval"`), not only after an
  `aidlc engine log decision --checkpoint plan-approval`. A Request Changes answer (`aidlc engine log answer …
  --details "Request Changes"`) reopens it for the revised plan.
- A gate is not opened by a report the engine refused (`"kind": "error"`).
- The same question until a message of the agent in the session's transcript carries the page's link
  `<artifact url>#<gate id>`: you get the link before the question, every time. Only visible text counts: thinking, tool calls and results, text after the question, "see the linked artifact" with no URL and a markdown link to another address do not. It holds after a session restart too (1.19.0): the guard finds the page again from any session's record and from the transcript, and its refusal gives three numbered steps with the exact link.
- A turn that ends on the link, with the gate question never asked (a `Stop` hook blocks the stop once per published page and asks for the question; send the link and the question in one response).
- The same question with the page's link in its text: the link goes in a message of its own, so the dialog stays readable.
- `aidlc engine orchestrate report … --result approved|rejected|accepted` before that row exists.
- A write to `gates/<id>` that carries `notes` (or a decision field: the page records none).

Every refusal (1.20.0) has one shape: a first line `Refused: <what>, because <why>`, then `Do this:` with numbered
steps the agent can follow word for word (exact commands, script paths and links where they are known), then `It worked
when: <how to tell>`, then how the developer releases the guard. A blocked stop has the same shape. The tests hold every
refusal they meet to it.

It does nothing outside an AI-DLC project (no `aidlc/spaces`), on input it cannot read, and in the
after-call and prompt hooks it never fails. The project is the working directory's (or its nearest parent's)
when that holds one, before `CLAUDE_PROJECT_DIR`: in a git worktree the latter is the main checkout, whose
per-clone pointers (`aidlc/active-space`, `active-intent`, `.aidlc-engine/`) are not the worktree's. Its state is `~/.claude/approval-gates/<session>.json`
(`APPROVAL_GATES_DIR` changes the folder). To clear it, type `/approval-gates:release`.

## Data contract, in brief (per-stage)

```
gates/<id>                  {title ("Unit <unit>: Approve <Stage name>", or "Approve <Stage name>" without a Unit), stage, stageName, phase?, intent, project?, unit?, round, why?, status,
                             createdAt, summary?, brief?, review?, nextStage?, options, ids?, documents: [index]}
gates/<id>/documents/<key>  {n, key, title, path, kind, text}
page writes                 gates/<id>.notes[<key>]
                            gates/<id>.targetPicks[<target id>]   (Build and Test: {pick, note?})
                            data/users/<viewer>/reads-<intent>--<stage>--<unit>   (the viewer's read marks)
```

`<id>` is `<intent>-<stage>[-<unit>]-<YYYYMMDDTHHMM>`, new for every presentation. The full contract is
the header of `approval-gate.html`.

## Install

```bash
claude plugin marketplace add maksymskuibida/mskuibida-ai-tools
claude plugin install approval-gates@mskuibida-tooling
```

## Pairs with

`question-forms` (the same artifact style, and the questions files that come before a gate). The
`aidlc` CLI is needed only for the review brief; without it `gate_bundle.py` leaves the brief out.

## Tests

```bash
python3 -m unittest discover -s plugins/approval-gates/tests
```

Python 3 standard library only. The tests use a fake project under `tests/fixtures/project` and a
stand-in for `aidlc` (`$APPROVAL_GATES_AIDLC`). The unit page's renderer runs under Node when `node` is installed,
and those tests are skipped without it.

`test_unit_bundle.TestRealU4Records` builds, validates and renders both pages from Dayboard's real U4 records. It
reads them from that checkout's git branch into a temporary folder: `APPROVAL_GATES_U4_REPO`, default `~/dayboard`;
`APPROVAL_GATES_U4_REF`, default `origin/unit/u4-day-navigation`. The records are never copied into this repository,
so the class is skipped where that checkout is missing, such as in CI.

## Testing the not-verified points

On the unit-end page every row under "Not verified yet" has a **Test now / Later** pick. Before approving, you can test
those points through a guided test plan:

- Answer the unit-end gate **Test first** (the third option next to Approve and Request Changes), or type
  `/approval-gates:test-plan` at any time. Test first is neither an approval nor a rejection; the gate stays open.
- The agent writes a plan from the rows picked Test now (all of them if none is, and it says so): sections A, B, C …
  with steps A.1, A.2, B.1 …. A new section starts wherever the agent must do something first (seed data, start a server,
  deploy, reset state). Each section has the agent's step and your steps (what to do, what to expect), and each step
  names the not-verified rows it verifies. `scripts/test_plan.py` checks the plan before it is shown.
- The plan is a row in a third private artifact, **AI-DLC test plans** (`skills/approval-gates/test-plan.html`, published
  once per developer). You mark each step **Pass** or **Fail**, with an optional note on a Pass and a required note on a
  Fail. The agent does each section's agent step, then asks "Section A completed, go on", and reads your results.
- At the end `test-plan.md` (plan, each step's result, notes, date) is written to the Unit's code-generation stage
  folder. With no fails, the unit-end page is built again with the not-verified section split into *Verified by you*,
  *Still not verified* and *Failed, left as known*, and the gate is asked again. With fails, you choose which to fix
  (inline for one or two, a question form for more); fixes go back as Request Changes with the failures and your notes.

Only the unit-end rhythm has a test plan; per-stage gates are unchanged. The contract is in
[`contract/README.md`](contract/README.md#the-test-plan-unit-end-page-only).
